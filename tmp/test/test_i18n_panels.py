import json
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PANELS = [ROOT / 'code' / name / 'static' for name in ('lifeviz', 'brainviz', 'houseviz')]


class PanelI18nTests(unittest.TestCase):
    def test_all_panel_keys_exist_in_three_catalogs_with_matching_parameters(self):
        catalogs = [json.loads((ROOT / 'locales' / f'panels.{locale}.json').read_text())
                    for locale in ('zh-CN', 'zh-TW', 'en')]
        self.assertEqual(set(catalogs[0]), set(catalogs[1]))
        self.assertEqual(set(catalogs[0]), set(catalogs[2]))
        keys = set()
        for folder in PANELS:
            for path in list(folder.glob('*.js')) + list(folder.glob('*.html')):
                keys.update(re.findall(r'[\'"](panels\.[\w.]+)[\'"]', path.read_text()))
        self.assertTrue(keys)
        for key in keys:
            for catalog in catalogs:
                self.assertIn(key, catalog)
            placeholders = [set(re.findall(r'\{(\w+)\}', catalog[key])) for catalog in catalogs]
            self.assertEqual(placeholders[0], placeholders[1], key)
            self.assertEqual(placeholders[0], placeholders[2], key)
        self.assertNotEqual(catalogs[0]['panels.memory_title'], catalogs[1]['panels.memory_title'])
        self.assertEqual(catalogs[2]['panels.silence_minutes'], 'No conversation for {minutes} minutes')

    def test_pages_load_core_before_app_and_offer_language_selection(self):
        for folder in PANELS:
            for path in folder.glob('*.html'):
                source = path.read_text()
                with self.subTest(page=path.name, panel=folder.parent.name):
                    self.assertIn('<script src="/i18n.js"></script>', source)
                    self.assertIn('mountLanguageSelector', source)
                    self.assertLess(source.index('/i18n.js'), source.index('mountLanguageSelector'))
                    self.assertNotRegex(source, r'<title>\s*<span')
        house = (PANELS[2] / 'app.js').read_text()
        self.assertIn("f.note === '她的床'", house, 'Wire-value comparisons must stay unchanged')
        brain = (PANELS[1] / 'app.js').read_text()
        self.assertIn('data.phases[name]', brain, 'Backend phase keys must not be translated')

    @unittest.skipUnless(shutil.which('node'), 'Node is required for browser-side checks')
    def test_javascript_syntax_and_life_language_change_preserve_state(self):
        for folder in PANELS:
            for path in folder.glob('*.js'):
                result = subprocess.run(['node', '--check', str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
        script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const elements = new Map(), handlers = {};
function element(id) {
  if (!elements.has(id)) elements.set(id, {style:{}, className:'', textContent:'', innerHTML:'',
    classList:{toggle(){}}, children:[], appendChild(row){this.children.push(row);}, setAttribute(){}});
  return elements.get(id);
}
const catalogs = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
let language = 'zh-CN';
const context = {document:{getElementById:element, createElement:()=>element(Symbol())},
  window:{LysmorI18n:{t:(key, vars)=> {
    let value = catalogs[language][key] || key;
    return value.replace(/\{(\w+)\}/g,(m,k)=>vars && k in vars ? vars[k] : m);
  }, language:()=>language}, addEventListener:(name, fn)=>handlers[name]=fn},
  fetch:()=>Promise.reject(new Error('offline')), setInterval(){}, Date, console};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), context);
const chinese = element('bars').children[0].innerHTML;
assert(chinese.includes('多巴胺'));
context.window.__endoState = {hunger:0.2, thirst:0.3, dopamine:0.5, oxytocin:0.5,
  cortisol:0.2, serotonin:0.5, noradrenaline:0.2, last_meal_name:'user meal'};
language = 'en';
handlers['lysmor:languagechange']();
assert(element('bars').children.at(-5).innerHTML.includes('Dopamine'));
assert(element('intake-line').innerHTML.includes('user meal'));
assert(element('hunger-val').textContent === 20);
context.fetch = ()=>Promise.resolve({json:()=>Promise.resolve({sick:false})});
vm.runInContext(fs.readFileSync(process.argv[3], 'utf8'), context);
setImmediate(()=> {
  assert.equal(element('sick-state').textContent, 'Healthy');
  assert.equal(element('sick-plan').children.at(-1).textContent, 'Healthy: keep eating and sleeping regularly.');
});
'''
        catalogs = {locale: json.loads((ROOT / 'locales' / f'panels.{locale}.json').read_text())
                    for locale in ('zh-CN', 'en')}
        fixture = ROOT / 'tmp' / 'test' / 'test_panels_catalogs.json'
        fixture.write_text(json.dumps(catalogs, ensure_ascii=False))
        result = subprocess.run(['node', '-e', script, str(fixture), str(PANELS[0] / 'app.js'), str(PANELS[0] / 'sick.js')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
