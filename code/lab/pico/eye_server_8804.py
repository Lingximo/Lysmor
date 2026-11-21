# -*- coding: utf-8 -*-
"""她通过 Pico 的眼睛看世界：相机帧接收服务（端口 8804）

2026-11-10 为 Pico 4 Ultra 准备：
  Pico 上的 OpenXR 应用把透视相机帧（JPEG）POST 到这里
  这里做限流 + 缓存 + 调本地视觉模型描述
  描述结果可以被她的话引用（第一期先独立，第二期接进 video server）

接口：
  GET  /health
  GET  /state                → 帧计数 / 最近时间 / 最近描述
  POST /frame?describe=1      body 就是 JPEG 原始字节
  GET  /latest.jpg            → 最近一帧（调试用）
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import time

import aiohttp
from aiohttp import web

PORT = 8804
OLLAMA = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3-vl:4b"
DESCRIBE_MIN_GAP = 3.0      # 同一个源最多 3 秒描述一次
LOG_DIR = r"D:\你的数据目录\logs"
LOG = os.path.join(LOG_DIR, "pico_eye.log")

STATE = {
    "frames": 0,
    "bytes": 0,
    "last_frame_at": 0.0,
    "last_desc": "",
    "last_desc_at": 0.0,
    "describes": 0,
    "errors": 0,
    "latest": None,
    "fps_window": [],
}

_LOCK = asyncio.Lock()


def log(tag: str, detail) -> None:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s\t%s\t%s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), tag,
                json.dumps(detail, ensure_ascii=False)[:300]))
    except Exception:
        pass


async def describe(jpg: bytes) -> str:
    import base64
    b64 = base64.b64encode(jpg).decode()
    prompt = (
        "这是头显彩色透视相机看到的画面。用一两句话描述：你在做什么、"
        "手里/周围有什么值得注意的东西。不要提'相机'、'画面'、'屏幕'。"
    )
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "images": [b64],
        "stream": False,
        "options": {"num_predict": 900, "temperature": 0.2},
    }
    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(OLLAMA, json=payload) as resp:
            j = await resp.json(content_type=None)
    return str((j or {}).get("response") or "").strip()


async def api_frame(request: web.Request) -> web.Response:
    raw = await request.read()
    if not raw or len(raw) < 1024:
        return web.json_response({"ok": False, "error": "frame too small"}, status=400)
    if len(raw) > 4 * 1024 * 1024:
        return web.json_response({"ok": False, "error": "frame too large"}, status=413)

    now = time.time()
    STATE["frames"] += 1
    STATE["bytes"] += len(raw)
    STATE["last_frame_at"] = now
    STATE["latest"] = raw
    win = STATE["fps_window"]
    win.append(now)
    STATE["fps_window"] = [t for t in win if now - t <= 5.0]

    want = request.query.get("describe", "1") not in ("0", "false", "no")
    if not want or now - STATE["last_desc_at"] < DESCRIBE_MIN_GAP:
        return web.json_response({"ok": True, "described": False, "bytes": len(raw)})

    if _LOCK.locked():
        return web.json_response({"ok": True, "described": False, "busy": True})

    async with _LOCK:
        STATE["last_desc_at"] = now
        try:
            desc = await describe(raw)
            STATE["describes"] += 1
            STATE["last_desc"] = desc
            log("frame", {"bytes": len(raw), "desc": desc[:80]})
            return web.json_response({"ok": True, "described": True, "desc": desc})
        except Exception as exc:  # noqa: BLE001
            STATE["errors"] += 1
            log("error", {"error": str(exc)[:120]})
            return web.json_response({"ok": False, "error": str(exc)[:150]}, status=500)


async def api_state(request: web.Request) -> web.Response:
    now = time.time()
    fps = len([t for t in STATE["fps_window"] if now - t <= 5.0]) / 5.0
    return web.json_response({
        "ok": True,
        "frames": STATE["frames"],
        "mb": round(STATE["bytes"] / 1e6, 1),
        "fps": round(fps, 1),
        "last_frame_age": round(now - STATE["last_frame_at"], 1) if STATE["last_frame_at"] else None,
        "last_desc": STATE["last_desc"],
        "describes": STATE["describes"],
        "errors": STATE["errors"],
    })


async def api_latest(request: web.Request) -> web.Response:
    if not STATE["latest"]:
        return web.Response(status=404)
    return web.Response(body=STATE["latest"], content_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})


async def api_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "pico-eye"})


def build_app() -> web.Application:
    app = web.Application(client_max_size=8 * 1024 * 1024)
    app.router.add_get("/health", api_health)
    app.router.add_get("/state", api_state)
    app.router.add_get("/latest.jpg", api_latest)
    app.router.add_post("/frame", api_frame)
    return app


def main() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    print("Pico 眼睛服务：http://127.0.0.1:%d  （POST /frame 收 JPEG）" % PORT, flush=True)
    web.run_app(build_app(), host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
