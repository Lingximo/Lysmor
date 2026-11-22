import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location('nirvana_' + name, ROOT / 'tools/nirvana' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NirvanaReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / 'tmp/test')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def archive(self, entries, listed=None):
        path = self.root / 'backup.tar.gz'
        manifest = {'files': [{'path': name, 'sha256': hashlib.sha256(data).hexdigest()}
                              for name, data in entries if listed is None or name in listed]}
        with tarfile.open(path, 'w:gz') as tar:
            for name, data in entries + [('manifest.json', json.dumps(manifest).encode())]:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return path, manifest

    def test_restore_routes_framework_config_and_plugin_data_to_original_locations(self):
        restore = load('restore')
        stage = self.root / 'stage'
        (stage / 'config/bot').mkdir(parents=True)
        (stage / 'config/bot/config.json').write_text('{"configured":true}')
        (stage / 'state/plugin_data/companion').mkdir(parents=True)
        (stage / 'state/plugin_data/companion/state.json').write_text('{"memory":1}')
        (stage / 'state/general.json').write_text('{}')
        targets = {}
        for name, target in restore.MOUNTS.items():
            if name.startswith('config/bot') or name == 'state/plugin_data':
                targets[name] = str(self.root / 'bot' / ('plugin_data' if name == 'state/plugin_data' else 'config.json'))
            else:
                targets[name] = str(self.root / 'live' / name)
        with patch.object(restore, 'MOUNTS', targets), contextlib.redirect_stdout(io.StringIO()):
            restore.place(str(stage), live=True)
        self.assertTrue((self.root / 'bot/config.json').is_file())
        self.assertTrue((self.root / 'bot/plugin_data/companion/state.json').is_file())
        self.assertTrue((self.root / 'live/state/general.json').is_file())
        self.assertFalse((self.root / 'live/state/plugin_data').exists())

    def test_manifest_rejects_unlisted_files_duplicates_and_links(self):
        restore = load('restore')
        path, manifest = self.archive([('memory/a.txt', b'checked'), ('memory/injected.txt', b'unchecked')], {'memory/a.txt'})
        self.assertIn(('memory/injected.txt', '文件不在校验清单内'), restore.verify(path, manifest))
        path, manifest = self.archive([('memory/a.txt', b'first'), ('memory/a.txt', b'second')])
        self.assertTrue(restore.verify(path, manifest))
        with tarfile.open(path, 'w:gz') as tar:
            info = tarfile.TarInfo('memory/link')
            info.type = tarfile.SYMTYPE
            info.linkname = '../outside'
            tar.addfile(info)
        self.assertTrue(restore.verify(path, {'files': []}))

    def test_corrupt_database_snapshot_does_not_replace_previous_backup(self):
        build = load('build')
        out = self.root / 'backup/out'
        out.mkdir(parents=True)
        existing = out / 'backup_fixed.tar.gz'
        existing.write_bytes(b'previous valid backup')
        (out / 'latest.json').write_text('{"path":"previous"}')
        database = self.root / 'broken.db'
        database.write_bytes(b'not a sqlite database')
        with patch.multiple(build, ROOT=str(self.root), OUT=str(out)), \
                patch.object(build, 'collect', return_value=[(str(database), 'memory/memory.db')]), \
                patch.object(build, 'coverage_warnings'), patch.object(build, 'db_stats', return_value={}), \
                patch.object(build.time, 'strftime', return_value='fixed'), \
                patch.object(build.sys, 'stdout', io.StringIO()), \
                patch.object(build.sys.stdout, 'reconfigure', create=True):
            with self.assertRaises(RuntimeError):
                build.main()
        self.assertEqual(existing.read_bytes(), b'previous valid backup')
        self.assertEqual(json.loads((out / 'latest.json').read_text()), {'path': 'previous'})
        self.assertFalse(list(out.glob('.backup-*')))

    def test_wal_database_is_restorable_with_matching_manifest(self):
        build, restore = load('build'), load('restore')
        database = self.root / 'live.db'
        con = sqlite3.connect(database)
        self.addCleanup(con.close)
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('CREATE TABLE documents (text TEXT)')
        con.execute('INSERT INTO documents VALUES (?)', ('latest committed memory',))
        con.commit()
        out = self.root / 'backup/out'
        with patch.multiple(build, ROOT=str(self.root), OUT=str(out)), \
                patch.object(build, 'collect', return_value=[(str(database), 'memory/memory.db')]), \
                patch.object(build, 'coverage_warnings'), patch.object(build, 'db_stats', return_value={}), \
                patch.object(build, 'local_complete_snapshot'), patch.object(build.sys, 'stdout', io.StringIO()), \
                patch.object(build.sys.stdout, 'reconfigure', create=True):
            archive = build.main()
        manifest = restore.read_manifest(archive)
        self.assertEqual(restore.verify(archive, manifest), [])
        dest = self.root / 'restore'
        with contextlib.redirect_stdout(io.StringIO()):
            restore.extract(archive, dest)
        with sqlite3.connect(dest / 'memory/memory.db') as recovered:
            self.assertEqual(recovered.execute('SELECT text FROM documents').fetchone()[0], 'latest committed memory')


if __name__ == '__main__':
    unittest.main()
