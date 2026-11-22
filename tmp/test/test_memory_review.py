import contextlib
import ast
import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    with patch('os.makedirs'):
        spec.loader.exec_module(module)
    return module


class MemoryReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.db = self.root / 'memory.db'
        self.writer = sqlite3.connect(self.db)
        self.addCleanup(self.writer.close)
        self.writer.execute('pragma journal_mode=wal')
        self.writer.execute('pragma wal_autocheckpoint=0')
        self.writer.execute('create table documents(id integer primary key, text text, metadata text, created_at text)')
        self.writer.commit()

    def insert(self, identifier, text, created='2026-01-01', metadata=None):
        self.writer.execute('insert into documents values(?,?,?,?)',
                            (identifier, text, json.dumps(metadata or {}), created))
        self.writer.commit()

    def test_maintenance_backup_includes_wal_and_keeps_earliest_timestamp(self):
        maintenance = load_module('review_maintenance', 'code/tools/memory_maintenance.py')
        self.insert(1, 'same', '2026-02-01')
        self.insert(2, 'same', '2026-01-01')
        self.insert(3, 'unique')
        with patch.object(maintenance, 'LOG_DIR', str(self.root)), \
                patch.object(maintenance, '_retire_ledger', None), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(maintenance.apply(str(self.db), str(self.root / 'absent.db')), 1)
        backups = list(self.root.glob('backup-memory-*.db'))
        self.assertEqual(len(backups), 1)
        with contextlib.closing(sqlite3.connect(backups[0])) as snapshot:
            self.assertEqual(snapshot.execute('select count(*) from documents').fetchone()[0], 3)
        self.assertEqual(self.writer.execute('select id from documents order by id').fetchall(), [(2,), (3,)])

    def test_short_dedupe_backup_does_not_depend_on_successful_checkpoint(self):
        dedupe = load_module('review_dedupe', 'code/tools/dedupe_memories.py')
        self.insert(1, 'same')
        self.insert(2, 'same')
        real_connect = sqlite3.connect

        class Connection:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, sql, *args):
                if 'wal_checkpoint' in sql.lower():
                    return self.connection.execute('select 1,1,0')
                return self.connection.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(self.connection, name)

        def connect(path, *args, **kwargs):
            connection = real_connect(path, *args, **kwargs)
            return Connection(connection) if str(path) == str(self.db) else connection

        with patch.object(dedupe, 'DB', str(self.db)), patch.object(dedupe, 'LOGS', str(self.root)), \
                patch.object(dedupe, '_retire_ledger', None), patch.object(dedupe.sqlite3, 'connect', connect), \
                contextlib.redirect_stdout(io.StringIO()):
            dedupe.main()
        with contextlib.closing(real_connect(next(self.root.glob('backup-memory-before-dedupe-*.db')))) as snapshot:
            self.assertEqual(snapshot.execute('select count(*) from documents').fetchone()[0], 2)

    def test_claim_preserves_metadata_and_uses_current_text(self):
        claim = load_module('review_claim', 'code/tools/memory_claim.py')
        self.insert(1, 'an old fact', metadata={'access_count': 1})
        original_load = claim.load

        def load_then_concurrent_update():
            rows = original_load()
            self.writer.execute('update documents set text=?, metadata=? where id=1',
                                ('可能是推断', json.dumps({'access_count': 9, 'status': 'archived'})))
            self.writer.commit()
            return rows

        with patch.object(claim, 'DB', str(self.db)), patch.object(claim, 'BACKUP_DIR', str(self.root)), \
                patch.object(claim, 'load', load_then_concurrent_update), \
                patch.object(sys, 'argv', ['memory_claim.py', '--apply']), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(claim.main(), 0)
        metadata = json.loads(self.writer.execute('select metadata from documents where id=1').fetchone()[0])
        self.assertEqual(metadata['access_count'], 9)
        self.assertEqual(metadata['status'], 'archived')
        self.assertEqual(metadata['claim_type'], 'inference')

    def test_ppr_reuses_graph_and_excludes_unreachable_memories(self):
        brain = load_module('review_brain', 'code/lab/memory_brain/companion_brain.py')
        graph = {1: {2}, 2: {1, 3}, 3: {2}, 4: {5}, 5: {4}}
        with patch.object(brain, '_load_mem_graph', return_value=graph):
            self.assertEqual(brain.ppr_expand([1]), [2, 3])
        with patch.object(brain, '_load_mem_graph', return_value={}):
            self.assertEqual(brain.ppr_expand([1]), [])

    def test_graph_reads_committed_wal_without_waiting_for_checkpoint(self):
        brain = load_module('review_graph_wal', 'code/lab/memory_brain/companion_brain.py')
        self.addCleanup(brain._GRAPH_CACHE.close)
        self.writer.executescript('''
            create table graph_edges(source_memory_id, target_memory_id, status);
            create table graph_entries(id, source_memory_id);
            create table graph_entry_nodes(entry_id, node_id);
            insert into graph_edges values(1,2,'active');
        ''')
        with patch.object(brain, 'DB', str(self.db)):
            self.assertEqual(brain.ppr_expand([1]), [2])
            main_mtime = self.db.stat().st_mtime_ns
            self.writer.execute("update graph_edges set target_memory_id=3")
            self.assertEqual(brain.ppr_expand([1]), [2])
            self.writer.commit()
            self.assertEqual(self.db.stat().st_mtime_ns, main_mtime)
            self.assertEqual(brain.ppr_expand([1]), [3])

    def test_links_read_committed_wal_and_do_not_keep_deleted_rows(self):
        brain = load_module('review_links_wal', 'code/lab/memory_brain/companion_brain.py')
        self.addCleanup(brain._LINKS_CACHE.close)
        self.writer.executescript('create table links(a,b,sim); insert into links values(1,2,0.9);')
        with patch.object(brain, 'LINKS_DB', str(self.db)):
            self.assertEqual(brain.load_links(), {1: [(2, 0.9)]})
            main_mtime = self.db.stat().st_mtime_ns
            self.writer.execute('delete from links')
            self.writer.commit()
            self.assertEqual(self.db.stat().st_mtime_ns, main_mtime)
            self.assertEqual(brain.load_links(), {})
            with patch.object(brain, '_read_links', side_effect=AssertionError('cache miss')):
                self.assertEqual(brain.load_links(), {})

    def test_memory_translations_cover_call_sites_and_preserve_variables(self):
        import i18n

        source_files = ['code/tools/memory_maintenance.py', 'code/tools/dedupe_memories.py',
                        'code/tools/memory_claim.py', 'code/lab/memory_brain/companion_brain.py',
                        'code/plugins/astrbot_plugin_companion_memfix/main.py']
        keys = set()
        for relative in source_files:
            tree = ast.parse((ROOT / relative).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 't':
                    keys.add(node.args[0].value)
        catalogs = [json.loads((ROOT / 'locales' / ('memory.' + locale + '.json')).read_text())
                    for locale in i18n.LOCALES]
        for catalog in catalogs:
            self.assertTrue(keys.issubset(catalog))
            for key in keys:
                self.assertEqual(set(i18n._VARIABLE.findall(catalog[key])),
                                 set(i18n._VARIABLE.findall(catalogs[0][key])))
        self.assertEqual(i18n.t('memory.written', locale='en', count=2), 'Updated 2 memories')
        self.assertIn('2 筆', i18n.t('memory.written', locale='zh-TW', count=2))


if __name__ == '__main__':
    unittest.main()
