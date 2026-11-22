import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class VideoI18NTests(unittest.TestCase):
    def test_catalog_parity_and_interpolation(self):
        catalogs = [json.loads((ROOT / ('locales/video.' + locale + '.json')).read_text())
                    for locale in ('zh-CN', 'zh-TW', 'en')]
        self.assertEqual(set(catalogs[0]), set(catalogs[1]))
        self.assertEqual(set(catalogs[0]), set(catalogs[2]))
        for key, value in catalogs[0].items():
            placeholders = set(re.findall(r'\{(\w+)\}', value))
            for catalog in catalogs[1:]:
                self.assertEqual(placeholders, set(re.findall(r'\{(\w+)\}', catalog[key])), key)
        for name in ('code/video/static/index.html', 'code/video/static/app.js'):
            page = (ROOT / name).read_text()
            keys = set(re.findall(r'[\'"](video\.[\w.]+)[\'"]', page))
            self.assertTrue(keys.issubset(catalogs[0]), keys - catalogs[0].keys())
        result = subprocess.run(['node', '--check', str(ROOT / 'code/video/static/app.js')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_live_status_survives_language_change(self):
        spec = importlib.util.spec_from_file_location('video_i18n_fixture', ROOT / 'i18n.py')
        core = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(core)
        source = (ROOT / 'code/video/static/app.js').read_text()
        prefix = source.split('// 前端诊断', 1)[0]
        change = source[source.rindex("window.addEventListener('lysmor:languagechange'"):]
        harness = r'''
const vm=require('vm'), fs=require('fs'), assert=require('assert');
const elements=new Map();
const node=id=>{if(!elements.has(id))elements.set(id,{textContent:'',getAttribute(){return null;},removeAttribute(){}});return elements.get(id);};
const events={};
const document={readyState:'complete',documentElement:{lang:'zh-CN'},querySelectorAll(){return [];},getElementById:node};
const window={location:{search:'?lang=en',href:'http://localhost/?lang=en'},localStorage:{getItem(){return null;},setItem(){}},history:{replaceState(){}},addEventListener:(name,fn)=>{(events[name]??=[]).push(fn);},dispatchEvent:event=>{for(const fn of events[event.type]||[])fn(event);}};
const context={window,document,URL,URLSearchParams,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
vm.runInContext(fs.readFileSync(process.argv[3],'utf8'),context);
vm.runInContext("document.getElementById('status').textContent=vt('video.lens_open',{lens:vt('video.rear')});",context);
assert.strictEqual(node('status').textContent,'Camera is on · Rear');
window.LysmorI18n.setLanguage('zh-TW');
assert.strictEqual(node('status').textContent,'攝影機已開啟 · 後置鏡頭');
vm.runInContext("document.getElementById('status').textContent='user supplied state';",context);
window.LysmorI18n.setLanguage('en');
assert.strictEqual(node('status').textContent,'user supplied state');
'''
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp/test', prefix='test_video_i18n_') as directory:
            directory = Path(directory)
            asset = directory / 'i18n.js'
            asset.write_bytes(core.build_browser_asset())
            test_source = directory / 'video.js'
            test_source.write_text(prefix + '\n' + change)
            runner = directory / 'test.cjs'
            runner.write_text(harness)
            result = subprocess.run(['node', str(runner), str(asset), str(test_source)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
