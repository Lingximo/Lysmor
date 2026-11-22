import importlib.util
import io
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")
spec = importlib.util.spec_from_file_location("lysmor_i18n_core_test", ROOT / "i18n.py")
i18n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(i18n)


class I18nCoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / "tmp/test")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "locales").mkdir()
        for locale, catalog in {
            "zh-CN": {"greeting": "你好，{name}", "fallback": "默认文案", "common.language": "语言"},
            "zh-TW": {"greeting": "你好，{name}", "common.language": "語言"},
            "en": {"greeting": "Hello, {name}", "common.language": "Language"},
        }.items():
            (self.root / "locales" / (locale + ".json")).write_text(json.dumps(catalog), encoding="utf-8")
        shutil.copyfile(ROOT / "i18n.js", self.root / "i18n.js")
        self.addCleanup(patch.stopall)
        patch.object(i18n, "ROOT", self.root).start()
        patch.dict(os.environ, {}, clear=True).start()

    def test_language_precedence_aliases_and_quality_header(self):
        (self.root / "config.json").write_text('{"language":"zh-TW"}', encoding="utf-8")
        self.assertEqual(i18n.language(), "zh-TW")
        os.environ["LYSMOR_LANGUAGE"] = "en-US"
        self.assertEqual(i18n.language(), "en")
        with i18n.locale_context("zh_Hant_HK"):
            self.assertEqual(i18n.language(), "zh-TW")
            self.assertEqual(i18n.language("zh"), "zh-CN")
        self.assertEqual(i18n.language(), "en")
        self.assertEqual(i18n.language_from_header("fr;q=1, zh-TW;q=0.5,en-US;q=0.9"), "en")
        self.assertIsNone(i18n.language_from_header("en;q=0,zh;q=invalid"))

    def test_interpolation_and_missing_key_fallback(self):
        self.assertEqual(i18n.t("greeting", locale="en", name="<b>A</b>"), "Hello, <b>A</b>")
        self.assertEqual(i18n.t("greeting", locale="en"), "Hello, {name}")
        self.assertEqual(i18n.t("fallback", locale="en"), "默认文案")
        self.assertEqual(i18n.t("unknown", locale="en"), "unknown")

    def test_fragment_merge_and_ambiguous_key_rejection(self):
        path = self.root / "locales/module.en.json"
        path.write_text('{"module.ready":"Ready"}', encoding="utf-8")
        self.assertEqual(i18n.t("module.ready", locale="en"), "Ready")
        path.write_text('{"greeting":"Conflicting"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Conflicting translation key"):
            i18n.load_catalog("en")

    def test_public_assets_allowlist_and_stdlib_response(self):
        self.assertIsNone(i18n.browser_asset("/locales/../../config.json"))
        self.assertIsNone(i18n.browser_asset("/locales/unsupported.json"))
        body, mime = i18n.browser_asset("/locales/en.json")
        self.assertEqual(json.loads(body)["greeting"], "Hello, {name}")
        self.assertTrue(mime.startswith("application/json"))
        handler = unittest.mock.Mock()
        handler.wfile = io.BytesIO()
        self.assertTrue(i18n.send_browser_asset(handler, "/i18n.js"))
        handler.send_response.assert_called_once_with(200)
        self.assertIn(b"LysmorI18n", handler.wfile.getvalue())

    @unittest.skipUnless(NODE, "Node.js is needed for browser runtime verification")
    def test_browser_runtime_switching_safe_text_and_variables(self):
        (self.root / "config.json").write_text('{"language":"en"}', encoding="utf-8")
        source = i18n.build_browser_asset().decode("utf-8")
        program = r"""
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = JSON.parse(process.argv[1]);
const text = { attrs: {'data-i18n':'greeting'}, textContent:'', getAttribute(k){return this.attrs[k];} };
const input = { attrs: {'data-i18n-placeholder':'greeting'}, value:'typed input', setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k];} };
const listeners = {};
const document = {readyState:'complete',documentElement:{lang:'zh-CN'}, querySelectorAll(s){return s==='[data-i18n]'?[text]:s==='[data-i18n-placeholder]'?[input]:[];}};
const window = { location:{search:'',href:'https://example.invalid/'},localStorage:{getItem(){throw Error('disabled');},setItem(){throw Error('disabled');}},history:{replaceState(){}},dispatchEvent(event){listeners[event.type]=event.detail;} };
const sandbox = {window,document,URL,URLSearchParams,WeakSet,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}}};
vm.runInNewContext(source,sandbox);
assert.equal(window.LysmorI18n.language(),'en');
assert.equal(text.textContent,'Hello, {name}');
assert.equal(input.value,'typed input');
assert.equal(input.attrs.placeholder,'Hello, {name}');
assert.equal(window.LysmorI18n.t('greeting',{name:'<script>alert(1)</script>'}),'Hello, <script>alert(1)</script>');
window.LysmorI18n.setLanguage('zh-Hant');
assert.equal(document.documentElement.lang,'zh-TW');
assert.equal(listeners['lysmor:languagechange'].language,'zh-TW');
assert.equal(text.textContent,'你好，{name}');
assert.equal(window.LysmorI18n.t('fallback'),'默认文案');
assert.equal(window.LysmorI18n.t('missing'),'missing');
"""
        result = subprocess.run([NODE, "-e", program, json.dumps(source)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class CatalogConsistencyTests(unittest.TestCase):
    def test_all_languages_have_matching_keys_and_interpolation_variables(self):
        catalogs = {locale: i18n.load_catalog(locale) for locale in i18n.LOCALES}
        baseline = catalogs[i18n.DEFAULT_LOCALE]
        for locale, catalog in catalogs.items():
            with self.subTest(locale=locale):
                self.assertEqual(set(catalog), set(baseline))
                for key, value in catalog.items():
                    self.assertEqual(set(re.findall(r"\{(\w+)\}", value)),
                                     set(re.findall(r"\{(\w+)\}", baseline[key])), key)


if __name__ == "__main__":
    unittest.main()
