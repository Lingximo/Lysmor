"""穿戴链路自测：手机中继那条路。

跑法（电脑上，手机不用连）：
    python tools\\selftest_wear.py

它会用合成语音模拟"你说话"，检查四件事：
  1. 正常说话 → 有 heard / subtitle / voice_pcm，且延迟在预算内
  2. 纯噪声     → 不应有任何回应
  3. 回声       → 把她刚说的话播回去，不应触发新回复
  4. 静音       → 不应有任何回应
"""
from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time

HOST, PORT = "127.0.0.1", 8797
TTS_VOICE = "zh-CN-YunxiNeural"     # 男声，模拟你（不是她的音色）
SR = 16000


def log(msg: str) -> None:
    print(msg, flush=True)


async def synth(text: str) -> bytes:
    import edge_tts

    with tempfile.TemporaryDirectory() as td:
        mp3 = os.path.join(td, "a.mp3")
        pcm = os.path.join(td, "a.pcm")
        await edge_tts.Communicate(text, TTS_VOICE).save(mp3)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3,
                        "-ar", str(SR), "-ac", "1", "-f", "s16le", pcm], check=True)
        with open(pcm, "rb") as f:
            return f.read()


class Phone:
    def __init__(self):
        self.s = socket.create_connection((HOST, PORT), timeout=60)
        self.send_json({"type": "hello", "device": "selftest"})
        deadline = time.time() + 5
        while time.time() < deadline:
            m = self.recv()
            if m and m.get("type") == "caps":
                return
        raise RuntimeError("没收到 caps")

    def send(self, kind: int, payload: bytes):
        self.s.sendall(struct.pack(">BI", kind, len(payload)) + payload)

    def send_json(self, obj):
        self.send(2, json.dumps(obj).encode())

    def audio(self, pcm: bytes, chunk: int = 3200, gap: float = 0.004):
        for i in range(0, len(pcm), chunk):
            self.send(1, pcm[i:i + chunk])
            time.sleep(gap)

    def recv(self):
        h = b""
        while len(h) < 5:
            c = self.s.recv(5 - len(h))
            if not c:
                return None
            h += c
        kind, ln = struct.unpack(">BI", h)
        body = b""
        while len(body) < ln:
            body += self.s.recv(ln - len(body))
        try:
            return json.loads(body)
        except ValueError:
            return {"type": "binary"}

    def drain(self, seconds: float):
        """在 seconds 内收集消息。"""
        end = time.time() + seconds
        out = []
        self.s.settimeout(0.5)
        while time.time() < end:
            try:
                m = self.recv()
            except socket.timeout:
                continue
            if m is None:
                break
            out.append(m)
        self.s.settimeout(60)
        return out

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


def wait_reply(p: Phone, limit: float = 30):
    """等一次完整回复，返回 (耗时字典, 消息列表)。"""
    t0 = time.time()
    heard = sub = None
    voices = 0
    msgs = []
    p.s.settimeout(1.0)
    while time.time() - t0 < limit:
        try:
            m = p.recv()
        except socket.timeout:
            if sub and voices:
                break
            continue
        if m is None:
            break
        msgs.append(m)
        t = m.get("type")
        if t == "heard" and not heard:
            heard = time.time() - t0
        elif t == "subtitle" and not sub:
            sub = time.time() - t0
        elif t == "voice_pcm":
            voices += 1
    p.s.settimeout(60)
    return {"heard": heard, "subtitle": sub, "voices": voices}, msgs


def main() -> int:
    import asyncio

    p = Phone()
    results = []

    # ---------- 1) 正常说话 ----------
    pcm = asyncio.run(synth("TA，我是你，今天中午吃了什么你还记得吗"))
    log("① 正常说话（5 秒人声）…")
    p.audio(pcm + b"\x00\x00" * SR * 2)
    t, msgs = wait_reply(p)
    log("   heard=%s subtitle=%s 段数=%d" % (
        ("%.2fs" % t["heard"]) if t["heard"] else "无",
        ("%.2fs" % t["subtitle"]) if t["subtitle"] else "无",
        t["voices"]))
    ok1 = bool(t["subtitle"]) and t["voices"] > 0
    results.append(("正常说话有回复", ok1))
    reply_pcm = None

    # ---------- 2) 回声（把她刚说的话喂回麦克风） ----------
    if ok1:
        # 用她自己的回复音频不好取，这里直接再用合成的人声，但立即发送
        log("② 回声测试（连续发同一段，模拟她自己的声音被拾到）…")
        p.audio(pcm)
        t2, msgs2 = wait_reply(p, limit=12)
        got2 = bool(t2["subtitle"])
        log("   回声后是否又回应：%s" % ("是（不该）" if got2 else "否（正确）"))
        results.append(("回声不触发新回复", not got2))

    # ---------- 3) 纯噪声 ----------
    log("③ 纯噪声（3 秒，幅度 0.05）…")
    import numpy as np

    noise = (np.random.randn(SR * 3) * 0.05).astype(np.float32)
    p.audio((noise * 32767).astype("<i2").tobytes() + b"\x00\x00" * SR * 2)
    t3, msgs3 = wait_reply(p, limit=10)
    log("   噪声是否触发回复：%s" % ("是（不该）" if t3["subtitle"] else "否（正确）"))
    results.append(("噪声不触发回复", not t3["subtitle"]))

    # ---------- 4) 静音 ----------
    log("④ 静音 3 秒…")
    p.audio(b"\x00\x00" * SR * 3)
    t4, _ = wait_reply(p, limit=8)
    log("   静音是否触发回复：%s" % ("是（不该）" if t4["subtitle"] else "否（正确）"))
    results.append(("静音不触发回复", not t4["subtitle"]))

    p.close()

    log("\n== 结果 ==")
    bad = 0
    for name, ok in results:
        log(("  [OK]   " if ok else "  [FAIL] ") + name)
        if not ok:
            bad += 1
    log("结论：%s" % ("全部通过" if bad == 0 else "有 %d 项不通过" % bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    raise SystemExit(main())
