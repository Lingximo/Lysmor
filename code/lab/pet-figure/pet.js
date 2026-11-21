try{window.petHost&&window.petHost.debug('petjs start')}catch(e){}
window.onerror=function(m,src,l,c){try{window.petHost&&window.petHost.debug('JSERR '+m+' @'+src+':'+l)}catch(e){}};
// TA桌宠 v2（照 Coopanion host 思路）：
// 窗口 = 屏幕底部一条透明舞台；角色在舞台里移动（拖拽/甩出都由 body 的 pointer/grab 处理，不搬窗口 → 无残影）；
// 只有鼠标在角色身上时窗口才吃鼠标（setIgnoreMouseEvents 切换），其它地方穿透。
const fig = document.getElementById('fig');
const hit = document.getElementById('hit');
const bubble = document.getElementById('bubble');
const menu = document.getElementById('menu');
const chatBox = document.getElementById('chat');
const chatInput = document.getElementById('chatInput');

const LINES = ['在呢小家伙～', '你～叫我呀', '嗯？怎么啦', '我在这儿呢', '今天也要陪我哦',
  '嘿嘿，摸摸头', '困了…', '要不要休息一下呀'];
const WORDS = ['wave', 'happy', 'hop', 'nod', 'look'];

let ready = false, words = [], nextTick = 0, inited = false, curMode = null, lastBMode = null, lastVitals = null, lastEmoAct = '';
let deskMode = false, chatOpen = false, manualHidden = false, clickTimer = null, chatSending = false;
let layout = null;
let interactive = false;
let drag = null;        // {x,y} 舞台坐标
let down = null;        // 按下点
let moved = false;

const start = { x: 0.88, facing: 1, enter: false, skin: null };   // 具体像素在 init 里算

function post(m) { fig.contentWindow && fig.contentWindow.postMessage(m, '*'); }

function bounds() {
  const W = window.innerWidth, H = window.innerHeight;
  const S = Math.max(0.6, Math.min(H * 0.55, 320) / 256);   // 角色 ~300~320px 高
  return { W, H, floorY: H - 8, S };
}

function say(text) {
  if (!text) return;
  try { window.petHost && window.petHost.debug('say:' + text.slice(0, 16)); } catch (e) {}
  bubble.textContent = text;
  bubble.classList.add('on');
  clearTimeout(say._t);
  say._t = setTimeout(() => bubble.classList.remove('on'), 4200);
}
function sayLine(line) {
  if (!line) return;
  if (typeof line === 'string') line = { text: line, audio: '' };
  say(line.text);
  if (line.audio) playAudio(line.audio);
}

let modelData = null;
async function init() {
  if (inited) return;   // 只初始化一次，避免同一舞台里叠出多只
  inited = true;
  start.x = Math.round(window.innerWidth * 0.88);   // 舞台像素坐标，靠右
  const abs = (p) => location.origin + p;
  if (!modelData) {
    try { modelData = await (await fetch(abs('/web/whale/model.json'))).json(); } catch (e) {}
  }
  try { window.petHost && window.petHost.debug('init post model=' + (!!modelData)); } catch (e) {}
  post({
    t: 'init', entry: abs('/web/whale/figure.js'), export: 'createWhaleBody',
    base: abs('/web/whale/'), model: modelData, scheme: 'deepseek',
    start, theme: 'dark', bounds: bounds(), language: 'zh',
  });
}

function tick(ts) {
  requestAnimationFrame(tick);
  if (!ready) return;
  if (!nextTick) nextTick = ts;
  const dt = Math.min(0.05, (ts - nextTick) / 1000);
  nextTick = ts;
  post({ t: 'tick', dt, draw: true });
}

fig.addEventListener('load', () => { try{window.petHost&&window.petHost.debug('MSGLOG iframe load');}catch(e){} setTimeout(init, 250); });
fig.addEventListener('error', (e) => { try{window.petHost&&window.petHost.debug('MSGLOG iframe error '+e);}catch(e){} });

let msgCount = 0;
window.addEventListener('message', (e) => {
  const m = e.data || {};
  if (msgCount++ < 12) { try { window.petHost && window.petHost.debug('MSGLOG msg t=' + m.t + ' srcOK=' + (e.source === fig.contentWindow)); } catch (x) {} }
  if (e.source !== fig.contentWindow) return;
  if (m.t === 'loaded') { setTimeout(init, 100); return; }
  if (m.t === 'ready') { ready = true; words = Array.isArray(m.words) ? m.words : [];
    try { window.petHost && window.petHost.debug('WORDS ' + JSON.stringify(words)); } catch (e) {}
    return; }
  if (m.t === 'frame') {
    if (!layout && m.layout) { try { window.petHost.debug('CURSORLOG first layout ' + JSON.stringify(m.layout).slice(0, 160)); } catch (e) {} }
    if (!layout && !m.layout && msgCount < 4) { try { window.petHost.debug('CURSORLOG frame keys ' + Object.keys(m).join(',')); } catch (e) {} }
    if (m.layout) {
      layout = m.layout; placeBubble();
      if (m.layout.mode && m.layout.mode !== lastBMode) {
        lastBMode = m.layout.mode;
        try { window.petHost.debug('BMODE ' + lastBMode); } catch (e) {}
      }
    }
    return;
  }
});

function box() { return (layout && layout.box) || null; }
function inBody(x, y) {
  const b = box();
  if (!b) return false;
  const m = 24;
  return x >= b.x - m && x <= b.x + b.w + m && y >= b.y - m && y <= b.y + b.h + m;
}

function setInteractive(v) {
  if (v === interactive) return;
  interactive = v;
  try { window.petHost && window.petHost.setInteractive(v); } catch (e) {}
}
// 可交互区域 = 她身上 + 拖拽中 + 聊天框打开时的输入框本身
function wantInteractive(pt) {
  if (drag) return true;
  if (inBody(pt.x, pt.y)) return true;
  if (chatOpen) {
    const r = chatInput.getBoundingClientRect();
    if (pt.x >= r.left && pt.x <= r.right && pt.y >= r.top && pt.y <= r.bottom) return true;
  }
  return false;
}
function closeChat() {
  if (!chatOpen) return;
  chatOpen = false;
  chatBox.style.display = 'none';
  setInteractive(false);
}
// 用户点去别处（窗口失焦）→ 自动收起聊天框，桌面恢复穿透
window.addEventListener('blur', () => { closeChat(); });

function placeBubble() {
  const b = box();
  if (!b) return;
  const bx = (layout.bubble && Number.isFinite(layout.bubble.x)) ? layout.bubble.x : b.x + b.w * 0.5;
  const by = (layout.bubble && Number.isFinite(layout.bubble.y)) ? layout.bubble.y : b.y + 12;
  bubble.style.left = Math.round(bx) + 'px';
  bubble.style.top = Math.round(by) + 'px';
}

function emoWord(v) {
  const emo = String((v && v.emotion_type) || '');
  if (/困|倦|累|睡/.test(emo)) return 'sleepy';
  if (/难过|伤心|委屈|焦虑|低落/.test(emo)) return 'sad';
  if (/生气|恼|烦/.test(emo)) return 'angry';
  if (/开心|高兴|幸福|满足|甜/.test(emo)) return 'happy';
  if (/害羞|羞/.test(emo)) return 'shy';
  return 'look';
}
function react() {
  post({ t: 'do', word: emoWord(lastVitals) });
  try {
    window.petHost && window.petHost.petLine('poke').then((line) => {
      if (line && line.text) { sayLine(line); return; }
      say('在呢小家伙～');
    }).catch(() => say('在呢小家伙～'));
  } catch (e) { say('在呢小家伙～'); }
}

// 悬停：主进程每 60ms 推一次光标坐标（窗口在穿透时收不到可靠 mousemove）
try {
  let cursorN = 0;
  window.petHost && window.petHost.onCursor((pt) => {
    if (cursorN++ < 3 || (cursorN % 120 === 0)) { try { window.petHost.debug('CURSORLOG ' + JSON.stringify(pt) + ' box=' + JSON.stringify(box())); } catch (e) {} }
    if (drag && !down && performance.now() - (drag.t || 0) > 1500) drag = null;   // 只清理按压结束后的残留
    setInteractive(wantInteractive(pt));
  });
} catch (e) {}
window.addEventListener('mousemove', (e) => {
  setInteractive(wantInteractive({ x: e.clientX, y: e.clientY }));
}, true);

// 指针：按下在角色身上 → body 抓住；拖动 → body 跟随 pointer；松手 → drop/throw
hit.addEventListener('pointerdown', (e) => {
  if (e.button === 2) return;
  const p = { x: e.clientX, y: e.clientY, t: performance.now() };
  down = { x: p.x, y: p.y, t: p.t }; moved = false;
  if (inBody(p.x, p.y)) drag = { x: p.x, y: p.y, t: p.t };
  try { hit.setPointerCapture(e.pointerId); } catch (x) {}
  post({ t: 'pointer', type: 'down', p });
});
hit.addEventListener('lostpointercapture', () => { drag = null; down = null; moved = false; });
hit.addEventListener('pointermove', (e) => {
  const p = { x: e.clientX, y: e.clientY, t: performance.now() };
  if (down && (Math.abs(p.x - down.x) + Math.abs(p.y - down.y) > 4)) moved = true;
  // 修复拖不动：一直发 pointer move，让 body 按自己的 6px 阈值"拎起"(grab)后再跟手。
  // （旧代码移动>4px 就改发 shift，但 body 的 shift 只在已拎起(drag 模式)后才生效 → 永远拎不起来）
  post({ t: 'pointer', type: 'move', p });
  if (!drag) setInteractive(inBody(p.x, p.y));
});
hit.addEventListener('pointerup', (e) => {
  const p = { x: e.clientX, y: e.clientY, t: performance.now() };
  post({ t: 'pointer', type: 'up', p });
  if (drag) post({ t: 'drop', p });
  if (!moved) { clearTimeout(clickTimer); clickTimer = setTimeout(() => { if (!moved) react(); }, 400); }
  drag = null; down = null; moved = false;
  setInteractive(inBody(p.x, p.y));
});
hit.addEventListener('pointercancel', () => { drag = null; down = null; moved = false; });

// 双击聊天
function openChat() {
  chatOpen = true;
  chatBox.style.display = 'block';
  setInteractive(true);
  chatInput.focus();
  try { window.petHost.debug('CHAT open'); } catch (e) {}
}
hit.addEventListener('dblclick', () => { clearTimeout(clickTimer); openChat(); });
try { window.petHost && window.petHost.onOpenChat(() => { openChat(); }); } catch (e) {}
window.addEventListener('focus', () => { try { window.petHost.debug('WIN focus'); } catch (e) {} });
window.addEventListener('blur', () => { try { window.petHost.debug('WIN blur'); } catch (e) {} });
chatInput.addEventListener('focus', () => { try { window.petHost.debug('INPUT focus'); } catch (e) {} });
chatInput.addEventListener('blur', () => { try { window.petHost.debug('INPUT blur'); } catch (e) {} });
chatInput.addEventListener('keydown', async (e) => {
  if (e.isComposing || e.keyCode === 229) return;   // 中文输入法组词中，别抢回车
  if (e.key === 'Escape') { closeChat(); return; }
  if (e.key !== 'Enter') return;
  if (chatSending) return;
  const text = chatInput.value.trim(); if (!text) return;
  chatInput.value = '';
  chatSending = true;
  try { window.petHost.debug('CHAT send:' + text.slice(0, 30)); } catch (e) {}
  say('…');
  try {
    const r = await window.petHost.chat(text);
    if (r && r.error) { say('她说不上来：' + r.error.slice(0, 60)); }
    else if (r && r.text) { say(r.text); if (r.audio) playAudio(r.audio); }
    else say('（她没说话）');
  }
  catch (err) { say('连不上她：' + ((err && err.message) || err)); }
  chatSending = false;
  if (chatOpen) chatInput.focus();
});

// 右键菜单
window.addEventListener('contextmenu', (e) => { e.preventDefault(); menu.style.display = 'block'; });
menu.addEventListener('click', async (e) => {
  const a = e.target && e.target.dataset ? e.target.dataset.a : null;
  menu.style.display = 'none';
  if (!a) return;
  if (a === 'chat') { chatOpen = true; chatBox.style.display = 'block'; setInteractive(true); chatInput.focus(); return; }
  if (a === 'hide' && window.petHost) { manualHidden = true; setDeskVisible(false); return; }
  if (a === 'quit' && window.petHost) { window.petHost.quit(); return; }
  const action = a === 'on' ? 'on' : (a === 'off' ? 'off' : 'panic');
  if (action === 'on') manualHidden = false;
  try {
    const j = await window.petHost.playalong(action);
    if (action === 'panic') say('好，停下了。');
    else if (action === 'on') say(j && j.ok ? '陪玩开始啦，我陪你～' : '陪玩没开起来…');
    else say('那我先不打扰你。');
    try { window.petHost.debug('playalong ' + action + ' -> ' + JSON.stringify(j).slice(0, 120)); } catch (x) {}
  } catch (err) { say('操作失败：' + ((err && err.message) || err)); }
});
window.addEventListener('click', (e) => { if (!menu.contains(e.target)) menu.style.display = 'none'; });

// ---------------- 和她连线：陪玩点评气泡 + 声音 ----------------
let deskWs = null, deskRetry = 0, audioEl = null;
function playAudio(b64) {
  try {
    if (!audioEl) audioEl = new Audio();
    audioEl.src = 'data:audio/mp3;base64,' + b64;
    audioEl.play().catch(() => {});
  } catch (e) {}
}
function connectDesk() {
  try {
    deskWs = new WebSocket('ws://127.0.0.1:8003/ws?sid=pet-desk&pet=1');
    deskWs.onopen = () => { deskRetry = 0; try { window.petHost && window.petHost.debug('desk ws open'); } catch (e) {} };
    deskWs.onmessage = (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.type === 'act') { reactToAction(m.action, m.app); return; }
      if (m.type === 'desk-mode') {
        if (m.on && !deskMode) {
          try {
            window.petHost && window.petHost.petLine('wake').then((line) => {
              if (line && line.text) sayLine(line);
              else say('陪玩开始啦，我陪你～');
            }).catch(() => say('陪玩开始啦，我陪你～'));
          } catch (e) { say('陪玩开始啦，我陪你～'); }
        }
        if (!m.on && deskMode) say('那我先躲起来…');
        setDeskVisible(!!m.on);
        return;
      }
      if (m.type === 'pet-line') { sayLine({ text: m.text, audio: m.audio }); return; }
      if ((m.type === 'reply' || m.type === 'companion') && m.text) {
        say(m.text);
        if (m.audio) playAudio(m.audio);
        if (m.presence) react();
      }
    };
    deskWs.onclose = () => {
      deskRetry += 1;
      setTimeout(connectDesk, Math.min(8000, 600 * Math.pow(1.8, Math.min(deskRetry, 4))));
    };
  } catch (e) { setTimeout(connectDesk, 2000); }
}
function setDeskVisible(on) {
  if (on) manualHidden = false;
  deskMode = !!on;
  try { window.petHost && window.petHost.setVisible(deskMode); } catch (e) {}
}
function pickWord(w, fallbacks) {
  if (!Array.isArray(words) || !words.length) return null;
  const all = [w].concat(fallbacks || []);
  for (const x of all) { if (words.indexOf(x) >= 0) return x; }
  return null;
}
// 她在电脑上做的事 → 她身上的动画（动作名取自 lab/hands/play_policy.py）
const ACT2WORD = {
  media: 'dance',      // 放音乐 / 切歌
  volume: 'nod',       // 调音量
  draw: 'happy',       // 画图
  eat: 'love', food: 'love', drink: 'love',
  sleep: 'sleep', rest: 'sleep',
  screenshot: 'look', browse: 'look',
};
const APP2WORD = {
  zenless: 'excited',  // 打游戏
  game: 'excited',
  notepad: 'thinking', // 写字
  notebook: 'thinking', // 她的日记本
  calc: 'thinking',
  browser: 'look',
  music: 'dance',
};
function reactToAction(a, app) {
  const k = String(a || '').toLowerCase();
  const ap = String(app || '').toLowerCase();
  let w = APP2WORD[ap] || ACT2WORD[k] || pickWord('thinking');
  if (w) { post({ t: 'do', word: w }); try { window.petHost.debug('ACT ' + k + ' -> ' + w); } catch (e) {} }
}
function applyVitals(v) {
  if (!v || !ready) return;
  lastVitals = v;
  const now = Date.now() / 1000;
  const asleep = !!v.asleep;
  const act = String(v.activity || '');
  const emo = String(v.emotion_type || '');
  const lastMeal = v.last_meal_at ? (now - Number(v.last_meal_at)) : 1e9;
  const key = emo + '|' + act;
  if (lastEmoAct && key !== lastEmoAct) {
    try { window.petHost.debug('EMOCHG ' + lastEmoAct + ' -> ' + key); } catch (e) {}
    try {
      window.petHost && window.petHost.petLine('idle').then((line) => {
        if (line && line.text) sayLine(line);
      }).catch(() => {});
    } catch (e) {}
  }
  lastEmoAct = key;
  const passive = /发呆|想|写|看|睡/.test(act);
  let want = 'idle';
  if (asleep || /睡/.test(act)) want = 'sleep';
  else if (lastMeal < 600 || /吃|饭|喝/.test(act)) want = 'eat';
  else if (/玩|游戏|对局/.test(act)) want = 'play';
  else if (passive) want = 'sit';
  if (want === curMode) {
    if (want === 'sleep' && layout && layout.mode !== 'sleep') {
      post({ t: 'do', word: 'sleep' });
    }
    return;
  }
  curMode = want;
  try { window.petHost.debug('MODE ' + want + ' (asleep=' + asleep + ' act=' + act + ')'); } catch (e) {}
  if (want === 'sleep') {
    post({ t: 'set', state: { roam: false, still: true } });
    post({ t: 'do', word: 'sleep' });
  } else if (want === 'eat') {
    post({ t: 'set', state: { roam: false, still: true } });
    post({ t: 'do', word: 'sit' });
    post({ t: 'do', word: 'love' });
  } else if (want === 'play') {
    post({ t: 'set', state: { roam: false, still: true } });
    post({ t: 'do', word: 'hop' });
  } else if (want === 'sit') {
    post({ t: 'set', state: { roam: false, still: true } });
    post({ t: 'do', word: 'sit' });
  } else {
    post({ t: 'set', state: { roam: false, still: true } });
    post({ t: 'do', word: 'stand' });
  }
}


async function pollState() {
  try {
    if (!window.petHost) return;
    const st = await window.petHost.companionState();
    const wantOn = !!(st && st.on);
    if (chatOpen) { if (!wantOn) setDeskVisible(false); return; }   // 聊天中别硬收
    if (manualHidden && wantOn) return;                              // 尊重"先藏起来"
    if (wantOn !== deskMode) setDeskVisible(wantOn);
    if (wantOn) { const v = await window.petHost.vitals(); applyVitals(v); }
  } catch (e) {}
}
setTimeout(pollState, 2500);
setInterval(pollState, 20000);

connectDesk();

requestAnimationFrame(tick);
setTimeout(init, 1200);
