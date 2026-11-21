// TA · 桌面 App（Electron 壳）
// 作用：一个独立窗口装下整个 Hub；摄像头/麦克风在这里一次性放行，不再每次弹窗。
const { app, BrowserWindow, session, Menu, shell, ipcMain } = require('electron');
const fs = require('fs');
const http = require('http');
const path = require('path');

const GATE_FILE = 'D:\\你的数据目录\\gate_token.txt';
const HUB = 'http://127.0.0.1:8009';
const ICON = path.join(__dirname, 'icon.ico');

function readToken() {
  try { return fs.readFileSync(GATE_FILE, 'utf8').trim(); } catch (e) { return ''; }
}
function isLocal(url) {
  try {
    const u = new URL(url);
    return (u.hostname === '127.0.0.1' || u.hostname === 'localhost' || u.hostname === '::1');
  } catch (e) { return false; }
}

let win = null;

// ---------------- 桌宠：本地静态服务 + 透明窗口 ----------------
const PET_ROOT = 'D:\\dev\\companion-app\\petweb';
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml',
  '.webm': 'video/webm', '.mp3': 'audio/mpeg', '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf' };
let petServer = null, petWin = null;

function startPetServer() {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      try {
        let p = decodeURIComponent((req.url || '/').split('?')[0]);
        if (p === '/') p = '/pet.html';
        const file = require('path').join(PET_ROOT, p);
        if (!file.startsWith(PET_ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
          res.writeHead(404); res.end('not found'); return;
        }
        res.writeHead(200, { 'Content-Type': MIME[require('path').extname(file).toLowerCase()] || 'application/octet-stream',
          'Cache-Control': 'no-store' });
        fs.createReadStream(file).pipe(res);
      } catch (e) { try { res.writeHead(500); res.end('err'); } catch (_) {} }
    });
    srv.listen(0, '127.0.0.1', () => { petServer = srv; resolve(srv.address().port); });
  });
}

async function createPetWindow() {
  // petWin guard: 已经有一个就复用，绝不再开第二只
  if (petWin && !petWin.isDestroyed()) return;   // 复用已有窗口，不打扰
  const port = await startPetServer();
  // 舞台窗：横跨屏幕底部的一条透明窗，角色在窗内移动（不搬窗口，避免透明窗残影）
  const { width, height } = require('electron').screen.getPrimaryDisplay().workAreaSize;
  const STAGE_H = Math.min(760, Math.max(560, Math.round(height * 0.5)));
  petWin = new BrowserWindow({
    width: width, height: STAGE_H, x: 0, y: height - STAGE_H,
    transparent: true, frame: false, resizable: false, hasShadow: false,
    alwaysOnTop: true, skipTaskbar: true, focusable: true, show: false,
    backgroundColor: '#00000000',
    webPreferences: { preload: require('path').join(__dirname, 'pet-preload.js'), contextIsolation: true, nodeIntegration: false },
  });
  petWin.setAlwaysOnTop(true, 'screen-saver');
  petWin.webContents.on('did-finish-load', () => bootLog('PETW loaded'));
  petWin.webContents.on('did-fail-load', (_e, code, desc) => bootLog('PETW fail ' + code + ' ' + desc));
  petWin.webContents.on('console-message', (_e, level, message) => { if (level >= 2) bootLog('PETW console[' + level + '] ' + message); });
  petWin.loadURL('http://127.0.0.1:' + port + '/pet.html');
  petWin.once('ready-to-show', () => {
    // 初始隐藏：等陪玩 desk-mode on（或状态轮询）再显示，避免开机先闪一下
    try { petWin.setIgnoreMouseEvents(true, { forward: true }); } catch (e) {}
    bootLog('PETW stage ready (hidden, click-through)');
  });
  petWin.on('closed', () => { petWin = null; });
}

ipcMain.on('pet-move', (e, d) => {
  const w = BrowserWindow.fromWebContents(e.sender);
  if (!w || !d) return;
  const [x, y] = w.getPosition();
  w.setPosition(Math.round(x + (d.dx || 0)), Math.round(y + (d.dy || 0)));
});
// 全局快捷键：不管桌宠在哪，Ctrl+Shift+X 打开/聚焦聊天框
try {
  const { globalShortcut } = require('electron');
  app.on('will-quit', () => { try { require('electron').globalShortcut.unregisterAll(); } catch (e) {} });
app.whenReady().then(() => {
    globalShortcut.register('CommandOrControl+Shift+X', () => {
      try {
        if (!petWin || petWin.isDestroyed()) { createPetWindow(); return; }
        if (petWin._fadeT) { clearInterval(petWin._fadeT); petWin._fadeT = null; }
        if (!petWin.isVisible()) { petWin.setOpacity(0); petWin.show(); let op = 0; petWin._fadeT = setInterval(() => { op += 0.1; try { petWin.setOpacity(Math.min(1, op)); } catch (e) {} if (op >= 1) { clearInterval(petWin._fadeT); petWin._fadeT = null; } }, 30); }
        petWin.show(); petWin.focus();   // 让输入法/键盘落在聊天框
        petWin.webContents.send('pet-open-chat');
      } catch (e) { bootLog('PETW openchat failed ' + e); }
    });
  });
} catch (e) {}
ipcMain.on('pet-visible', (e, on) => {
  try {
    if (!petWin || petWin.isDestroyed()) { createPetWindow(); return; }
    if (petWin._fadeT) { clearInterval(petWin._fadeT); petWin._fadeT = null; }
    if (on) {
      petWin.setOpacity(0);
      petWin.showInactive();
      let op = 0;
      petWin._fadeT = setInterval(() => { op += 0.1; try { petWin.setOpacity(Math.min(1, op)); } catch (err) {} if (op >= 1) { clearInterval(petWin._fadeT); petWin._fadeT = null; } }, 30);
    } else {
      let op = 1;
      petWin._fadeT = setInterval(() => { op -= 0.1; if (op <= 0) { clearInterval(petWin._fadeT); petWin._fadeT = null; try { petWin.hide(); petWin.setOpacity(1); } catch (err) {} } else { try { petWin.setOpacity(op); } catch (err) {} } }, 30);
    }
  } catch (err) {}
});
ipcMain.handle('pet-companion-state', async () => {
  try {
    const r = await fetch('http://127.0.0.1:8003/api/companion/state?t=' + encodeURIComponent(readToken()));
    return await r.json();
  } catch (e) { return {}; }
});
ipcMain.handle('pet-line', async (e, kind) => {
  try {
    const r = await fetch('http://127.0.0.1:8003/api/pet-line?kind=' + encodeURIComponent(kind || 'poke') + '&t=' + encodeURIComponent(readToken()));
    return await r.json();
  } catch (err) { return { text: '', audio: '' }; }
});
ipcMain.handle('pet-vitals', async () => {
  try {
    const r = await fetch('http://127.0.0.1:8003/api/mood?t=' + encodeURIComponent(readToken()));
    return await r.json();
  } catch (e) { return {}; }
});
ipcMain.handle('pet-playalong', async (e, action) => {
  const tok = readToken();
  let path = '/api/companion/toggle';
  let body = JSON.stringify({ on: action === 'on' });
  if (action === 'panic') { path = '/api/companion/panic'; body = '{}'; }
  return await new Promise((resolve) => {
    const req = http.request({ host: '127.0.0.1', port: 8003, path: path + '?t=' + encodeURIComponent(tok),
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) }, timeout: 30000 },
      (res) => { let buf = ''; res.on('data', (c) => { buf += c; }); res.on('end', () => { try { resolve(JSON.parse(buf)); } catch (err) { resolve({}); } }); });
    req.on('error', () => resolve({}));
    req.on('timeout', () => { req.destroy(); resolve({}); });
    req.write(body); req.end();
  });
});
ipcMain.handle('pet-chat', async (e, text) => {
  const tok = readToken();
  const body = JSON.stringify({ text: String(text || '').slice(0, 500) });
  return await new Promise((resolve) => {
    const req = http.request({ host: '127.0.0.1', port: 8003, path: '/api/chat?t=' + encodeURIComponent(tok),
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) }, timeout: 60000 },
      (res) => {
        let buf = '';
        res.on('data', (c) => { buf += c; });
        res.on('end', () => {
          try {
            const j = JSON.parse(buf);
            if (res.statusCode >= 400) { resolve({ text: '', audio: '', error: (j && j.error) || ('HTTP ' + res.statusCode) }); return; }
            resolve({ text: j.text || '', audio: j.audio || '', error: j.error || '' });
          } catch (err) { resolve({ text: '', audio: '', error: '解析失败' }); }
        });
      });
    req.on('error', () => resolve({ text: '', audio: '', error: '连不上 8003' }));
    req.on('timeout', () => { req.destroy(); resolve({ text: '', audio: '', error: '她想了太久，超时了' }); });
    req.write(body); req.end();
  });
});
// Coopanion 式：主进程轮询光标，把窗口内坐标推给桌宠页，页面自己判断是否在角色身上
setInterval(() => {
  try {
    if (!petWin || petWin.isDestroyed() || !petWin.isVisible()) return;
    if (!petWin.webContents || petWin.webContents.isDestroyed()) return;
    const p = require('electron').screen.getCursorScreenPoint();
    const b = petWin.getBounds();
    petWin.webContents.send('pet-cursor', { x: p.x - b.x, y: p.y - b.y });
  } catch (e) {}
}, 60);
ipcMain.on('pet-debug', (e, m) => bootLog('PETD ' + m));
ipcMain.on('pet-interactive', (e, on) => {
  const w = BrowserWindow.fromWebContents(e.sender);
  if (!w) return;
  try { w.setIgnoreMouseEvents(!on, { forward: true }); } catch (err) {}
});
ipcMain.on('pet-hide', (e) => { const w = BrowserWindow.fromWebContents(e.sender); if (w) w.hide(); });
ipcMain.on('pet-quit', () => { app.quit(); });


const BOOT_LOG = 'D:\\dev\\companion-app\\boot.log';
function bootLog(msg) { try { fs.appendFileSync(BOOT_LOG, new Date().toISOString() + ' ' + msg + '\r\n'); } catch (e) {} }

function createWindow() {
  win = new BrowserWindow({
    width: 1200,
    height: 820,
    minWidth: 900,
    minHeight: 640,
    title: 'TA',
    icon: fs.existsSync(ICON) ? ICON : undefined,
    backgroundColor: '#070d18',
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      spellcheck: false,
    },
  });
  Menu.setApplicationMenu(null);

  const ses = win.webContents.session;
  // 只对本机的几个页面放行摄像头/麦克风；其它来源一律拒绝
  const ALLOW = new Set(['media', 'camera', 'microphone', 'display-capture', 'fullscreen', 'notifications', 'clipboard-read']);
  ses.setPermissionRequestHandler((wc, permission, callback, details) => {
    const url = (details && (details.requestingUrl || details.securityOrigin)) || (wc && wc.getURL()) || '';
    bootLog('perm request ' + permission + ' from ' + url + ' -> ' + (ALLOW.has(permission) && isLocal(url)));
    if (ALLOW.has(permission) && isLocal(url)) return callback(true);
    return callback(false);
  });
  try {
    ses.setPermissionCheckHandler((wc, permission, requestingOrigin) => {
      return ALLOW.has(permission) && isLocal(requestingOrigin || (wc && wc.getURL()) || '');
    });
  } catch (e) { /* 旧版 Electron 没有这个 API */ }

  win.webContents.setWindowOpenHandler(({ url }) => {
    // 页面里"在浏览器里打开"之类的：交给系统浏览器
    if (url && url.startsWith('http')) shell.openExternal(url);
    return { action: 'deny' };
  });

  try { win.webContents.insertCSS('html{scrollbar-width:none}body::-webkit-scrollbar{width:0;height:0}'); } catch (e) {}
  const token = readToken();
  win.loadURL(token ? (HUB + '/?t=' + encodeURIComponent(token)) : HUB);

  win.webContents.on('did-fail-load', (_e, code, desc) => {
    if (code === -6) return; // 用户主动取消
    const html = encodeURIComponent(
      '<body style="background:#0b1220;color:#dbeafe;font-family:sans-serif;padding:48px;line-height:1.8">'
      + '<h2>TA还没起来</h2><p>Hub 服务（8009）没连上：' + desc + '</p>'
      + '<p>先运行：C:\\Users\\你的用户\\CompanionStartup\\start-astrbot.ps1（或重启TA。）</p></body>');
    win.loadURL('data:text/html;charset=utf-8,' + html);
  });

  win.webContents.on('did-finish-load', () => { bootLog('did-finish-load ' + win.webContents.getURL()); });
  win.webContents.on('console-message', (_e, level, message) => { bootLog('console[' + level + '] ' + message); });
  win.on('closed', () => { win = null; });
  if (!process.env.COMPANION_NO_PET) createPetWindow().catch((e) => bootLog('pet window failed ' + e));
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win) { if (win.isMinimized()) win.restore(); win.focus(); return; }
    createWindow();
  });
  bootLog('app ready');
  if (process.env.COMPANION_PERM_TEST === '5') {
    app.whenReady().then(async () => {
      const w = new BrowserWindow({ width: 1200, height: 860, show: false });
      const ses = w.webContents.session;
      ses.setPermissionRequestHandler((wc, permission, cb) => cb(['media','camera','microphone'].includes(permission)));
      try { ses.setPermissionCheckHandler(() => true); } catch (e) {}
      const token = readToken();
      await w.loadURL(HUB + '/?t=' + encodeURIComponent(token));
      const ok = await w.webContents.executeJavaScript("(function(){try{openApp({t:'视频通话',p:8003,path:'/',tok:" + JSON.stringify(token) + "});return 'ok';}catch(e){return 'ERR '+e.message;}})()", true);
      bootLog('T5 openApp ' + ok);
      await new Promise(r => setTimeout(r, 5000));
      let frame = null;
      for (const f of w.webContents.mainFrame.frames) { if (f.url && f.url.indexOf('8003') >= 0) { frame = f; break; } }
      if (!frame) { bootLog('T5 NO_FRAME ' + w.webContents.mainFrame.frames.map(f=>f.url).join(' | ')); }
      else {
        const info = await frame.executeJavaScript("(function(){var fp=document.featurePolicy;return {camera: fp&&fp.allowsFeature?fp.allowsFeature('camera'):'n/a', mic: fp&&fp.allowsFeature?fp.allowsFeature('microphone'):'n/a'};})()", true);
        bootLog('T5 frame ' + JSON.stringify(info));
        const r = await frame.executeJavaScript("navigator.mediaDevices.getUserMedia({video:true,audio:true}).then(function(s){var n=s.getTracks().length;s.getTracks().forEach(function(t){t.stop();});return 'OK tracks='+n;}).catch(function(e){return 'ERR '+e.name+':'+e.message;})", true);
        bootLog('T5 gum ' + r);
      }
      setTimeout(() => app.quit(), 300);
    });
  } else if (process.env.COMPANION_PERM_TEST === '4') {

    app.whenReady().then(async () => {
      const w = new BrowserWindow({ width: 1200, height: 860, show: false });
      const ses = w.webContents.session;
      ses.setPermissionRequestHandler((wc, permission, cb, d) => { bootLog('T4 req ' + permission + ' ' + JSON.stringify(d && (d.requestingUrl || d.securityOrigin))); cb(['media','camera','microphone'].includes(permission)); });
      try { ses.setPermissionCheckHandler((wc, p, o) => { bootLog('T4 check ' + p + ' ' + o); return ['media','camera','microphone'].includes(p); }); } catch (e) {}
      const token = readToken();
      await w.loadURL(HUB + '/?t=' + encodeURIComponent(token));
      const parentInfo = await w.webContents.executeJavaScript("(function(){var f=document.getElementById('fr-call');return {allow: f.getAttribute('allow'), src: f.src};})()", true);
      bootLog('T4 parent ' + JSON.stringify(parentInfo));
      await w.webContents.executeJavaScript("(function(){var v=document.getElementById('v-call');if(v){v.classList.add('on');}document.querySelectorAll('.view').forEach(function(e){if(e!==v)e.classList.remove('on');});var f=document.getElementById('fr-call');f.loading='eager';f.src='http://127.0.0.1:8003/?t='+encodeURIComponent(" + JSON.stringify(token) + ");return 'ok';})()");
      await new Promise(r => setTimeout(r, 5000));
      let frame = null;
      for (const f of w.webContents.mainFrame.frames) { if (f.url && f.url.indexOf('8003') >= 0) { frame = f; break; } }
      if (frame) {
        const info = await frame.executeJavaScript("(function(){var fp=document.featurePolicy;return {camera: fp && fp.allowsFeature ? fp.allowsFeature('camera') : 'n/a', mic: fp && fp.allowsFeature ? fp.allowsFeature('microphone') : 'n/a', origin: location.origin};})()", true);
        bootLog('T4 frame ' + JSON.stringify(info));
        const r = await frame.executeJavaScript("navigator.mediaDevices.getUserMedia({video:true,audio:true}).then(function(s){var n=s.getTracks().length;s.getTracks().forEach(function(t){t.stop();});return 'OK tracks='+n;}).catch(function(e){return 'ERR '+e.name+':'+e.message;})", true);
        bootLog('T4 gum ' + r);
      } else { bootLog('T4 NO_FRAME'); }
      setTimeout(() => app.quit(), 300);
    });
  } else if (process.env.COMPANION_PERM_TEST === '3') {

    app.whenReady().then(async () => {
      const w = new BrowserWindow({ width: 1200, height: 860, show: false,
        webPreferences: { contextIsolation: true, nodeIntegration: false } });
      const ses = w.webContents.session;
      ses.setPermissionRequestHandler((wc, permission, cb) => cb(['media','camera','microphone'].includes(permission)));
      try { ses.setPermissionCheckHandler(() => true); } catch (e) {}
      const token = readToken();
      await w.loadURL(HUB + '/?t=' + encodeURIComponent(token));
      await w.webContents.executeJavaScript("(function(){var v=document.getElementById('v-call');if(v){v.classList.add('on');}document.querySelectorAll('.view').forEach(function(e){if(e!==v)e.classList.remove('on');});var f=document.getElementById('fr-call');f.loading='eager';f.src='http://127.0.0.1:8003/?t='+encodeURIComponent(" + JSON.stringify(token) + ");return 'ok';})()");
      await new Promise(r => setTimeout(r, 7000));
      let frame = null;
      for (const f of w.webContents.mainFrame.frames) { if (f.url && f.url.indexOf('8003') >= 0) { frame = f; break; } }
      if (frame) {
        const info = await frame.executeJavaScript("(function(){var b=document.getElementById('perm-bar');return {hidden: !!b && b.hidden, text: document.getElementById('perm-txt') ? document.getElementById('perm-txt').textContent : '(none)', uaElectron: /electron/i.test(navigator.userAgent)};})()", true);
        bootLog('PERM_TEST_3 ' + JSON.stringify(info));
      }
      const img = await w.webContents.capturePage();
      require('fs').writeFileSync('D:\\dev\\companion-app\\app-check.png', img.toPNG());
      bootLog('PERM_TEST_3 screenshot saved');
      setTimeout(() => app.quit(), 300);
    });
  } else if (process.env.COMPANION_PERM_TEST === '2') {

    app.whenReady().then(async () => {
      const w = new BrowserWindow({ width: 1200, height: 860 });
      const ses = w.webContents.session;
      ses.setPermissionRequestHandler((wc, permission, cb) => cb(['media','camera','microphone'].includes(permission)));
      try { ses.setPermissionCheckHandler(() => true); } catch (e) {}
      const token = readToken();
      await w.loadURL(HUB + '/?t=' + encodeURIComponent(token));
      await w.webContents.executeJavaScript("(function(){var v=document.getElementById('v-call');if(v){v.classList.add('on');}document.querySelectorAll('.view').forEach(function(e){if(e!==v)e.classList.remove('on');});var f=document.getElementById('fr-call');f.loading='eager';f.src='http://127.0.0.1:8003/?t='+encodeURIComponent(" + JSON.stringify(token) + ");return 'ok';})()");
      await new Promise(r => setTimeout(r, 4000));
      const frames = w.webContents.mainFrame.frames;
      let frame = null;
      for (const f of frames) { if (f.url && f.url.indexOf('8003') >= 0) { frame = f; break; } }
      bootLog('PERM_TEST_IFRAME frames=' + frames.map(f => f.url).join(' | '));
      if (!frame) { bootLog('PERM_TEST_IFRAME NO_FRAME'); setTimeout(() => app.quit(), 300); return; }
      const r = await frame.executeJavaScript(
        "navigator.mediaDevices.getUserMedia({video:true,audio:true})" +
        ".then(function(s){var n=s.getTracks().length;s.getTracks().forEach(function(t){t.stop();});return 'OK tracks='+n;})" +
        ".catch(function(e){return 'ERR '+e.name+':'+e.message;})", true);
      bootLog('PERM_TEST_IFRAME ' + r);
      setTimeout(() => app.quit(), 500);
    });
  } else if (process.env.COMPANION_PERM_TEST === '1') {
    app.whenReady().then(async () => {
      const testWin = new BrowserWindow({ show: false, webPreferences: { contextIsolation: true, nodeIntegration: false } });
      const ses = testWin.webContents.session;
      ses.setPermissionRequestHandler((wc, permission, cb) => cb(['media','camera','microphone'].includes(permission)));
      try { ses.setPermissionCheckHandler(() => true); } catch (e) {}
      await testWin.loadURL('http://127.0.0.1:8003/?t=' + encodeURIComponent(readToken()));
      const r = await testWin.webContents.executeJavaScript(
        "navigator.mediaDevices.getUserMedia({video:true,audio:true})" +
        ".then(function(s){var n=s.getTracks().length;s.getTracks().forEach(function(t){t.stop();});return 'OK tracks='+n;})" +
        ".catch(function(e){return 'ERR '+e.name+':'+e.message;})", true);
      bootLog('PERM_TEST ' + r);
      setTimeout(() => app.quit(), 500);
    });
  } else {
    app.whenReady().then(createWindow);
  }
  app.on('window-all-closed', () => app.quit());
  app.on('activate', () => { if (!win) createWindow(); });
}