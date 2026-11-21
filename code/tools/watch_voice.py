# -*- coding: utf-8 -*-
"""实时盯语音链路：谁在连、有没有下发音频、播放有没有报错。

只读日志，每秒扫一次新的行。
"""
from __future__ import annotations

import os
import time

FILES = {
    "webchat.out": r"D:\你的数据目录\logs\webchat.out.log",
    "webchat.err": r"D:\你的数据目录\logs\webchat.err.log",
    "video.out": r"D:\你的数据目录\logs\video.out.log",
    "video.err": r"D:\你的数据目录\logs\video.err.log",
    "wear.out": r"D:\你的数据目录\logs\wear.out.log",
    "wear.err": r"D:\你的数据目录\logs\wear.err.log",
}
KEY = ("语音", "voice", "Voice", "TTS", "tts", "音频", "Audio", "audio",
       "听", "耳", "Error", "error", "Traceback", "字幕", "reply", "presence",
       "在场", "前端", "播放")

pos = {}
for path in FILES.values():
    try:
        pos[path] = os.path.getsize(path)
    except OSError:
        pos[path] = 0

print("开始盯：", time.strftime("%H:%M:%S"), flush=True)
deadline = time.time() + 3600
while time.time() < deadline:
    for name, path in FILES.items():
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size < pos[path]:
            pos[path] = 0
        if size == pos[path]:
            continue
        try:
            with open(path, "rb") as f:
                f.seek(pos[path])
                chunk = f.read(size - pos[path])
            pos[path] = size
        except OSError:
            continue
        text = chunk.decode("utf-8", "replace")
        for line in text.splitlines():
            if any(k in line for k in KEY):
                print("%s | %-11s | %s" % (time.strftime("%H:%M:%S"), name, line.strip()[:220]),
                      flush=True)
    time.sleep(1.5)
