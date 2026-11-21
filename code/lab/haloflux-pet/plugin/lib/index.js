// dsh-haloflux-office —— HaloFlux 办公室宠物（DSH 页面内的悬浮层）
//
// 参考 dsh-whale-widget 的做法：Host 侧注册 webserver/index-inject 注入行，
// 由浏览器加载 /dsh-office/overlay.js，在 DSH 页面里开一个可拖动/可折叠的悬浮窗，
// 悬浮窗里用 iframe 装原来的 HaloFlux 办公室画布。
//
// 和旧方案的差别（旧方案 = Edge --app 窗口 + 板子服务 3005 + 改第三方桌宠插件）：
//   · 随 DSH 页面一起出现，没有"外部窗口开不起来"这一环；
//   · 看板状态由本插件在 Host 里直接跟 session/event 算，不再依赖 3005 python 进程；
//   · 所有资源走 DSH 自己的 webServer，不需要 PowerShell 改窗口样式；
//   · 出错只影响这个悬浮层，绝不连累页面启动（注入行自带 try/catch + onerror 吞错）。

import { promises as fsp, createReadStream } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const PKG_ROOT = path.dirname(HERE)
const ASSETS = path.join(PKG_ROOT, 'assets')
const LOG = path.join(PKG_ROOT, '..', 'office.log')
const ROUTE_ROOT = '/dsh-office'
const URL_PREFIX = ROUTE_ROOT + '/'

function log(msg) {
  try {
    fsp.appendFile(LOG, `[${new Date().toISOString()}] ${msg}\n`).catch(() => {})
  } catch (err) { /* 日志不能影响功能 */ }
}

function pad(n) { return n < 10 ? '0' + n : '' + n }
function ts() {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
    + `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

// ------------------------------------------------------------------ 看板状态
const AGENT_SEED = [
  ['导演', '项目经理', '#f0a6c6'],
  ['架构师', '技术负责人', '#98e0cf'],
  ['实现', '工程师', '#f0a6c6'],
  ['评审', '评审员', '#98e0cf'],
  ['跑腿', '测试/杂活', '#8a8f99'],
  ['翻译', '翻译官', '#f0a6c6'],
]

const board = {
  agents: AGENT_SEED.map(([name, role, color], i) => ({
    id: i + 1, name, role, color, status: 'idle', current_task: null,
  })),
  tasks: [{
    id: 1, title: '对话', description: '与部署者的实时交流',
    status: 'backlog', assignee: 1, created: ts(), updated: ts(),
  }],
  steps: [],
  seq: 0,
}

const subs = new Set()
function publish() {
  for (const q of subs) {
    try { q.push('refresh') } catch (err) { /* 单个订阅坏了不影响别人 */ }
  }
}

function newChat() {
  const now = ts()
  for (const s of board.steps) {
    if (s.status === 'running') {
      s.status = 'done'
      s.finished = now
      if (!s.output) s.output = '（上一轮结束）'
    }
  }
  board.tasks[0].status = 'doing'
  board.tasks[0].updated = now
  board.seq += 1
  board.steps.unshift({
    id: board.seq, task_id: 1, agent_id: 1, phase: '对话',
    action: '收到消息，开始处理', output: '', status: 'running',
    started: now, finished: null,
  })
  if (board.steps.length > 60) board.steps.length = 60
  const boss = board.agents[0]
  boss.status = 'working'
  boss.current_task = 1
  publish()
}

function closeChat() {
  const now = ts()
  let touched = false
  for (const s of board.steps) {
    if (s.status === 'running') {
      s.status = 'done'
      s.finished = now
      if (!s.output) s.output = '（本轮结束）'
      touched = true
    }
  }
  if (board.tasks[0].status === 'doing') {
    board.tasks[0].status = 'backlog'
    board.tasks[0].updated = now
  }
  const boss = board.agents[0]
  if (boss.current_task === 1) {
    boss.status = 'idle'
    boss.current_task = null
  }
  if (touched) publish()
  else publish()
}

function snapshot() {
  const running = board.steps.filter((s) => s.status === 'running').length
  return {
    agents: board.agents,
    tasks: board.tasks,
    steps: board.steps.slice(0, 30),
    stats: { running, tasks: board.tasks.length },
    time: ts(),
  }
}

// ------------------------------------------------------------------ 注入行
function inlineRow(config) {
  const w = Math.round(config.width ?? 520)
  const h = Math.round(config.height ?? 340)
  const hidden = config.startHidden === true ? '1' : '0'
  const src = `${URL_PREFIX}overlay.js?w=${w}&h=${h}&hidden=${hidden}&v=3`
  return '(function(){try{'
    + 'if(window.__DSH_OFFICE__)return;'
    + 'var d=document.body||document.head||document.documentElement;if(!d)return;'
    + 'var s=document.createElement("script");s.src="' + src + '";s.async=true;'
    + 's.onerror=function(){};d.appendChild(s)'
    + '}catch(e){}})()'
}

// ------------------------------------------------------------------ HTTP
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.mp3': 'audio/mpeg',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.wav': 'audio/wav',
  '.gif': 'image/gif',
}

function isLoopback(req) {
  try {
    const host = String((req && req.headers && req.headers.host) || '').toLowerCase()
    const name = host.replace(/^\[/, '').split(']')[0].split(':')[0]
    if (name === 'localhost' || name.endsWith('.localhost') || name === '::1') return true
    const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(name)
    return !!(m && Number(m[1]) === 127 && [m[2], m[3], m[4]].every((x) => Number(x) <= 255))
  } catch (err) {
    return false
  }
}

function sendJSON(res, obj, code = 200) {
  const buf = Buffer.from(JSON.stringify(obj), 'utf8')
  res.statusCode = code
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.setHeader('Content-Length', buf.length)
  res.setHeader('Cache-Control', 'no-store')
  res.end(buf)
}

async function serveAsset(req, res, rel) {
  const safe = rel.replace(/\\/g, '/').replace(/\.\.+/g, '')
  const file = path.join(ASSETS, safe)
  if (!file.startsWith(ASSETS)) { res.statusCode = 403; return res.end('forbidden') }
  let st
  try { st = await fsp.stat(file) } catch (err) { res.statusCode = 404; return res.end('missing') }
  if (!st.isFile()) { res.statusCode = 404; return res.end('missing') }
  const ext = path.extname(file).toLowerCase()
  const type = MIME[ext] || 'application/octet-stream'
  const size = st.size
  // 2026-11-16：音频/图片允许缓存（之前一律 no-store，BGM 每循环一次就整包重下）；
  // html/js 仍保持 no-store，改完刷新就生效。
  const CACHEABLE = (ext === '.mp3' || ext === '.wav' || ext === '.png'
    || ext === '.jpg' || ext === '.gif' || ext === '.svg')
  const cache = CACHEABLE ? 'public, max-age=3600' : 'no-store'

  // 2026-11-16：支持 Range。以前不支持时，画布里的 BGM 每循环一次就把 7.5MB 整包重拉一遍。
  const rangeHeader = req.headers && req.headers.range
  if (rangeHeader) {
    const m = /^bytes=(\d*)-(\d*)$/.exec(String(rangeHeader).trim())
    if (!m) { res.statusCode = 416; res.setHeader('Content-Range', 'bytes */' + size); return res.end() }
    let start = m[1] === '' ? null : parseInt(m[1], 10)
    let end = m[2] === '' ? null : parseInt(m[2], 10)
    if (start === null && end === null) { res.statusCode = 416; res.setHeader('Content-Range', 'bytes */' + size); return res.end() }
    if (start === null) { start = Math.max(0, size - end); end = size - 1 }      // bytes=-N 尾部
    if (end === null || end >= size) end = size - 1
    if (start >= size || start > end) {
      res.statusCode = 416
      res.setHeader('Content-Range', 'bytes */' + size)
      return res.end()
    }
    const len = end - start + 1
    res.statusCode = 206
    res.setHeader('Content-Type', type)
    res.setHeader('Content-Length', len)
    res.setHeader('Content-Range', `bytes ${start}-${end}/${size}`)
    res.setHeader('Accept-Ranges', 'bytes')
    res.setHeader('Cache-Control', cache)
    if (req.method === 'HEAD') return res.end()
    return createReadStream(file, { start, end })
      .on('error', () => { try { res.destroy() } catch (err) {} }).pipe(res)
  }

  res.statusCode = 200
  res.setHeader('Content-Type', type)
  res.setHeader('Content-Length', size)
  res.setHeader('Accept-Ranges', 'bytes')
  res.setHeader('Cache-Control', cache)
  if (req.method === 'HEAD') return res.end()
  createReadStream(file).on('error', () => { try { res.destroy() } catch (err) {} }).pipe(res)
}

function staticHandler(req, res) {
  if (!isLoopback(req)) { res.statusCode = 403; return res.end('forbidden') }
  let p = '/'
  try { p = new URL(req.url || '/', 'http://127.0.0.1').pathname } catch (err) { /* 保底 */ }
  if (p !== ROUTE_ROOT && !p.startsWith(URL_PREFIX)) { res.statusCode = 404; return res.end('missing') }
  const rel = decodeURIComponent(p.slice(ROUTE_ROOT.length).replace(/^\/+/, '')) || 'app.html'
  log('GET ' + p)
  return serveAsset(req, res, rel)
}

function stateHandler(req, res) {
  if (!isLoopback(req)) { res.statusCode = 403; return res.end('forbidden') }
  return sendJSON(res, snapshot())
}

function eventsHandler(req, res) {
  if (!isLoopback(req)) { res.statusCode = 403; return res.end('forbidden') }
  res.statusCode = 200
  res.setHeader('Content-Type', 'text/event-stream; charset=utf-8')
  res.setHeader('Cache-Control', 'no-cache')
  res.setHeader('Connection', 'keep-alive')
  const q = []
  subs.add(q)
  res.write('retry: 800\n\ndata: {"type":"hello"}\n\n')
  const timer = setInterval(() => {
    while (q.length) {
      q.shift()
      try { res.write('data: {"type":"refresh"}\n\n') } catch (err) { /* 断开就算了 */ }
    }
    try { res.write(': ping\n\n') } catch (err) { /* 断开就算了 */ }
  }, 1500)
  const cleanup = () => { clearInterval(timer); subs.delete(q) }
  req.on('close', cleanup)
  res.on('close', cleanup)
}

// ------------------------------------------------------------------ 插件
export const name = 'dsh-haloflux-office'

export function apply(ctx, config = {}) {
  const cfg = { enabled: true, width: 520, height: 340, startHidden: false, ...config }
  const disposers = []
  ctx.effect(() => () => {
    for (const d of disposers) { try { d() } catch (err) { /* 清理失败不抛 */ } }
    disposers.length = 0
  })

  // ① 注入行先注册（不等任何服务，避免桌面端收集注入表时错过）
  try {
    const off = ctx.on('webserver/index-inject', (table) => {
      if (!Array.isArray(table) || cfg.enabled === false) return
      const text = inlineRow(cfg)
      for (const row of table) {
        if (row && row.kind === 'script' && typeof row.text === 'string' && row.text.includes(URL_PREFIX + 'overlay.js')) return
      }
      table.push({ kind: 'script', placement: 'body', text })
    })
    disposers.push(off)
  } catch (err) { log('index-inject 注册失败: ' + err) }

  // ② 路由 + index 兜底注入（web 形态）
  ctx.inject(['webServer'], (wctx) => {
    const reg = [
      wctx.webServer.register({ kind: 'prefix', path: ROUTE_ROOT, handler: staticHandler }),
      wctx.webServer.register({ kind: 'exact', path: URL_PREFIX + 'state', handler: stateHandler }),
      wctx.webServer.register({ kind: 'exact', path: URL_PREFIX + 'events', handler: eventsHandler }),
    ]
    if (typeof wctx.webServer.tapIndex === 'function') {
      reg.push(wctx.webServer.tapIndex((html) => {
        if (cfg.enabled === false) return html
        const tag = '<script>' + inlineRow(cfg) + '</script>'
        return html.includes(tag) ? html : html.replace('</body>', tag + '</body>')
      }))
    }
    disposers.push(() => { for (const d of reg) { try { d() } catch (err) {} } })
    log('routes ready')
  })

  // ③ 跟 DSH 的回合：她的消息 → 导演忙碌；答完 → 回待机
  try {
    const off = ctx.on('session/event', (session, event) => {
      if (!event) return
      if (session && session.header && session.header.origin === 'subagent') return
      if (event.type === 'turn/start') newChat()
      else if (event.type === 'turn/end' || event.type === 'turn/error') closeChat()
    }, { global: true })
    disposers.push(off)
  } catch (err) { log('session/event 注册失败: ' + err) }

  log('plugin applied')
}
