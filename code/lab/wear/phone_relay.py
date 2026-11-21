"""手机转发通道：给安卓 App 用的原始 TCP 协议。

为什么不用 WebSocket：安卓端我们要手写客户端（没有 Gradle），
裸 TCP + 定长帧最省事，也少一层依赖。

帧格式（双向一致）：
    [1 字节 类型][4 字节 大端长度][负载]
    类型 1 = PCM16 麦克风音频（16k 单声道）
    类型 2 = JSON 控制消息（UTF-8）

手机 → 电脑：类型 1（音频）、类型 2（hello / ping）
电脑 → 手机：类型 2（heard / subtitle / voice_pcm）
"""
from __future__ import annotations

import asyncio
import base64
import json
import struct
import time

import sys
sys.path.insert(0, r"D:\你的数据目录\lab\hands")
try:
    import hands_client
except Exception:  # noqa: BLE001
    hands_client = None
sys.path.insert(0, r"D:\你的数据目录\lab\game")
try:
    import playbook
except Exception:  # noqa: BLE001
    playbook = None

TYPE_AUDIO = 1
TYPE_JSON = 2

# "看看我"这类话 → 用电脑上的 E4 看她爸，而不是手机相机
EYE_PHRASES = ("看看我", "看看你", "看着我", "看看你", "看看我现在", "看看我干嘛")



def pack(kind: int, payload: bytes) -> bytes:
    return struct.pack(">BI", kind, len(payload)) + payload


async def read_frame(reader: asyncio.StreamReader):
    head = await reader.readexactly(5)
    kind, length = struct.unpack(">BI", head)
    body = await reader.readexactly(length) if length else b""
    return kind, body


def mp3_to_pcm16k(mp3: bytes) -> bytes:
    """把 TTS 的 mp3 转成 16k 单声道 PCM，手机端直接 AudioTrack 播。"""
    import os
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "a.mp3")
        dst = os.path.join(td, "a.pcm")
        with open(src, "wb") as f:
            f.write(mp3)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", src,
             "-f", "s16le", "-ar", "16000", "-ac", "1", dst],
            check=True, timeout=60,
        )
        with open(dst, "rb") as f:
            return f.read()


def ctx_tts_text(text: str) -> str:
    """播报前去掉颜文字/表情（字幕保留，只影响语音）。"""
    import re as _re
    if not text:
        return ""
    t = text
    t = _re.sub(r"[（(][^）)]{0,12}[）)]", "", t)
    t = _re.sub(r"[\^_~`´｀・ω・∇ﾟ▽△□☆★♪♡♥→←↑↓]", "", t)
    t = _re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", t)
    t = _re.sub(r"\s{2,}", " ", t)
    return t.strip() or text.strip()


SYNTH = None      # 由 server 注入：本地 piper 合成（同步，返回 PCM bytes）


async def tts_pcm_b64(text: str, voice: str) -> str:
    """给她的话合成 PCM（手机端不用解码 ogg）。

    优先本地 piper（约 0.1 秒），失败退回 edge-tts（约 1.2 秒，走网络）。
    """
    text = ctx_tts_text(text)
    if not text:
        return ""

    # 少女音优先（edge），失败再退回本地 piper
    try:
        import local_tts
        pcm = await local_tts.edge_pcm16k(text)
        if pcm:
            return base64.b64encode(pcm).decode()
    except Exception as exc:  # noqa: BLE001
        print("[手机通道] edge 少女音失败，用本地:", exc)

    if SYNTH:
        try:
            pcm = await asyncio.to_thread(SYNTH, text)
            if pcm:
                return base64.b64encode(pcm).decode()
        except Exception as exc:  # noqa: BLE001
            print("[手机通道] 本地合成失败:", exc)

    try:
        import edge_tts

        com = edge_tts.Communicate(text, voice)
        buf = bytearray()
        async for chunk in com.stream():
            if chunk.get("type") == "audio":
                buf.extend(chunk["data"])
        if not buf:
            return ""
        pcm = await asyncio.to_thread(mp3_to_pcm16k, bytes(buf))
        return base64.b64encode(pcm).decode()
    except Exception as exc:  # noqa: BLE001
        print("[手机通道] TTS 失败:", exc)
        return ""


async def handle_phone(reader, writer, ctx):
    """一个手机连接：收音频、断句、识别、回复。"""
    peer = writer.get_extra_info("peername")
    print("[手机] 连上", peer)
    try:
        await ctx["broadcast"]({"type": "phone", "state": "online"})
    except Exception:  # noqa: BLE001
        pass
    buf = bytearray()
    has_speech = False
    silence_ms = 0.0
    t0 = None
    try:
        while True:
            kind, body = await read_frame(reader)

            if kind == TYPE_JSON:
                try:
                    msg = json.loads(body)
                except ValueError:
                    continue
                if msg.get("type") == "hello":
                    try:
                        n = ctx["take_armed"]() if ctx.get("take_armed") else 0
                        if n:
                            print("[声纹]", ctx["enroll_start"](n))
                            writer.write(pack(TYPE_JSON, json.dumps(
                                {"type": "subtitle", "text": "开始录音纹，说 %d 句话" % n,
                                 "mood": "serious"}, ensure_ascii=False).encode()))
                            await writer.drain()
                    except Exception as exc:  # noqa: BLE001
                        print("[声纹] 自动注册失败:", exc)
                    writer.write(pack(TYPE_JSON, json.dumps(
                        {"type": "caps", "sr": ctx["sr"], "device": "phone"}
                    ).encode()))
                    await writer.drain()
                elif msg.get("type") == "ping":
                    writer.write(pack(TYPE_JSON, b'{"type":"pong"}'))
                    await writer.drain()
                elif msg.get("type") == "image":
                    shot = msg.get("data", "")
                    said = msg.get("text", "") or "看看这个"
                    b64 = shot.split(",", 1)[-1] if shot.startswith("data:") else shot
                    desc = await asyncio.to_thread(ctx["describe"], b64) if b64 else ""
                    if desc:
                        composed = ("（你把手机镜头对着前方，你看见：%s）%s" % (desc, said)).strip()
                    else:
                        composed = ("（你举起手机给你看，但你没看清）%s" % said).strip()
                    reply = ctx["clean"](await asyncio.to_thread(ctx["ask"], composed))
                    ctx["remember"](composed, reply)
                    send({"type": "heard", "text": said})
                    send({"type": "subtitle", "text": reply, "mood": ctx["mood"]()})
                    pcm = await tts_pcm_b64(reply, ctx["voice"])
                    if pcm:
                        send({"type": "voice_pcm", "data": pcm, "sr": ctx["sr"]})
                    await writer.drain()
                elif msg.get("type") == "text":
                    text = msg.get("text", "")
                    if text:
                        await reply_to(reader, writer, ctx, text, t0)
                    continue
                continue

            if kind != TYPE_AUDIO:
                continue

            pcm = body

            # 防回路：她正在播报时，麦克风收到的声音一律丢掉
            if time.time() < ctx.get("busy_until", 0.0):
                buf.clear()
                has_speech = False
                silence_ms = 0.0
                t0 = None
                continue

            # 预录缓冲：把说话前 0.4 秒也留下，避免吃掉第一个字
            if "preroll" not in ctx:
                ctx["preroll"] = bytearray()
            preroll = ctx["preroll"]
            preroll.extend(pcm)
            max_pre = int(ctx["sr"] * 2 * 0.4)
            if len(preroll) > max_pre:
                del preroll[:len(preroll) - max_pre]

            import numpy as np
            arr = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
            rms = float(np.sqrt((arr ** 2).mean())) if arr.size else 0.0

            if rms > 0.008:
                if not has_speech:
                    buf.extend(preroll)      # 第一次检测到说话：连预录一起收
                    has_speech = True
                else:
                    buf.extend(pcm)          # 后续帧正常追加
                silence_ms = 0.0
            elif has_speech:
                buf.extend(pcm)              # 收尾的静音也留着，方便断句
                silence_ms += arr.size / ctx["sr"] * 1000.0

            if not has_speech:
                t0 = None
                continue

            if t0 is None:
                t0 = time.time()
            dur = len(buf) / 2 / ctx["sr"]
            if dur < 0.8 or (silence_ms < 1500 and dur < 25.0):
                continue

            audio = bytes(buf)
            buf.clear()
            has_speech = False
            silence_ms = 0.0
            await reply_to(reader, writer, ctx, None, t0, audio)
            t0 = None
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass
    except Exception as exc:  # noqa: BLE001
        print("[手机] 异常:", exc)
    finally:
        print("[手机] 断开", peer)
        try:
            await ctx["broadcast"]({"type": "phone", "state": "offline"})
        except Exception:  # noqa: BLE001
            pass
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass


def looks_like_speech(audio: bytes, sr: int) -> bool:
    """判断这段音频像不像人说话，挡掉噪声被识别成字的情况。"""
    import numpy as np

    if not audio or len(audio) < sr:          # 少于 0.5 秒直接丢
        return False
    arr = np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768.0
    frame = int(sr * 0.02)                    # 20ms 一帧
    if frame <= 0:
        return False
    n = len(arr) // frame
    if n < 5:
        return False
    frames = arr[: n * frame].reshape(n, frame)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    loud = (rms > 0.015).mean()               # 有多少帧像说话
    peak = float(np.abs(arr).max())
    return loud > 0.03 and peak > 0.01   # 蓝牙 HFP 音量偏低，门槛放宽


async def reply_to(reader, writer, ctx, text, t0, audio=None):
    """识别（如果需要）→ 问她 → 回字幕 + PCM 语音。"""
    if text is None:
        try:
            import numpy as np

            enrolling = False
            try:
                ea = ctx.get("enroll_active")
                enrolling = bool(ea and ea())
            except Exception:  # noqa: BLE001
                enrolling = False

            if enrolling:
                # 注册期间：必须真的识别出话，才当作样本（挡掉噪声）
                import numpy as _np
                wave = _np.frombuffer(audio, dtype="<i2").astype(_np.float32) / 32768.0
                try:
                    said = await asyncio.to_thread(ctx["asr"].transcribe, wave)
                except Exception as exc:  # noqa: BLE001
                    print("[声纹] 转写失败:", exc)
                    return
                said = (said or "").strip()
                if len(said) < 4:
                    print("[声纹] 这段没听出内容，跳过（%r）" % said[:12])
                    return
                print("[声纹] 这段听到：%s" % said[:30])
                try:
                    ctx["speaker_ok"](audio)
                except Exception as exc:  # noqa: BLE001
                    print("[声纹] 收样本失败:", exc)
                return

            # 2026-11-08：只保留"有没有声音"的最低门槛
            # 静音段绝不送识别，否则 whisper 会顺着热词编内容
            import numpy as _np
            arr = _np.frombuffer(audio, dtype="<i2").astype(_np.float32) / 32768.0
            peak = float(_np.abs(arr).max()) if arr.size else 0.0
            rms = float(_np.sqrt((arr ** 2).mean())) if arr.size else 0.0
            if peak < 0.02 or rms < 0.004:
                print("[手机] 基本是静音（peak %.3f rms %.3f），跳过识别" % (peak, rms))
                return

            wave = np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768.0
            _t0 = time.time()
            text, ok = await asyncio.to_thread(ctx["asr"].transcribe_scored, wave)
            print("[耗时] 识别 %.2fs" % (time.time() - _t0), flush=True)
            if not ok:
                print("[手机] 识别置信度太低（疑似噪声），丢弃：%r" % (text or "")[:20])
                return
            print("[调试] 这段听到：%r（%.1f 秒）" % ((text or "")[:40], len(audio)/2.0/ctx["sr"]), flush=True)
            try:
                import wave as _wv
                import os as _os
                d = r"D:\你的数据目录\lab\voice\debug"
                _os.makedirs(d, exist_ok=True)
                fn = _os.path.join(d, "last_%d.wav" % int(time.time()))
                with _wv.open(fn, "wb") as wf:
                    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(ctx["sr"])
                    wf.writeframes(audio)
                # 只留最近 20 段，避免越攒越多
                old_files = sorted(_os.listdir(d))[:-20]
                for name in old_files:
                    try:
                        _os.unlink(_os.path.join(d, name))
                    except OSError:
                        pass
            except Exception:  # noqa: BLE001
                pass

            # 先识别，再判断说话人（否则"记住你的声纹"这句本身也会被拒）
            if text and "声纹" in text and ("记住" in text or "注册" in text):
                pass                      # 触发句：放行，下面处理
            else:
                # 窗口级过滤：只保留像你的片段，别人的话被切掉
                # 2026-11-08：窗口过滤误杀太狠（保留率 9%），暂时停用
                # 只保留整段声纹判定，避免把你自己也切掉
                if False:
                    flt = ctx.get("speaker_filter")
                    if flt:
                        audio = await asyncio.to_thread(flt, audio)
                        if not audio:
                            print("[手机] 过滤后没有你的声音，跳过")
                            return
                spk_ok = ctx.get("speaker_ok")
                if spk_ok and not await asyncio.to_thread(spk_ok, audio):
                    # 声纹没过：只有喊了称呼才再给一次机会
                    said = (text or "")
                    if any(k in said for k in ("TA", "你", "TA")):
                        print("[手机] 声纹没过但喊了称呼，放行")
                    else:
                        print("[手机] 声纹不通过，跳过")
                        return
                wave = np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768.0
        except Exception as exc:  # noqa: BLE001
            print("[手机] 识别失败:", exc)
            return

    text = (text or "").strip()
    if len(text) < 2:
        return

    def send(obj):
        writer.write(pack(TYPE_JSON, json.dumps(obj, ensure_ascii=False).encode()))

    send({"type": "heard", "text": text})

    # 语音触发注册声纹：「TA，记住你的声纹」
    if "声纹" in text and ("记住" in text or "注册" in text):
        try:
            msg = ctx["enroll_start"](6)
        except Exception as exc:  # noqa: BLE001
            msg = "注册失败：%s" % exc
        send({"type": "subtitle", "text": "好，现在开始记你的声音。\n说六句话，每句两三秒。",
              "mood": "serious"})
        try:
            await ctx["broadcast"]({"type": "subtitle",
                                    "text": "开始录音纹，说六句话",
                                    "mood": "serious"})
        except Exception:  # noqa: BLE001
            pass
        await writer.drain()
        print("[声纹]", msg)
        return
    try:
        await ctx["broadcast"]({"type": "heard", "text": text})
    except Exception:  # noqa: BLE001
        pass

    if "休息" in text:
        goodbye = "那我先歇会儿，你叫我再来。"
        pcm = await tts_pcm_b64(goodbye, ctx["voice"])
        if pcm:
            send({"type": "voice_pcm", "data": pcm, "sr": ctx["sr"]})
            import base64 as _b64
            seconds = len(_b64.b64decode(pcm)) / 2.0 / ctx["sr"]
            ctx["busy_until"] = time.time() + seconds + 0.8
        send({"type": "close", "text": goodbye})
        await writer.drain()
        return

    # 操作电脑：只认少量固定句式，走 8010 白名单
    if hands_client is not None:
        try:
            act = hands_client.parse(text)
        except Exception:  # noqa: BLE001
            act = None
        if act:
            res = await asyncio.to_thread(hands_client.call, act)
            prompt = hands_client.hint_text(act, res)
            send({"type": "heard", "text": text})
            reply = ctx["clean"](await asyncio.to_thread(ctx["ask"], prompt))
            ctx["remember"](text, reply)
            send({"type": "subtitle", "text": reply, "mood": ctx["mood"]()})
            pcm = await tts_pcm_b64(reply, ctx["voice"])
            if pcm:
                send({"type": "voice_pcm", "data": pcm, "sr": ctx["sr"]})
            ctx["busy_until"] = time.time() + max(1.5, len(reply) * 0.22) + 0.8
            await writer.drain()
            return

    if any(k in text for k in EYE_PHRASES):
        # 看画面要几秒：先说一句口头禅，别让她"没声"
        try:
            filler = ctx.get("filler")
            if filler:
                fb64 = await asyncio.to_thread(filler)
                if fb64:
                    send({"type": "voice_pcm", "data": fb64, "sr": ctx["sr"]})
                    await writer.drain()
        except Exception:  # noqa: BLE001
            pass
        try:
            fn = ctx.get("pc_eye")
            note = await asyncio.to_thread(fn) if fn else ""
        except Exception as exc:  # noqa: BLE001
            print("[手机] 电脑摄像头失败:", exc)
            note = ""
        ask_text = (note + text) if note else text
        send({"type": "heard", "text": text})
        reply = ctx["clean"](await asyncio.to_thread(ctx["ask"], ask_text))
        ctx["remember"](ask_text, reply)
        send({"type": "subtitle", "text": reply, "mood": ctx["mood"]()})
        pcm = await tts_pcm_b64(reply, ctx["voice"])
        if pcm:
            send({"type": "voice_pcm", "data": pcm, "sr": ctx["sr"]})
        # 播报期间静默，顺带把重复分段挡掉
        ctx["busy_until"] = time.time() + max(2.0, len(reply) * 0.22) + 1.0
        await writer.drain()
        return

    if any(k in text for k in ("看看", "看一下", "看这个")):
        send({"type": "need_photo", "text": text})
        # 关键：眼镜上的 HUD 也要收到，否则页面不知道要拍照
        try:
            await ctx["broadcast"]({"type": "need_photo", "text": text})
            print("[手机] 已通知眼镜拍照")
        except Exception as exc:  # noqa: BLE001
            print("[手机] 通知眼镜失败:", exc)
        await writer.drain()
        return

    note = ""
    try:
        fn = ctx.get("frame_note")
        if fn:
            note = await asyncio.to_thread(fn)
    except Exception:  # noqa: BLE001
        note = ""
    # 2026-11-08：边生成边合成，先出声再等全文
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def on_sentence(piece):
        loop.call_soon_threadsafe(queue.put_nowait, piece)

    # 并发合成、按顺序播放：每句的 edge-tts 网络往返约 1.2 秒，
    # 串行会累加；并发后总时长约等于最长的一句。
    pending = []

    async def flush_ready(final=False):
        while pending and (final or pending[0][1].done()):
            idx, task = pending[0]
            try:
                pcm = await task if final else task.result()
            except Exception as exc:  # noqa: BLE001
                print("[手机] 分段语音失败:", exc)
                pcm = None
            pending.pop(0)
            if pcm:
                send({"type": "voice_pcm", "data": pcm, "sr": ctx["sr"]})
                await writer.drain()
            if not final:
                break

    async def speak_worker():
        while True:
            piece = await queue.get()
            if piece is None:
                await flush_ready(final=True)
                return
            pending.append((len(pending), asyncio.create_task(
                tts_pcm_b64(piece, ctx["voice"]))))
            print("[耗时] 已排队合成「%s」" % piece[:10], flush=True)
            await flush_ready()

    # 先放一句口头禅，别让她"想"的时候没声音
    try:
        filler = ctx.get("filler")
        if filler:
            fb64 = await asyncio.to_thread(filler)
            if fb64:
                send({"type": "voice_pcm", "data": fb64, "sr": ctx["sr"]})
                await writer.drain()
                import base64 as _b64
                ctx["busy_until"] = time.time() + len(_b64.b64decode(fb64)) / 2.0 / ctx["sr"] + 0.3
    except Exception as exc:  # noqa: BLE001
        print("[手机] 占位音失败:", exc)

    worker = asyncio.create_task(speak_worker())
    _t_ask0 = time.time()
    _first = {"t": 0.0}

    _acc = {"text": ""}

    def on_sentence_timed(piece):
        if not _first["t"]:
            _first["t"] = time.time() - _t_ask0
            print("[耗时] 首句 %.2fs" % _first["t"], flush=True)
        # 逐句把字幕推过去：她说到哪，屏幕就显示到哪
        pro = _acc["text"] + piece
        keep = _acc["text"]
        _acc["text"] = pro
        if pro.strip():
            async def _emit(txt=pro):
                send({"type": "subtitle", "text": txt, "mood": ctx["mood"](),
                      "progressive": True})
                await writer.drain()
            try:
                asyncio.run_coroutine_threadsafe(_emit(), loop)
            except Exception as exc:  # noqa: BLE001
                print("[手机] 逐句字幕失败:", exc)
                _acc["text"] = keep
        on_sentence(piece)

    teach_quote = ""
    ask_text = (note + text) if note else text
    if playbook is not None:
        try:
            if playbook.is_teaching(text):
                teach_quote = text
                ask_text = ("（你在教你玩绝区零：%s）先用你自己的话总结：什么情况、怎么做、为什么（必须带一句\u201c因为\u2026\u201d），"
                            "再跟他说一句你记住了。不要背原话，要讲逻辑。" % text)
        except Exception as exc:  # noqa: BLE001
            print("[教学] 识别失败:", exc)

    raw = await asyncio.to_thread(ctx["ask"], ask_text, 60.0, on_sentence_timed)
    print("[耗时] 全文 %.2fs" % (time.time() - _t_ask0), flush=True)
    loop.call_soon_threadsafe(queue.put_nowait, None)
    reply = ctx["clean"](raw)
    ctx["remember"](text, reply)
    if teach_quote and reply and playbook is not None:
        try:
            rule = playbook.add(summary=reply, quote=teach_quote)
            print("[教学] 已记住玩法 %s（键位 %s）" % (rule["id"], rule["keys"]))
            try:
                import json as _json
                _pf = r"D:\你的数据目录\video\pending_memories.json"
                try:
                    with open(_pf, encoding="utf-8") as _f:
                        _items = _json.load(_f)
                    if not isinstance(_items, list):
                        _items = []
                except Exception:  # noqa: BLE001
                    _items = []
                _items.append({"summary": reply, "importance": 0.55,
                               "source": "game_teach", "time": time.time()})
                with open(_pf, "w", encoding="utf-8") as _f:
                    _json.dump(_items, _f, ensure_ascii=False, indent=2)
            except Exception as exc:  # noqa: BLE001
                print("[教学] 写记忆队列失败:", exc)
        except Exception as exc:  # noqa: BLE001
            print("[教学] 存档失败:", exc)
    mood = ctx["mood"]()
    send({"type": "subtitle", "text": reply, "mood": mood})
    try:
        await ctx["broadcast"]({"type": "subtitle", "text": reply, "mood": mood})
    except Exception as exc:  # noqa: BLE001
        print("[手机] 广播字幕失败:", exc)
    await worker
    # 播报期间静默（按总字数估个保守窗口）
    ctx["busy_until"] = time.time() + max(1.5, len(reply) * 0.22) + 0.8
    await writer.drain()


async def serve_phone(host: str, port: int, ctx):
    server = await asyncio.start_server(
        lambda r, w: handle_phone(r, w, ctx), host, port
    )
    print("手机转发通道已启动：tcp://%s:%d" % (host, port))
    async with server:
        await server.serve_forever()
