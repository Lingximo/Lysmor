const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const catalogs = Object.fromEntries(['zh-CN', 'zh-TW', 'en'].map(lang => [lang, JSON.parse(fs.readFileSync(path.join(root, 'locales', `services.${lang}.json`)))]));
const attack = '<img src=x onerror=alert(1)>';

async function check(service) {
  const elements = new Map();
  const all = [];
  function element(tag = 'div') {
    const e = {tagName: tag, children: [], style: {}, dataset: {}, listeners: {}, value: '', hidden: false,
      appendChild(c) { this.children.push(c); return c; },
      addEventListener(name, callback) { this.listeners[name] = callback; },
      setAttribute(name, value) { this[name] = value; },
      focus() {},
      getBoundingClientRect() { return { left: 0, top: 0 }; },
      getContext() { return context; },
      querySelector(selector) { return this.parts[selector] ||= element(); }, parts: {}
    };
    Object.defineProperty(e, 'innerHTML', {set(value) { assert(!String(value).includes(attack), `${service} inserted user content as HTML`); this.html = value; this.children = []; }, get() { return this.html || ''; }});
    Object.defineProperty(e, 'textContent', {set(value) { this.text = String(value); this.children = []; }, get() { return this.text || ''; }});
    all.push(e);
    return e;
  }
  const context = new Proxy({}, {get(_, key) { if (String(key).startsWith('create')) return () => ({ addColorStop() {} }); return () => {}; }, set() { return true; }});
  const events = {};
  let locale = 'en';
  const i18n = {language() { return locale; }, applyText() {}, t(key, vars) { return (catalogs[locale][key] || key).replace(/\{(\w+)\}/g, (_, name) => vars?.[name] ?? `{${name}}`); }};
  const fixtures = {
    brain: { nodes: [{id: 1, importance: 0.5, topic: attack, summary: attack, t: attack}], links: [] },
    console: {t: 1, services: [{url: 'http://localhost', page: '/', name: attack, up: true}], life: {vitals: {custom: 0.3}, labels: {custom: attack}}, activities: [{t: attack, text: attack}], memory_count: 1},
    gallery: {works: [{image: attack, title: attack, note: attack, t: attack}]},
    house: {room: {w: 8, d: 6}, furniture: [{x: 4, y: 3, w: 0, d: 0, h: 1, color: '#ffffff', name: attack, note: attack}]},
    life: {t: 1, vitals: {custom: 0.3}, labels: {custom: attack}, notes: {custom: attack}, trend: []},
    webchat: {history: [{role: 'user', text: attack}]}
  };
  const sandbox = {console, URL, URLSearchParams, Date, Math, Promise, innerWidth: 800, innerHeight: 600, devicePixelRatio: 1,
    location: {search: '', href: 'http://localhost/'},
    document: {getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); }, createElement: element, createTextNode(text) { const node = element('#text'); node.textContent = text; return node; }},
    fetch() { return Promise.resolve({ok: true, json: async () => fixtures[service]}); },
    setInterval() {}, addEventListener(name, callback) { events[name] = callback; },
    window: {LysmorI18n: i18n}
  };
  vm.runInNewContext(fs.readFileSync(path.join(root, 'services', service, 'static/app.js'), 'utf8'), sandbox);
  await new Promise(resolve => setImmediate(resolve));
  if (service === 'brain') elements.get('sky').listeners.mousemove({clientX: 440, clientY: 300});
  if (service === 'house') elements.get('room').listeners.mousemove({clientX: 400, clientY: 300});
  assert(all.some(e => e.textContent.includes(attack)), `${service} must preserve user data as text`);
  if (service === 'gallery') assert.equal(elements.get('count').textContent, '1 works');
  if (service === 'webchat') assert.equal(elements.get('status-text').textContent, 'Online');
  locale = 'zh-TW';
  events['lysmor:languagechange']();
  await new Promise(resolve => setImmediate(resolve));
  if (service === 'gallery') assert.equal(elements.get('count').textContent, '1 件作品');
  if (service === 'webchat') assert.equal(elements.get('status-text').textContent, '在線');
}
(async () => { for (const service of ['brain', 'console', 'gallery', 'house', 'life', 'webchat']) await check(service); console.log('Six service DOM rendering and language-switch regressions passed'); })().catch(error => {console.error(error); process.exitCode = 1;});
