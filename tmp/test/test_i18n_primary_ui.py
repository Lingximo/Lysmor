import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PAGES = ('code/hub/static/index.html', 'code/webchat/static/index.html', 'code/webchat/static/doodle.html')


class PrimaryI18NTests(unittest.TestCase):
    def test_catalog_parity_and_interpolation(self):
        catalogs = [json.loads((ROOT / ('locales/primary.' + locale + '.json')).read_text())
                    for locale in ('zh-CN', 'zh-TW', 'en')]
        self.assertEqual(set(catalogs[0]), set(catalogs[1]))
        self.assertEqual(set(catalogs[0]), set(catalogs[2]))
        for key, value in catalogs[0].items():
            placeholders = set(re.findall(r'\{(\w+)\}', value))
            for catalog in catalogs[1:]:
                self.assertEqual(placeholders, set(re.findall(r'\{(\w+)\}', catalog[key])), key)
        for name in PAGES:
            page = (ROOT / name).read_text()
            keys = set(re.findall(r'[\'"](primary\.[\w.]+)[\'"]', page))
            self.assertTrue(keys, name)
            self.assertTrue(keys.issubset(catalogs[0]), keys - catalogs[0].keys())
            self.assertIn('<script src="/i18n.js"></script>', page)
            self.assertIn('data-language-select', page)

    def test_inline_scripts_are_valid_and_ui_renders_selected_language(self):
        spec = importlib.util.spec_from_file_location('primary_i18n_fixture', ROOT / 'i18n.py')
        core = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(core)
        harness = r'''
const vm=require('vm');
const fs=require('fs');
const assert=require('assert');
class Element {
  constructor(tag='div') { this.tag=tag; this.children=[]; this.dataset={}; this.style={}; this.attributes={}; this.textContent=''; this.hidden=false; this.classList={toggle(){},add(){},remove(){}}; }
  appendChild(e){this.children.push(e);return e;}
  replaceChildren(){this.children=[];}
  addEventListener(){}
  focus(){}
  getAttribute(k){return this.attributes[k];}
  setAttribute(k,v){this.attributes[k]=v;}
  querySelectorAll(){return [];}
}
const elements=new Map();
const element=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const document={readyState:'complete',documentElement:{lang:'zh-CN'},querySelectorAll(){return [];},getElementById:element,createElement:t=>new Element(t),createTextNode:t=>({textContent:t}),addEventListener(){}};
const data={her:{energy:0.5},services:[],memory:{documents:3},source:'desktop',turns:2,avg_latency_ms:5,avg_selected:1,avg_chars:7,recent:[]};
const events={};
const window={location:{search:'?lang=en',hostname:'localhost',hash:'',href:'http://localhost/?lang=en'},history:{replaceState(){}},localStorage:{getItem(){return null;},setItem(){}},addEventListener:(name,fn)=>{(events[name]??=[]).push(fn);},dispatchEvent:e=>{for(const f of events[e.type]||[])f(e);},open(){}};
window.window=window;
const context={window,document,location:window.location,history:window.history,localStorage:window.localStorage,URL,URLSearchParams,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},navigator:{},fetch:async path=>({json:async()=>path.includes('art')||path.includes('doodles')?[]:data,ok:true}),setInterval(){},Audio:class{setAttribute(){} play(){return Promise.resolve();}},console,FileReader:class{}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
const page=fs.readFileSync(process.argv[3],'utf8');
for(const script of page.matchAll(/<script>([\s\S]*?)<\/script>/g))vm.runInContext(script[1],context);
if(process.argv[3].includes('/hub/')){
 assert.strictEqual(element('apps').children[0].children[0].textContent,'Her · Now');
 element('apps').children[0].onclick();
 assert.ok(element('appframe').src.includes('lang=en'));
 window.LysmorI18n.setLanguage('zh-TW');
 assert.strictEqual(element('apps').children[0].children[0].textContent,'她 · 此刻');
 assert.strictEqual(element('outing-btn').textContent,'帶TA出門');
}
if(process.argv[3].endsWith('/webchat/static/index.html')){
 assert.strictEqual(element('vox').title,'Voice playback: on');
 window.LysmorI18n.setLanguage('zh-TW');
 assert.strictEqual(element('vox').title,'語音播報：開');
}
'''
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp/test', prefix='test_primary_ui_') as directory:
            directory = Path(directory)
            asset = directory / 'i18n.js'
            asset.write_bytes(core.build_browser_asset())
            runner = directory / 'runner.cjs'
            runner.write_text(harness)
            for name in PAGES:
                result = subprocess.run(['node', str(runner), str(asset), str(ROOT / name)],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, name + '\n' + result.stderr)


if __name__ == '__main__':
    unittest.main()
