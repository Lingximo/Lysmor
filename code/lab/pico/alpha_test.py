# -*- coding: utf-8 -*-
"""测试：headless Edge + CDP 截一张带 alpha 的 Live2D 图。"""
import asyncio
import base64
import json
import subprocess
import time

import requests
import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9223
URL = "http://127.0.0.1:8003/?panel=1"
UD = r"D:\你的数据目录\logs\edge_alpha"


async def main():
    proc = subprocess.Popen([
        EDGE, "--headless=new", f"--remote-debugging-port={PORT}",
        f"--user-data-dir={UD}", "--window-size=512,768",
        "--use-gl=swiftshader", "--enable-unsafe-swiftshader",
        "--default-background-color=00000000", "--hide-scrollbars", "--remote-allow-origins=*", "--no-first-run", "--no-default-browser-check",
        URL,
    ])
    try:
        ws_url = None
        for _ in range(30):
            time.sleep(0.5)
            try:
                tabs = requests.get(f"http://127.0.0.1:{PORT}/json", timeout=2).json()
                for t in tabs:
                    if t.get("type") == "page":
                        ws_url = t["webSocketDebuggerUrl"]
                        break
                if ws_url:
                    break
            except Exception:
                continue
        print("ws:", bool(ws_url))
        async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
            mid = 1

            async def cmd(method, params=None):
                nonlocal mid
                await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
                my = mid
                mid += 1
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == my:
                        return msg

            await cmd("Page.enable")
            await cmd("Emulation.setDeviceMetricsOverride",
                      {"width": 512, "height": 768, "deviceScaleFactor": 1, "mobile": False})
            await asyncio.sleep(6)
            r = await cmd("Page.captureScreenshot",
                          {"format": "png", "omitBackground": True, "fromSurface": True})
            data = base64.b64decode(r["result"]["data"])
            open(r"D:\你的数据目录\logs\alpha_test.png", "wb").write(data)
            print("bytes", len(data))
    finally:
        proc.terminate()


asyncio.run(main())
