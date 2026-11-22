const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const root = path.resolve(__dirname, '../..');
const read = file => readFileSync(path.join(root, file), 'utf8');
const html = read('code/video/static/playalong.html');
const asset = execFileSync('python3', ['-B', '-c',
  'import sys, i18n; sys.stdout.buffer.write(i18n.browser_asset("/i18n.js")[0])'], {cwd:root, encoding:'utf8'});
const locales = ['zh-CN', 'zh-TW', 'en'];
const fragments = Object.fromEntries(locales.map(locale => [locale, JSON.parse(read(`locales/playalong.${locale}.json`))]));

test('source catalogs cover the page without fixed service ports', () => {
  assert.match(html, /<script src="\/i18n\.js"><\/script>/);
  const keys = [...new Set(html.match(/playalong\.\w+/g))].sort();
  for (const catalog of Object.values(fragments)) {
    assert.deepEqual(Object.keys(catalog).sort(), keys);
    assert.doesNotMatch(catalog['playalong.state_unavailable'], /\d/);
    for (const key of keys) {
      assert.ok(catalog[key].trim());
      assert.deepEqual(catalog[key].match(/\{\w+\}/g) || [],
        ['playalong.pets', 'playalong.overlays'].includes(key) ? ['{count}'] : []);
    }
  }
});

function openPage(locale) {
  const elements = Array.from(html.matchAll(/<([\w-]+)\b([^<>]*)>/g), ([, tag, attrs]) => {
    const attributes = Object.fromEntries(Array.from(attrs.matchAll(/\b(id|data-i18n|data-language-select)(?:="([^"]*)")?/g),
      ([, name, value]) => [name, value || '']));
    return {tag, attributes, textContent:'', options:[], classList:{toggle(name, value) { this[name] = value; }},
      getAttribute(name) { return attributes[name]; }, setAttribute(name, value) { attributes[name] = value; },
      appendChild(option) { this.options.push(option); }, addEventListener(name, handler) { this[name] = handler; }};
  });
  const byId = id => elements.find(element => element.attributes.id === id);
  const document = {readyState:'complete', documentElement:{lang:'zh-CN'}, createElement:() => ({}),
    querySelector:selector => byId(selector.slice(1)),
    querySelectorAll:selector => elements.filter(element => Object.hasOwn(element.attributes, selector.slice(1,-1)))};
  const events = new Map();
  const window = {location:new URL(`http://localhost:49123/playalong?lang=${locale}`),
    addEventListener(name, handler) { events.set(name, handler); }, dispatchEvent(event) { events.get(event.type)?.(); }};
  const api = {state:{on:false}, status:200, action:{ok:true}, calls:[]};
  async function fetch(url, options) {
    api.calls.push({url, ...options});
    const status = url.endsWith('/state') ? api.status : 200;
    return {status, ok:status === 200, json:async () => url.endsWith('/state') ? api.state : api.action};
  }
  const context = vm.createContext({window, document, URL, URLSearchParams, fetch,
    CustomEvent:class { constructor(type) { this.type = type; } },
    setInterval(handler, delay) { assert.equal(delay, 5000); api.poll = handler; }});
  vm.runInContext(asset, context);
  vm.runInContext(html.match(/<script type="module">([^]*?)<\/script>/)[1], context);
  return {api, byId, elements, i18n:window.LysmorI18n};
}

for (const locale of locales) test(`${locale}: enter, start, switch, stop, emergency stop, failure`, async () => {
  const {api, byId, elements, i18n} = openPage(locale);
  const text = id => byId(id).textContent;
  const translated = key => fragments[i18n.language()]['playalong.' + key];
  const checkLog = (action, result) => assert.ok(text('log').split('\n')[0].endsWith(`${translated(action)} → ${result}`));
  assert.equal(i18n.language(), locale);
  assert.equal(text('label'), i18n.t('common.loading'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(text('label'), i18n.t('video.play_off'));
  for (const element of elements.filter(node => node.attributes['data-i18n'])) {
    assert.equal(element.textContent, fragments[locale][element.attributes['data-i18n']]);
  }
  api.state = {on:true, pet_clients:2, overlay_pids:[13]};
  await byId('on').onclick();
  const command = api.calls.at(-2);
  assert.equal(command.url, '/api/companion/toggle');
  assert.equal(command.method, 'POST');
  assert.equal(command.headers['Accept-Language'], locale);
  assert.equal(command.body, '{"on":true}');
  assert.equal(text('label'), translated('pets').replace('{count}', '2'));
  checkLog('start', translated('done'));
  const selector = elements.find(node => node.tag === 'select');
  selector.value = locales[(locales.indexOf(locale) + 1) % locales.length];
  selector.change();
  assert.equal(i18n.language(), selector.value);
  checkLog('start', translated('done'));
  assert.equal(text('label'), translated('pets').replace('{count}', '2'));
  api.state.pet_clients = 0;
  await api.poll();
  assert.equal(text('label'), translated('overlays').replace('{count}', '1'));
  api.state = {on:false};
  await byId('off').onclick();
  assert.equal(api.calls.at(-2).body, '{"on":false}');
  checkLog('stop', translated('done'));
  api.action = {ok:true, screen:{ok:false}};
  await byId('panic').onclick();
  assert.equal(api.calls.at(-2).url, '/api/companion/panic');
  assert.equal(api.calls.at(-2).method, 'POST');
  checkLog('panic', translated('screen_failed'));
  api.action = {ok:true, errors:['overlay:error']};
  await byId('panic').onclick();
  checkLog('panic', translated('incomplete'));
  api.action = {ok:false, mode:'none'};
  await byId('on').onclick();
  checkLog('start', i18n.t('http.error.pet_disconnected'));
  api.status = 401;
  await api.poll();
  assert.equal(text('label'), i18n.t('http.auth.required'));
  api.status = 503;
  await api.poll();
  assert.equal(text('label'), translated('state_unavailable'));
});
