import hashlib
import json
import multiprocessing
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
TOOLS = TEST_DIR.parents[1] / 'code' / 'tools'


def run_writer(root, operation, ready, resume, done, result):
    os.environ.update(MEM_DB=str(root / 'db'), MEM_LEDGER=str(root / 'ledger.json'),
                      MEM_LEDGER_SUPPLEMENT=str(root / 'supplement.json'))
    sys.path.insert(0, str(TOOLS))
    import memory_ledger as ledger

    if resume is not None:
        load_docs = ledger.load_docs

        def paused_load():
            ready.set()
            if not resume.wait(15):
                raise TimeoutError('writer was not released')
            return load_docs()

        ledger.load_docs = paused_load
    else:
        ready.set()
    operations = {'init': ledger.cmd_init, 'sync': ledger.cmd_sync,
                  'retire': lambda: ledger.cmd_retire(1, 'correct', 3),
                  'batch': lambda: ledger.retire_many([2], 'dedupe'),
                  'force': lambda: ledger.cmd_init(force=True)}
    try:
        result.value = operations[operation]()
    finally:
        done.set()


class LedgerConcurrencyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=TEST_DIR)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.ledger = self.root / 'ledger.json'
        self.context = multiprocessing.get_context('spawn')
        with closing(sqlite3.connect(self.root / 'db')) as connection, connection:
            connection.execute('CREATE TABLE documents (id INTEGER PRIMARY KEY, text TEXT)')
            connection.executemany('INSERT INTO documents VALUES (?, ?)', [(1, '旧文'), (2, '重复')])

    def start(self, operation, resume=None):
        ready = self.context.Event()
        done = self.context.Event()
        result = self.context.Value('i', -99)
        process = self.context.Process(target=run_writer,
                                       args=(self.root, operation, ready, resume, done, result))
        process.start()

        def cleanup():
            if process.is_alive():
                process.terminate()
            process.join(10)

        self.addCleanup(cleanup)
        self.assertTrue(ready.wait(10), operation)
        return process, done, result

    def finish(self, worker, expected=0):
        process, done, result = worker
        self.assertTrue(done.wait(15))
        process.join(10)
        self.assertEqual(process.exitcode, 0)
        self.assertEqual(result.value, expected)

    def test_sync_cannot_overwrite_single_or_batch_retirement(self):
        self.finish(self.start('init'))
        with closing(sqlite3.connect(self.root / 'db')) as connection, connection:
            connection.execute("INSERT INTO documents VALUES (3, '新文')")
        resume = self.context.Event()
        sync = self.start('sync', resume)
        single = self.start('retire')
        batch = self.start('batch')
        try:
            self.assertFalse(single[1].wait(0.5), 'single retirement bypassed sync')
            self.assertFalse(batch[1].wait(0.5), 'batch retirement bypassed sync')
        finally:
            resume.set()
        self.finish(sync)
        self.finish(single)
        self.finish(batch, 1)
        data = json.loads(self.ledger.read_text(encoding='utf-8'))
        self.assertEqual(set(data['entries']), {'3'})
        self.assertEqual(set(data['retired']), {'1', '2'})
        self.assertEqual(data['retired']['1']['replaced_by'], 3)
        self.assertEqual(data['retired']['1']['sha256'], hashlib.sha256('旧文'.encode()).hexdigest())
        self.assertEqual(data['retired']['2']['reason'], 'dedupe')

    def test_sync_initializes_once_against_explicit_init(self):
        resume = self.context.Event()
        sync = self.start('sync', resume)
        contender = self.start('init')
        try:
            self.assertFalse(contender[1].wait(0.5), 'concurrent init bypassed sync')
        finally:
            resume.set()
        self.finish(sync)
        self.finish(contender, 1)
        self.assertEqual(set(json.loads(self.ledger.read_text(encoding='utf-8'))['entries']), {'1', '2'})

    def test_interrupted_force_init_keeps_old_ledger_and_releases_lock(self):
        self.finish(self.start('init'))
        original = self.ledger.read_bytes()
        worker, _, _ = self.start('force', self.context.Event())
        worker.terminate()
        worker.join(10)
        self.assertEqual(self.ledger.read_bytes(), original)
        self.finish(self.start('force'))
        self.assertIn(original, [backup.read_bytes() for backup in self.root.glob('ledger.json.old-*')])


if __name__ == '__main__':
    unittest.main()
