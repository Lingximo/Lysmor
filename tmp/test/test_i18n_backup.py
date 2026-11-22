import ast
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import i18n


class Output(io.StringIO):
    def reconfigure(self, **kwargs):
        pass


class BackupI18NTests(unittest.TestCase):
    def test_upload_cli_uses_translator_without_local_name_shadowing(self):
        spec = importlib.util.spec_from_file_location('backup_upload_i18n_test', ROOT / 'tools/nirvana/upload.py')
        upload = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(upload)
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp/test') as temporary:
            root = Path(temporary)
            archive = root / 'fixture.tar.gz'
            archive.write_bytes(b'archive fixture')
            (root / 'latest.json').write_text(json.dumps({'path': str(archive), 'created': 'fixture',
                                                        'sha256': 'fixture-hash', 'size': archive.stat().st_size}))
            with patch.multiple(upload, OUT=str(root), TMP=str(root / 'parts'),
                                STATE_FILE=str(root / 'state.json'), LOG_FILE=str(root / 'log.txt')), \
                    patch.object(sys, 'argv', ['upload.py', '--upload-only']), \
                    patch.dict(sys.modules, {'kit': type('Kit', (), {'main': staticmethod(lambda: 0)})()}), \
                    i18n.locale_context('en'), contextlib.redirect_stdout(Output()) as output:
                self.assertEqual(upload.main(), 0)
            self.assertIn('No cloud integration', output.getvalue())
            self.assertFalse(json.loads((root / 'state.json').read_text())['verified'])

    def test_catalogs_match_and_preserve_printf_arguments(self):
        catalogs = {locale: json.loads((ROOT / 'locales' / ('nirvana.' + locale + '.json')).read_text())
                    for locale in i18n.LOCALES}
        expected = set(catalogs['zh-CN'])
        for locale, catalog in catalogs.items():
            self.assertEqual(set(catalog), expected)
            for key, value in catalog.items():
                self.assertEqual(re.findall(r'%(?:[-+0-9.]*[sdif])', value),
                                 re.findall(r'%(?:[-+0-9.]*[sdif])', catalogs['zh-CN'][key]), (locale, key))
        self.assertEqual(i18n.t('nirvana.memory_database', locale='zh-TW'), '記憶庫')
        self.assertEqual(i18n.t('nirvana.memory_database', locale='en'), 'Memory database')

    def test_user_messages_are_catalogued_in_all_tools(self):
        for path in (ROOT / 'tools/nirvana').glob('*.py'):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 't':
                    self.assertTrue(node.args and isinstance(node.args[0], ast.Constant))
                    for locale in i18n.LOCALES:
                        self.assertNotEqual(i18n.t(node.args[0].value, locale=locale), node.args[0].value)

    def test_standalone_emergency_kit_contains_translations(self):
        spec = importlib.util.spec_from_file_location('backup_kit_i18n_test', ROOT / 'tools/nirvana/kit.py')
        kit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(kit)
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp/test') as temporary:
            root = Path(temporary)
            out = root / 'backup/out'
            out.mkdir(parents=True)
            archive = out / 'backup_fixture.tar.gz'
            archive.write_bytes(b'fixture archive')
            (out / 'latest.json').write_text(json.dumps({'path': str(archive)}))
            destination = out / 'kit'
            with patch.multiple(kit, ROOT=str(root), NIRVANA=str(ROOT / 'tools/nirvana'),
                                OUT=str(out), KIT=str(destination)), \
                    patch.object(sys, 'argv', ['kit.py']), i18n.locale_context('en'), \
                    contextlib.redirect_stdout(Output()):
                self.assertEqual(kit.main(), 0)
            self.assertTrue((destination / 'i18n.py').is_file())
            self.assertTrue((destination / 'i18n.js').is_file())
            self.assertTrue((destination / 'locales/nirvana.en.json').is_file())
            self.assertIn('Read README.md first', (destination / '1-先看我.bat').read_text())
            result = subprocess.run([sys.executable, str(destination / 'restore.py'), '--cloud'],
                                    cwd=root, env={**os.environ, 'LYSMOR_LANGUAGE': 'en'},
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Cloud downloads require a cloud drive integration', result.stdout)
            self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
