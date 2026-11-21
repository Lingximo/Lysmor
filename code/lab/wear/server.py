"""她的穿戴服务（电脑端）：眼镜 / 手机 ↔ 家里这台电脑。

只做四件事：
    ① 收眼镜上传的音频（PCM16 / 16k）
    ② 调本地 ASR 转文字（faster-whisper，GPU 6x 实时）
    ③ 调她的正式对话接口（8001）拿回复 —— 正文只由 deepseek-flash 生成
    ④ 回字幕（可能还有 TTS 音频）

眼镜那端（或手机浏览器）连 ws://<本机IP>:8014/ws 就行。

为什么是 WebSocket：一条连接双向跑，音频上行、字幕下行，NAT 友好；
    预算是 2 秒一轮，WS 那 50~100ms 完全够。

隔离：不开公网、不写她的 state/记忆、不改她的服务；只调用她已有的 HTTP 接口。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(LAB, "asr", "pylibs"))
sys.path.insert(0, os.path.join(LAB, "vision", "pylibs"))
sys.path.insert(0, os.path.join(LAB, "asr"))

import numpy as np  # noqa: E402
import websockets  # noqa: E402
import phone_relay  # noqa: E402

MOOD_STATE = (r"C:\你的用户\.astrbot_launcher\instances"
              r"\<BOT_INSTANCE>\core\data\plugin_data"
              r"\astrbot_plugin_companion_mood\state.json")


def mood_label() -> str:
    """读她的生理/情绪状态，映射到 8 张表情之一。"""
    try:
        with open(MOOD_STATE, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:  # noqa: BLE001
        return "neutral"

    def v(k, d=0.0):
        try:
            return float(st.get(k, d) or d)
        except Exception:  # noqa: BLE001
            return d

    # 难受优先：疼、经期、难过都算 sad
    if v("pain") > 0.5 or v("cramps") > 0.5:
        return "sad"
    if v("sadness") > 0.45 or v("valence") < -0.2:
        return "sad"
    # 害怕/惊讶
    if v("fear") > 0.55:
        return "surprised"
    # 生气/认真
    if v("anger") > 0.45:
        return "serious"
    # 害羞
    if v("shy") > 0.4:
        return "shy"
    # 睡着或很困
    if st.get("asleep") or v("energy") < 0.2:
        return "neutral"
    # 心情
    if v("valence") > 0.45:
        return "blissful"
    if v("valence") > 0.15:
        return "happy"
    return "neutral"


def describe_image(b64: str) -> str:
    """让本机 qwen3-vl 看一眼图，返回一句中文描述（失败返回空串）。"""
    import re
    import requests as _rq
    payload = {
        "model": "qwen3-vl:4b",
        "prompt": "这张图里有什么？用一句中文说。",
        "images": [b64],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2, "num_predict": 500},
    }
    for budget in (500, 900, 1400):
        payload["options"]["num_predict"] = budget
        try:
            r = _rq.post("http://127.0.0.1:11434/api/generate", json=payload, timeout=120)
            if r.status_code != 200:
                continue
            out = str((r.json() or {}).get("response") or "")
            out = re.sub(r"(?is)<think>.*?</think>", "", out)
            out = re.sub(r"(?is)<think>.*$", "", out).replace("</think>", "")
            out = " ".join(out.split())
            if out:
                return out[:160]
        except Exception:  # noqa: BLE001
            continue
    return ""


def remember(user_text: str, her_reply: str) -> None:
    """把眼镜上的对话写进待处理记忆队列（和其他入口共用同一条链路）。"""
    try:
        import sys
        if r"D:\你的数据目录\video" not in sys.path:
            sys.path.insert(0, r"D:\你的数据目录\video")
        import bridge
        bridge.append_pending(
            "你在眼镜上跟我说：%s；我回：%s" % (user_text[:200], her_reply[:300]),
            0.6,
            "glasses",
        )
    except Exception as exc:  # noqa: BLE001
        print("[记忆] 写入失败:", exc)


def clean_reply(text: str) -> str:
    """去掉思考过程/内心旁白，只留她要说的那句话。"""
    import re as _re
    if not text:
        return ""
    out = text
    out = _re.sub(r"(?is)<think[^>]*>.*?</think>", "", out)
    out = _re.sub(r"(?is)<think[^>]*>.*$", "", out)
    out = out.replace("</think>", "")
    lines = []
    for line in out.splitlines():
        t = line.strip()
        if not t:
            continue
        if _re.match(r"^(思考|分析|推理|步骤|让我想想|先想一下|内心|旁白)[:：]", t):
            continue
        if t.startswith("（") and t.endswith("）") and len(t) < 40:
            continue
        lines.append(t)
    out = "\n".join(lines).strip()
    return out or text.strip()


VOICE = "zh-CN-XiaoyiNeural"

sys.path.insert(0, os.path.join(LAB, "tts"))
try:
    import local_tts
except Exception:  # noqa: BLE001
    local_tts = None   # 2026-11-08：和 QQ 上同一个音色


PIPER_DIR = os.path.join(LAB, "tts", "piper")
PIPER_MODEL = os.path.join(PIPER_DIR, "zh_CN-huayan-medium.onnx")
_piper_voice = None


def _get_piper():
    global _piper_voice
    if _piper_voice is None and os.path.exists(PIPER_MODEL):
        try:
            from piper import PiperVoice
            _piper_voice = PiperVoice.load(PIPER_MODEL)
            print("[TTS] piper 已加载")
        except Exception as exc:  # noqa: BLE001
            print("[TTS] piper 加载失败:", exc)
            _piper_voice = False
    return _piper_voice or None


def piper_pcm(text: str):
    """本地合成，返回 16k 单声道 PCM16 bytes；不可用返回 None。"""
    voice = _get_piper()
    if not voice:
        return None
    try:
        import subprocess
        import tempfile
        import wave

        with tempfile.TemporaryDirectory() as td:
            raw = os.path.join(td, "a.wav")
            out = os.path.join(td, "a.pcm")
            with wave.open(raw, "wb") as wf:
                voice.synthesize_wav(text, wf)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw,
                            "-ar", str(SR), "-ac", "1", "-f", "s16le", out],
                           check=True, timeout=60)
            with open(out, "rb") as f:
                return f.read()
    except Exception as exc:  # noqa: BLE001
        print("[TTS] piper 合成失败:", exc)
        return None


def tts_text(text: str) -> str:
    """播报用的文本：去掉颜文字、表情、括号里的语气符号。"""
    import re as _re
    if not text:
        return ""
    t = text
    # 常见颜文字字符集
    t = _re.sub(r"[（(][^）)]{0,12}[）)]", "", t)      # (´-ω-`) 这类
    t = _re.sub(r"[\^_~`´｀・ω・∇ﾟ▽△□☆★♪♡♥→←↑↓]", "", t)
    t = _re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", t)  # emoji
    t = _re.sub(r"\s{2,}", " ", t)
    return t.strip() or text.strip()


async def tts_b64(text: str) -> str:
    """合成她的语音，转成 ogg/opus 的 data URL。

    AIUI 的 AudioPlayer 只明确支持 ogg_opus / pcm，mp3 播不出来，
    所以这里用 edge-tts 出 mp3，再用 ffmpeg 转 ogg。
    """
    try:
        import base64
        import os
        import subprocess
        import tempfile
        import edge_tts

        if local_tts is not None:
            ogg_edge = await local_tts.edge_ogg(text)
            if ogg_edge:
                return "data:audio/ogg;base64," + base64.b64encode(ogg_edge).decode()
            ogg_local = await asyncio.to_thread(local_tts.synth_ogg, text)
            if ogg_local:
                return "data:audio/ogg;base64," + base64.b64encode(ogg_local).decode()

        text = tts_text(text)
        com = edge_tts.Communicate(text, VOICE)
        mp3 = bytearray()
        async for chunk in com.stream():
            if chunk.get("type") == "audio":
                mp3.extend(chunk["data"])
        if not mp3:
            return ""

        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "a.mp3")
            dst = os.path.join(td, "a.ogg")
            with open(src, "wb") as f:
                f.write(bytes(mp3))
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                 "-c:a", "libopus", "-b:a", "24k", "-ar", "24000",
                 "-ac", "1", "-f", "ogg", dst],
                check=True, timeout=60,
            )
            with open(dst, "rb") as f:
                ogg = f.read()
        if not ogg:
            return ""
        return "data:audio/ogg;base64," + base64.b64encode(ogg).decode()
    except Exception as exc:  # noqa: BLE001
        print("[TTS] 合成失败:", exc)
        return ""



HER_API = "http://127.0.0.1:8001/api/send"
SR = 16000
FRAME = 640  # 20ms

_ears = None


def ears():
    """懒加载 ASR，第一次用才占显存。"""
    global _ears
    if _ears is None:
        import asr_lib
        _ears = asr_lib.Ears()
    return _ears


def ask_her(text: str, timeout: float = 60.0, on_sentence=None) -> str:
    """走她自己的对话接口。回复正文永远由她的模型生成（§74.2 红线）。"""
    import requests
    out = ""
    sent_from = 0
    with requests.post(HER_API, json={"text": text}, timeout=timeout, stream=True) as r:
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if "t" in ev:
                out += ev["t"]
                if on_sentence is not None:
                    # 按中文句末标点切句，切出来就回调（用于边生成边合成语音）
                    while True:
                        idx = -1
                        for ch in "。！？\n":
                            pos = out.find(ch, sent_from)
                            if pos >= 0 and (idx < 0 or pos < idx):
                                idx = pos
                        if idx < 0:
                            break
                        piece = out[sent_from:idx + 1].strip()
                        sent_from = idx + 1
                        if len(piece) >= 2:
                            on_sentence(piece)
            if ev.get("done"):
                break
    return out.strip()


# ---------------- 声纹：只认你 ----------------
VOICE_DIR = os.path.join(LAB, "voice")
PROFILE = os.path.join(VOICE_DIR, "profile_dad.npz")
SPK_THRESHOLD = 0.55          # 同人约 0.75，异人约 0.35
_SPK = None
_PROFILE_VEC = None
_ENROLL = {"left": 0, "vecs": []}
_ARM = {"n": 0}
TRUST_UNTIL = {"t": 0.0}   # 最近一次验证通过的时间   # 手机下次连上时自动开始注册


def _spk():
    global _SPK
    if _SPK is None:
        import sys
        if os.path.join(LAB, "voice") not in sys.path:
            sys.path.insert(0, os.path.join(LAB, "voice"))
        import speaker_lib
        _SPK = speaker_lib.SpeakerEncoder()
    return _SPK


def _ENROLL_vec_norm(v):
    import numpy as np
    return v / (np.linalg.norm(v) + 1e-8)


def _profile():
    """返回 (向量, 阈值)；没注册返回 (None, 0.0)。"""
    global _PROFILE_VEC
    if _PROFILE_VEC is None and os.path.exists(PROFILE):
        try:
            import numpy as np
            if PROFILE.endswith(".npz"):
                z = np.load(PROFILE)
                _PROFILE_VEC = (z["vec"], float(z["thr"]))
            else:
                _PROFILE_VEC = (np.load(PROFILE), SPK_THRESHOLD)
        except Exception:  # noqa: BLE001
            _PROFILE_VEC = None
    return _PROFILE_VEC or (None, 0.0)


def speaker_embed(audio: bytes):
    """PCM16 → 说话人向量（失败返回 None）。"""
    try:
        import numpy as np
        wave = np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768.0
        if wave.size < SR * 0.8:
            return None
        peak = float(np.abs(wave).max())
        if peak > 1e-4:
            wave = wave * (0.9 / peak)      # 音量归一化，减少链路增益差异
        return _spk().embed_pcm(wave)
    except Exception as exc:  # noqa: BLE001
        print("[声纹] 取向量失败:", exc)
        return None


def speaker_filter(audio: bytes, win: float = 1.6) -> bytes:
    """按 1.6 秒小窗口筛：只保留像你的片段，拼回去再识别。

    这样同段里混进别人的话，会被切掉，而不是整段带进去。
    """
    import numpy as np

    prof, thr = _profile()
    if prof is None:
        return audio

    try:
        wave = np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768.0
        if wave.size < SR * 1.0:
            return audio

        n = int(SR * win)
        keep = []
        total = 0
        for i in range(0, wave.size - n + 1, n):   # 不重叠，避免拼接后重复
            part = wave[i:i + n]
            peak = float(np.abs(part).max())
            if peak < 0.01:
                continue                    # 太安静，跳过
            norm = part * (0.9 / peak)
            try:
                vec = _spk().embed_pcm(norm)
            except Exception:  # noqa: BLE001
                continue
            score = float(np.dot(vec, prof))
            total += 1
            if score >= thr:
                keep.append(part)

        if not keep:
            print("[声纹] 整段都不像你，丢弃")
            return b""

        joined = np.concatenate(keep)
        print("[声纹] 窗口 %d 个，保留 %d 个（%.0f%%）" % (
            total, len(keep), 100.0 * len(keep) / max(total, 1)))
        return (joined * 32767).astype("<i2").tobytes()
    except Exception as exc:  # noqa: BLE001
        print("[声纹] 过滤失败，原样放行:", exc)
        return audio


def speaker_ok(audio: bytes) -> bool:
    """注册模式：收样本；平时：比对是不是你。"""
    import numpy as np

    import numpy as _np
    try:
        _dur = len(audio) / 2.0 / SR
    except Exception:  # noqa: BLE001
        _dur = 0.0
    if _dur < 1.5:
        # 极短：只在信任窗内放行，否则丢弃
        if time.time() < TRUST_UNTIL["t"]:
            return True
        print("[声纹] 段太短（%.1fs），又没有信任窗，丢弃" % _dur)
        return False

    vec = speaker_embed(audio)
    if vec is None:
        return True

    if _ENROLL["left"] > 0:
        _ENROLL["vecs"].append(vec)
        _ENROLL["left"] -= 1
        print("[声纹] 收到样本，还差 %d 段" % _ENROLL["left"])
        if _ENROLL["left"] == 0 and _ENROLL["vecs"]:
            mat = np.stack(_ENROLL["vecs"])
            mean = np.mean(mat, axis=0)
            mean = mean / (np.linalg.norm(mean) + 1e-8)

            # 自己跟自己比，估一个合理阈值
            sims = []
            for i in range(len(mat)):
                for j in range(i + 1, len(mat)):
                    sims.append(float(np.dot(_ENROLL_vec_norm(mat[i]), _ENROLL_vec_norm(mat[j]))))
            try:
                if sims:
                    avg = float(np.mean(sims))
                    std = float(np.std(sims))
                    thr = max(0.40, min(0.55, avg - 1.0 * std))
                    print("[声纹] 样本自比：平均 %.2f 标准差 %.2f → 阈值 %.2f" % (avg, std, thr))
                else:
                    thr = 0.45
            except Exception as exc:  # noqa: BLE001
                thr = 0.45
                print("[声纹] 算阈值失败，用默认 0.45：", exc)

            os.makedirs(VOICE_DIR, exist_ok=True)
            np.savez(PROFILE, vec=mean, thr=thr)
            print("[声纹] 已保存你的声纹: %s（阈值 %.2f）" % (PROFILE, thr))
            _PROFILE_VEC = None
            _ENROLL["vecs"] = []
        return False         # 注册期间不回复

    prof, thr = _profile()
    if prof is None:
        return True
    score = float(np.dot(vec, prof))
    # 短句算出来的向量不稳，阈值降一档
    hard = 0.52 if _dur < 3.5 else 0.58   # 实测你长句约 0.58~0.61，0.62 会误杀
    if score >= hard:
        TRUST_UNTIL["t"] = time.time() + 120      # 验证通过，2 分钟信任窗
        return True
    if time.time() < TRUST_UNTIL["t"] and score >= 0.50:
        return True                               # 信任窗口内的波动，放过
    print("[声纹] 不像你（%.2f < %.2f，时长 %.1fs），跳过" % (score, hard, _dur))
    return False


def arm_enroll(n: int = 6) -> str:
    _ARM["n"] = n
    return "已武装：手机下次连上就开始录 %d 段" % n


def take_armed() -> int:
    n = _ARM.get("n", 0)
    _ARM["n"] = 0
    return n


def enroll_start(n: int = 3) -> str:
    _ENROLL["left"] = n
    _ENROLL["vecs"] = []
    return "开始注册声纹：请说 %d 句话，每句 2~4 秒" % n


SPEAK_UNTIL = {"t": 0.0}   # 她播报期间，麦克风输入一律丢弃

FILLER_TEXT = ["嗯", "我在呢", "让我想想", "好"]
FILLER_PCM = {}          # 文本 → base64 PCM16 16k，第一次用到时合成并缓存


def filler_pcm(kind: int = 0) -> str:
    """取一句口头禅的 PCM（懒合成 + 缓存），用于"她还没想好"时先出声。"""
    try:
        text = FILLER_TEXT[kind % len(FILLER_TEXT)]
        cached = FILLER_PCM.get(text)
        if cached is not None:
            return cached
        import base64
        import subprocess
        import tempfile

        # 用统一音色（少女音 +20%/-15Hz）；失败再退回默认 VOICE
        if local_tts is not None:
            raw = asyncio.run(local_tts.edge_pcm16k(text))
            if raw:
                b64 = base64.b64encode(raw).decode()
                FILLER_PCM[text] = b64
                print("[占位音] 已合成：%s（%d 字节）" % (text, len(b64)))
                return b64

        import edge_tts
        with tempfile.TemporaryDirectory() as td:
            mp3 = os.path.join(td, "f.mp3")
            pcm = os.path.join(td, "f.pcm")
            asyncio.run(edge_tts.Communicate(text, VOICE).save(mp3))
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3,
                            "-ar", str(SR), "-ac", "1", "-f", "s16le", pcm],
                           check=True, timeout=60)
            with open(pcm, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
        FILLER_PCM[text] = b64
        print("[占位音] 已合成：%s（%d 字节）" % (text, len(b64)))
        return b64
    except Exception as exc:  # noqa: BLE001
        print("[占位音] 失败:", exc)
        return ""


def pc_eye_note(timeout: float = 120.0) -> str:
    """让电脑上的 E4 看一眼，返回能塞进对话的一句话（失败返回空）。"""
    try:
        import requests
        r = requests.get("http://127.0.0.1:8801/look", timeout=timeout)
        if r.status_code != 200:
            return ""
        j = r.json() or {}
        desc = str(j.get("desc") or "").strip()
        faces = int(j.get("faces") or 0)
        if not desc:
            return ""
        who = "你" if faces else "画面里没人"
        return "（电脑摄像头看到：%s，%s）" % (desc, who)
    except Exception as exc:  # noqa: BLE001
        print("[眼睛] 取画面失败:", exc)
        return ""


LAST_FRAME = {"b64": "", "ts": 0.0}


def frame_note(max_age: float = 4.0) -> str:
    """如果最近收到过画面，让视觉模型看一眼，作为背景交给她。

    用完立刻清空：否则下一句话还会拿到旧画面，
    表现为"第二次说的还是第一张图"。
    """
    try:
        b64 = LAST_FRAME.get("b64") or ""
        ts = float(LAST_FRAME.get("ts") or 0.0)
        if not b64 or (time.time() - ts) > max_age:
            return ""
        LAST_FRAME["b64"] = ""
        LAST_FRAME["ts"] = 0.0
        desc = describe_image(b64)
        if not desc:
            return ""
        return "（他眼前是：%s）" % desc
    except Exception:  # noqa: BLE001
        return ""


SCENE_LAST = {"t": 0.0}


async def maybe_react_to_scene(ws, diff) -> None:
    """画面变化大、又安静了一阵，就让她主动说一句她看见了什么。"""
    try:
        d = float(diff or 0)
    except Exception:  # noqa: BLE001
        d = 0.0
    now = time.time()
    if d < 0.12:
        return
    if now - SCENE_LAST["t"] < 25:
        return
    if now < SPEAK_UNTIL["t"]:
        return
    SCENE_LAST["t"] = now

    b64 = LAST_FRAME.get("b64") or ""
    if not b64:
        return
    LAST_FRAME["b64"] = ""
    desc = await asyncio.to_thread(describe_image, b64)
    if not desc:
        return
    prompt = ("（你眼前变了，你看见：%s）用一句话跟你说你看到了什么，"
              "不要提图片、模型、识别。" % desc)
    reply = clean_reply(await asyncio.to_thread(ask_her, prompt))
    if not reply:
        return
    await ws.send(json.dumps({"type": "subtitle", "text": reply,
                              "role": "her", "mood": mood_label()},
                             ensure_ascii=False))
    audio = await tts_b64(reply)
    if audio:
        await ws.send(json.dumps({"type": "voice", "data": audio}, ensure_ascii=False))
        SPEAK_UNTIL["t"] = now + max(1.5, len(reply) * 0.22) + 0.8


HUD_CLIENTS = set()


async def broadcast_to_hud(obj: dict) -> None:
    """把字幕/表情推给所有连着的眼镜 HUD。"""
    if not HUD_CLIENTS:
        return
    text = json.dumps(obj, ensure_ascii=False)
    for client in list(HUD_CLIENTS):
        try:
            await client.send(text)
        except Exception:  # noqa: BLE001
            HUD_CLIENTS.discard(client)


async def handle(ws, path=None):
    peer = getattr(ws, "remote_address", ("?", 0))
    print("[连接] %s" % (peer,))
    HUD_CLIENTS.add(ws)
    buf = bytearray()
    t0 = None
    has_speech = False
    silence_ms = 0.0
    try:
        async for msg in ws:
            if isinstance(msg, bytes):
                if time.time() < SPEAK_UNTIL["t"]:
                    buf.clear()
                    has_speech = False
                    silence_ms = 0.0
                    t0 = None
                    continue
                buf.extend(msg)
                if t0 is None:
                    t0 = time.time()
                # 2026-11-07 v2：状态机断句——先检测到"有人说话"，再等静音收尾。
                # （之前只看尾部能量，TTS/真人开头的静音会让它提前切断）
                chunk = np.frombuffer(msg, dtype="<i2").astype(np.float32) / 32768.0
                rms = float(np.sqrt((chunk ** 2).mean())) if chunk.size else 0.0
                if rms > 0.020:
                    if not has_speech:
                        has_speech = True
                    silence_ms = 0
                elif has_speech:
                    silence_ms += chunk.size / SR * 1000.0
                dur = buf.__len__() / 2 / SR
                if not has_speech:
                    if dur > 2.0:          # 两秒还没声音，丢掉
                        buf.clear(); t0 = None
                    continue
                print('[段] rms=%.3f dur=%.2f silence=%.0f speech=%s' % (rms, dur, silence_ms, has_speech), flush=True)
                if dur < 1.2 or (silence_ms < 900 and dur < 10.0):
                    continue
                raw_audio = bytes(buf)
                pcm = np.frombuffer(raw_audio, dtype="<i2").astype(np.float32) / 32768.0
                buf.clear()
                has_speech = False
                silence_ms = 0.0
                t1 = time.time()
                if not await asyncio.to_thread(speaker_ok, raw_audio):
                    t0 = None
                    continue
                try:
                    text = await asyncio.to_thread(ears().transcribe, pcm)
                except Exception as exc:  # noqa: BLE001
                    await ws.send(json.dumps({"type": "error", "msg": str(exc)[:120]}, ensure_ascii=False))
                    t0 = None
                    continue
                if not text:
                    t0 = None
                    continue
                await ws.send(json.dumps({"type": "heard", "text": text,
                                          "asr_ms": int((time.time() - t1) * 1000)},
                                         ensure_ascii=False))

                # 语音指令分流（不送模型，省时间）
                if "休息" in text:
                    goodbye = "那我先歇会儿，你叫我再来。"
                    audio = await tts_b64(goodbye)
                    if audio:
                        await ws.send(json.dumps({"type": "voice", "data": audio},
                                                 ensure_ascii=False))
                    await ws.send(json.dumps({"type": "close", "text": goodbye},
                                             ensure_ascii=False))
                    t0 = None
                    continue

                if any(k in text for k in ("看看", "看一下", "看这个", "拍一张", "拍个照")):
                    await ws.send(json.dumps({"type": "need_photo", "text": text},
                                             ensure_ascii=False))
                    t0 = None
                    continue

                note = await asyncio.to_thread(frame_note)
                reply = clean_reply(
                    await asyncio.to_thread(ask_her, (note + text) if note else text)
                )
                await asyncio.to_thread(remember, text, reply)
                # 先发字幕：让她的话 1.3 秒就出现在眼前，语音随后补上
                await ws.send(json.dumps({"type": "subtitle", "text": reply, "role": "her",
                                          "mood": mood_label(), "total_ms": int((time.time() - t0) * 1000)},
                                         ensure_ascii=False))
                audio = await tts_b64(reply)
                if audio:
                    await ws.send(json.dumps({"type": "voice", "data": audio},
                                             ensure_ascii=False))
                    SPEAK_UNTIL["t"] = time.time() + max(1.5, len(reply) * 0.22) + 0.8
                t0 = None
            else:
                try:
                    data = json.loads(msg)
                except ValueError:
                    continue
                t = data.get("type")
                if t == "hello":
                    await ws.send(json.dumps({
                        "type": "caps", "asr": "faster-whisper", "sr": SR,
                        "frame_bytes": FRAME * 2, "session": "dad"}, ensure_ascii=False))
                elif t == "ping":
                    await ws.send(json.dumps({"type": "pong", "t": time.time()}))
                elif t == "image":       # 眼镜拍的照：先让本地视觉模型看一眼，再问她
                    shot = data.get("data", "")
                    said = data.get("text", "")
                    b64 = shot.split(",", 1)[-1] if shot.startswith("data:") else shot
                    desc = await asyncio.to_thread(describe_image, b64) if b64 else ""
                    if desc:
                        composed = ("（你把眼前的东西给你看，你看清了：%s）%s" % (desc, said)).strip()
                    else:
                        composed = ("（你把眼前的东西给你看，但你没看清）%s" % said).strip()
                    reply = clean_reply(await asyncio.to_thread(ask_her, composed))
                    await asyncio.to_thread(remember, composed, reply)
                    await ws.send(json.dumps({"type": "heard", "text": said or "（看了一眼）"},
                                             ensure_ascii=False))
                    await ws.send(json.dumps({"type": "subtitle", "text": reply,
                                              "role": "her", "mood": "surprised"},
                                             ensure_ascii=False))
                    audio = await tts_b64(reply)
                    if audio:
                        await ws.send(json.dumps({"type": "voice", "data": audio},
                                                 ensure_ascii=False))
                elif t == "arm_enroll":    # 手机下次连上就开录
                    print("[声纹]", arm_enroll(int(data.get("count", 6))))
                elif t == "test_photo":    # 遥控一次拍照（调试相机）
                    await broadcast_to_hud({"type": "do_photo"})
                elif t == "enroll_start":  # 注册声纹（我从电脑发）
                    print("[声纹]", enroll_start(int(data.get("count", 3))))
                elif t == "frame":         # 观察窗口的帧：只存，不立刻算
                    shot = data.get("data", "")
                    b64 = shot.split(",", 1)[-1] if shot.startswith("data:") else shot
                    if b64:
                        LAST_FRAME["b64"] = b64
                        LAST_FRAME["ts"] = time.time()
                        print("[帧] 收到图片 %d 字节 diff=%s" % (len(b64), data.get("diff")), flush=True)
                        try:
                            await maybe_react_to_scene(ws, data.get("diff"))
                        except Exception as exc:  # noqa: BLE001
                            print("[看见] 主动回应失败:", exc)
                elif t == "text":          # 调试：直接发文字给她
                    _t = data.get("text", "")
                    note = await asyncio.to_thread(frame_note)
                    reply = clean_reply(
                        await asyncio.to_thread(ask_her, (note + _t) if note else _t)
                    )
                    await asyncio.to_thread(remember, data.get("text", ""), reply)
                    await ws.send(json.dumps({"type": "subtitle", "text": reply,
                                              "role": "her", "mood": "surprised"},
                                             ensure_ascii=False))
                    audio = await tts_b64(reply)      # 调试路径也带语音，方便验
                    if audio:
                        await ws.send(json.dumps({"type": "voice", "data": audio},
                                                 ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print("[断开] %s %s" % (peer, exc))
    finally:
        HUD_CLIENTS.discard(ws)
        print("[关闭] %s" % (peer,))


async def main_async(host: str, port: int, enable_hud: bool = True):
    import phone_relay
    phone_relay.SYNTH = piper_pcm

    ctx = {
        "asr": ears(),            # 懒加载会拖慢第一条消息，这里提前载入
        "ask": ask_her,
        "clean": clean_reply,
        "remember": remember,
        "mood": mood_label,
        "voice": VOICE,
        "sr": SR,
        "broadcast": broadcast_to_hud,
        "describe": describe_image,
        "pc_eye": pc_eye_note,
        "filler": filler_pcm,
        "synth": piper_pcm,
        "frame_note": frame_note,
        "speaker_ok": speaker_ok,
        "speaker_filter": speaker_filter,
        "enroll_start": enroll_start,
        "enroll_active": lambda: _ENROLL["left"] > 0,
        "take_armed": take_armed,
    }
    relay = asyncio.create_task(phone_relay.serve_phone(host, 8797, ctx))
    if not enable_hud:
        # 2026-11-10：眼镜退了，只保留手机中继（8797），不再开 HUD 的 WebSocket
        print("手机中继已启动：tcp://%s:8797（眼镜 HUD 已退役）" % host)
        await relay
        return
    async with websockets.serve(handle, host, port, max_size=4 * 1024 * 1024,
                                ping_interval=None):   # AIUI 不回应 ping 帧，靠应用层心跳
        print("穿戴服务已启动：ws://%s:%d/ws" % (host, port))
        print("  眼镜（WebSocket）和手机（TCP 8797）都可以连")
        await asyncio.Future()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8014)
    args = ap.parse_args()
    try:
        asyncio.run(main_async(args.host, args.port))
    except KeyboardInterrupt:
        print("\n停了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
