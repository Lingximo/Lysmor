# -*- coding: utf-8 -*-
"""TA · 统一入口（Hub）

一个图标 / 一个地址，把所有功能收进来：
  /            统一的壳（聊天 / 视频 / 状态 / 画廊）
  /api/status  服务健康 + 她的状态 + 记忆条数
  /api/art     画廊列表
  /artimg      画廊图片（只读）

保护：
  · 本机免口令；局域网要 ?t=口令（存在 hub/key.txt）
  · 只读她的状态和记忆，不写、不改
  · 聊天/视频仍然走各自原来的服务，Hub 不碰它们的逻辑
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import time

import aiohttp
from aiohttp import web

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
KEY_PATH = os.path.join(HERE, "key.txt")
PORT = 8009

STATE = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
         r"\core\data\plugin_data\astrbot_plugin_companion_mood\state.json")
MEMDB = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
         r"\core\data\plugin_data\astrbot_plugin_livingmemory\livingmemory.db")
GALLERY = r"D:\你的数据目录\art\gallery"
WEBCHAT_KEY = r"D:\你的数据目录\webchat\key.txt"
VIDEO_GATE = r"D:\你的数据目录\gate_token.txt"
CAMERA_SOURCE = r"D:\你的数据目录\state\camera_source.json"

SERVICES = [
    ("聊天", 8001), ("视频", 8003), ("状态面板", 8005), ("画廊", 8002),
    ("她的手", 8010), ("AstrBot", 8011), ("控制台", 8012),
]

COOKIE = "companion_hub"


def load_key() -> str:
    try:
        with open(KEY_PATH, encoding="utf-8") as f:
            k = f.read().strip()
            if k:
                return k
    except OSError:
        pass
    k = secrets.token_urlsafe(24)
    with open(KEY_PATH, "w", encoding="utf-8") as f:
        f.write(k)
    return k


KEY = load_key()


def read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _local(request: web.Request) -> bool:
    host = (request.host or "").split(":")[0]
    return host in ("127.0.0.1", "localhost", "::1")


def allowed(request: web.Request) -> bool:
    if _local(request):
        return True
    token = request.query.get("t") or request.cookies.get(COOKIE) or request.headers.get("X-Hub")
    return token == KEY


async def gate_middleware(app, handler):
    async def wrapper(request):
        if request.path.startswith("/static/") or request.path in (
                "/manifest.webmanifest", "/sw.js", "/icon.png", "/api/ping"):
            return await handler(request)
        if not allowed(request):
            return web.Response(status=403, text="口令不对。用带 ?t= 的地址打开。",
                                content_type="text/plain")
        return await handler(request)
    return wrapper


def port_ok(port: int, timeout: float = 0.4) -> bool:
    import socket
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def her_state() -> dict:
    try:
        d = json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for k in ("emotion_level", "energy", "hunger", "thirst", "asleep", "sleep_kind",
              "adenosine", "cortisol", "valence", "happiness", "sadness",
              "lymph_edema", "lymph_tenderness", "lymph_flow", "lymph_capacity",
              "sick_cause", "sick_recovery", "cycle_phase", "cycle_day",
              "activity", "activity_note", "last_update"):
        v = d.get(k)
        if isinstance(v, float):
            v = round(v, 3)
        out[k] = v
    return out


def self_ctx() -> dict:
    try:
        with open(r"D:\你的数据目录\state\self.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def mem_count() -> dict:
    try:
        con = sqlite3.connect("file:%s?mode=ro" % MEMDB, uri=True)
        n = con.execute("select count(*) from documents").fetchone()[0]
        last = con.execute("select max(created_at) from documents").fetchone()[0]
        con.close()
        return {"documents": n, "last": last}
    except Exception:
        return {"documents": None, "last": None}


def _ink_ok(path, pencil=True):
    try:
        from PIL import Image
        im = Image.open(path).convert("L")
        w, h = im.size
        if w > 2000 and h > 1000:
            return False
        if w < 120 or h < 60:
            return False
        hist = im.histogram()
        total = float(w * h)
        if pencil:
            ratio = sum(hist[:90]) / total
            if not (0.0004 <= ratio <= 0.15):
                return False
            px = im.load()
            by, bx = max(2, h // 50), max(2, w // 50)
            edge = 0
            for y in range(by):
                for x in range(0, w, 3):
                    if px[x, y] < 90:
                        edge += 1
            for x in range(0, w, 3):
                for y in range(h - by, h):
                    if px[x, y] < 90:
                        edge += 1
            for x in range(bx):
                for y in range(0, h, 3):
                    if px[x, y] < 90:
                        edge += 1
            for x in range(w - bx, w):
                for y in range(0, h, 3):
                    if px[x, y] < 90:
                        edge += 1
            return edge < 4
        ratio = (total - sum(hist[236:])) / total
        return 0.004 <= ratio <= 0.85
    except Exception:
        return False


def art_list() -> list:
    try:
        names = [n for n in os.listdir(GALLERY) if n.lower().endswith((".jpg", ".png"))]
    except OSError:
        return []
    doodles = sorted([n for n in names if n.startswith("doodle_")], reverse=True)
    sketches = sorted([n for n in names if n.startswith("sketch_")], reverse=True)
    arts = sorted([n for n in names if not n.startswith(("doodle_", "sketch_"))], reverse=True)

    def ts(n):
        return "".join(c for c in n if c.isdigit())[:14]

    out, used = [], set()
    for d in doodles:
        if not _ink_ok(os.path.join(GALLERY, d)):
            continue
        t = ts(d)
        color = ""
        for sk in sketches:
            if sk in used:
                continue
            if ts(sk) >= t:
                used.add(sk)
                color = sk if _ink_ok(os.path.join(GALLERY, sk), pencil=False) else ""
                break
        out.append({"time": t, "doodle": d, "sketch": color, "kind": "doodle"})
    for a in arts[:40]:
        out.append({"time": ts(a), "doodle": a, "sketch": "", "kind": "art"})
    out.sort(key=lambda x: x["time"], reverse=True)
    return out[:60]


async def api_ping(request):
    return web.json_response({"ok": True, "ts": int(time.time())})


async def api_status(request):
    services = [{"name": n, "port": p, "ok": port_ok(p)} for n, p in SERVICES]
    return web.json_response({
        "ok": True,
        "services": services,
        "her": her_state(),
        "memory": mem_count(),
        "self": self_ctx(),
        "art": len(art_list()),
        "now": int(time.time()),
    })


OPS_LOG = r"D:\你的数据目录\logs\ops_events.jsonl"


async def api_ops(request):
    import datetime
    today = datetime.date.today().isoformat()
    rows = []
    try:
        with open(OPS_LOG, encoding="utf-8", errors="replace") as f:
            for line in f.readlines()[-4000:]:
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                ts = float(ev.get("ts") or 0)
                if datetime.date.fromtimestamp(ts).isoformat() == today:
                    rows.append(ev)
    except OSError:
        pass
    n = len(rows)
    avg = lambda k: round(sum(float(r.get(k) or 0) for r in rows) / n, 1) if n else 0
    by_src = {}
    for r in rows:
        by_src[r.get("src") or "?"] = by_src.get(r.get("src") or "?", 0) + 1
    return web.json_response({
        "ok": True, "turns": n,
        "avg_latency_ms": avg("latency_ms"),
        "avg_selected": avg("selected"),
        "avg_chars": avg("chars"),
        "by_src": by_src,
        "memory": mem_count(),
        "recent": rows[-10:][::-1],
    })


async def api_art(request):
    return web.json_response({"ok": True, "items": art_list()})


def _camera_source() -> str:
    try:
        with open(CAMERA_SOURCE, encoding="utf-8") as f:
            s = str(json.load(f).get("source") or "pc").lower()
            return "pico" if s == "pico" else "pc"
    except Exception:
        return "pc"


async def api_camera_source(request):
    """带TA出门：全局切换她的视觉入口。"""
    if request.method == "GET":
        return web.json_response({"ok": True, "source": _camera_source()})
    try:
        body = await request.json()
    except Exception:
        body = {}
    source = "pico" if bool(body.get("on")) or str(body.get("source") or "").lower() == "pico" else "pc"
    os.makedirs(os.path.dirname(CAMERA_SOURCE), exist_ok=True)
    tmp = CAMERA_SOURCE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"source": source, "updated": int(time.time())}, f, ensure_ascii=False)
    os.replace(tmp, CAMERA_SOURCE)
    return web.json_response({"ok": True, "source": source})


async def artimg(request):
    name = os.path.basename(request.query.get("name") or "")
    full = os.path.normpath(os.path.join(GALLERY, name))
    if not full.startswith(os.path.normpath(GALLERY) + os.sep) or not os.path.isfile(full):
        return web.Response(status=404)
    ctype = "image/png" if name.lower().endswith(".png") else "image/jpeg"
    with open(full, "rb") as f:
        return web.Response(body=f.read(), content_type=ctype,
                            headers={"Cache-Control": "max-age=3600"})


async def manifest_dynamic(request):
    """PWA 清单：start_url 带口令，装成应用后一打开就是能用的页面。"""
    tok = read_text(VIDEO_GATE)
    data = {
        "name": "TA",
        "short_name": "TA",
        "description": "TA的家：聊天 / 视频通话 / 状态 / 画廊 / 控制台",
        "start_url": "/?t=" + tok,
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#070d18",
        "theme_color": "#070d18",
        "icons": [
            {"src": "/icon.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icon.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    resp = web.json_response(data, content_type="application/manifest+json")
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def index(request):
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    # 把口令注入 iframe 地址（页面本身已经过 gate）
    chat_key = read_text(WEBCHAT_KEY)
    video_key = read_text(VIDEO_GATE)
    html = html.replace("__CHAT_TOK__", chat_key).replace("__VIDEO_TOK__", video_key)
    return web.Response(text=html, content_type="text/html")


async def static_file(request):
    name = os.path.basename(request.path)
    full = os.path.join(STATIC, name)
    if not os.path.isfile(full):
        return web.Response(status=404)
    ext = os.path.splitext(full)[1].lower()
    ctype = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
             ".css": "text/css; charset=utf-8", ".png": "image/png",
             ".webmanifest": "application/manifest+json"}.get(ext, "application/octet-stream")
    with open(full, "rb") as f:
        return web.Response(body=f.read(), headers={"Content-Type": ctype})


# ---------------- 她 · 此刻（生命+脑内整合页）的只读代理 ----------------
async def _proxy_json(url, timeout=10):
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as sess:
            async with sess.get(url) as r:
                return web.Response(body=await r.read(),
                                    headers={"Content-Type": "application/json; charset=utf-8"})
    except Exception:
        return web.Response(status=502, text="{}",
                            headers={"Content-Type": "application/json"})


async def she_page(request):
    return web.Response(
        text=open(os.path.join(STATIC, "she.html"), encoding="utf-8").read(),
        content_type="text/html", charset="utf-8")



async def api_she(request):
    return await _proxy_json("http://127.0.0.1:8003/api/she-state?t=" + read_text(VIDEO_GATE))


async def api_life_state(request):
    """lifeviz 页用的原始接口（与 /api/life 同源）"""
    return await _proxy_json("http://127.0.0.1:8005/api/state")


async def api_life(request):
    return await _proxy_json("http://127.0.0.1:8005/api/state")


async def api_brain_stats(request):
    return await _proxy_json("http://127.0.0.1:8006/api/stats")


async def api_brain_recent(request):
    return await _proxy_json("http://127.0.0.1:8006/api/recent?n=6")


async def api_brain_graph(request):
    return await _proxy_json("http://127.0.0.1:8006/api/graph", timeout=20)


async def api_brain_node(request):
    nid = str(request.query.get("id") or "0")
    return await _proxy_json("http://127.0.0.1:8006/api/node?id=" + nid)




# ---------------- 脑内（直接搬运 brainviz 页面） ----------------
BRAIN_STATIC = os.path.join(STATIC, "brain")


async def lvb_static(request):
    """lifeviz 的可视化脚本（直接搬过来的那套）"""
    name = os.path.basename(request.path)
    full = os.path.join(STATIC, "lvb", name)
    if not os.path.isfile(full):
        return web.Response(status=404)
    ext = os.path.splitext(full)[1].lower()
    ctype = {".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}.get(ext, "application/octet-stream")
    with open(full, "rb") as f:
        body = f.read()
    return web.Response(body=body, headers={"Content-Type": ctype, "Cache-Control": "no-store"})


async def brain_page(request):
    return await brain_static(request)


async def brain_static(request):
    name = os.path.basename(request.path)
    if name in ("", "brain"):
        name = "index.html"
    full = os.path.join(BRAIN_STATIC, name)
    if not os.path.isfile(full):
        return web.Response(status=404)
    ext = os.path.splitext(full)[1].lower()
    ctype = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
             ".css": "text/css; charset=utf-8", ".png": "image/png"}.get(ext, "application/octet-stream")
    with open(full, "rb") as f:
        body = f.read()
    return web.Response(body=body, headers={"Content-Type": ctype, "Cache-Control": "no-store"})


async def api_graph(request):
    return await _proxy_json("http://127.0.0.1:8006/api/graph", timeout=25)


async def api_bstats(request):
    return await _proxy_json("http://127.0.0.1:8006/api/stats")


async def api_brecent(request):
    return await _proxy_json("http://127.0.0.1:8006/api/recent?n=12")


async def api_bdecay(request):
    return await _proxy_json("http://127.0.0.1:8006/api/decay")


async def api_bnode(request):
    return await _proxy_json("http://127.0.0.1:8006/api/node?id=" + str(request.query.get("id", "0")))


async def api_bsearch(request):
    return await _proxy_json("http://127.0.0.1:8006/api/search?q=" + str(request.query.get("q", "")))


def build_app():
    app = web.Application(middlewares=[gate_middleware])
    app.router.add_get("/", index)
    app.router.add_get("/she", she_page)
    app.router.add_get("/brain/", brain_page)
    app.router.add_get("/lvb/{name}", lvb_static)
    app.router.add_get("/brain/{name}", brain_static)
    app.router.add_get("/api/graph", api_graph)
    app.router.add_get("/api/stats", api_bstats)
    app.router.add_get("/api/recent", api_brecent)
    app.router.add_get("/api/decay", api_bdecay)
    app.router.add_get("/api/node", api_bnode)
    app.router.add_get("/api/search", api_bsearch)
    app.router.add_get("/api/ping", api_ping)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/art", api_art)
    app.router.add_get("/api/camera_source", api_camera_source)
    app.router.add_post("/api/camera_source", api_camera_source)
    app.router.add_get("/api/ops", api_ops)
    app.router.add_get("/api/she", api_she)
    app.router.add_get("/api/life", api_life)
    app.router.add_get("/api/state", api_life_state)
    app.router.add_get("/api/brain-stats", api_brain_stats)
    app.router.add_get("/api/brain-recent", api_brain_recent)
    app.router.add_get("/api/brain-graph", api_brain_graph)
    app.router.add_get("/api/brain-node", api_brain_node)
    app.router.add_get("/artimg", artimg)
    app.router.add_get("/manifest.webmanifest", manifest_dynamic)
    app.router.add_get("/sw.js", static_file)
    app.router.add_get("/icon.png", static_file)
    app.router.add_get("/static/{name}", static_file)
    return app


def main():
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("TA Hub：http://127.0.0.1:%d/?t=%s" % (PORT, KEY), flush=True)
    web.run_app(build_app(), host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
