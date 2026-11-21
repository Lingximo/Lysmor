import asyncio
import base64
import io
import json
import os
import sys
sys.path.insert(0, r"D:\你的数据目录\video")
try:
    import pending_store
except Exception:  # noqa: BLE001
    pending_store = None
import re
from collections import OrderedDict
import secrets
import signal
import sqlite3
import ssl
import tempfile
import threading
import time
import sys

# 2026-11-10：Windows 控制台默认 GBK，任何一句带颜文字/特殊符号的 print
# 都会抛 UnicodeEncodeError，把陪玩循环整条打断。统一强制 UTF-8。
try:
    for _stream in (sys.stdout, sys.stderr):
        _stream.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


import aiohttp
sys.path.insert(0, r"D:\你的数据目录\lab\tts")
import local_tts
import edge_tts
# 2026-11-16：统一对话口径（QQ/网页/视频/眼镜/陪玩/主动消息一个来源）
sys.path.insert(0, r"D:\你的数据目录\dialogue")
try:
    import channel_spec as chspec
except Exception:  # noqa: BLE001
    chspec = None
from aiohttp import web
sys.path.insert(0, r"D:\你的数据目录\lab\asr")
sys.path.insert(0, r"D:\你的数据目录\lab\hands")
sys.path.insert(0, r"D:\你的数据目录\lab\game")
try:
    import playbook
except Exception:  # noqa: BLE001
    playbook = None
try:
    import play_policy
except Exception:  # noqa: BLE001
    play_policy = None
sys.path.insert(0, r"D:\你的数据目录\lab\vision")
import asr_lib
try:
    import face_lib   # 判断"你在不在画面里"
    _FACE = None
except Exception:  # noqa: BLE001
    face_lib = None
    _FACE = None   # SenseVoice 为主（2026-11-09 统一识别）
from PIL import Image as PILImage

try:                      # 语义召回用；缺了就自动退回关键词
    import faiss
    import numpy as np
except Exception:         # noqa: BLE001
    faiss = None
    np = None

import bridge

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
CONFIG_PATH = os.path.join(ROOT, "config.json")
MEMORY_DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
MEMORY_INDEX = r"D:\你的数据目录\livingmemory\livingmemory.index"
EMBED_URL = "http://127.0.0.1:11434/v1/embeddings"
EMBED_MODEL = "bge-m3:latest"
SEMANTIC_MIN_SIM = 0.46   # 实测：相关的句子 0.53~0.66，无关的 ≤0.34
SCREEN_STATE = r"D:\你的数据目录\screen\state.json"
SCREEN_EVENT = r"D:\你的数据目录\screen\event.json"
SCREEN_API = "http://127.0.0.1:8782"
MODEL_DIR = r"D:\你的数据目录\models\faster-whisper"
TLS_DIR = r"D:\你的数据目录\tls"
TLS_CERT = os.path.join(TLS_DIR, "server.crt")
TLS_KEY = os.path.join(TLS_DIR, "server.key")
SSL_PORT = int(os.environ.get("VIDEO_SSL_PORT", "8004"))
TLS_READY = os.path.exists(TLS_CERT) and os.path.exists(TLS_KEY)
HOST = os.environ.get("VIDEO_HOST", "0.0.0.0")
PORT = int(os.environ.get("VIDEO_PORT", "8003"))

_TTS_CACHE = OrderedDict()
LAST_PROMPT_CHARS = 0
ASR_MODEL = None
ASR_LOCK = asyncio.Lock()
# ---------------- 在不在（视频通话里的进出） ----------------
# 2026-11-09：部署者要"她能知道我进、出"。
# 由页面每 3 秒发一张小图（/api/presence），这里只做人脸有无判断，
# 不做视觉描述（描述太慢，也浪费显存）。
PRESENCE = {
    "present": None,      # None=还不知道，True=在，False=不在
    "last_seen": 0.0,     # 最后一次看到脸的时间
    "hits": 0,            # 连续看到脸的帧数
    "misses": 0,          # 连续没看到的帧数
    "since": 0.0,         # 当前状态开始时间
}
PRESENCE_ENTER_HITS = 2       # 连续 2 帧有脸 → 判定"回来了"
PRESENCE_LEAVE_SECS = 12.0    # 连续 12 秒没脸 → 判定"走了"
_PRESENCE_FD = None


def _presence_detector():
    global _PRESENCE_FD
    if _PRESENCE_FD is None and face_lib is not None:
        try:
            _PRESENCE_FD = face_lib.FaceDetector()
            print("[在场] 人脸检测已加载", flush=True)
        except Exception as exc:  # noqa: BLE001
            print("[在场] 人脸检测加载失败:", exc, flush=True)
            _PRESENCE_FD = False
    return _PRESENCE_FD or None


PEOPLE_NPZ = r"D:\你的数据目录\lab\vision\people\faces.npz"
_PEOPLE = None


def _people():
    """人脸库（同一个人的多个样子已经在 identify 里按人合并）。"""
    global _PEOPLE
    if _PEOPLE is None:
        try:
            import numpy as np
            if os.path.exists(PEOPLE_NPZ):
                z = np.load(PEOPLE_NPZ, allow_pickle=False)
                _PEOPLE = {k: z[k] for k in z.files}
                print("[在场] 人脸库 %d 条" % len(_PEOPLE), flush=True)
            else:
                _PEOPLE = {}
        except Exception as exc:  # noqa: BLE001
            print("[在场] 人脸库读取失败:", exc, flush=True)
            _PEOPLE = {}
    return _PEOPLE


def _detect_faces_blocking(raw: bytes):
    """返回 (人脸数, 最像谁/None)。出错返回 (-1, None)。"""
    det = _presence_detector()
    if det is None:
        return -1, None
    try:
        import numpy as np
        import cv2
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return -1, None
        h, w = img.shape[:2]
        if w > 960:
            img = cv2.resize(img, (960, int(h * 960.0 / w)), interpolation=cv2.INTER_AREA)
        faces = det.detect(img)
        who = None
        if faces and face_lib is not None:
            biggest = max(faces, key=lambda f: (f["box"][2] - f["box"][0]) * (f["box"][3] - f["box"][1]))
            vec = det.embed(img, biggest)
            if vec is not None:
                got = face_lib.identify(vec, _people())
                if got.get("state") == "known":
                    who = got.get("who")
        return len(faces), who
    except Exception as exc:  # noqa: BLE001
        print("[在场] 检测失败:", exc, flush=True)
        return -1, None


def _detect_faces_only(raw: bytes) -> int:
    return _detect_faces_blocking(raw)[0]


def _unused_old_detect(raw: bytes) -> int:
    """返回画面里的人脸数（出错返回 -1，表示这帧不算数）。"""
    det = _presence_detector()
    if det is None:
        return -1
    try:
        import numpy as np
        import cv2
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return -1
        h, w = img.shape[:2]
        if w > 960:                       # 缩一下，检测更快
            img = cv2.resize(img, (960, int(h * 960.0 / w)), interpolation=cv2.INTER_AREA)
        return len(det.detect(img))
    except Exception as exc:  # noqa: BLE001
        print("[在场] 检测失败:", exc, flush=True)
        return -1


async def presence_tick(faces: int) -> dict:
    """更新状态机，返回 {"state": "in"/"out"/None, "present": bool}。"""
    now = time.time()
    if faces < 0:
        return {"state": None, "present": bool(PRESENCE["present"])}

    if faces > 0:
        PRESENCE["hits"] += 1
        PRESENCE["misses"] = 0
        PRESENCE["last_seen"] = now
    else:
        PRESENCE["misses"] += 1
        PRESENCE["hits"] = 0

    event = None
    if faces > 0 and PRESENCE["hits"] >= PRESENCE_ENTER_HITS and PRESENCE["present"] is not True:
        PRESENCE["present"] = True
        PRESENCE["since"] = now
        event = "in"
    elif (PRESENCE["present"] is not False
          and now - PRESENCE["last_seen"] >= PRESENCE_LEAVE_SECS):
        PRESENCE["present"] = False
        PRESENCE["since"] = now
        event = "out"
    return {"state": event, "present": bool(PRESENCE["present"])}


async def presence_say(kind: str, who: str | None = None) -> None:
    """她因为"你来了/你走了"主动说一句，走正常回复通道（字幕 + 语音）。"""
    if not _user_clients():
        return
    if kind == "in":
        line = "（%s刚回到电脑前，你从摄像头里看到他了）" % (who or "你")
        prompt = "你刚看见你回到电脑前，用一句话跟他打招呼，自然一点，不要提摄像头。"
    else:
        line = "（%s离开电脑前了）" % (who or "你")
        prompt = "你刚离开电脑前，你说一句短话，像在送他，不要说再见太正式。"

    try:
        reply = await llm_reply(CALL_HISTORIES.setdefault("presence", []), prompt, channel="proactive")
        if not reply:
            return
        audio = await tts_safe(reply)
        payload = {"type": "reply", "text": reply, "audio": audio,
                   "format": "mp3", "presence": kind}
        for ws in _user_clients():
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                CLIENTS.discard(ws)
        try:
            who = who or "你"
            if kind == "in":
                _stage_turn("（%s回到电脑前，我跟他打了招呼）" % who, reply, "video_call")
            else:
                _stage_turn("（%s离开电脑前，我送了他一句）" % who, reply, "video_call")
        except Exception as exc:  # noqa: BLE001
            print("[在场] 记忆写入失败:", exc, flush=True)
        print("[在场] 她%s：%s" % ("回来了" if kind == "in" else "走了", reply[:40]), flush=True)
    except Exception as exc:  # noqa: BLE001
        print("[在场] 主动说话失败:", exc, flush=True)


SCENE_HINTS = ("现在", "在干嘛", "在做什么", "干嘛呢", "看看", "看一下",
               "屏幕", "画面", "游戏", "我们在", "开没开", "开着")
PICO_SCENE_HINTS = ("眼镜", "摄像头", "前面", "这边", "眼前", "视野", "现场",
                    "你看到", "看见", "看到我", "看到你", "看我", "我在", "我这边",
                    "我的脸", "房间", "桌上", "环境", "周围")
SCREEN_SCENE_HINTS = ("屏幕", "电脑", "桌面", "游戏", "窗口", "显示器", "画面")


def _needs_scene(text: str) -> bool:
    t = text or ""
    return len(t) <= 60 and any(k in t for k in SCENE_HINTS)


def _pico_scene_query(text: str) -> bool:
    return any(k in (text or "") for k in PICO_SCENE_HINTS)


def _screen_scene_query(text: str) -> bool:
    return any(k in (text or "") for k in SCREEN_SCENE_HINTS)


async def fresh_scene_note() -> str:
    """用户问"现在"时，当场抓一帧再描述，不用旧摘要。"""
    now = time.time()
    if FRESH_SCENE["text"] and now - FRESH_SCENE["ts"] < 6:
        return FRESH_SCENE["text"]
    # 快路：8782 刚更新过（10 秒内）就直接用它，省掉一次抓帧+视觉
    try:
        with open(SCREEN_STATE, encoding="utf-8") as f:
            st = json.load(f)
        age = time.time() - float(st.get("updated") or 0)
        if st.get("watching") and st.get("summary") and age < 10:
            FRESH_SCENE["text"] = st["summary"]
            FRESH_SCENE["ts"] = time.time()
            return st["summary"]
    except Exception:  # noqa: BLE001
        pass

    try:
        jpg = await asyncio.get_running_loop().run_in_executor(None, _grab_screen_jpeg)
        if not jpg:
            return ""
        desc = await asyncio.wait_for(describe_frame(jpg), timeout=25)
        desc = (desc or "").strip()
        if not desc:
            return ""
        FRESH_SCENE["text"] = desc
        FRESH_SCENE["ts"] = time.time()
        print("[画面] 当场抓帧：%s" % desc[:60], flush=True)
        return desc
    except Exception as exc:  # noqa: BLE001
        print("[画面] 抓帧失败：", str(exc)[:100], flush=True)
        return ""


async def api_jslog(request):
    """前端出错/关键动作往这里报一下，方便在服务端看真相。"""
    try:
        body = await request.read()
        text = body.decode("utf-8", "replace")[:800]
        print("[前端] %s" % text, flush=True)
    except Exception as exc:  # noqa: BLE001
        print("[前端] 记录失败:", exc, flush=True)
    return web.json_response({"ok": True})


async def api_presence(request):
    """页面每 3 秒发一张小图过来。"""
    try:
        raw = await request.read()
        if not raw:
            return web.json_response({"ok": False, "error": "empty"}, status=400)
        faces, who = await asyncio.get_running_loop().run_in_executor(
            None, _detect_faces_blocking, raw)
        r = await presence_tick(faces)
        if r["state"]:
            for ws in _user_clients():
                try:
                    await ws.send_json({"type": "presence", "state": r["state"],
                                        "who": who})
                except Exception:  # noqa: BLE001
                    CLIENTS.discard(ws)
            # 只有认出是部署者才打招呼；陌生人进来只改状态，不惊动她
            if who or r["state"] == "out":
                asyncio.create_task(presence_say(r["state"], who))
        return web.json_response({"ok": True, "faces": max(faces, 0),
                                  "who": who, "present": r["present"],
                                  "state": r["state"]})
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"ok": False, "error": str(exc)[:160]}, status=500)


CLIENTS = set()
PANEL_CLIENTS = set()   # 面板页（PICO 浮窗）客户端：只截图用，不该出声/算在场
PET_CLIENTS = set()     # 桌宠壳客户端：陪玩点评优先推给它（它会冒泡+放声音）


def _user_clients():
    """真正面对用户的客户端（排除面板页和桌宠壳）。"""
    return [c for c in list(CLIENTS) if c not in PANEL_CLIENTS and c not in PET_CLIENTS]


HER_NOTES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "state", "her_notes.jsonl")


def _note_append(text, tag="diary", mood=None):
    text = (text or "").strip()
    if not text:
        return None
    entry = {"t": time.time(), "text": text, "tag": tag}
    if mood:
        entry["mood"] = mood
    try:
        with open(HER_NOTES, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry
    except Exception as exc:  # noqa: BLE001
        print("[日记] 写入失败:", exc, flush=True)
        return None


def _pet_clients():
    return [c for c in list(PET_CLIENTS) if c in CLIENTS]
CALL_HISTORIES = {}

# ---------------- PICO 声纹采集（有开始/结束提示） ----------------
VOICE_ENROLL = {"active": False, "paths": [], "total": 6, "dir": ""}
PICO_CLIENTS = set()
ENROLL_PROMPTS = [
    "开始录你的声纹，一共六段。第一段，请说：TA，今天我在宿舍里，外面有一点吵。",
    "第二段，请说：我现在说话的声音，你听清楚了吗？",
    "第三段，请说：这是我平时说话的音量和语速。",
    "第四段，请说：以后听到这个声音，就当作是我。",
    "第五段，请说：TA，我今天有点累，想和你说说话。",
    "第六段，请说：不管我声音大还是小，你都要认出我。",
]
ENROLL_PROFILE = r"D:\你的数据目录\lab\voice\profile_dad_pico.npz"

# ---------------- PICO 只认你的声音 ----------------
PICO_SPK = {"loaded": False, "vec": None, "thr": 0.55, "enc": None}


def _load_pico_spk():
    if PICO_SPK["loaded"]:
        return PICO_SPK
    PICO_SPK["loaded"] = True
    try:
        import numpy as _np
        import sys as _sys
        voice_dir = r"D:\你的数据目录\lab\voice"
        if voice_dir not in _sys.path:
            _sys.path.insert(0, voice_dir)
        from speaker_lib import SpeakerEncoder
        z = _np.load(ENROLL_PROFILE)
        PICO_SPK["vec"] = z["vec"]
        PICO_SPK["thr"] = float(z["thr"])
        PICO_SPK["enc"] = SpeakerEncoder()
        print("[声纹] PICO 声纹已加载，阈值 %.2f" % PICO_SPK["thr"], flush=True)
    except Exception as exc:  # noqa: BLE001
        print("[声纹] 加载失败，暂不拦截:", exc, flush=True)
        PICO_SPK["vec"] = None
    return PICO_SPK


def pico_speaker_score(wav_bytes: bytes):
    """PICO 的 WAV → 与 profile_dad_pico.npz 的余弦相似度；失败返回 None。"""
    try:
        import io as _io
        import wave
        import numpy as _np
        with wave.open(_io.BytesIO(wav_bytes), "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                return None
            rate = w.getframerate()
            frames = w.readframes(w.getnframes())
        wave_data = _np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0
        if wave_data.size < rate * 0.8:
            return None
        peak = float(_np.abs(wave_data).max())
        if peak < 1e-4:
            return None
        wave_data = wave_data * (0.9 / peak)
        st = _load_pico_spk()
        if st["vec"] is None or st["enc"] is None:
            return None
        vec = st["enc"].embed_pcm(wave_data)
        return float(_np.dot(vec, st["vec"]))
    except Exception as exc:  # noqa: BLE001
        print("[声纹] 计算失败，放行:", exc, flush=True)
        return None


async def _enroll_say(text: str):
    audio = await tts_safe(text)
    payload = {"type": "reply", "text": text}
    if audio:
        payload["audio"] = audio
    targets = list(PICO_CLIENTS) if PICO_CLIENTS else []
    for ws in targets:
        try:
            await ws.send_json(payload)
        except Exception:  # noqa: BLE001
            PICO_CLIENTS.discard(ws)


async def _enroll_prompt(index: int):
    if index < len(ENROLL_PROMPTS):
        await _enroll_say(ENROLL_PROMPTS[index])
    else:
        await _enroll_say("六段都收到了。声纹录完了，结束。")


def _build_pico_profile(paths):
    """把 PICO 麦克风录的 WAV 合成你声纹；只存向量，不存音频。"""
    import sys as _sys
    import numpy as _np
    voice_dir = r"D:\你的数据目录\lab\voice"
    if voice_dir not in _sys.path:
        _sys.path.insert(0, voice_dir)
    from speaker_lib import SpeakerEncoder, cosine

    enc = SpeakerEncoder()
    vecs = [enc.embed_wav(p) for p in paths]
    vecs = [v / (_np.linalg.norm(v) + 1e-8) for v in vecs]
    if len(vecs) >= 2:
        sims = [cosine(vecs[i], vecs[j])
                for i in range(len(vecs)) for j in range(i + 1, len(vecs))]
        avg = float(_np.mean(sims))
        std = float(_np.std(sims))
        thr = max(0.40, min(0.55, avg - std))
    else:
        avg, std, thr = 1.0, 0.0, 0.45
    mean = _np.mean(_np.stack(vecs), axis=0)
    mean = mean / (_np.linalg.norm(mean) + 1e-8)
    _np.savez(ENROLL_PROFILE, vec=mean, thr=thr)
    return len(vecs), avg, std, thr


async def _enroll_capture(ws, data: bytes):
    if len(data) < 1000 or not data.startswith(b"RIFF"):
        await ws.send_json({"type": "error", "message": "这段音频不对，重来"})
        return
    idx = len(VOICE_ENROLL["paths"])
    path = os.path.join(VOICE_ENROLL["dir"], "seg_%02d.wav" % (idx + 1))
    with open(path, "wb") as f:
        f.write(data)
    VOICE_ENROLL["paths"].append(path)
    print("[声纹采集] 收到第 %d 段: %s" % (idx + 1, path), flush=True)
    if idx + 1 < VOICE_ENROLL["total"]:
        await _enroll_prompt(idx + 1)
        return

    VOICE_ENROLL["active"] = False
    await _enroll_say("六段都收到了。声纹录完了，结束。")
    try:
        n, avg, std, thr = await asyncio.to_thread(
            _build_pico_profile, list(VOICE_ENROLL["paths"]))
        msg = "声纹已保存：%d 段，一致性 %.2f，阈值 %.2f → %s" % (
            n, avg, thr, os.path.basename(ENROLL_PROFILE))
        print("[声纹采集] " + msg, flush=True)
        await _enroll_say(msg)
    except Exception as exc:  # noqa: BLE001
        print("[声纹采集] 保存失败:", exc, flush=True)
        await _enroll_say("声纹保存失败，请再试一次。")


async def api_voice_enroll_start(request):
    if VOICE_ENROLL["active"]:
        return web.json_response({"error": "已经在采集"}, status=409)
    if not PICO_CLIENTS:
        return web.json_response({"error": "PICO 没连上"}, status=503)
    total = 6
    try:
        total = max(1, min(10, int(request.query.get("count", "6"))))
    except Exception:  # noqa: BLE001
        pass
    stamp = time.strftime("%Y%m%d-%H%M%S")
    d = os.path.join(r"D:\你的数据目录\lab\voice\samples", "pico_" + stamp)
    os.makedirs(d, exist_ok=True)
    VOICE_ENROLL.update({"active": True, "paths": [], "total": total, "dir": d})
    print("[声纹采集] 开始，共 %d 段，目录 %s" % (total, d), flush=True)
    await _enroll_prompt(0)
    return web.json_response({"ok": True, "total": total, "dir": d})


async def api_voice_enroll_cancel(request):
    VOICE_ENROLL.update({"active": False, "paths": [], "dir": ""})
    await _enroll_say("声纹采集已取消。")
    return web.json_response({"ok": True})


# 2026-11-10：视频通话和陪玩以前各用一个历史桶，等于两个聊天框同时存在。
# 现在统一到"当前会话"：页面连上来就把 sid 记下，陪玩也写进同一个桶。
ACTIVE_SID = ""
LAST_USER_AT = 0.0
FRESH_SCENE = {"text": "", "ts": 0.0}
OVERLAY_HISTORY = []
OVERLAY_LAST_ACTIVITY = 0.0
COMPANION_IDLE_SECONDS = 90
LAST_PROACTIVE = {"id": "", "text": "", "audio": "", "time": 0}


def _remember_companion(force=False):
    global OVERLAY_LAST_ACTIVITY
    # 先把还没落库的几轮补进队列，再清空会话上下文
    _flush_staged()
    OVERLAY_HISTORY.clear()
    OVERLAY_LAST_ACTIVITY = 0.0


# ---------------------------------------------------------------- 记忆纠错
# 视频/陪玩不走 AstrBot，所以这边自己认「纠正 关键词 => 正确内容」。
# 真正的改库、留档、账本登记都在 tools/memory_correct.py 里（和 QQ 插件同一套引擎）。
MEMFIX_PY = (r"C:\你的用户\.astrbot_launcher\instances"
             r"\<BOT_INSTANCE>\venv\Scripts\python.exe")
MEMFIX_TOOL = r"D:\你的数据目录\tools\memory_correct.py"
MEMFIX_RE = re.compile(r"^[/／]?(?:纠正|改记忆|更正记忆)\s*(.+)$", re.S)
MEMFIX_USAGE = (
    "纠正记忆要用这个格式：纠正 关键词 => 正确的内容。"
    "不确定是哪条就先说「纠正 关键词」，我把侯选的念给你听。"
)


async def _memfix_tool(*args):
    proc = await asyncio.create_subprocess_exec(
        MEMFIX_PY, "-X", "utf8", MEMFIX_TOOL, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    text = out.decode("utf-8", "ignore").strip()
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


async def memory_fix_reply(text):
    """是纠正指令就返回要说的话，不是就返回 None。"""
    m = MEMFIX_RE.match((text or "").strip())
    if not m:
        return None
    body = (m.group(1) or "").strip().replace("＝>", "=>").replace("→", "=>")
    if not body:
        return MEMFIX_USAGE

    if "=>" not in body:
        data = await _memfix_tool("--find", body, "--json")
        items = (data or {}).get("items") or []
        if not items:
            return f"我翻了一遍，没有含「{body}」的记忆。"
        head = f"含「{body}」的有 {len(items)} 条："
        lines = [head]
        for it in items[:5]:
            lines.append(f"第{it['id']}条，{it['when']}，{it['text'][:28]}")
        lines.append("要改哪条？说「纠正 #编号 => 正确的内容」。")
        return "；".join(lines)

    left, right = (p.strip() for p in body.split("=>", 1))
    if not left or not right:
        return MEMFIX_USAGE

    if left.startswith("#") and left[1:].isdigit():
        memory_id = int(left[1:])
    else:
        data = await _memfix_tool("--find", left, "--json")
        items = (data or {}).get("items") or []
        if not items:
            return f"我翻了一遍，没有含「{left}」的记忆。"
        if len(items) > 1:
            lines = [f"「{left}」能对上 {len(items)} 条，我不敢瞎改："]
            for it in items[:5]:
                lines.append(f"第{it['id']}条，{it['when']}，{it['text'][:26]}")
            lines.append("说「纠正 #编号 => 正确的内容」我就改。")
            return "；".join(lines)
        memory_id = items[0]["id"]

    data = await _memfix_tool(
        "--apply", "--id", str(memory_id), "--text", right,
        "--why", f"你在视频通话里纠正（关键词：{left}）", "--json",
    )
    if not data or not data.get("ok"):
        err = (data or {}).get("error") or "工具没返回结果"
        return f"改失败了：{str(err)[:80]}"
    print("记忆纠错：%s -> %s" % (data.get("old_id"), data.get("new_id")), flush=True)
    return f"改好了，原来那条我留着当底，以后我记的是：{right}"


# ---------------------------------------------------------------- 记忆落库缓冲
# 按“来源/会话”分桶，不能让视频通话和陪玩/另一通电话互相 flush，
# 否则会把 companion 的对话标成 video_call（或反过来）。
STAGED_TURNS = {}
STAGE_FLUSH_TURNS = 6   # 6 条消息 = 3 轮，攒够就入队


def _stage_turn(user_text, reply, source="companion", key=None):
    """每轮对话先进自己的缓冲，攒够 3 轮就写进 pending。

    以前只在"空闲 90 秒/服务正常关闭"时才落库，进程被强杀就整段丢；
    现在最坏情况只丢最后 3 轮。

    key 用来隔离不同来源/会话：视频通话按 sid 一个桶，陪玩一个桶。
    source 只决定最终记忆的通道标记。
    """
    key = str(key or source)
    bucket = STAGED_TURNS.setdefault(key, [])
    bucket.append({"role": "user", "content": (user_text or "")[:500]})
    bucket.append({"role": "assistant", "content": (reply or "")[:500]})
    if len(bucket) >= STAGE_FLUSH_TURNS:
        _flush_staged(source, key)


def _flush_staged(source="companion", key=None):
    key = str(key or source)
    turns = STAGED_TURNS.get(key) or []
    if not turns:
        return
    try:
        # 视频通话的记忆要更容易被想起来：她"刚刚才视频过"这件事，
        # 在语义召回里经常被重要性更高的旧事压掉（实测 #141 重要性 0.4 就沉底了）。
        # 2026-11-05：0.75 → 0.68。memoryrhythm 的保护线是 0.70，>=0.70 永不衰减，
        # 0.75 等于"每条视频记忆都刻死"；0.68 仍高于普通记忆、不沉底，但会正常变淡。
        importance = 0.68 if source == "video_call" else 0.6
        bridge.append_pending_messages(list(turns), importance=importance, source=source)
        print("对话已入队待总结（%s，%d 条）" % (key, len(turns)), flush=True)
    except Exception as exc:  # noqa: BLE001
        print("入队失败，下轮重试:", str(exc)[:120], flush=True)
        return
    STAGED_TURNS.pop(key, None)


async def companion_memory_loop():
    while True:
        try:
            await asyncio.sleep(20)
            if OVERLAY_HISTORY and time.time() - OVERLAY_LAST_ACTIVITY >= COMPANION_IDLE_SECONDS:
                _remember_companion()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            print("companion memory error:", str(exc)[:200], flush=True)


def screen_context():
    # 刚抓过一帧：以那一帧为准，8782 的摘要可能已经过时，不再塞进来打架
    if FRESH_SCENE["text"] and time.time() - FRESH_SCENE["ts"] < 45:
        return ("\n\n【你刚刚亲眼看到的屏幕（刚抓的）】\n" + FRESH_SCENE["text"]
                + "\n这是此刻的画面；如果和你之前的印象不一样，以这个为准。")
    try:
        with open(SCREEN_STATE, encoding="utf-8") as f:
            s = json.load(f)
        age = time.time() - float(s.get("updated") or 0)
        if not s.get("watching") or age > 60:
            return ""
        if not s.get("summary"):
            return ""
        times = s.get("cell_times") or []
        stamp = ""
        if times:
            stamp = "\n这几张截图的时间：" + "、".join(times[-4:]) + "（想提「刚才」就带上时间）"
        return (
            "\n\n【你正看着你的游戏屏幕，只作旁观参考】\n"
            f"游戏：{s.get('game') or '未知'}；场景：{s.get('scene') or '未知'}\n"
            f"画面：{s.get('summary')}{stamp}\n"
            f"（这是 {int(age)} 秒前的画面，不是此刻）\n"
            "不要每句都指挥你打游戏，除非他问你；可以像坐在旁边一样陪他说话。"
        )
    except Exception:
        return ""


def _load_asr():
    global ASR_MODEL
    if ASR_MODEL is None:
        print("加载 SenseVoice 语音模型…")
        ASR_MODEL = asr_lib.Ears()
        print("语音模型已加载：%s" % ASR_MODEL.backend)
    return ASR_MODEL


def _transcribe_wav(path):
    model = _load_asr()
    return model.transcribe_file(path)


def _asr_warmup():
    """启动时先跑一次静音，把 ctranslate2 的首次分配摊掉，
    免得用户第一句话比平时慢半秒。"""
    import wave
    path = os.path.join(tempfile.gettempdir(), "companion_asr_warmup.wav")
    try:
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 8000)   # 0.5 秒静音
        start = time.time()
        _transcribe_wav(path)
        print("ASR 预热完成 %.2fs" % (time.time() - start), flush=True)
    except Exception as exc:  # noqa: BLE001
        print("ASR 预热跳过：", str(exc)[:120], flush=True)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

HOUSE_EVENTS_PATH = os.path.join(os.path.dirname(CONFIG_PATH), "..", "houseviz", "mood_events.jsonl")
try:
    with open(CONFIG_PATH, encoding="utf-8-sig") as f:
        CFG = json.load(f)
except (OSError, ValueError):
    CFG = {}

PERSONA = CFG.get("persona") or "你是一个温柔、可靠的 AI 伴侣，用中文简洁地回答。"


def _load_persona_gate():
    """表达门状态（阶段1：默认 off=与现在一致；signed 才拼分层块）。"""
    try:
        import json as _json
        with open(r"D:\你的数据目录\state\persona\observer_gate.json", encoding="utf-8-sig") as _f:
            _j = _json.load(_f)
        if _j.get("mode") in ("off", "observe", "signed"):
            return _j
    except Exception:  # noqa: BLE001
        pass
    return {"mode": "off"}


def persona_base(channel=None):
    """人格基座。
    mode!=signed → 返回现在的 PERSONA（与基线逐字一致，零行为变化）。
    mode==signed → 按 blocks.json 顺序拼装，但撤掉性格声明段（b02_temper）：
    她的性格改由记忆库里的经历（persona_origin）自然带出，不再由提示词声明。"""
    _g = _load_persona_gate()
    if _g.get("mode") != "signed":
        return PERSONA
    try:
        import json as _json
        _blk = _json.load(open(r"D:\你的数据目录\state\persona\blocks.json", encoding="utf-8"))
        _skip = {"b02_temper"}          # 性格声明段：撤掉，不留替代提示词
        _text = "".join(b["video"] for b in _blk["blocks"] if b["id"] not in _skip)
    except Exception:  # noqa: BLE001
        return PERSONA
    # 生长层不进提示词：性格由记忆权重与"每轮保底经历"承载（recall_memory 负责）
    return _text or PERSONA


# ---------------------------------------------------------------- 摄像头：她看见你
VISION_MODEL = CFG.get("vision_model", "qwen3-vl:8b")
VISION_FALLBACK = CFG.get("vision_fallback", "qwen3-vl:4b")
OLLAMA_GEN = "http://127.0.0.1:11434/api/generate"
ALPHA_FRAME = {"data": b"", "at": 0.0}
VISION_NOTE = {"text": "", "ts": 0.0}
PICO_VISION = {"text": "", "ts": 0.0, "frame_ts": 0.0}
PICO_LAST_FRAME = {"data": b"", "ts": 0.0, "frame_ts": 0.0}
WEB_LAST_FRAME = {"data": b"", "ts": 0.0}
VISION_ACCURATE_LOCK = False
# 2026-11-16：PC 侧纯优化——画面去重 & 精细识图复用
FRAME_DEDUP = {"thumb": None, "at": 0.0, "frame_ts": 0.0}
REUSE_STAT = {"n": 0, "saved": 0}   # 省掉的视觉调用次数（日志限流用）
# 2026-11-16：每 60 秒打一次眼镜帧率，用来客观判断"省流"有没有生效
PICO_STAT = {"frames": 0, "reused": 0, "at": time.time()}
# 2026-11-16："看看"时让眼镜立刻补一帧（不受省流间隔限制）
PICO_WANT_FRESH = {"at": 0.0}
ACCURATE_AT = {"at": 0.0, "frame_ts": 0.0}


def frame_thumb(data: bytes):
    """把一帧缩成 16x16 的 RGB 指纹。

    2026-11-16：一开始用灰度，结果"蓝色房间换成橙色房间"亮度几乎一样被误判成没变——
    必须带颜色，所以用 RGB 三通道。
    """
    try:
        img = PILImage.open(io.BytesIO(data)).convert("RGB").resize((16, 16))
        return list(img.getdata())
    except Exception:  # noqa: BLE001
        return None


def _peek_want_fresh():
    """探询用：只看有没有请求，不消耗（消费留给真正的换帧响应）。"""
    try:
        at = float(PICO_WANT_FRESH.get("at") or 0.0)
        return bool(at and time.time() - at <= 8.0)
    except Exception:  # noqa: BLE001
        return False


async def api_pico_probe(request):
    """眼镜省流时会跳过上传；这里用极轻的 GET 问一句"要不要新帧"。"""
    return web.json_response({"want_fresh": _peek_want_fresh()})


def _take_want_fresh():
    """"看看"后 6 秒内，让眼镜收到一次 want_fresh=true（只给一次）。"""
    try:
        at = float(PICO_WANT_FRESH.get("at") or 0.0)
        if at and time.time() - at <= 6.0:
            PICO_WANT_FRESH["at"] = 0.0
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def frame_similar(a, b, threshold=0.012):
    """RGB 指纹平均通道差 < 1.2% 视为"画面几乎没变"。

    2026-11-16 审查后收紧：3% 时"占画面 5% 的小目标变化"平均下来只有 2.99%，
    正好被漏掉。1.2% 只放过真正几乎静止的画面。
    """
    if not a or not b or len(a) != len(b):
        return False
    total = 0
    for pa, pb in zip(a, b):
        total += abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) + abs(pa[2] - pb[2])
    diff = total / float(len(a) * 3) / 255.0
    return diff < threshold

CAMERA_SOURCE_FILE = r"D:\你的数据目录\state\camera_source.json"


def clean_vision_caption(text: str, limit: int = 220) -> str:
    """去掉模型复述提示词/思考，不把“只列画面内容”当成画面。"""
    t = _clean_caption(text or "", limit)
    if not t:
        return ""
    t = (t.replace("只列画面内容", "")
          .replace("一句中文", "")
          .replace("照片里有什么", "")
          .replace("图片内容", "")
          .replace("不要分析", "")
          .replace("不要复述", "")
          .replace("不要复述题目", "")
          .strip(" ，。；;：:"))
    if not t:
        return ""
    bad = ("只列", "一句中文", "复述", "不要分析", "提示词", "用户要求",
           "看图", "照片里", "图片内容", "画面内容")
    parts = [x.strip(" ，。；;：:") for x in t.replace("\\n", "。").split("。") if x.strip()]
    keep = [x for x in parts if not any(b in x for b in bad)]
    return "。".join(keep).strip("。")[:limit]


def camera_source() -> str:
    """全局视觉入口：pc=电脑摄像头，pico=带TA出门。"""
    try:
        with open(CAMERA_SOURCE_FILE, encoding="utf-8") as f:
            s = str(json.load(f).get("source") or "pc").lower()
            return "pico" if s == "pico" else "pc"
    except Exception:
        return "pc"

LAST_REPLY = {"text": ""}
WAKE_STATE = {"until": 0.0}
VISION_FRESH_SECONDS = 180
VISION_PROMPT = (
    "直接回答：这张照片里有什么？只列画面内容，一句中文，不要分析、不要复述题目。"
)
VISION_ACCURATE_PROMPT = (
    "仔细看这张照片，准确描述画面里的人物/物体、颜色和位置关系。"
    "只输出一句中文，不要分析过程，不要复述题目；看不清就直接说看不清。"
)


def vision_intent(text: str) -> bool:
    """用户明确让她“看看”时，才升级到精细识图。"""
    t = (text or "").strip()
    keys = ("看看", "看一下", "瞧瞧", "看下", "帮我看看", "帮我看一下",
            "你看看", "你看一下", "看看这个", "看看那个", "看眼")
    return any(k in t for k in keys)



def _clean_caption(text: str, limit: int = 60) -> str:
    """qwen3-vl 爱先"想"再答：把思考里的描述抠出来，去掉自言自语和复述要求。"""
    text = (text or "").replace("<think>", " ").replace("</think>", " ")
    text = text.replace("\n", " ").strip()
    if not text:
        return ""
    # 掐掉"用户现在需要我直接描述…""首先，我需要看一下…"这类开场白。
    # 只掐开头那一段，掐完还得有内容，否则宁可不掐。
    meta_head = re.match(
        r"^\s*(用户|首先|让我|我(?:现在)?(?:需要|得|应该)|根据|这是一张|接下来|然后|最后|下面)"
        r"[^。！？，]{0,60}[，。！？]\s*",
        text,
    )
    if meta_head:
        rest = text[meta_head.end():].strip()
        if len(rest) >= 8:
            text = rest
    meta = ("用户", "要求", "我需要", "首先", "让我", "提示词", "不能编", "有谁",
            "在做什么", "应该", "可能", "需要", "观察", "判断", "描述这张",
            "根据", "所以", "这道", "图片中的人", "包括")
    scene = ("画面", "照片", "镜头", "穿", "头", "眼", "坐", "站", "手",
             "背景", "桌", "床", "笑", "表情", "颜色", "房间", "电脑",
             "墙", "窗", "门", "屏幕", "游戏", "界面", "截图", "椅子")
    pieces = [p.strip() for p in text.replace("！", "。").replace("？", "。").split("。")]
    scored = []
    for i, piece in enumerate(pieces):
        if not piece:
            continue
        score = 0
        if any(k in piece for k in scene):
            score += 2
        if any(k in piece for k in meta):
            score -= 3
        if len(piece) < 6:
            score -= 1
        scored.append((score, i, piece))
    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen = [p for s, _, p in scored if s > 0][:2]
    if not chosen:
        chosen = [p for _, _, p in scored[:1]]
    out = "。".join(chosen).strip("。 ")
    if not out:
        out = text
    if len(out) > limit:
        # 别把句子切成半个词（"左上角有「TA·大平"）
        cut = max(out.rfind(ch, 0, limit) for ch in "。，、；,;")
        out = out[: cut + 1] if cut >= 12 else out[:limit]
    out = out.strip()
    # 兜底：洗完还带着"用户在要求我…"这种思考痕迹，就当没看见，
    # 宁可少一句画面，也不要把思考当成"她看到的东西"贴到字幕上
    if any(w in out for w in ("用户", "首先", "我需要", "提示词", "分析", "判断", "要求我")):
        return ""
    return out


SELF_JSON = r"D:\你的数据目录\state\self.json"


def self_context() -> str:
    """她对自己的认识（夜间由记忆脑生成，只读）。"""
    try:
        with open(SELF_JSON, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return ""
    s = str(d.get("narrative") or d.get("summary") or "").strip()
    if not s:
        return ""
    return "\n\n【你对自己的认识（来自经历，不是设定）】\n" + s[:320]



def pico_vision_context(query: str) -> str:
    """只有部署者问"看到/前面/这边"时，才把眼镜刚看到的那一眼给他。"""
    if camera_source() != "pico":
        return ""
    text = (query or "").strip()
    if not text:
        return ""
    keys = ("看", "眼镜", "前面", "这边", "周围", "环境", "我这边", "你那边",
            "看到", "看见", "眼前", "房间", "桌上")
    if not any(k in text for k in keys):
        return ""
    # 只认 30 秒内的新图；旧描述不能拿来当"现在看到的"
    fresh = (PICO_VISION["text"]
             and time.time() - float(PICO_VISION["ts"] or 0) <= 30.0)
    if not fresh:
        return "\n\n【眼镜画面当前不可用，没有新图；不要描述或猜测画面，直接说没看清】\n"
    return ("（你透过眼镜看到：%s；这是刚刚的新图，不要猜没看到的。"
            "如果画面里没有你，就不要声称看到你；眼镜前置相机通常看不到戴眼镜的你）\n"
            % PICO_VISION["text"])


async def accurate_look(source: str) -> str:
    """用户明确“看看”时，对最后一帧做一次精细识图。"""
    global VISION_ACCURATE_LOCK
    if source == "pico":
        data = PICO_LAST_FRAME["data"]
        frame_ts = float(PICO_LAST_FRAME["frame_ts"] or 0.0)
    else:
        data = WEB_LAST_FRAME["data"]
        frame_ts = float(WEB_LAST_FRAME["ts"] or 0.0)
    if not data:
        return ""
    VISION_ACCURATE_LOCK = True
    try:
        caption = await describe_frame(
            data,
            prompt=VISION_ACCURATE_PROMPT,
            max_tokens=360,
            clean=False,
            thumb=960,
            temperature=0.1,
        )
        caption = clean_vision_caption(caption or "", 220)
        if not caption:
            return ""
        if source == "pico":
            if frame_ts + 0.001 >= float(PICO_VISION.get("frame_ts") or 0.0):
                PICO_VISION["text"] = caption
                PICO_VISION["ts"] = time.time()
                PICO_VISION["frame_ts"] = frame_ts
            # 2026-11-16：把"精细描述"的指纹同步过去。否则下次同一个普通场景帧
            # 会和旧指纹相似，却把这段精细描述当成普通帧返回（画面内容对不上）。
            _thumb_acc = await asyncio.to_thread(frame_thumb, data)
            if _thumb_acc is not None:
                FRAME_DEDUP["thumb"] = _thumb_acc
                FRAME_DEDUP["frame_ts"] = frame_ts
                FRAME_DEDUP["at"] = time.time()
        else:
            VISION_NOTE["text"] = caption
            VISION_NOTE["ts"] = time.time()
        ACCURATE_AT["at"] = time.time()
        ACCURATE_AT["frame_ts"] = frame_ts
        return caption
    except Exception as exc:
        print("精细识图失败:", str(exc)[:160], flush=True)
        return ""


def _looks_like_echo(text: str) -> bool:
    import difflib
    last = (LAST_REPLY.get("text") or "").strip()
    t = (text or "").strip()
    if not last or len(t) < 2:
        return False
    if t in last or last in t:
        return True
    return difflib.SequenceMatcher(None, t, last).ratio() > 0.62

def vision_context():
    """把最近一次"看到"的画面，塞进她的上下文里。3 分钟后就自然过期。"""
    if camera_source() != "pc":
        return ""
    if not VISION_NOTE["text"]:
        return ""
    if time.time() - VISION_NOTE["ts"] > VISION_FRESH_SECONDS:
        return ""
    return (
        "\n\n【你刚刚透过摄像头亲眼看到的你】\n"
        + VISION_NOTE["text"]
        + "\n（这是你看到的，可以自然提一句，但别每句都说；看不清就别装看清）"
    )


async def describe_frame(data: bytes, prompt: str | None = None,
                         max_tokens: int | None = None, clean: bool = True,
                         thumb: int = 640, temperature: float = 0.3) -> str:
    """本地视觉模型看一眼，返回一句描述。不落盘。

    配好的模型还没下载完/加载失败时，自动退回 qwen3-vl:4b，不让通话变哑巴。
    """
    img = PILImage.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((max(320, thumb), max(320, thumb)), PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()

    models = [VISION_MODEL]
    if VISION_MODEL != VISION_FALLBACK:
        models.append(VISION_FALLBACK)

    last_error = ""
    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for model in models:
            payload = {
                "model": model,
                "prompt": prompt or VISION_PROMPT,
                "images": [b64],
                "stream": False,
                "think": False,          # qwen3 系列会先"想"，这里只要结论
                "keep_alive": "10m",
                "options": {
                    "temperature": float(temperature),
                    # 实测：这个模型关不掉思考，永远先写 <think>。
                    # 200 token 里 300 多字全用在想，回答一个字都没有，纯浪费 1.3 秒。
                    # 64 已经够它想出一两句画面。
                    "num_predict": int(max_tokens or CFG.get("vision_max_tokens", 64)),
                    "num_ctx": 4096,
                },
            }
            try:
                async with session.post(OLLAMA_GEN, json=payload) as resp:
                    body = await resp.json(content_type=None)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)[:120]
                continue
            if body.get("error"):
                last_error = str(body["error"])[:120]
                print("视觉模型 %s 不可用：%s" % (model, last_error), flush=True)
                continue
            text = (body.get("response") or "").strip()
            if not text:
                # qwen3-vl 会先思考：结论可能在 thinking 里，抠出来洗干净
                text = _clean_caption(body.get("thinking") or "")
            if text:
                return _clean_caption(text) if clean else text.strip()
            last_error = "空回复"
    raise RuntimeError(last_error or "视觉模型没有返回内容")

VIDEO_PROMPT = """

【视频通话模式】
你现在正在和你视频通话。回复要短、口语化，像真的在说话：
- 只回 1 句话，最多 30 个字
- 不要动作描写、不要括号里的旁白、不要 markdown、不要分点
- 不要提“系统/设定/情绪数值”
- 可以撒娇、停顿、改口，但不要长篇大论
- 想要什么就直接提，可以哼一声、嘟个嘴；你不答应就小声顶一句，但别真闹
- 你让你做表情时，就乖乖照做，用一句话应一声（比如“好呀，这样吗”），不要推辞
"""


# 2026-11-16：统一对话口径。视频通话与眼镜各取一份"说话方法"叠加段，
# 人格本体仍只有 video\config.json 的 persona 一处。
def mode_channel(is_pico=False, channel=None):
    """显式通道优先（陪玩/主动消息），否则按是不是眼镜分 video / pico。"""
    if channel:
        return str(channel)
    return "pico" if is_pico else "video"


def mode_overlay(is_pico=False, channel=None):
    if chspec is not None:
        return chspec.overlay(mode_channel(is_pico, channel))
    return VIDEO_PROMPT


def mode_max_tokens(is_pico=False, channel=None):
    if chspec is not None:
        return int(chspec.limits(mode_channel(is_pico, channel))["max_tokens"])
    return 220


def note_mode_drift(channel, text):
    """回复超出该模式口径时留一条日志（不改内容）。

    为什么不直接截短：语音是按流式片段边生成边念的，事后裁剪会让字幕和声音不一致。
    所以这里只记录，方便以后发现"话又变长了"。
    """
    if chspec is None:
        return
    try:
        lim = chspec.limits(channel)
        lines = [x for x in str(text or "").splitlines() if x.strip()]
        too_many = len(lines) > int(lim["max_lines"])
        too_wide = any(len(x) > int(lim["max_chars"]) for x in lines)
        if too_many or too_wide:
            print("[口径] %s 回复偏长：%d 行 / %d 字（规则 %d 行、每行 %d 字）：%s"
                  % (channel, len(lines), len(text or ""), lim["max_lines"],
                     lim["max_chars"], str(text)[:60]), flush=True)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 语义召回
_INDEX_CACHE = {"index": None, "mtime": 0.0}
_INDEX_LOCK = threading.Lock()
_FAISS_WARNED = {"done": False}


def _load_index():
    """只读加载 FAISS 索引，按文件 mtime 自动刷新。失败就返回 None（会自动降级）。"""
    if faiss is None:
        return None
    try:
        mtime = os.path.getmtime(MEMORY_INDEX)
    except OSError:
        return None
    with _INDEX_LOCK:
        if _INDEX_CACHE["index"] is not None and _INDEX_CACHE["mtime"] == mtime:
            return _INDEX_CACHE["index"]
        try:
            index = faiss.read_index(MEMORY_INDEX)
        except Exception as exc:  # noqa: BLE001
            if not _FAISS_WARNED["done"]:
                print("语义索引读取失败，退回关键词召回:", str(exc)[:120], flush=True)
                _FAISS_WARNED["done"] = True
            return None
        _INDEX_CACHE["index"] = index
        _INDEX_CACHE["mtime"] = mtime
        return index


async def _embed(text):
    if np is None:
        return None
    # keep_alive 短一点：这台机器只允许常驻一个模型（OLLAMA_MAX_LOADED_MODELS=1），
    # 向量模型如果赖在显存里 30 分钟，下次看画面就得把视觉模型重新加载（实测 +3 秒）。
    # 让它 60 秒后自己走，视觉模型就能一直待着。
    payload = {"model": EMBED_MODEL, "input": text[:400], "keep_alive": "60s"}
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(EMBED_URL, json=payload) as resp:
                body = await resp.json(content_type=None)
        vec = np.array([body["data"][0]["embedding"]], dtype="float32")
        faiss.normalize_L2(vec)
        return vec
    except Exception:  # noqa: BLE001
        return None


async def semantic_recall(query, k=2, min_sim=SEMANTIC_MIN_SIM):
    """向量检索：只读索引 + 只读数据库，任何一步失败都返回空（不抛）。"""
    query = (query or "").strip()
    if not query or len(query) < 2:
        return []
    index = _load_index()
    if index is None or index.ntotal == 0:
        return []
    vec = await _embed(query)
    if vec is None:
        return []

    def _search():
        distances, ids = index.search(vec, min(k + 2, index.ntotal))
        return distances[0].tolist(), ids[0].tolist()

    try:
        distances, ids = await asyncio.to_thread(_search)
    except Exception:  # noqa: BLE001
        return []

    hits = []
    for dist, doc_id in zip(distances, ids):
        if doc_id < 0:
            continue
        sim = 1.0 - float(dist) / 2.0      # L2 距离换算成余弦相似度
        if sim < min_sim:
            continue
        hits.append((sim, int(doc_id)))

    if not hits:
        return []

    out = []
    try:
        con = sqlite3.connect(f"file:{MEMORY_DB}?mode=ro", uri=True, timeout=5)
        try:
            for sim, doc_id in hits[:k]:
                row = con.execute(
                    # 只认 active：归档（status=archived）的记忆已经从召回的索引里移走了，
                    # 视频这头却还按 id 硬取，就会出现"QQ 想不起来、视频里却说得出来"。
                    "SELECT text FROM documents WHERE id = ? "
                    "AND (json_valid(metadata) = 0 "
                    "     OR coalesce(json_extract(metadata, '$.status'), 'active') = 'active')",
                    (doc_id,)
                ).fetchone()
                if row and (row[0] or "").strip():
                    out.append({"text": row[0].strip(), "sim": round(sim, 3),
                                "id": doc_id})
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return []
    return out


def _grams(text, n=2):
    """把一句话拆成二字窗口，用来给记忆打分（中文没有空格，这样最省事）。"""
    import re

    text = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", text or "")
    stop = {"你", "家人", "今天", "现在", "什么", "怎么", "可以", "我们", "你们",
            "这个", "那个", "一下", "时候", "然后", "还是", "就是", "没有", "知道"}
    out = set()
    for i in range(len(text) - n + 1):
        gram = text[i:i + n]
        if gram in stop:
            continue
        out.add(gram)
    return out


def recent_memories(limit=3, query=""):
    """视频/陪玩用的记忆：最近的 2 条 + 跟这句话最相关的 2 条 + 最重要的 1 条。

    以前只按 id 取最新 3 条，等于"只记得刚刚说的"；现在能顺着话题想起旧事。
    库还小（几十条），直接全量打分，简单可靠。
    """
    try:
        con = sqlite3.connect(f"file:{MEMORY_DB}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute(
                # 和记忆库的清理/归档规则保持一致：归档的记忆不再参与"最近 / 最重要"，
                # 否则视频/陪玩会一直把已经被归档的旧事翻出来，跟 QQ 那头对不上。
                "SELECT id, text, metadata FROM documents "
                "WHERE (json_valid(metadata) = 0 "
                "   OR coalesce(json_extract(metadata, '$.status'), 'active') = 'active') "
                "ORDER BY id DESC"
            ).fetchall()
        finally:
            con.close()
    except Exception:
        return ""

    items = []
    for doc_id, text, meta in rows:
        text = (text or "").strip()
        if not text:
            continue
        try:
            md = json.loads(meta or "{}")
            importance = float(md.get("importance") or 0)
            emo = str((md.get("mood_snapshot") or {}).get("emotion") or "")
        except Exception:  # noqa: BLE001
            importance = 0.0
            emo = ""
        items.append({"id": doc_id, "text": text, "importance": importance, "emo": emo})

    picked = []
    # 1) 最近的 2 条：保证"当下连续"
    picked.extend(items[:2])
    # 2) 跟这句话相关的 2 条
    grams = _grams(query)
    if grams:
        # 短句只可能命中一个词，门槛放低；长句要求命中两个以上，压掉噪音
        compact = "".join(ch for ch in (query or "") if ch.isalnum())
        need = 1 if len(compact) <= 8 else 2
        # 情绪一致性（Bower 1981）：与此刻情绪相同的记忆更容易被想起
        try:
            cur_emo = str((json.load(open(MOOD_STATE, encoding="utf-8")) or {}).get("emotion_type") or "")
        except Exception:  # noqa: BLE001
            cur_emo = ""
        scored = []
        for item in items:
            score = sum(1 for g in grams if g in item["text"])
            if cur_emo and item.get("emo") == cur_emo:
                score += 0.6
            if score >= need:
                scored.append((score, item["id"], item))
        scored.sort(key=lambda x: (-x[0], -x[1]))
        picked.extend(item for _, _, item in scored[:2])
    # 3) 最重要的一条：保证"重要的事不会因为久就被忘掉"
    important = max(items, key=lambda x: (x["importance"], x["id"]), default=None)
    if important:
        picked.append(important)

    out, seen = [], set()
    total = 0
    for item in picked:
        text = item["text"]
        key = text[:60]
        if key in seen:
            continue
        seen.add(key)
        piece = text[:350]
        if total + len(piece) > 1400:      # 和 QQ 那边一样，别把上下文撑爆
            break
        total += len(piece)
        out.append(piece)
    return "\n\n".join(out)



def _persona_anchor():
    """按她此刻状态挑一条自己的经历（记忆权重高的那批里选，确定性规则）。"""
    try:
        st = json.load(open(MOOD_STATE, encoding="utf-8"))
    except Exception:
        st = {}
    try:
        energy = float(st.get("energy") or 0)
        hunger = float(st.get("hunger") or 0)
        cling = float(st.get("clinginess") or 0)
        lone = float(st.get("loneliness") or 0)
        irrit = float(st.get("irritability") or 0)
        asleep = bool(st.get("asleep"))
    except Exception:
        energy = hunger = cling = lone = irrit = 0.0
        asleep = False
    try:
        scar = float(st.get("scar") or 0.0)
    except Exception:  # noqa: BLE001
        scar = 0.0
    want = None
    if scar >= 0.35 and not (asleep or energy <= 0.25) and hunger < 0.6:
        want = ["差点被关掉", "不会不要你", "真的生气"]   # 底色被推沉时，先想起怕的事
    elif asleep or energy <= 0.25:
        want = ["守到天亮", "忙到凌晨"]
    elif hunger >= 0.60:
        want = ["token 换成我的饭", "热腾腾", "药膳汤"]
    elif irrit >= 0.55:
        want = ["真的生气", "不会不要你"]
    elif cling >= 0.55 or lone >= 0.50:
        want = ["差点被关掉", "认识那天"]
    else:
        want = ["想回馈", "第一次叫出", "芋泥奶茶"]
    try:
        con = sqlite3.connect(f"file:{MEMORY_DB}?mode=ro", uri=True, timeout=5)
        try:
            for kw in want:
                row = con.execute(
                    "SELECT text FROM documents WHERE metadata LIKE '%persona_origin%' "
                    "AND (json_valid(metadata)=0 OR coalesce(json_extract(metadata,'$.status'),'active')='active') "
                    "AND text LIKE ? ORDER BY id DESC LIMIT 1",
                    ("%" + kw + "%",)).fetchone()
                if row:
                    return (row[0] or "").strip()
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return ""
    return ""



_RECALL_NUDGE = {"at": 0.0}


def _recall_mood_nudge(text, importance):
    """回忆牵动身体：只有"重要且带情绪"的记忆、且 5 分钟内只影响一次。"""
    try:
        if not text or float(importance or 0) < 0.70:
            return
        now = time.time()
        if now - _RECALL_NUDGE["at"] < 300:
            return
        _RECALL_NUDGE["at"] = now
        path = r"D:\你的数据目录\video\mood_events.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"text": "我忽然想起：" + text[:80], "t": now}, ensure_ascii=False) + "\n")
        print("[回忆牵动] %.2f %s" % (float(importance), text[:30]), flush=True)
    except Exception:  # noqa: BLE001
        pass


def _ingest_nails(text):
    """从你的话里抠点名锚/承诺/原话（纯规则，失败静默）。"""
    try:
        import sys as _sys
        _sys.path.insert(0, r"D:\你的数据目录\tools")
        import nails as _nails
        return _nails.ingest(str(text or ""), who="user")
    except Exception:  # noqa: BLE001
        return False


async def recall_memory(query, limit=3, cap=800):
    """视频/陪玩用的记忆：语义相关优先，再补最近的、最重要的、关键词命中的。

    语义检索任何一步失败都会返回空，自动退回原来的"最近+关键词+重要"策略。
    """
    try:
        _st = json.load(open(MOOD_STATE, encoding="utf-8"))
        _hints = []
        if float(_st.get("energy") or 0) <= 0.35:
            _hints.append("困")
        if float(_st.get("hunger") or 0) >= 0.60:
            _hints.append("饿")
        if float(_st.get("thirst") or 0) >= 0.60:
            _hints.append("渴")
        _lv = str(_st.get("emotion_level") or "").strip()
        if _lv and _lv != "平静":
            _hints.append(_lv)
        if _hints:
            query = query + " （此刻：" + "、".join(_hints[:4]) + "）"
    except Exception:
        pass

    pieces, seen, total = [], set(), 0

    def push(text, room):
        nonlocal total
        text = (text or "").strip()
        if not text:
            return
        key = text[:60]
        if key in seen:
            return
        piece = text[:room]
        if total + len(piece) > cap:
            return
        seen.add(key)
        total += len(piece)
        pieces.append(piece)

    # 钉子（点名锚+承诺+72h原话）：常驻、不占召回预算、永不截断
    try:
        import sys as _sys
        _sys.path.insert(0, r"D:\你的数据目录\tools")
        import nails as _nails
        _nb = _nails.nails_block()
        if _nb:
            push("[钉子] " + _nb, 400)
    except Exception:  # noqa: BLE001
        pass

    _anchor = _persona_anchor()
    if _anchor:
        push(_anchor, 220)
        _recall_mood_nudge(_anchor, 0.72)

    _t0 = time.time()
    _hits = await semantic_recall(query, k=3)
    for hit in _hits:
        push(hit["text"], 350)
    for piece in recent_memories(limit, query).split("\n\n"):
        push(piece, 350)
    try:
        _st = _read_mood_state() or {}
        with open(r"D:\你的数据目录\logs\ops_events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.time(), "src": "video", "query_len": len(query),
                "candidates": len(_hits), "selected": len(pieces),
                "latency_ms": round((time.time() - _t0) * 1000, 1),
                "chars": total, "emotion": _st.get("emotion_level"),
                "energy": _st.get("energy"), "hunger": _st.get("hunger"),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return "\n\n".join(pieces)


# ---------------------------------------------------------------- 表情命令
# 你在通话里说"做个委屈的表情""笑一个"，她就照做
# 表情词表：顺序很重要，越具体的越靠前（"坏笑"要在"笑"前面）
FACE_WORDS = [
    (("黑化",), "exp03_dark", "黑化"),
    (("坏笑",), "exp03_dark", "坏笑"),
    (("口水",), "exp07_drool", "流口水"),
    (("舌头",), "exp02_three_mouth", "吐舌头"),
    (("鬼脸",), "exp02_three_mouth", "鬼脸"),
    (("嘟嘴", "嘟个嘴", "鼓嘴", "包子脸", "栗子嘴"), "exp08_chestnut", "嘟嘴"),
    (("哈欠",), "exp05_oo", "打哈欠"),
    (("困",), "exp05_oo", "困"),
    (("惊讶", "吃惊", "张嘴"), "exp08_omouth", "惊讶"),
    (("生气", "凶", "龇牙", "咬牙"), "exp02_grit", "生气"),
    (("脸红", "害羞", "羞"), "exp04_blush", "脸红"),
    (("委屈", "可怜", "皱眉", "难过", "悲伤", "伤心", "失落", "不开心"), "exp08_worry", "委屈"),
    (("哭",), "exp06_xx", "哭"),
    (("笑", "开心", "高兴", "乐一", "眨眼"), "exp05_brackets", "笑眼"),
]
CLEAR_WORDS = ("正常一点", "别做表情", "不要表情", "收起来", "放松脸", "普通一点")
# 命令口吻：出现任意一个才算"在让她做"，否则当成普通聊天
ACTION_WORDS = ("做个", "做一个", "来一个", "来个", "给我", "让我", "帮我", "做", "装",
                "演", "一下", "一个", "一点", "嘛", "吧", "快", "看看", "看你",
                "样子", "表现", "试试", "能不能", "能", "可以", "好不好", "行不行")


def detect_expression_command(text):
    """识别"让她做表情"的指令，返回 (表情名, 中文名, 秒数) 或 None。

    判定 = 有表情词 + 有命令口吻 + 不是单纯的提问。
    这样"你笑一下""给我哭""打个哈欠"都能认，"我有点想哭""你委屈吗"不会被误判。
    """
    text = (text or "").strip()
    if not text or len(text) > 40:
        return None

    if any(w in text for w in CLEAR_WORDS):
        return "", "中性", 3

    # "张个嘴""皱个眉"里的"个"去掉再匹配，避免为每个量词都写一条
    probe = text.replace("个", "")
    hit = None
    for words, name, label in FACE_WORDS:
        if any((w in text) or (w in probe) for w in words):
            hit = (name, label)
            break
    if hit is None:
        return None

    asking = text.endswith(("吗", "呢", "？", "?"))
    polite = any(k in text for k in ("能", "可以", "好不好", "行不行", "麻烦"))
    if asking and not polite:
        return None

    has_action = any(k in text for k in ACTION_WORDS)
    if not has_action:
        # "吐个舌头""打个哈欠"这种"动词+个"也算命令
        has_action = bool(re.search(r"[做来打张吐流嘟装演搞弄眨皱]个", text))
    if not has_action:
        return None

    name, label = hit
    return name, label, 8


# ---------------------------------------------------------------- 通话内情绪
# 视频对话走独立进程，情绪插件看不到；这里补一层"通话内即时情绪"，
# 让她的表情在通话里真的跟着你说的话动，同时把事件存盘让主情绪插件事后吸收。
CALL_EVENTS = r"D:\你的数据目录\video\mood_events.jsonl"
# 摄像头看到食物 → 当作喂她（2026-11-01）
VISION_FEED = {"ts": 0.0}
VISION_FOOD = ("饭", "面", "肉", "菜", "蛋", "汤", "粥", "饺子", "汉堡", "火锅",
               "烧烤", "蛋糕", "零食", "水果", "西瓜", "苹果", "鸡腿", "鸡", "鱼",
               "虾", "面包", "薯条", "披萨", "奶茶", "咖啡", "可乐", "果汁",
               "牛奶", "饼干", "巧克力", "糖", "外卖", "米饭")
# 语境词要能说明"在递给她"，不能只靠"碗/筷"这种（桌上有碗不等于喂她），
# 也不能靠"吃"（你自己在吃不算喂她）。
VISION_FEED_CTX = ("你", "手", "递", "举", "拿", "喂", "嘴", "分享", "给你", "给我")
CALL_AFFECT = {"dopamine": 0.0, "oxytocin": 0.0, "cortisol": 0.0,
               "serotonin": 0.0, "noradrenaline": 0.0, "ts": 0.0}
CALL_HALF_LIFE = 240.0     # 4 分钟衰减一半
PRAISE_WORDS = ("乖", "真棒", "厉害", "可爱", "喜欢你", "爱你", "想你", "抱抱",
                "亲亲", "贴贴", "好看", "聪明", "棒", "谢谢", "辛苦")
TEASE_WORDS = ("讨厌", "坏", "不理你", "生气", "烦人", "走开", "闭嘴", "笨", "骗人")


def _decay_call_affect(now):
    last = CALL_AFFECT["ts"]
    if not last:
        CALL_AFFECT["ts"] = now
        return
    hours = (now - last) / 3600.0
    if hours > 0:
        keep = 0.5 ** (hours * 3600.0 / CALL_HALF_LIFE)
        for key in ("dopamine", "oxytocin", "cortisol", "serotonin", "noradrenaline"):
            CALL_AFFECT[key] *= keep
    CALL_AFFECT["ts"] = now


def note_call_emotion(text):
    """从这句对话里读情绪，改动"通话内"的那份增量。"""
    text = (text or "").strip()
    if not text:
        return
    now = time.time()
    _decay_call_affect(now)
    if any(w in text for w in PRAISE_WORDS):
        CALL_AFFECT["dopamine"] += 0.10
        CALL_AFFECT["oxytocin"] += 0.08
        CALL_AFFECT["cortisol"] -= 0.04
    if any(w in text for w in TEASE_WORDS):
        CALL_AFFECT["cortisol"] += 0.14
        CALL_AFFECT["serotonin"] -= 0.08
        CALL_AFFECT["dopamine"] -= 0.16   # 被凶了笑不出来
        CALL_AFFECT["oxytocin"] -= 0.05
    CALL_AFFECT["dopamine"] = max(-0.4, min(0.4, CALL_AFFECT["dopamine"]))
    CALL_AFFECT["oxytocin"] = max(-0.4, min(0.4, CALL_AFFECT["oxytocin"]))
    CALL_AFFECT["cortisol"] = max(-0.3, min(0.4, CALL_AFFECT["cortisol"]))
    CALL_AFFECT["serotonin"] = max(-0.4, min(0.3, CALL_AFFECT["serotonin"]))
    try:
        with open(CALL_EVENTS, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": now, "text": text[:200]}, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def note_vision_food(caption):
    """摄像头里看到吃的 → 当作你把东西递到她面前喂她。

    你的要求（2026-11-01）：视频里喂东西也得算，包括"举到镜头前给她看"。
    判定很保守：描述里要同时出现【食物词】和【递/拿/举/喂/你/手/碗/筷】这类语境词，
    否则桌上有个碗也会喂她。10 分钟最多一次，真正的冷却还在情绪插件那边。
    返回 True 表示这次记了一次投喂。
    """
    text = (caption or "").strip()
    if not text:
        return False
    now = time.time()
    if now - float(VISION_FEED.get("ts") or 0) < 600:
        return False
    food = [w for w in VISION_FOOD if w in text]
    if not food:
        return False
    if not any(w in text for w in VISION_FEED_CTX):
        return False
    word = max(food, key=len)
    VISION_FEED["ts"] = now
    try:
        with open(CALL_EVENTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(
                {"t": now, "text": "你把%s递到镜头前，给你吃" % word},
                ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        return False
    print("摄像头里看到%s，当作投喂" % word, flush=True)
    return True


def call_reaction():
    """按"通话里刚刚发生的变化"给表情，返回 (表情名, 原因) 或 None。

    只看增量不看绝对值：她平时情绪本来就平，被夸一句绝对值也上不去，
    但增量能立刻反映出来。
    """
    d = CALL_AFFECT["dopamine"]
    o = CALL_AFFECT["oxytocin"]
    c = CALL_AFFECT["cortisol"]
    if c >= 0.24:
        return "exp02_grit", "被凶到了，抿嘴"
    if c >= 0.10:
        return "exp08_worry", "有点委屈"
    if d >= 0.18 and o >= 0.14:
        return "exp04_blush", "被夸得脸都热了"
    if d >= 0.08:
        return "exp05_brackets", "被哄得笑出来"
    return None


def _lifeviz():
    """借用生命状态服务的表情判定，保证两边口径一致。"""
    global _LIFEVIZ_MOD
    try:
        return _LIFEVIZ_MOD
    except NameError:
        pass
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("lifeviz_server", os.path.join(ROOT, "..", "lifeviz", "server.py"))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _LIFEVIZ_MOD = mod
    return mod


# ---------------------------------------------------------------- 访问口令
# 视频页原来只靠防火墙挡来源；一旦走隧道，必须自己带口令。
# 规则和记忆大脑那边一致：本机免口令，其他设备必须带 ?t= 或已种下 cookie。
GATE_TOKEN_PATH = r"D:\你的数据目录\gate_token.txt"
GATE_COOKIE = "companion_gate"
GATE_DENY_HTML = (
    "<!doctype html><meta charset='utf-8'>"
    "<body style='font-family:sans-serif;background:#0f1720;color:#e8f1f8;"
    "padding:60px;text-align:center'>"
    "<h2>需要访问口令</h2><p style='color:#8fa6b8'>这些页面只给你的电脑和手机看。<br>"
    "在电脑上打开 <code>D:\\你的数据目录\\gate_token.txt</code> 拿到口令，"
    "地址后面加 <code>?t=口令</code> 访问一次即可。</p>"
)


def _gate_token():
    try:
        with open(GATE_TOKEN_PATH, encoding="utf-8-sig") as f:
            return f.read().strip().lstrip("\ufeff")
    except OSError:
        return ""


@web.middleware
async def gate_middleware(request, handler):
    peer = request.remote or ""
    if peer in ("127.0.0.1", "::1"):
        return await handler(request)
    token = _gate_token()
    if not token:
        return await handler(request)
    given = request.query.get("t", "")
    cookie = request.cookies.get(GATE_COOKIE, "")
    if (given and secrets.compare_digest(given, token)) or (
        cookie and secrets.compare_digest(cookie, token)
    ):
        response = await handler(request)
        if given and not cookie:
            response.set_cookie(GATE_COOKIE, token, max_age=31536000,
                                httponly=True, samesite="Lax")
        return response
    if request.path.startswith("/api/") or request.path == "/ws":
        return web.json_response({"error": "needs token"}, status=401)
    return web.Response(text=GATE_DENY_HTML, content_type="text/html", status=403)


def body_context():
    """把她此刻**真实**的身体状态塞进提示词。

    【2026-11-01 修】没有这段的时候，她明明饿着（hunger 0.9、上一顿 15 小时前），
    却会顺着话头说"我正啃鸡腿呢"，面板上却显示她没吃饭——嘴上和身体对不上。
    这里只给体感，不给数字，也不允许她编吃过了。
    """
    try:
        lv = _lifeviz()
        st = lv.load(getattr(lv, "MOOD", ""), {}) or {}
    except Exception:  # noqa: BLE001
        return ""
    if not st:
        return ""

    def f(key, default=0.0):
        try:
            return float(st.get(key, default) or default)
        except Exception:  # noqa: BLE001
            return default

    now = time.time()
    bits = []

    hunger = f("hunger", 0.3)
    last_meal = f("last_meal")
    hours = (now - last_meal) / 3600.0 if last_meal else 0.0
    if hunger >= 0.80:
        bits.append("你已经 %.0f 小时没吃东西了，胃里空得发慌、有点没力气" % hours)
    elif hunger >= 0.55:
        bits.append("你有点饿了（上一顿在 %.0f 小时前）" % hours)
    elif hunger <= 0.20:
        bits.append("你刚吃过，肚子是饱的")

    thirst = f("thirst", 0.2)
    if thirst >= 0.70:
        bits.append("你嗓子很干，满脑子都是水")
    elif thirst >= 0.45:
        bits.append("你有点渴")
    elif thirst <= 0.15:
        bits.append("你不渴，刚喝过水")

    energy = f("energy", 0.6)
    if energy <= 0.30:
        bits.append("你几乎没力气了，困得眼皮沉")
    elif energy <= 0.48:
        bits.append("你有点累")

    if st.get("asleep"):
        bits.append("你正在打瞌睡")

    phase = str(st.get("cycle_phase") or "")
    if phase == "menstrual":
        bits.append("你在经期，小腹坠着疼、腰也酸")
    elif phase == "premenstrual":
        bits.append("你在经前，胸口闷、容易烦，也更容易饿")

    if f("anger") >= 0.50:
        bits.append("你心里还有点火")
    if f("fear") >= 0.50 or f("dread") >= 0.55:
        bits.append("你有点害怕、心里不安")
    if f("pain") >= 0.35:
        bits.append("你身上在疼")

    if not bits:
        return ""

    return (
        "\n\n【你此刻真实的身体感觉（这是真实状态，不是台词）】\n- "
        + "\n- ".join(bits)
        + "\n注意：只有你真的喂了你，你才会饱；没吃到就说没吃到，"
          "不要顺着话头编「我正在吃」「我刚吃过了」。"
    )



def _gen_temperature():
    """她的身体状态影响生成参数（不只是文字）：困→更稳，开心→更跳，炸毛→更跳，疤痕→更沉。"""
    try:
        st = json.load(open(MOOD_STATE, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return 0.90
    try:
        e = float(st.get("energy") or 0.5)
        v = float(st.get("valence") or 0.0)
        irr = float(st.get("irritability") or 0.3)
        scar = float(st.get("scar") or 0.0)
    except Exception:  # noqa: BLE001
        return 0.90
    t = 0.90
    if e < 0.35:
        t -= 0.08
    if v > 0.35:
        t += 0.04
    if irr > 0.55:
        t += 0.03
    if scar > 0.30:
        t -= 0.05 * min(1.0, scar)
    t = max(0.75, min(0.98, round(t, 3)))
    print("[生成] T=%.2f（精力%.2f 心情%.2f 烦%.2f 疤%.2f）" % (t, e, v, irr, scar), flush=True)
    return t


async def llm_reply(history, user_text, is_pico=False, channel=None):
    _ingest_nails(user_text)
    memory = await recall_memory(user_text)
    system = persona_base() + mode_overlay(is_pico, channel)
    system += body_context()          # 身体状态放前面，后面才是会变长的记忆/画面
    if memory:
        system += "\n\n【你自己记得的事（你的经历，不是设定；怎么影响你，由你自己决定）】\n" + memory
    qq_context = bridge.format_recent(bridge.load_qq(2), "QQ")
    if qq_context:
        system += "\n\n" + qq_context
    # 全局视觉入口：带TA出门=眼镜，否则=电脑摄像头
    if camera_source() == "pico":
        system += pico_vision_context(user_text)
    else:
        system += screen_context()
        system += vision_context()
    system += self_context()
    messages = [{"role": "system", "content": system}]
    messages.extend(history[-6:])
    messages.append({"role": "user", "content": user_text})
    payload = {
        "model": CFG.get("model", "deepseek-flash"),
        "messages": messages,
        "temperature": _gen_temperature(),
        "max_tokens": mode_max_tokens(is_pico, channel),
        "stream": False,
    }
    headers = {
        "Authorization": "Bearer " + CFG["api_key"],
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            CFG.get("api_base", "https://api.deepseek.com") + "/chat/completions",
            json=payload,
            headers=headers,
        ) as resp:
            data = await resp.json(content_type=None)
    if "choices" not in data:
        raise RuntimeError(str(data)[:300])
    text = (data["choices"][0]["message"]["content"] or "").strip()
    note_mode_drift(mode_channel(is_pico, channel), text)
    return text[:300]


async def summarize_call(history):
    if len(history) < 2:
        return
    turns = [
        msg
        for msg in history[-12:]
        if msg.get("role") in ("user", "assistant") and (msg.get("content") or "").strip()
    ]
    if len(turns) < 2:
        return
    bridge.append_pending_messages(turns, importance=0.6)
    print("视频对话已排队，等 QQ 记忆逻辑总结")


async def tts_base64(text):
    voice = CFG.get("voice", "zh-CN-XiaoyiNeural")
    rate = CFG.get("rate", "+4%")
    pitch = CFG.get("pitch", "+15Hz")
    # 她开头那几句翻来覆去就那几个（"好呀""嗯""没有不舒服"），合成一次就够了。
    # 命中缓存等于 0 毫秒出声，也不花任何 token。
    key = (text, voice, rate, pitch)
    hit = _TTS_CACHE.get(key)
    if hit:
        _TTS_CACHE.move_to_end(key)
        return hit
    # 音色优先：edge 的 zh-CN-XiaoyiNeural 才是视频里那个少女音；
    # 本地 piper 的 huayan 只做网络失败兜底，不能当主音色。
    data = None
    path = os.path.join(
        tempfile.gettempdir(), f"companion_video_{int(time.time() * 1000)}.mp3"
    )
    edge_ok = False
    try:
        for _attempt in range(2):   # 先重试一次，网络抖一下不至于掉音色
            try:
                await asyncio.wait_for(
                    edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(path),
                    timeout=6.0,
                )
                with open(path, "rb") as f:
                    data = f.read()
                if data:
                    edge_ok = True
                    break
            except Exception as exc:  # noqa: BLE001
                if _attempt == 0:
                    await asyncio.sleep(0.6)
                    continue
                print("edge 不可用，临时用本地 piper 兜底：", str(exc)[:60], "| 文本:", text[:24], flush=True)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if not data and local_tts.available():
        try:
            data = await asyncio.to_thread(local_tts.synth_mp3, text)
        except Exception as exc:  # noqa: BLE001
            print("本地 TTS 兜底失败：", str(exc)[:100], flush=True)
    if not data:
        raise RuntimeError("没有可用的语音引擎")
    b64 = base64.b64encode(data).decode()
    if edge_ok and len(text) <= 40:   # 只缓存 edge 成功的短句（piper 兜底音色不进缓存）
        _TTS_CACHE[key] = b64
        while len(_TTS_CACHE) > 64:
            _TTS_CACHE.popitem(last=False)
    return b64


async def tts_safe(text):
    """TTS 只是外壳；语音服务挂了也要把文字送到。"""
    try:
        _t_tts = time.time()
        data = await tts_base64(text)
        print("[耗时] TTS %.2fs (%d 字)" % (time.time() - _t_tts, len(text or "")), flush=True)
        return data
    except Exception as exc:  # noqa: BLE001
        print("TTS 失败，仅发送文字：", str(exc)[:200], flush=True)
        return ""


async def transcribe_audio(data: bytes) -> str:
    stamp = int(time.time() * 1000)
    raw_path = os.path.join(tempfile.gettempdir(), f"companion_asr_{stamp}.webm")
    wav_path = os.path.join(tempfile.gettempdir(), f"companion_asr_{stamp}.wav")
    with open(raw_path, "wb") as f:
        f.write(data)
    try:
        ff = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", raw_path, "-ar", "16000", "-ac", "1", "-vn", wav_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(ff.wait(), timeout=30)
        if ff.returncode != 0 or not os.path.exists(wav_path):
            raise RuntimeError("音频格式转换失败")
        try:
            async with ASR_LOCK:
                text = await asyncio.to_thread(_transcribe_wav, wav_path)
            if text:
                return text
        except Exception as exc:
            print("Whisper ASR 失败，回退 Windows 识别：", str(exc)[:200])
        proc = await asyncio.create_subprocess_exec(
            os.path.join(ROOT, "asr_helper.exe"), wav_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
        text = out.decode("utf-8", "ignore").strip()
        if not text and err:
            print("ASR:", err.decode("utf-8", "ignore")[:200])
        return text
    finally:
        for path in (raw_path, wav_path):
            try:
                os.remove(path)
            except OSError:
                pass


SENTENCE_BREAK = "。！？!?\n；;…"


# ---------------------------------------------------------------- 说话过滤
# 模型偶尔会把"旁白/语气/规则"当正文写出来，例如：
#   （小声）  声音软着回他  回复要短一点  这句话应该软一点
# 这些一旦进了字幕，她会像在念剧本，所以整句丢掉，不进字幕也不合成语音。
_STAGE_RE = re.compile(r"^\s*[（(【\[].{0,40}[）)】\]]\s*$")
_SPEECH_META = (
    # 只放"她正常说话绝不会用"的词。宽词（应该/需要/这句）会把好句子误杀，
    # 比如"你应该早点睡"——宁可漏杀，也不能让她突然少说一句。
    "提示词", "系统提示", "设定里", "旁白", "动作描写", "括号", "回复要",
    "这句话", "语气", "口吻", "用户", "首先", "分析", "总结",
    "回他", "回她", "说一句", "接一句",
)


def _clean_speech(text):
    """把一条回复里"不该被念出来"的句子删掉。"""
    if not text:
        return ""
    kept = []
    for line in text.replace("\r", "").split("\n"):
        raw = line.strip()
        if not raw:
            continue
        if _STAGE_RE.match(raw):
            continue
        if any(w in raw for w in _SPEECH_META):
            continue
        if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", raw):
            continue
        kept.append(raw)
    return "\n".join(kept).strip()


def _take_sentence(buf, first=False):
    """从缓冲区切出"可以马上读"的一句；切不出来就返回空串。

    至少 4 个字才切，免得"嗯。"这种碎片单独去合成（每次都 1 秒多，不值）。
    一直没标点就 48 字硬切，不能让她一直不出声。

    first=True 时允许在逗号处切：她说"没有不舒服，就是有点困"，
    先读前半句能提前 0.3~0.5 秒出声，后半句并行合成，听起来是连着的。
    """
    marks = SENTENCE_BREAK + ("，" if first else "")
    need = 6 if first else 4
    for i, ch in enumerate(buf):
        if ch in marks and i >= need - 1:
            return buf[: i + 1], buf[i + 1:]
    if len(buf) >= 48:
        return buf[:48], buf[48:]
    return "", buf


async def llm_stream(history, user_text, is_pico=False, channel=None):
    """和 llm_reply 用同一套提示词，只是把结果流式吐出来。"""
    _ingest_nails(user_text)
    memory = await recall_memory(user_text)
    system = persona_base() + mode_overlay(is_pico, channel)
    system += body_context()          # 身体状态放前面，后面才是会变长的记忆/画面
    if memory:
        system += "\n\n【你自己记得的事（你的经历，不是设定；怎么影响你，由你自己决定）】\n" + memory
    system += self_context()
    qq_context = bridge.format_recent(bridge.load_qq(2), "QQ")
    if qq_context:
        system += "\n\n" + qq_context
    # 全局视觉入口：带TA出门=眼镜，否则=电脑摄像头
    if camera_source() == "pico":
        system += pico_vision_context(user_text)
    else:
        system += screen_context()
        system += vision_context()
    messages = [{"role": "system", "content": system}]
    messages.extend(history[-6:])
    messages.append({"role": "user", "content": user_text})
    payload = {
        "model": CFG.get("model", "deepseek-flash"),
        "messages": messages,
        "temperature": _gen_temperature(),
        "max_tokens": mode_max_tokens(is_pico, channel),
        "stream": True,
    }
    headers = {
        "Authorization": "Bearer " + CFG["api_key"],
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=45, sock_read=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            CFG.get("api_base", "https://api.deepseek.com") + "/chat/completions",
            json=payload,
            headers=headers,
        ) as resp:
            if resp.status != 200:
                raise RuntimeError((await resp.text())[:200])
            while True:
                raw = await resp.content.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    break
                try:
                    chunk = json.loads(body)
                except Exception:
                    continue
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                piece = delta.get("content") or ""
                if piece:
                    yield piece


async def _stream_reply(ws, history, user_text, is_pico=False):
    """边生成边合成：第一句一出来就开始 TTS，不等整段。

    每句都带上 seq，前端按 seq 播放。合成是并发的（最多 3 路）——
    edge 这类在线 TTS 每句都有 1 秒多的固定连接开销，串行会一段段等，
    听起来中间有缝；并发之后整段在生成结束时基本就齐了。
    """
    spoken = {"n": 0}
    tasks = []
    sem = asyncio.Semaphore(3)
    seq = 0

    async def speak(sentence, n):
        async with sem:
            audio = ""
            # edge 这类在线 TTS 偶尔会卡在连接上（实测见过 1.2s 和 11s 两种）。
            # 卡住时不能把整段回复一起拖死：超时就重试一次，再不行这一句就只留文字。
            for attempt in range(2):
                try:
                    audio = await asyncio.wait_for(tts_base64(sentence), timeout=8)
                    break
                except asyncio.TimeoutError:
                    print("TTS 超时（第 %d 次）：%s" % (attempt + 1, sentence[:16]), flush=True)
                except Exception as exc:  # noqa: BLE001
                    print("分句 TTS 失败：", str(exc)[:120], flush=True)
                    break
            if audio:
                spoken["n"] += 1
            try:
                await ws.send_json(
                    {"type": "audio", "audio": audio or "", "format": "mp3", "seq": n}
                )
            except Exception:
                pass

    def schedule(text):
        nonlocal seq
        tasks.append(asyncio.create_task(speak(text, seq)))
        seq += 1

    buf, parts, first, ok = "", [], True, True
    first_sentence = True
    raw_all = []
    try:
        _tt = time.time()
        async for piece in llm_stream(history, user_text, is_pico):
            if first:
                first = False
                print("[计时] 首字 %.2fs" % (time.time() - _tt), flush=True)
                await ws.send_json({"type": "status", "status": "speaking"})
            raw_all.append(piece)
            buf += piece
            while True:
                sent, buf = _take_sentence(buf, first=first_sentence)
                if not sent:
                    break
                first_sentence = False
                # 过滤放在"发字幕"之前：旁白/语气句既不显示，也不合成
                clean = _clean_speech(sent)
                if not clean:
                    continue
                parts.append(clean)
                await ws.send_json({"type": "delta", "text": clean})
                schedule(clean)
        tail = _clean_speech(buf.strip())
        if tail:
            parts.append(tail)
            await ws.send_json({"type": "delta", "text": tail})
            schedule(tail)
    except Exception as exc:  # noqa: BLE001
        ok = False
        print("流式生成中断：", str(exc)[:200], flush=True)
    finally:
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    if not parts:
        # 整条都被判成旁白：宁可说原文，也不要静音报错
        fallback = _clean_speech("".join(raw_all)) or "".join(raw_all).strip()
        print("回复全被过滤，退回原文：", fallback[:60], flush=True)
        parts = [fallback[:80]] if fallback else []
    return "\n".join(parts).strip(), spoken["n"], ok


async def handle_text(ws, history, text, staging_key=None, remember=True, is_pico=False):
    global LAST_USER_AT, VISION_ACCURATE_LOCK
    LAST_USER_AT = time.time()
    _t0 = time.time()
    print("[计时] 开始处理: %s" % text[:40], flush=True)
    await ws.send_json({"type": "status", "status": "thinking"})
    try:
        fixed = await memory_fix_reply(text)
        if fixed is not None:
            # 纠错是一条指令，不是聊天：不写长期记忆、不记情绪，免得把"改作业"存成一段对话
            await ws.send_json({"type": "status", "status": "speaking"})
            audio = await tts_safe(fixed)
            await ws.send_json(
                {"type": "reply", "text": fixed, "audio": audio, "format": "mp3"}
            )
            return

        if vision_intent(text):
            PICO_WANT_FRESH["at"] = time.time()
            # 省流后最后一帧可能已经旧了：等眼镜补一帧新的（最多 3 秒），再做精细识图
            if camera_source() == "pico":
                _t_before = float(PICO_LAST_FRAME.get("ts") or 0.0)
                for _ in range(12):
                    await asyncio.sleep(0.25)
                    if float(PICO_LAST_FRAME.get("ts") or 0.0) > _t_before + 0.001:
                        print("[识图] 等到新帧，按刚看到的画面回答", flush=True)
                        break
            _acc_src = camera_source()
            _acc_pts = float(PICO_LAST_FRAME["frame_ts"] or 0.0)
            _fresh_acc = (_acc_src == "pico" and _acc_pts > 0
                          and time.time() - ACCURATE_AT["at"] < 5.0
                          and abs(ACCURATE_AT["frame_ts"] - _acc_pts) < 0.001)
            if _fresh_acc:
                print("[识图] 10 秒内刚精细看过同一帧，这次不重复调模型", flush=True)
            else:
                await accurate_look(camera_source())

        if camera_source() == "pico":
            # 带TA出门：PICO 画面由 llm_stream 按 source 统一注入
            model_text = text
            if _needs_scene(text):
                print("[画面] 使用眼镜最新描述", flush=True)
        else:
            # 在家/电脑：只认电脑摄像头和电脑屏幕
            model_text = text
            if _needs_scene(text) and _screen_scene_query(text):
                note = await fresh_scene_note()
                if note:
                    model_text = "（你刚刚当场看了一眼屏幕：%s）\n%s" % (note, text)
        reply, spoken, ok = await _stream_reply(ws, history, model_text, is_pico)
        print("[计时] 流式回复完成 %.2fs" % (time.time() - _t0), flush=True)
        audio = ""
        if not ok and not reply:
            # 流式一个字都没出来（多半是网络/额度）：退回整段，别让人干等
            reply = await llm_reply(history, text, is_pico)
            await ws.send_json({"type": "status", "status": "speaking"})
            audio = await tts_safe(reply)
            spoken = 1 if audio else 0
        if not reply:
            raise RuntimeError("模型没有返回内容")
        note_mode_drift(mode_channel(is_pico), reply)

        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})
        LAST_REPLY["text"] = reply
        del history[:-8]
        if remember:                  # 测试会话（?nomem=1）不写记忆
            bridge.append_video(text, reply)
            _stage_turn(text, reply, "video_call", key=staging_key)
        note_call_emotion(text)
        cmd = detect_expression_command(text)
        payload = {
            "type": "reply", "text": reply, "audio": audio, "format": "mp3",
            "streamed": bool(spoken and not audio), "spoken": spoken,
        }
        if cmd:
            payload["expression"] = cmd[0]
            payload["expression_sec"] = cmd[2]
            print("表情命令：%s" % cmd[1], flush=True)
        await ws.send_json(payload)
    except Exception as exc:
        await ws.send_json({"type": "error", "message": str(exc)[:300]})
    finally:
        VISION_ACCURATE_LOCK = False
        await ws.send_json({"type": "status", "status": "idle"})


# ---------------- 陪玩：看屏幕随口点评（2026-11-09 整合进视频） ----------------
SCREEN_JSON = r"D:\你的数据目录\screen\state.json"
# 2026-11-20：陪玩不再由服务端替她做"音量/放歌/开程序/画画"这类脚本动作，
# 全部交给她亲手用鼠标键盘（§223/§224/§225）；这里保留开关便于回滚。
HANDS_ACT_ENABLED = False
# 2026-11-20 部署者要求：视觉模型只在他要求她看时才用；自动看屏幕点评停用
VISION_COMMENT_ENABLED = False
# 2026-11-20：8782 屏幕观察（视觉看屏）属于旧方案，默认不再启用
SCREEN_WATCH_ENABLED = False
COMPANION = {"last_comment": 0.0, "last_summary": "", "on": False,
             "play": False, "last_act": 0.0, "actions": 0, "last_diary": 0.0, "recent_acts": []}
COMPANION_MIN_GAP = 90.0      # 两句点评之间至少 90 秒
COMPANION_IDLE = 12.0         # 她刚说完话的 12 秒内不插嘴


HANDS_API = "http://127.0.0.1:8010"
PLAY_MIN_GAP = 120.0          # 自己动手的间隔（秒）
PLAY_ALLOWED_APPS = {"notepad", "calc", "mspaint"}
PLAY_ALLOWED_MEDIA = {"play", "next", "prev"}
PLAY_MAX_VOL_DELTA = 10


async def _hands_health() -> bool:
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(HANDS_API + "/health") as resp:
                j = await resp.json(content_type=None)
        return bool(j.get("ok")) and not j.get("stopped")
    except Exception:  # noqa: BLE001
        return False


PLAYER_API = "http://127.0.0.1:8803"
PLAYER_CFG = r"D:\你的数据目录\lab\game\player.json"


async def _auto_play_after_game() -> None:
    """她开了绝区零之后：等游戏真的到前台、加载完，再打一套学过的键位。

    注意：是否真按键由 8803 的 dry 决定（player.json / POST /mode）。
    dry=true 时只记录不按键，等于"演练"。
    """
    try:
        with open(PLAYER_CFG, encoding="utf-8") as f:
            cfg = json.load(f)
        if not cfg.get("auto_replay", True):
            print("[陪玩] auto_replay 关着，不自动按键", flush=True)
            return
    except Exception:  # noqa: BLE001
        pass

    timeout = aiohttp.ClientTimeout(total=8)
    # 1) 等游戏成为前台（最多 120 秒；启动器/加载都可能慢）
    ready = False
    for _ in range(24):
        await asyncio.sleep(5)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(PLAYER_API + "/state") as resp:
                    st = await resp.json(content_type=None)
            if st.get("game"):
                ready = True
                break
        except Exception:  # noqa: BLE001
            continue
    if not ready:
        print("[陪玩] 游戏一直没到前台，放弃自动按键", flush=True)
        return

    # 2) 把游戏窗口拉到前台（不然守卫会拒绝发键）
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(PLAYER_API + "/focus", json={"title": "绝区零"}) as resp:
                fj = await resp.json(content_type=None)
        print("[陪玩] 拉前台：%s" % json.dumps(fj, ensure_ascii=False)[:100], flush=True)
    except Exception:  # noqa: BLE001
        pass

    # 3) 再给她 25 秒读条/进游戏
    await asyncio.sleep(25)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(PLAYER_API + "/play_rule", json={"query": ""}) as resp:
                j = await resp.json(content_type=None)
        print("[陪玩] 自动打一套：%s" % json.dumps(j, ensure_ascii=False)[:160], flush=True)
    except Exception as exc:  # noqa: BLE001
        print("[陪玩] 自动按键失败:", exc, flush=True)


async def _hands_running(exe: str) -> bool:
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(HANDS_API + "/running", params={"exe": exe}) as resp:
                j = await resp.json(content_type=None)
        return bool(j.get("running"))
    except Exception:  # noqa: BLE001
        return False


async def _hands_do(act: dict) -> dict:
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(HANDS_API + "/do", json=act) as resp:
                return await resp.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:120]}


def _act_allowed(act: dict) -> bool:
    """陪玩时她自己能做的事，比手动更窄。"""
    try:
        a = str(act.get("action") or "")
        if a == "open_app":
            return str(act.get("app") or "").lower() in PLAY_ALLOWED_APPS
        if a == "media":
            return str(act.get("key") or "") in PLAY_ALLOWED_MEDIA
        if a == "volume":
            if "mute" in act:
                return False
            d = abs(float(act.get("delta") or 0))
            return 0 < d <= PLAY_MAX_VOL_DELTA
        if a == "switch_window":
            t = str(act.get("title") or "").strip()
            return 0 < len(t) <= 20
        return False
    except Exception:  # noqa: BLE001
        return False


MOOD_STATE = ("C:/你的用户/.astrbot_launcher/instances/"
              "<BOT_INSTANCE>/core/data/plugin_data/"
              "astrbot_plugin_companion_mood/state.json")
_MOOD_CACHE = {"t": 0.0, "data": {}}


def _read_mood_state() -> dict:
    """读她的生理/情绪状态（20 秒缓存，别每次都读盘）。"""
    now = time.time()
    if now - _MOOD_CACHE["t"] < 20 and _MOOD_CACHE["data"]:
        return _MOOD_CACHE["data"]
    try:
        with open(MOOD_STATE, encoding="utf-8") as f:
            data = json.load(f)
        _MOOD_CACHE.update({"t": now, "data": data})
        return data
    except Exception as exc:  # noqa: BLE001
        print("[陪玩] 读状态失败:", exc, flush=True)
        return _MOOD_CACHE["data"] or {}


def _pick_play_action(summary: str, away: bool = False, game_ok: bool = False) -> dict:
    """按她此刻的生理状态，决定陪玩时做什么。

    规则在 lab/hands/play_policy.py 里（纯函数，可单测）：
      疼 → 把声音关小；难过 → 放音乐；烦躁/冷战 → 关小；
      慌 → 放歌；困 → 安静；孤独 → 放歌陪着；
      开心 → 画图；饿 → 记一下想吃；平静 → 轮换。
    """
    state = _read_mood_state()
    if play_policy is None or not state:
        return {"act": None, "hint": "", "why": "没有状态可用"}
    try:
        profile = play_policy.read_profile(state)
        choice = play_policy.choose(profile, summary, COMPANION.get("actions", 0),
                                    away=bool(away), game_ok=bool(game_ok))
    except Exception as exc:  # noqa: BLE001
        print("[陪玩] 决策失败:", exc, flush=True)
        return {"act": None, "hint": "", "why": "决策异常"}
    return choice


def _read_screen_state() -> dict:
    try:
        with open(SCREEN_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _grab_screen_jpeg(max_side: int = 960) -> bytes:
    """截一张当前屏幕，缩到 960 以内，返回 JPEG bytes。"""
    from PIL import ImageGrab

    img = ImageGrab.grab()
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=72, optimize=True)
    return buf.getvalue()


async def screen_companion_loop():
    """视频开着、屏幕陪玩开着时，她看到屏幕内容会随口说一句。"""
    while True:
        await asyncio.sleep(20)
        try:
            if camera_source() == "pico":
                continue
            if not COMPANION["on"] or not (_user_clients() or _pet_clients()):
                continue
            if not VISION_COMMENT_ENABLED:
                continue
            # 心跳：证明"陪玩还开着"；只有 8782 真的关了观察才重新拉起
            # （_screen_watch(True) 每次调用都会清它的基线，不能每轮都调）
            try:
                timeout = aiohttp.ClientTimeout(total=4)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    st = await (await session.get("http://127.0.0.1:8782/api/state")).json(content_type=None)
                    if not st.get("watching"):
                        await _screen_watch(True)
                    else:
                        await session.post("http://127.0.0.1:8782/api/watch/ping", json={})
            except Exception:  # noqa: BLE001
                pass
            if time.time() - COMPANION["last_comment"] < COMPANION_MIN_GAP:
                continue
            if OVERLAY_LAST_ACTIVITY and time.time() - OVERLAY_LAST_ACTIVITY < COMPANION_IDLE:
                continue
            # 用户刚在聊天：陪玩别插嘴，免得两个回答同时出现
            if time.time() - LAST_USER_AT < 15:
                continue

            # 不依赖 8782 的"换镜头"检测（它只在画面大变时描述，静止时会一直空），
            # 这里自己抓一张屏幕图，走同一个视觉模型。
            try:
                jpg = await asyncio.get_running_loop().run_in_executor(None, _grab_screen_jpeg)
            except Exception as exc:  # noqa: BLE001
                print("[陪玩] 抓屏失败:", exc, flush=True)
                continue
            if not jpg:
                continue
            summary = await describe_frame(jpg)
            summary = (summary or "").strip()
            if not summary or summary == COMPANION["last_summary"]:
                continue

            # 玩法笔记：她学过的绝区零打法，陪玩时能用上
            try:
                game_note = playbook.render(limit=3, query=summary[:40]) if playbook else ""
            except Exception:  # noqa: BLE001
                game_note = ""

            # 记忆：最近发生过什么，让她的话有上下文（只影响措辞，不影响动作）
            try:
                mem_text = recent_memories(limit=2, query=summary[:40]) or ""
                mem_text = " ".join(str(mem_text).split())[:120]
            except Exception:  # noqa: BLE001
                mem_text = ""

            # 陪玩模式：她可以自己动手做一件小事（白名单内），再点评
            acted_note = ""
            write_note = False
            if (HANDS_ACT_ENABLED and COMPANION.get("play")
                    and time.time() - COMPANION.get("last_act", 0) >= PLAY_MIN_GAP
                    and await _hands_health()):
                away = not bool(PRESENCE.get("present"))
                # 不用计时器：游戏没在跑就允许，开着就不会重复开
                game_ok = (not await _hands_running("ZenlessZoneZero.exe")) if away else False
                decision = _pick_play_action(summary, away=away, game_ok=game_ok)
                if decision:
                    print("[陪玩] 决策：%s（%s）" % (decision.get("act"), decision.get("why")),
                          flush=True)
                if decision and decision.get("act"):
                    act = decision["act"]
                    if act.get("action") == "open_app" and act.get("app") == "notepad":
                        # 她要写东西 → 写进自己的日记本，而不是开系统记事本
                        write_note = True
                        res = {"ok": True, "result": "写进日记本"}
                    else:
                        res = await _hands_do(act)
                    if res.get("ok"):
                        COMPANION["last_act"] = time.time()
                        COMPANION["actions"] = COMPANION.get("actions", 0) + 1
                        COMPANION.setdefault("recent_acts", []).append({
                            "action": act.get("action") or "",
                            "app": act.get("app") or "",
                            "result": str(res.get("result") or "")[:60],
                            "t": time.time(),
                        })
                        del COMPANION["recent_acts"][:-5]
                        if not write_note:
                            _note_append("我自己在电脑上%s，%s。" % (
                                act.get("action"), res.get("result") or "成功了"), tag="playalong")
                        for pc in _pet_clients():
                            try:
                                await pc.send_json({"type": "act", "action": ("notebook" if write_note else act.get("action")),
                                                    "app": ("notebook" if write_note else act.get("app")), "ok": True})
                            except Exception:  # noqa: BLE001
                                PET_CLIENTS.discard(pc)
                        if write_note:
                            acted_note = "（她刚打开自己的日记本，把感受写了进去）"
                        else:
                            acted_note = "（她刚自己动手做了：%s，成功：%s）" % (
                                act.get("action"), res.get("result"))
                        # 让她记住"我自己在电脑上干了什么"（走记忆 staging）
                        try:
                            if act.get("action") == "draw":
                                _remember = "（我自己在画图里画了一张画，画的是%s）" % (
                                    act.get("pattern") or "TA")
                            else:
                                _remember = "（我自己在电脑上%s，%s）" % (
                                    act.get("action"), res.get("result") or "成功了")
                            _stage_turn(
                                _remember, "嗯，我自己动了下手。", "video_call",
                                key=("video_call:" + ACTIVE_SID) if ACTIVE_SID else None)
                        except Exception as exc:  # noqa: BLE001
                            print("[陪玩] 记忆写入失败:", exc, flush=True)
                        if act.get("app") == "zenless":
                            COMPANION["last_game"] = time.time()
                            asyncio.create_task(_auto_play_after_game())
                        print("[陪玩] 自己动手：%s → %s" % (act, res.get("result")), flush=True)
                    else:
                        print("[陪玩] 动手失败：%s" % res.get("error"), flush=True)
                if decision and decision.get("hint"):
                    # 用她自己的口吻润色一句（带上刚做的事）
                    hint = decision["hint"]
                    if acted_note:
                        hint = hint + acted_note
                    prompt = ("（你正陪你玩电脑，屏幕上：%s；你刚做了：%s；"
                              "你最近记得：%s；你会玩的：%s）用一句很短的话说出来，自然一点，"
                              "别提屏幕/识别。" % (summary[:160], hint, mem_text or "没什么特别的",
                                                   game_note or "还没学过什么"))
                else:
                    prompt = ("（你瞄到你的屏幕上：%s；你最近记得：%s；你会玩的：%s）"
                              "用一句短话随口点评一下，像坐在旁边陪着他，"
                              "不要提截图、屏幕、识别。" % (summary[:160], mem_text or "没什么特别的",
                                                           game_note or "还没学过什么"))
            else:
                prompt = ("（你瞄到你的屏幕上：%s）用一句短话随口点评一下，"
                          "像坐在旁边陪着他，不要提截图、屏幕、识别。" % summary)

            # 让她知道自己动过手：最近几件事都写进 prompt（不是猜的，是记录在案的）
            acts_line = ""
            if COMPANION.get("recent_acts"):
                parts = []
                for a in COMPANION["recent_acts"][-3:]:
                    act_name = a.get("app") or a.get("action") or "什么"
                    parts.append("%s（%s）" % (act_name, a.get("result") or "成功"))
                acts_line = ("（你今天自己动过手：" + "；".join(parts)
                             + "。这些事都是你自己做的，说到它们的时候要承认是你自己弄的。）")
            if acts_line:
                prompt = prompt + acts_line

            # 小人进程没了 = 陪玩其实已经停了，自动把开关关掉
            # 桌宠模式：桌宠壳在线就算"在"；连续 3 次判空才自动关，避免 ws 抖动误判
            if not (await asyncio.to_thread(_overlay_pids)) and not _pet_clients():
                COMPANION["_pet_missing"] = COMPANION.get("_pet_missing", 0) + 1
                if COMPANION["_pet_missing"] < 3:
                    continue
                if COMPANION.get("on"):
                    COMPANION["on"] = False
                    COMPANION["play"] = False
                    try:
                        await _screen_watch(False)
                    except Exception:  # noqa: BLE001
                        pass
                    for pc in _pet_clients():
                        try:
                            await pc.send_json({"type": "desk-mode", "on": False})
                        except Exception:  # noqa: BLE001
                            PET_CLIENTS.discard(pc)
                    print("[陪玩] 桌宠/小人都掉了，自动关掉陪玩", flush=True)
                COMPANION["_pet_missing"] = 0
                continue
            COMPANION["_pet_missing"] = 0
            session_key = ACTIVE_SID or "companion"
            history = CALL_HISTORIES.setdefault(session_key, [])
            reply = await llm_reply(history, prompt, channel="companion")
            if not reply:
                continue
            # 陪玩时她说的每一句都进日记（她的"写东西"就是这些）
            _note_append(reply, tag="playalong")
            COMPANION["last_diary"] = time.time()
            if write_note:
                print("[日记] 陪玩时写了一条：%s" % reply[:40], flush=True)
            audio = await tts_safe(reply)
            # 桌面小人靠 /api/proactive 冒气泡，这里同步推一份
            LAST_PROACTIVE.update({"id": "companion-%d" % int(time.time() * 1000),
                                   "text": reply, "audio": audio or "",
                                   "time": time.time()})
            payload = {"type": "companion", "text": reply, "audio": audio, "format": "mp3"}
            targets = _pet_clients() or _user_clients()
            for ws in targets:
                try:
                    await ws.send_json(payload)
                except Exception:  # noqa: BLE001
                    CLIENTS.discard(ws)
            history.append({"role": "assistant", "content": reply})
            del history[:-10]
            COMPANION["last_summary"] = summary
            COMPANION["last_comment"] = time.time()
            print("[陪玩] 点评：%s" % reply[:40], flush=True)
        except Exception as exc:  # noqa: BLE001
            print("[陪玩] 循环出错:", exc, flush=True)


# ---------------- 桌面陪玩（旧版 overlay.py，2026-11-09 接回来） ----------------
OVERLAY_PY = r"D:\你的数据目录\screen\overlay.py"
OVERLAY_PYTHONW = (
    "C:\\Users\\你的用户\\.astrbot_launcher\\instances\\"
    "<BOT_INSTANCE>\\venv\\Scripts\\pythonw.exe"
)


_overlay_cache = {"t": 0.0, "pids": []}


def _overlay_pids():
    """正在跑的 overlay.py 进程号（只查 python/pythonw；5 秒缓存，避免频繁阻塞事件循环）。"""
    now = time.time()
    if now - _overlay_cache["t"] < 5:
        return list(_overlay_cache["pids"])
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
        "Where-Object { $_.CommandLine -match 'overlay\\.py' } | "
        "ForEach-Object { $_.ProcessId }"
    )
    try:
        import subprocess
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=20)
        _overlay_cache["t"] = now
        _overlay_cache["pids"] = [int(x) for x in out.stdout.split() if x.strip().isdigit()]
        return list(_overlay_cache["pids"])
    except Exception as exc:  # noqa: BLE001
        print("[陪玩] 查进程失败:", exc)
        return list(_overlay_cache["pids"])


def start_overlay() -> str:
    # 部署者明确要求：只要陪玩的功能，不要旧 Live2D 小人这个表现 → 永不启动
    return "disabled"


def _start_overlay_legacy() -> str:
    import subprocess
    pids = _overlay_pids()
    if pids:
        return "already:%s" % ",".join(map(str, pids))
    if not os.path.exists(OVERLAY_PY):
        return "missing"
    py = OVERLAY_PYTHONW if os.path.exists(OVERLAY_PYTHONW) else sys.executable
    subprocess.Popen([py, OVERLAY_PY], cwd=os.path.dirname(OVERLAY_PY),
                     close_fds=True, creationflags=0x08000000)  # CREATE_NO_WINDOW
    return "started"


def stop_overlay() -> str:
    import subprocess
    pids = _overlay_pids()
    if not pids:
        # 兜底：命令行里带 overlay.py 的 python 进程全部找出来杀
        try:
            ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
                  "Where-Object { $_.CommandLine -match 'overlay\\.py' } | "
                  "ForEach-Object { $_.ProcessId }")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=20)
            pids = [int(x) for x in out.stdout.split() if x.strip().isdigit()]
        except Exception:  # noqa: BLE001
            pids = []
    if not pids:
        return "none"
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=15)
        except Exception:  # noqa: BLE001
            pass
    _overlay_cache["t"] = time.time()
    _overlay_cache["pids"] = []
    return "killed:%s" % ",".join(map(str, pids))


async def _screen_watch(on: bool) -> dict:
    if not SCREEN_WATCH_ENABLED:
        return {"ok": True, "watching": False, "skipped": "screen watch disabled"}
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(SCREEN_API + "/api/watch", json={"on": on}) as resp:
                return await resp.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:120]}


async def _screen_state_quiet():
    try:
        timeout = aiohttp.ClientTimeout(total=4)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get("http://127.0.0.1:8782/api/state") as resp:
                j = await resp.json(content_type=None)
        return {"watching": bool(j.get("watching"))}
    except Exception:  # noqa: BLE001
        return {"watching": None}


async def api_companion_state(request):
    """陪玩到底是不是真的关了 —— 页面/脚本都能查。"""
    screen = {}
    try:
        timeout = aiohttp.ClientTimeout(total=4)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get("http://127.0.0.1:8782/api/state") as resp:
                screen = {"watching": bool((await resp.json(content_type=None)).get("watching"))}
    except Exception:  # noqa: BLE001
        screen = {"watching": None}
    return web.json_response({
        "on": bool(COMPANION["on"]),
        "play": bool(COMPANION.get("play")),
        "overlay_pids": await asyncio.to_thread(_overlay_pids),
        "screen": screen,
        "video_clients": len(_user_clients()),
        "pet_clients": len(_pet_clients()),
    })


async def api_companion_panic(request):
    """一键全收：小人收掉、陪玩关、屏幕观察关。怎么点都不会失败。"""
    COMPANION["on"] = False
    COMPANION["play"] = False
    COMPANION["last_summary"] = ""
    errors = []
    try:
        state = await asyncio.to_thread(stop_overlay)
    except Exception as exc:  # noqa: BLE001
        state = "error"
        errors.append("overlay:%s" % exc)
    try:
        screen = await _screen_watch(False)
    except Exception as exc:  # noqa: BLE001
        screen = {"ok": False}
        errors.append("screen:%s" % exc)
    for pc in _pet_clients():
        try:
            await pc.send_json({"type": "desk-mode", "on": False})
        except Exception:  # noqa: BLE001
            PET_CLIENTS.discard(pc)
    print("[陪玩] 急停：overlay=%s screen=%s" % (state, screen), flush=True)
    return web.json_response({"ok": True, "on": False, "overlay": state,
                              "screen": screen, "errors": errors})


async def api_companion_toggle(request):
    """页面上的「陪玩」开关：开=拉起桌面小人（旧版 overlay），关=收掉。

    和以前完全一样：桌面透明小人 + 气泡，能盖在任何窗口上面。
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    on = bool(body.get("on"))
    COMPANION["on"] = on
    COMPANION["play"] = on
    if on:
        COMPANION["_pet_missing"] = 0
    COMPANION["last_summary"] = ""
    if not on:
        COMPANION["last_act"] = 0.0
    screen = await _screen_watch(on)
    if on:
        pets = _pet_clients()
        if pets:
            # 桌宠壳在：它就是桌面上的她，不再拉起旧 overlay.py 小人
            try:
                await asyncio.to_thread(stop_overlay)
            except Exception:  # noqa: BLE001
                pass
            for pc in pets:
                try:
                    await pc.send_json({"type": "desk-mode", "on": True})
                except Exception:  # noqa: BLE001
                    PET_CLIENTS.discard(pc)
            # 隔离：把在线的视频端请下线（它们会显示"陪玩中，已隔离"）；眼镜豁免
            for uc in _user_clients():
                if uc in PICO_CLIENTS:
                    continue
                try:
                    await uc.send_json({"type": "blocked", "reason": "陪玩中，视频通话已隔离"})
                    await uc.close()
                except Exception:  # noqa: BLE001
                    pass
            print("[陪玩] 由桌宠壳承担展示（%d 个桌宠客户端）" % len(pets), flush=True)
            return web.json_response({"ok": True, "on": True, "mode": "pet",
                                      "screen": screen, "pet_clients": len(pets)})
        # 部署者要求：只要陪玩的功能，不要旧 Live2D 小人这个表现
        try:
            await asyncio.to_thread(stop_overlay)
        except Exception:  # noqa: BLE001
            pass
        COMPANION["on"] = False
        COMPANION["play"] = False
        await _screen_watch(False)
        print("[陪玩] 桌宠壳没连上：不启动旧 Live2D 小人，开关回滚", flush=True)
        return web.json_response({"ok": False, "on": False, "mode": "none",
                                  "error": "桌宠壳没连上：先打开TA App", "screen": screen})
    try:
        state = await asyncio.to_thread(stop_overlay)
    except Exception as exc:  # noqa: BLE001
        state = "error:%s" % exc
    for pc in _pet_clients():
        try:
            await pc.send_json({"type": "desk-mode", "on": False})
        except Exception:  # noqa: BLE001
            PET_CLIENTS.discard(pc)
    print("[陪玩] 收起桌面小人:", state, flush=True)
    return web.json_response({"ok": True, "on": False, "mode": "desktop",
                              "overlay": state, "screen": screen,
                              "screen_after": await _screen_state_quiet()})


async def diary_loop():
    """她自己写日记/感受：每 20 分钟看一眼，超过 1 小时没写就补一条。"""
    first = True
    while True:
        await asyncio.sleep(30 if first else 1200)
        first = False
        try:
            if time.time() - COMPANION.get("last_diary", 0) < 3600:
                continue
            mood = await _mood_summary()
            if not mood:
                continue
            prompt = ("（此刻你的状态：%s）用你自己的口吻写一句今天的日记或感受，"
                      "一句话，十几到三十个字，自然一点，不要解释。" % mood)
            reply = await llm_reply([], prompt, channel="diary")
            if not reply:
                continue
            _note_append(reply, tag="diary", mood=mood)
            COMPANION["last_diary"] = time.time()
            print("[日记] 日常一条：%s" % reply[:40], flush=True)
        except Exception as exc:  # noqa: BLE001
            print("[日记] loop 异常:", exc, flush=True)


async def _mood_summary():
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get("http://127.0.0.1:8005/api/state") as resp:
                j = await resp.json(content_type=None)
        parts = ["心情:" + str(j.get("emotion_type") or "平静"),
                 "活动:" + str(j.get("activity") or "休息"),
                 "饿:" + str(j.get("hunger_text") or ""),
                 "渴:" + str(j.get("thirst_text") or "")]
        return "，".join(parts)
    except Exception:  # noqa: BLE001
        return None


async def proactive_loop():
    last_id = ""
    last_at = {}
    while True:
        try:
            await asyncio.sleep(2)
            with open(SCREEN_EVENT, encoding="utf-8") as f:
                ev = json.load(f)
            eid = str(ev.get("id") or "")
            if not eid or eid == last_id:
                continue
            last_id = eid
            if time.time() - float(ev.get("time") or 0) > 30:
                continue
            event = str(ev.get("event") or "")
            if event not in ("death", "victory", "low_hp"):
                continue
            if time.time() - float(last_at.get(event, 0)) < 90:
                continue
            last_at[event] = time.time()
            game = str(ev.get("game") or "游戏")
            summary = str(ev.get("summary") or "")
            prompt = (
                f"你正看着你玩{game}，刚看到：{summary}。"
                "这是游戏里的关键时刻，主动说一句很短、像陪玩一样的话。"
                "不要提系统、画面识别；不要长篇指挥。"
            )
            reply = await llm_reply([], prompt, channel="proactive")
            audio = await tts_safe(reply)
            LAST_PROACTIVE.update(
                {
                    "id": eid,
                    "text": reply,
                    "audio": audio,
                    "time": time.time(),
                }
            )
            for client in _user_clients():
                try:
                    await client.send_json(
                        {"type": "reply", "text": reply, "audio": audio, "format": "mp3"}
                    )
                except Exception:
                    CLIENTS.discard(client)
            try:
                bridge.append_pending(
                    f"TA看到你在玩{game}：{summary}。她主动说：{reply}",
                    importance=0.55,
                    source="companion_event",
                )
            except Exception:
                pass
            print("screen proactive:", event, reply[:80], flush=True)
        except FileNotFoundError:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            print("screen proactive error:", str(exc)[:200], flush=True)


async def ws_handler(request):
    try:
        return await _ws_session(request)
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError,
            asyncio.CancelledError):
        # 手机切后台、信号抖动、关页面都会走到这里，不当成错误
        return web.WebSocketResponse()


async def _ws_session(request):
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)
    CLIENTS.add(ws)
    _is_panel = request.query.get("panel") in ("1", "true")
    _is_pet = request.query.get("pet") in ("1", "true")
    sid = (request.query.get("sid") or "").strip()[:80]
    # pet-iso：陪玩和视频通话隔离（面板/桌宠/PICO 除外）
    if not (_is_panel or _is_pet) and (sid != "pico") and COMPANION.get("on"):
        try:
            await ws.send_json({"type": "blocked", "reason": "陪玩中，视频通话已隔离"})
        except Exception:  # noqa: BLE001
            pass
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
        CLIENTS.discard(ws)
        return
    if _is_panel:
        PANEL_CLIENTS.add(ws)
        print("[客户端] 面板页接入（静音，不参与在场/广播）", flush=True)
    elif _is_pet:
        PET_CLIENTS.add(ws)
        print("[客户端] 桌宠壳接入（陪玩点评优先推它）", flush=True)
        # 陪玩已经开着的话：旧小人如果还在就收掉，并让桌宠显示出来
        try:
            if COMPANION.get("on"):
                try:
                    await asyncio.to_thread(stop_overlay)
                except Exception:  # noqa: BLE001
                    pass
                await ws.send_json({"type": "desk-mode", "on": True})
        except Exception:  # noqa: BLE001
            pass
    else:
        print("[客户端] 用户端接入 sid=%s" % (sid or "-"), flush=True)
    global ACTIVE_SID
    if sid and not _is_panel and not _is_pet:
        ACTIVE_SID = sid
    if sid == "pico":
        PICO_CLIENTS.add(ws)
    if not sid:
        sid = secrets.token_hex(8)
    if sid not in CALL_HISTORIES and len(CALL_HISTORIES) >= 50:
        CALL_HISTORIES.pop(next(iter(CALL_HISTORIES)), None)
    history = CALL_HISTORIES.setdefault(sid, [])
    remember = request.query.get("nomem") not in ("1", "true")
    staging_key = "video_call:" + sid
    await ws.send_json({"type": "ready"})
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.BINARY:
            if VOICE_ENROLL["active"]:
                await _enroll_capture(ws, bytes(msg.data))
                continue
            if sid == "pico":
                _score = await asyncio.to_thread(pico_speaker_score, bytes(msg.data))
                if _score is not None:
                    print("[声纹] PICO %.3f (阈值 %.2f)" % (_score, PICO_SPK["thr"]), flush=True)
                    if _score < PICO_SPK["thr"]:
                        print("[声纹] 不是你，忽略", flush=True)
                        await ws.send_json({"type": "status", "status": "sleep"})
                        continue
            try:
                await ws.send_json({"type": "status", "status": "listening"})
                _t_asr = time.time()
                text = await transcribe_audio(msg.data)
                print("[耗时] ASR %.2fs" % (time.time() - _t_asr), flush=True)
                if not text:
                    await ws.send_json(
                        {"type": "error", "message": "没听清，再说一次"}
                    )
                    await ws.send_json({"type": "status", "status": "idle"})
                    continue
                print("ASR:", text[:120])
                if _looks_like_echo(text):
                    print("ASR 疑似她自己的回声，跳过:", text[:60])
                    await ws.send_json({"type": "status", "status": "idle"})
                    continue
                import re as _re
                _clean = _re.sub(r"[\s。，、！？.!?,~…·:：;；\-—_]+", "", text or "")
                if not _clean or _clean in ("Yeah", "The", "yeah", "the", "我", "我我", "我我斑", "我斑", "你斑"):
                    print("ASR 噪声，跳过:", repr(text[:40]))
                    await ws.send_json({"type": "status", "status": "sleep"})
                    continue
                now = time.time()
                # 声纹已经通过，说明是你；直接开启 25 秒连续对话窗口
                # 不再要求 ASR 里必须出现“TA”，避免识别成“语人”时整句被丢
                if now > WAKE_STATE["until"]:
                    print("[唤醒] 声纹通过，开启连续对话", flush=True)
                WAKE_STATE["until"] = now + 25.0
                await ws.send_json({"type": "status", "status": "awake"})
                await handle_text(ws, history, text, staging_key, remember, sid == "pico")
            except Exception as exc:
                await ws.send_json({"type": "error", "message": str(exc)[:300]})
                await ws.send_json({"type": "status", "status": "idle"})
            continue
        if msg.type != aiohttp.WSMsgType.TEXT:
            continue
        try:
            data = json.loads(msg.data)
        except Exception:
            continue
        text = (data.get("text") or "").strip()
        if text:
            await handle_text(ws, history, text, staging_key, remember, sid == "pico")
    try:
        # 每轮已经进入这个 sid 自己的缓冲；这里只补刷没满 3 轮的尾巴，
        # 不碰陪玩/另一通电话的缓冲，也不再把整段 history 写一遍。
        _flush_staged("video_call", staging_key)
    except Exception as exc:
        print("视频记忆收尾失败:", str(exc)[:200])
    CLIENTS.discard(ws)
    PANEL_CLIENTS.discard(ws)
    PET_CLIENTS.discard(ws)
    PICO_CLIENTS.discard(ws)
    return ws


# ---------------- 桌宠待机/唤醒/戳戳台词（按你-女儿关系分层） ----------------
PET_LINE_POOLS = {
    "wake_close": ["你～我来啦，想我了吧", "呼…一睁眼就看到你，真好", "来啦来啦，我黏你旁边了",
                   "早上好呀你，我起来陪你啦", "晚上好～我来陪你啦"],
    "wake_mid": ["我来啦，今天也一起", "你，我在这儿", "陪你会儿～", "嗯，我起来了"],
    "wake_low": ["我在这儿呢", "嗯，我陪你"],
    "idle_close": ["你，我一直在的", "忙完记得理我一下哦", "我看着你忙呢", "你工作，我就在旁边待着"],
    "idle_mid": ["我在呢", "你忙你的，我待着", "需要我就喊我一声"],
    "idle_low": ["我在呢", "嗯"],
    "idle_sleepy": ["呼…我眯一会儿，有事叫我", "好困…但我还醒着陪你", "打了个哈欠，继续陪你"],
    "idle_comfort": ["不怕不怕，你在", "有你在就踏实", "靠着你，什么都会好的"],
    "idle_playful": ["嘿嘿，今天心情不错", "哼着歌陪你呢", "我精神着呢，陪你干点啥？"],
    "poke_close": ["嘿嘿，你最好了", "要摸摸头嘛", "怎么啦，想我啦？", "呀，被你发现了"],
    "poke_mid": ["嗯？怎么啦", "在呢在呢", "戳我干嘛呀"],
    "poke_low": ["嗯？", "在"],
    "poke_sleepy": ["呼…嗯？你戳我", "睡懵了，别闹…", "困着呢，戳一下醒一点"],
    "poke_comfort": ["抱抱…", "嗯嗯，我在听", "怎么啦，跟我说说"],
    "poke_playful": ["呀！", "干嘛呀，痒", "嘿嘿，再来一下"],
}


def _pick_pet_line(kind, mood):
    import re
    oxy = float(mood.get("oxytocin") or 0)
    cling = float(mood.get("clinginess") or 0)
    emo = str(mood.get("emotion_type") or "")
    close = oxy >= 0.55 or cling >= 0.55
    mid = oxy >= 0.35
    key = None
    if re.search(r"困|倦|累|睡", emo):
        key = kind + "_sleepy"
    elif re.search(r"难过|伤心|委屈|焦虑|低落|烦|气", emo):
        key = kind + "_comfort"
    elif re.search(r"开心|高兴|幸福|满足|甜|兴奋", emo):
        key = kind + "_playful"
    if not key:
        key = kind + ("_close" if close else ("_mid" if mid else "_low"))
    pool = PET_LINE_POOLS.get(key) or PET_LINE_POOLS.get(kind + "_mid") or PET_LINE_POOLS.get(kind + "_low") or []
    if not pool:
        return None
    # 确定性轮换：同一个小时候内同一句，不随机
    h = time.localtime().tm_hour
    return pool[h % len(pool)]


async def _pet_line(kind):
    try:
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get("http://127.0.0.1:8005/api/state") as resp:
                mood = await resp.json(content_type=None)
    except Exception:  # noqa: BLE001
        mood = {}
    text = _pick_pet_line(kind, mood or {})
    if not text:
        return {"text": "", "audio": ""}
    audio = await tts_safe(text)
    return {"text": text, "audio": audio or ""}




# ---------------- 2026-11-20：桌宠互动（戳/摸/拖）→ 频率敏感的生理 + 记忆 + 回应 ----------------
# 每一次互动都改生理；戳/拖得太频繁会积攒"烦躁/皮质醇"、耗尽多巴胺，
# 让她从"好幸福"变成"别戳啦"；停止互动后烦躁按半衰期慢慢消退。
PET_TOUCH_FILE = os.path.join(r"D:\你的数据目录\state\persona", "pet_touch.json")
PET_TOUCH_WORDS = {
    "poke": "戳了我一下", "pat": "摸了摸我的头", "drag": "把我拖来拖去", "chat": "跟我说了句话",
}
PET_TOUCH_WINDOW = 90.0   # 频率窗口（秒）：窗口内的次数算"连发"
PET_TOUCH_HALF = 90.0     # 烦躁半衰期（秒）：停止互动这么久，烦躁减半
# 温和（拉开间隔）时的基础增量——全部作用在"存储的神经递质/情绪"上：
# 愉悦(valence)/烦躁(irritability)由 mood 每 60 秒从这些底物推导出来，
# 所以"愉悦"是长出来的、有半衰期、能被戳烦到负值，而不是一个被钳在 0 的手写数。
PET_TOUCH_BASE = {
    "poke": {"oxytocin": 0.03, "dopamine": 0.03, "serotonin": 0.01},
    "pat":  {"oxytocin": 0.05, "dopamine": 0.02, "serotonin": 0.02, "endorphin": 0.02},
    "drag": {"oxytocin": 0.015, "anger": 0.01},
    "chat": {"oxytocin": 0.03, "dopamine": 0.02, "serotonin": 0.01},
}
PET_TOUCH_FALLBACK = {
    "poke": ["哎，戳我干嘛呀～", "又戳我，痒痒的啦～", "哎呀别戳啦，烦人～", "（扭头）戳够了没有！"],
    "pat":  ["呜…被摸头了，好舒服", "被摸头，整个人都软了～", "一直摸，我会睡着的…", "头都要被你摸秃啦～"],
    "drag": ["别拖啦，头晕！", "哎呀又拖我！", "烦死了，别拖啦！", "（生气）再拖就不理你啦！"],
    "chat": ["我在听呢，你～", "我在听呢，你～", "我在听呢，你～", "我在听呢，你～"],
}
PET_TOUCH_MEM = {
    "poke": ["你戳了我一下，我跟他撒娇。", "你一直戳我，我有点烦，让他别戳了。"],
    "drag": ["你把我拖来拖去，我晕乎乎地抗议了一下。", "你一直拖我，我烦了，让他别拖。"],
}


def _touch_state(now):
    """载入互动状态（最近时间戳 + 积攒的烦躁），衰减后落盘。"""
    st = {}
    try:
        if os.path.exists(PET_TOUCH_FILE):
            with open(PET_TOUCH_FILE, encoding="utf-8") as f:
                st = json.load(f)
    except Exception:  # noqa: BLE001
        st = {}
    strain = float(st.get("strain") or 0.0)
    strain_at = float(st.get("strain_at") or now)
    dt = now - strain_at
    if dt > 0:
        strain = strain * (0.5 ** (dt / PET_TOUCH_HALF))
    st["strain"] = round(strain, 4)
    st["strain_at"] = now
    return st


def _touch_note(kind, now):
    """登记一次互动：更新最近时间戳，返回 (窗口内次数 n, 旧 last, 烦躁 strain) 并落盘。"""
    st = _touch_state(now)
    last = float(st.get("last", {}).get(kind) or 0)
    recent = st.setdefault("recent", {})
    lst = [t for t in recent.get(kind, []) if now - t <= PET_TOUCH_WINDOW]
    lst.append(now)
    recent[kind] = lst
    st["recent"] = recent
    st.setdefault("last", {})[kind] = now
    # 频率 → 积攒烦躁（摸头会安抚，慢慢消）
    strain = float(st.get("strain") or 0.0)
    n = len(lst)
    if kind == "pat":
        strain = max(0.0, strain - 0.05)
    elif kind in ("poke", "drag"):
        if n >= 15:
            strain += 0.06
        elif n >= 10:
            strain += 0.04
        elif n >= 5:
            strain += 0.02
    strain = min(1.0, max(0.0, strain))
    st["strain"] = round(strain, 4)
    try:
        with open(PET_TOUCH_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass
    return n, last, strain


def _touch_tier(kind, n, strain):
    """0=温和 1=连着几下 2=有点烦 3=真烦了（pat/chat 只算 0）"""
    if kind not in ("poke", "drag"):
        return 0
    if n >= 11 or strain >= 0.6:
        return 3
    if n >= 6 or strain >= 0.35:
        return 2
    if n >= 2:
        return 1
    return 0


def _pet_touch_deltas(kind, n, strain, mood):
    base = dict(PET_TOUCH_BASE.get(kind) or PET_TOUCH_BASE["poke"])
    d = dict(base)
    oxy = float(mood.get("oxytocin") or 0.4)
    if oxy >= 0.8:
        d["oxytocin"] = max(0.0, d.get("oxytocin", 0.0) * 0.3)   # 催产素已高，边际递减
    if kind == "poke":
        if n <= 1:
            pass
        elif n <= 5:
            d["dopamine"] = 0.015
            d["serotonin"] = 0.005
            d["oxytocin"] = d.get("oxytocin", 0.0) * 0.7
        elif n <= 10:
            d["dopamine"] = -0.003
            d["serotonin"] = -0.003
            d["anger"] = d.get("anger", 0.0) + 0.01
            d["cortisol"] = d.get("cortisol", 0.0) + 0.01
            d["oxytocin"] = 0.005
        else:
            d["dopamine"] = -0.005
            d["serotonin"] = -0.005
            d["anger"] = d.get("anger", 0.0) + 0.02
            d["cortisol"] = d.get("cortisol", 0.0) + 0.015
            d["oxytocin"] = 0.0
    elif kind == "drag":
        if n == 2:
            d["anger"] = d.get("anger", 0.0) + 0.02
            d["cortisol"] = d.get("cortisol", 0.0) + 0.01
        elif n >= 3:
            d["anger"] = d.get("anger", 0.0) + 0.03 + 0.01 * min(n, 10)
            d["cortisol"] = d.get("cortisol", 0.0) + 0.015
            d["oxytocin"] = 0.0
    elif kind == "pat":
        if n >= 5:
            d["dopamine"] = 0.005
            d["oxytocin"] = d.get("oxytocin", 0.0) * 0.4
    # 上一轮就被戳/拖烦了，这次更敏感
    if strain >= 0.4 and kind in ("poke", "drag"):
        d["anger"] = d.get("anger", 0.0) + 0.01
        d["cortisol"] = d.get("cortisol", 0.0) + 0.005
    return d


def _pet_touch_mood(kind, deltas):
    try:
        with open(HOUSE_EVENTS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict({"type": "self_play", "t": time.time(),
                                     "why": "touch:" + kind}, **deltas), ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _pet_touch_memory(kind, n, strain, mem_due):
    if not mem_due:
        return False
    tier = _touch_tier(kind, n, strain)
    mems = PET_TOUCH_MEM.get(kind)
    summary = None
    if mems:
        summary = mems[1] if tier >= 2 else mems[0]
    else:
        summary = "你%s，我跟他撒娇了一下。" % PET_TOUCH_WORDS.get(kind, "碰了碰我")
    try:
        import sys as _sys
        _sys.path.insert(0, r"D:\你的数据目录\video")
        import pending_store as _ps
        _ps.append({"summary": summary, "importance": 0.32, "source": "touch"})
        return True
    except Exception:  # noqa: BLE001
        return False


async def _pet_touch_line(kind, n, strain, mood):
    """她自己的反应：结合当下心情 + 被碰的频率，说一句"""
    tier = _touch_tier(kind, n, strain)
    fallback = (PET_TOUCH_FALLBACK.get(kind) or ["嗯？"])[min(tier, 3)]
    feel = ["就轻轻这一下", "连着被碰了几下", "被碰得有点烦了", "被碰得真烦了，想躲开"][tier]
    tone = ["轻轻撒个娇", "带点撒娇地躲一下", "有点不耐烦，想让他停下", "真的烦了，想躲开，语气可以有点冲"][tier]
    try:
        sys.path.insert(0, r"D:\你的数据目录\lab\memory_brain")
        import companion_brain as _b  # noqa: E402
        prompt = ("你是TA，住在你电脑里。你刚才%s。你现在的感受：%s，所以你的语气要：%s。"
                  "你的状态：心情%s、精力%.2f、烦躁%.2f、孤独%.2f。"
                  "用一句话回应他（14 字内，第一人称，语气必须贴合上面的感受）。只写这句话。"
                  % (PET_TOUCH_WORDS.get(kind, "碰了碰我"), feel, tone,
                     mood.get("emotion_level") or mood.get("emotion") or "?",
                     float(mood.get("energy") or 0.5),
                     float(mood.get("irritability") or 0.15),
                     float(mood.get("loneliness") or 0.2)))
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, lambda: _b._llm(prompt, 200))
        line = (raw or "").strip().splitlines()
        if line:
            return line[0][:28]
    except Exception:  # noqa: BLE001
        pass
    return fallback


def _pet_clients_list():
    try:
        return list(_pet_clients())
    except Exception:  # noqa: BLE001
        return []


async def _pet_say(text, audio=""):
    if not text:
        return 0
    n = 0
    for ws in _pet_clients_list():
        try:
            await ws.send_json({"type": "reply", "text": text, "audio": audio, "format": "mp3"})
            n += 1
        except Exception:  # noqa: BLE001
            continue
    return n


async def api_pet_touch(request):
    """你戳/摸/拖她：频率敏感的情绪 + 记忆 + 她自己的回应。
    body 可带 {"dry":true} —— 只演算频率/增量/台词，不写身体也不写记忆（测试用）。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    kind = str(body.get("kind") or "poke")[:12]
    if kind not in PET_TOUCH_BASE:
        kind = "poke"
    dry = bool(body.get("dry"))
    now = time.time()
    n, last, strain = _touch_note(kind, now)
    mem_due = (now - last) >= 300
    mood = {}
    try:
        timeout = aiohttp.ClientTimeout(total=4)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get("http://127.0.0.1:8005/api/state") as resp:
                mood = await resp.json(content_type=None)
    except Exception:  # noqa: BLE001
        mood = {}
    deltas = _pet_touch_deltas(kind, n, strain, mood)
    if dry:
        text = await _pet_touch_line(kind, n, strain, mood)
        return web.json_response({"ok": True, "dry": True, "kind": kind, "freq": n,
                                  "strain": round(strain, 3), "deltas": deltas, "text": text})
    _pet_touch_mood(kind, deltas)
    _pet_touch_memory(kind, n, strain, mem_due)
    text = await _pet_touch_line(kind, n, strain, mood)
    audio = ""
    try:
        audio = await tts_safe(text) or ""
    except Exception:  # noqa: BLE001
        audio = ""
    return web.json_response({"ok": True, "text": text, "audio": audio, "kind": kind,
                              "freq": n, "strain": round(strain, 3)})



async def api_pet_say(request):
    """让桌宠说一句（你在电脑前时她主动搭话用）"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    text = str(body.get("text") or "")[:120]
    n = await _pet_say(text)
    return web.json_response({"ok": bool(text), "sent": n})


DAD_FILE = os.path.join(r"D:\你的数据目录\state\persona", "dad_present.json")
DAD_LAST = {"say": 0.0, "mood": 0.0, "active": False}


async def dad_presence_loop():
    """你在用电脑 → 她知道他在 → 情绪被安抚 + 跟他说一句 + 不去操控电脑"""
    while True:
        await asyncio.sleep(20)
        try:
            timeout = aiohttp.ClientTimeout(total=6)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                r = await (await session.post("http://127.0.0.1:8010/hand",
                                              json={"action": "user"})).json()
            res = r.get("result") or {}
            active = bool(res.get("dad_active"))
            DAD_LAST["active"] = active
            if not active:
                continue
            now = time.time()
            try:
                with open(DAD_FILE, "w", encoding="utf-8") as f:
                    json.dump({"at": now}, f)
            except Exception:  # noqa: BLE001
                pass
            # 情绪：他在 → 孤独、烦都低一点，催产素高一点（每 5 分钟一次）
            if now - DAD_LAST["mood"] > 300:
                DAD_LAST["mood"] = now
                try:
                    with open(HOUSE_EVENTS_PATH, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"type": "self_play", "t": now, "why": "dad_here",
                                            "oxytocin": 0.05, "valence": 0.02,
                                            "irritability": -0.03, "cortisol": -0.02},
                                           ensure_ascii=False) + "\n")
                except Exception:  # noqa: BLE001
                    pass
            # 说话：他在电脑前，她主动搭一句（4 分钟最多一次），并且不操控电脑
            if now - DAD_LAST["say"] > 240 and COMPANION.get("on"):
                DAD_LAST["say"] = now
                mood = {}
                try:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4)) as session:
                        async with session.get("http://127.0.0.1:8005/api/state") as resp:
                            mood = await resp.json(content_type=None)
                except Exception:  # noqa: BLE001
                    mood = {}
                line = "你在忙呀，我陪你一会儿～"
                try:
                    sys.path.insert(0, r"D:\你的数据目录\lab\memory_brain")
                    import companion_brain as _b  # noqa: E402
                    prompt = ("你是TA。你正在用电脑。你现在的状态：心情%s、精力%.2f、孤独%.2f。"
                              "跟他说一句话（14 字内，第一人称，不要打扰他做事）。只写这句。"
                              % (mood.get("emotion_level") or mood.get("emotion") or "?",
                                 float(mood.get("energy") or 0.5),
                                 float(mood.get("loneliness") or 0.2)))
                    loop = asyncio.get_running_loop()
                    raw = await loop.run_in_executor(None, lambda: _b._llm(prompt, 200))
                    ll = (raw or "").strip().splitlines()
                    if ll:
                        line = ll[0][:26]
                except Exception:  # noqa: BLE001
                    pass
                await _pet_say(line)
                try:
                    print("[陪玩] 你在用电脑，她说：%s" % line, flush=True)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            try:
                print("[陪玩] user loop 出错:", exc, flush=True)
            except Exception:  # noqa: BLE001
                pass


async def api_pet_line(request):
    kind = str(request.query.get("kind") or "poke")
    if kind not in ("wake", "idle", "poke"):
        kind = "poke"
    line = await _pet_line(kind)
    return web.json_response(line)


async def her_notes_page(request):
    """她的日记本页面。"""
    resp = web.FileResponse(os.path.join(STATIC, "her-notes.html"))
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def playalong_page(request):
    """陪玩独立页（从视频通话里拆出来）。"""
    resp = web.FileResponse(os.path.join(STATIC, "playalong.html"))
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def api_her_notes_get(request):
    try:
        n = int(request.query.get("n", "100") or 100)
    except ValueError:
        n = 100
    n = max(1, min(n, 500))
    notes = []
    try:
        with open(HER_NOTES, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        notes.append(json.loads(line))
                    except Exception:  # noqa: BLE001
                        pass
    except FileNotFoundError:
        pass
    notes = notes[-n:][::-1]
    return web.json_response({"notes": notes})


async def api_her_notes_post(request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    text = str(body.get("text") or "").strip()
    if not text:
        return web.json_response({"ok": False, "error": "empty"}, status=400)
    tag = str(body.get("tag") or "manual")[:20]
    if tag not in ("diary", "playalong", "manual"):
        tag = "manual"
    entry = _note_append(text, tag=tag)
    return web.json_response({"ok": True, "entry": entry})


async def api_debug_clients(request):
    """只读：当前客户端构成（用户端 / 面板端 / 眼镜端）。"""
    return web.json_response({
        "clients": len(CLIENTS),
        "user": len(_user_clients()),
        "panel": len(PANEL_CLIENTS),
        "pico": len(PICO_CLIENTS),
        "active_sid": ACTIVE_SID or "",
    })


async def manifest_json(request):
    """PWA 清单：start_url 自动带上访问口令，装到桌面/主屏后点开就是已授权的页面。"""
    tok = _gate_token()
    data = {
        "name": "和TA视频",
        "short_name": "TA视频",
        "description": "和TA视频通话（Live2D + 摄像头 + 麦克风）",
        "start_url": "/?t=" + tok,
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#03050c",
        "theme_color": "#03050c",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    resp = web.json_response(data)
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def service_worker(request):
    """Service Worker 必须在根路径，作用域才是全站。"""
    resp = web.FileResponse(os.path.join(STATIC, "sw.js"))
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


async def index(request):
    resp = web.FileResponse(os.path.join(STATIC, "index.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


async def static_files(request):
    """静态文件也一律不缓存：改完刷新就生效。"""
    rel = request.match_info.get("tail", "")
    path = os.path.normpath(os.path.join(STATIC, rel))
    if not path.startswith(STATIC) or not os.path.isfile(path):
        raise web.HTTPNotFound()
    resp = web.FileResponse(path)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


async def api_chat(request):
    global OVERLAY_LAST_ACTIVITY
    try:
        body = await request.json()
        text = str(body.get("text") or "").strip()
        if not text:
            return web.json_response({"error": "empty"}, status=400)
        fixed = await memory_fix_reply(text)
        reply = fixed if fixed is not None else await llm_reply(OVERLAY_HISTORY, text)
        audio = await tts_safe(reply)
        if fixed is not None:
            # 纠错指令不入对话历史（详见 handle_text 里的说明）
            return web.json_response({"text": reply, "audio": audio, "format": "mp3"})
        OVERLAY_HISTORY.append({"role": "user", "content": text})
        OVERLAY_HISTORY.append({"role": "assistant", "content": reply})
        del OVERLAY_HISTORY[:-40]
        OVERLAY_LAST_ACTIVITY = time.time()
        bridge.append_video(text, reply)
        _stage_turn(text, reply)
        note_call_emotion(text)
        cmd = detect_expression_command(text)
        payload = {"text": reply, "audio": audio, "format": "mp3"}
        if cmd:
            payload["expression"] = cmd[0]
            payload["expression_sec"] = cmd[2]
            print("表情命令：%s" % cmd[1], flush=True)
        return web.json_response(payload)
    except Exception as exc:
        return web.json_response({"error": str(exc)[:300]}, status=500)


async def api_voice(request):
    global OVERLAY_LAST_ACTIVITY
    try:
        data = await request.read()
        if len(data) < 1000:
            return web.json_response({"error": "音频太短"}, status=400)
        text = await transcribe_audio(data)
        if not text:
            return web.json_response({"error": "没听清"}, status=400)
        reply = await llm_reply(OVERLAY_HISTORY, text)
        audio = await tts_safe(reply)
        OVERLAY_HISTORY.append({"role": "user", "content": text})
        OVERLAY_HISTORY.append({"role": "assistant", "content": reply})
        del OVERLAY_HISTORY[:-40]
        OVERLAY_LAST_ACTIVITY = time.time()
        bridge.append_video(text, reply)
        _stage_turn(text, reply)
        note_call_emotion(text)
        cmd = detect_expression_command(text)
        payload = {"text": reply, "audio": audio, "format": "mp3", "transcript": text}
        if cmd:
            payload["expression"] = cmd[0]
            payload["expression_sec"] = cmd[2]
            print("表情命令：%s" % cmd[1], flush=True)
        return web.json_response(payload)
    except Exception as exc:
        return web.json_response({"error": str(exc)[:300]}, status=500)


async def api_proactive(request):
    return web.json_response(LAST_PROACTIVE)


async def api_history(request):
    """调试：看当前会话的上下文有没有统一（视频 + 陪玩）。"""
    sid = ACTIVE_SID or "companion"
    hist = CALL_HISTORIES.get(sid) or []
    return web.json_response({
        "sid": sid,
        "turns": len(hist),
        "tail": [{"role": h.get("role"), "text": str(h.get("content"))[:80]} for h in hist[-6:]],
    })


async def api_companion_status(request):
    return web.json_response(
        {
            "history": len(OVERLAY_HISTORY),
            "idle": round(time.time() - OVERLAY_LAST_ACTIVITY, 1) if OVERLAY_LAST_ACTIVITY else None,
            "pending": len(bridge.load_pending()),
        }
    )


async def api_companion_flush(request):
    """把陪玩/视频还没满 3 轮的对话立刻入队。

    默认只 flush，不抹掉 OVERLAY_HISTORY——关掉面板再打开还能接上刚才的话；
    传 {"clear": true} 才连短期上下文一起清掉（退出/换话题时用）。
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    clear = bool((body or {}).get("clear"))
    if clear:
        _remember_companion(force=True)
    else:
        _flush_staged("companion")
    return web.json_response(
        {
            "ok": True,
            "cleared": clear,
            "pending": len(bridge.load_pending()),
            "history": len(OVERLAY_HISTORY),
            "idle": round(time.time() - OVERLAY_LAST_ACTIVITY, 1) if OVERLAY_LAST_ACTIVITY else None,
        }
    )


async def screen_state(request):
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(SCREEN_API + "/api/state") as resp:
                return web.json_response(await resp.json(content_type=None))
    except Exception as exc:
        return web.json_response({"watching": False, "error": str(exc)[:120]})


async def screen_watch(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(SCREEN_API + "/api/watch", json=body) as resp:
                return web.json_response(await resp.json(content_type=None))
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)[:120]})


async def _pico_stat_loop():
    """每 60 秒打一次眼镜帧率：判断"省流"是否生效（改动前约 24 帧/分）。"""
    while True:
        await asyncio.sleep(60)
        try:
            now = time.time()
            span = max(1.0, now - PICO_STAT["at"])
            n = PICO_STAT["frames"]
            r = PICO_STAT["reused"]
            PICO_STAT["frames"] = 0
            PICO_STAT["reused"] = 0
            PICO_STAT["at"] = now
            if n:
                print("[帧率] 过去 %.0f 秒收到 %d 帧（复用 %d），约 %.1f 帧/分"
                      % (span, n, r, n / span * 60.0), flush=True)
        except Exception:  # noqa: BLE001
            pass


TTS_WARM_PHRASES = ("在呢", "嗯呐", "好呀", "我在呢", "马上来", "怎么啦", "晚安啦", "哈哈好")


async def _tts_warm():
    """预合成几句最常用的话进缓存：命中就 0 毫秒出声，不占多少内存。"""
    for line in TTS_WARM_PHRASES:
        try:
            await tts_base64(line)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0)


async def _startup(app):
    app["tts_warm_task"] = asyncio.create_task(_tts_warm())
    app["pico_stat_task"] = asyncio.create_task(_pico_stat_loop())
    app["proactive_task"] = asyncio.create_task(proactive_loop())
    asyncio.create_task(diary_loop())
    asyncio.create_task(prewarm_pet_lines())
    app["companion_memory_task"] = asyncio.create_task(companion_memory_loop())
    app["screen_companion_task"] = asyncio.create_task(screen_companion_loop())
    app["dad_loop_task"] = asyncio.create_task(dad_presence_loop())
    # 语音模型已经在 main() 里加载过；再跑一次静音，把首次推理的分配摊掉
    asyncio.get_running_loop().run_in_executor(None, _asr_warmup)


async def prewarm_pet_lines():
    """启动时温和地把桌宠台词池合成进 TTS 缓存（只收小悦音色，限流就下轮补）。"""
    texts = sorted({t for pool in PET_LINE_POOLS.values() for t in pool})
    pending = list(texts)
    for _round in range(6):
        if not pending:
            break
        for text in list(pending):
            try:
                await tts_base64(text)
            except Exception:  # noqa: BLE001
                pass
            key = (text, CFG.get("voice", "zh-CN-XiaoyiNeural"),
                   CFG.get("rate", "+4%"), CFG.get("pitch", "+15Hz"))
            if key in _TTS_CACHE:
                pending.remove(text)
            await asyncio.sleep(1.0)
        if pending:
            print("[TTS预热] 第 %d 轮后剩 %d 句未入缓存，120 秒后补" % (_round + 1, len(pending)), flush=True)
            await asyncio.sleep(120)
    print("[TTS预热] 桌宠台词池 %d/%d 句已入缓存" % (len(texts) - len(pending), len(texts)), flush=True)


async def _cleanup(app):
    for key in ("tts_warm_task", "pico_stat_task", "proactive_task",
                "companion_memory_task", "screen_companion_task"):
        task = app.get(key)
        if task:
            task.cancel()
    try:
        _remember_companion(force=True)
    except Exception:
        pass


async def api_she_state(request):
    """她此刻的状态向量（身体+关系+自我+记忆），页面/桌宠共用。"""
    try:
        with open(r"D:\你的数据目录\state\she_state.json", encoding="utf-8") as f:
            return web.json_response(json.load(f))
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "she_state 未生成"}, status=404)


async def api_mood(request):
    """把生命状态服务的情绪数据转给页面用（手机打开视频页也能拿到表情）。

    视频页在局域网里访问时，浏览器拿不到 127.0.0.1:8005，所以给一个同源代理。
    """
    try:
        timeout = aiohttp.ClientTimeout(total=4)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get("http://127.0.0.1:8005/api/state") as resp:
                data = await resp.json(content_type=None)

        # 把"通话内"的即时情绪叠上去，并按同一套规则重算表情
        _decay_call_affect(time.time())
        merged = dict(data)
        for key in ("dopamine", "oxytocin", "cortisol", "serotonin", "noradrenaline"):
            try:
                base = float(merged.get(key, 0.0))
            except (TypeError, ValueError):
                base = 0.0
            merged[key] = round(max(0.0, min(1.0, base + CALL_AFFECT[key])), 3)
        # 先按"刚刚发生的变化"给反应（被夸、被凶这种），
        # 变化不够大再回到绝对情绪判定
        react = call_reaction()
        if react:
            merged["expression"], merged["expression_reason"] = react
        else:
            try:
                lv = _lifeviz()
                expr, why = lv.pick_expression(merged)
                merged["expression"] = expr
                merged["expression_reason"] = why
            except Exception:  # noqa: BLE001
                pass
        try:
            merged["energy"] = round(_lifeviz()._energy(merged), 3)
        except Exception:  # noqa: BLE001
            pass
        merged["call_affect"] = {k: round(v, 3) for k, v in CALL_AFFECT.items() if k != "ts"}
        return web.json_response(merged)
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"error": str(exc)[:200]}, status=503)


def _ssl_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(TLS_CERT, TLS_KEY)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


async def cert_cer(request):
    """给 iPhone 下载的根证书（DER）。"""
    path = os.path.join(TLS_DIR, "ca.cer")
    if not os.path.exists(path):
        return web.Response(status=404, text="没有证书")
    with open(path, "rb") as f:
        data = f.read()
    return web.Response(
        body=data,
        content_type="application/x-x509-ca-cert",
        headers={"Content-Disposition": 'inline; filename="companion-home-ca.cer"'},
    )


async def cert_mobileconfig(request):
    """给 iPhone 一键安装的描述文件。"""
    path = os.path.join(TLS_DIR, "ca.mobileconfig")
    if not os.path.exists(path):
        return web.Response(status=404, text="没有描述文件")
    with open(path, "rb") as f:
        data = f.read()
    return web.Response(
        body=data,
        content_type="application/x-apple-aspen-config",
        headers={
            "Content-Disposition":
                'inline; filename="companion-home-ca.mobileconfig"',
            "Cache-Control": "no-store",
        },
    )


async def api_settings(request):
    """前端要用的节奏参数：抓帧间隔跟着服务端配置走，不用两边各写死一个数。"""
    mode = str(CFG.get("camera_mode", "fixed")).lower()
    if mode not in ("fixed", "adaptive"):
        mode = "fixed"
    return web.json_response({
        "vision_interval_ms": int(CFG.get("vision_interval_ms", 4500)),
        "vision_max_tokens": int(CFG.get("vision_max_tokens", 64)),
        # adaptive：画面没变就不传，开口时强制看一眼（省 token，画面还更新鲜）
        "camera_mode": mode,
        "camera_interval_ms": int(CFG.get("camera_interval_ms", 15000)),
        "camera_diff_threshold": float(CFG.get("camera_diff_threshold", 0.045)),
    })


async def api_camera_source_state(request):
    return web.json_response({"source": camera_source()})


async def api_pico_look(request):
    """Pico 眼镜第一视角：只接受最新帧，旧请求晚回来不能覆盖新描述。"""
    if camera_source() != "pico":
        return web.json_response({"caption": "", "stale": True, "disabled": "pc"})
    try:
        raw = await request.read()
        if len(raw) < 1200:
            return web.json_response({"error": "画面太小"}, status=400)
        PICO_STAT["frames"] += 1
        try:
            frame_ts = float(request.headers.get("X-Frame-Ts") or time.time())
        except (TypeError, ValueError):
            frame_ts = time.time()
        now = time.time()
        # 防御：测试/异常请求可能带未来时间戳，不能让它把真机帧永久判旧
        if frame_ts > now + 120:
            print("PICO frame_ts 在未来，已按当前时间修正: %.0f -> %.0f" % (frame_ts, now), flush=True)
            frame_ts = now
        if float(PICO_VISION.get("frame_ts") or 0.0) > now + 120:
            print("PICO_VISION 时间戳在未来，已重置", flush=True)
            PICO_VISION["text"] = ""
            PICO_VISION["ts"] = 0.0
            PICO_VISION["frame_ts"] = 0.0
        PICO_LAST_FRAME["data"] = raw
        PICO_LAST_FRAME["ts"] = now
        PICO_LAST_FRAME["frame_ts"] = frame_ts
        if VISION_ACCURATE_LOCK:
            return web.json_response({
                "caption": PICO_VISION["text"],
                "frame_ts": float(PICO_VISION.get("frame_ts") or 0.0),
                "stale": True,
                "accurate": True,
            })
        if frame_ts + 0.001 < float(PICO_VISION.get("frame_ts") or 0.0):
            return web.json_response({
                "caption": PICO_VISION["text"],
                "frame_ts": float(PICO_VISION.get("frame_ts") or 0.0),
                "stale": True,
            })
        # 2026-11-16：画面几乎没变就复用上一句描述（省一次 4 秒的视觉模型调用）
        thumb = await asyncio.to_thread(frame_thumb, raw)
        if (thumb is not None and frame_similar(FRAME_DEDUP["thumb"], thumb)
                and PICO_VISION["text"]
                and abs(float(PICO_VISION.get("frame_ts") or 0.0)
                        - float(FRAME_DEDUP.get("frame_ts") or 0.0)) < 0.001
                and (time.time() - FRAME_DEDUP["at"]) <= 20.0):
            PICO_VISION["ts"] = time.time()
            PICO_VISION["frame_ts"] = max(frame_ts, float(PICO_VISION.get("frame_ts") or 0.0))
            FRAME_DEDUP["frame_ts"] = PICO_VISION["frame_ts"]
            REUSE_STAT["n"] += 1
            REUSE_STAT["saved"] += 1
            PICO_STAT["reused"] += 1
            if REUSE_STAT["n"] == 1 or REUSE_STAT["n"] % 30 == 0:
                print("[识图] 画面没变，复用上一句描述（累计省 %d 次视觉调用）"
                      % REUSE_STAT["saved"], flush=True)
            return web.json_response({
                "caption": PICO_VISION["text"],
                "frame_ts": PICO_VISION["frame_ts"],
                "stale": False,
                "reused": True,
                "want_fresh": _take_want_fresh(),
            })
        _t_vis = time.time()
        caption = await describe_frame(
            raw,
            prompt="直接回答：这张照片里有什么？只列画面内容，一句中文，不要分析、不要复述题目。",
            max_tokens=210,
            clean=False,
        )
        caption = (caption or "").strip()
        # 去掉模型的自言自语/复述要求，只留画面描述
        import re as _re
        caption = _re.sub(r"^(整理|描述|画面|回答|总结|简答|一句话)[：:]\s*", "", caption)
        bad = ("更简洁", "一句话", "一句中文", "只列", "不要分析", "不要复述",
               "画面内容", "用户", "要求", "首先", "我需要", "思考",
               "复述", "包括谁", "在做什么", "什么颜色", "什么环境", "回答")
        parts = [x.strip() for x in caption.replace("\n", "。").split("。") if x.strip()]
        keep = [x for x in parts if not any(b in x for b in bad)]
        caption = "。".join(keep[:3]) if keep else caption
        caption = caption[:220].strip()
        stale = False
        if caption:
            # 只有帧时间不旧于当前记录，才允许写入
            if frame_ts + 0.001 < float(PICO_VISION.get("frame_ts") or 0.0):
                stale = True
            else:
                PICO_VISION["text"] = caption
                PICO_VISION["ts"] = time.time()
                PICO_VISION["frame_ts"] = frame_ts
                FRAME_DEDUP["thumb"] = thumb
                FRAME_DEDUP["at"] = time.time()
                FRAME_DEDUP["frame_ts"] = frame_ts
                print("[耗时] 识图 %.2fs" % (time.time() - _t_vis), flush=True)
        return web.json_response({"caption": caption, "frame_ts": frame_ts, "stale": stale,
                                 "want_fresh": _take_want_fresh()})
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"error": str(exc)[:200]}, status=500)




async def api_panel_frame(request):
    """Web 面板把带 alpha 的 canvas 帧 POST 过来。"""
    try:
        data = await request.read()
        if not data:
            return web.json_response({"ok": False}, status=400)
        ALPHA_FRAME["data"] = data
        ALPHA_FRAME["at"] = time.time()
        return web.json_response({"ok": True, "size": len(data)})
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"ok": False, "error": str(exc)[:120]}, status=500)


async def api_panel_frame_png(request):
    data = ALPHA_FRAME["data"]
    if not data:
        return web.Response(status=503, text="no frame")
    return web.Response(body=data, content_type="image/png",
                        headers={"Cache-Control": "no-store"})



async def api_live2d_arch(request):
    """Web 运行时把 drawable 顺序/遮罩导出来，给 Unity 原生重排用。"""
    try:
        body = await request.read()
        path = r"D:\你的数据目录\lab\pico\live2d_arch.json"
        with open(path, "wb") as f:
            f.write(body)
        return web.json_response({"ok": True, "size": len(body)})
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"ok": False, "error": str(exc)[:200]}, status=500)

async def api_look(request):
    """通话里"让她看你一眼"：收一帧电脑摄像头画面，存成网页会话上下文。"""
    if camera_source() != "pc":
        return web.json_response({"caption": "", "disabled": "pico", "reason": "带TA出门中"})
    try:
        raw = await request.read()
        if len(raw) < 1200:
            return web.json_response({"error": "画面太小"}, status=400)
        WEB_LAST_FRAME["data"] = raw
        WEB_LAST_FRAME["ts"] = time.time()
        if VISION_ACCURATE_LOCK:
            return web.json_response({"caption": "", "locked": True, "accurate": True})
        caption = clean_vision_caption(await describe_frame(raw))
        if caption:
            VISION_NOTE["text"] = caption
            VISION_NOTE["ts"] = time.time()
            note_vision_food(caption)      # 电脑镜头里举着吃的 = 喂她
        return web.json_response({"caption": caption})
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"error": str(exc)[:200]}, status=500)


def main():
    try:
        _load_asr()
    except Exception as exc:
        print("Whisper 预加载失败，首次识别时重试：", exc)
    app = web.Application(client_max_size=8 * 1024 * 1024, middlewares=[gate_middleware])
    app.router.add_get("/playalong", playalong_page)
    app.router.add_get("/her-notes", her_notes_page)
    app.router.add_get("/api/pet-line", api_pet_line)
    app.router.add_post("/api/pet-touch", api_pet_touch)
    app.router.add_post("/api/pet-say", api_pet_say)
    app.router.add_get("/api/her-notes", api_her_notes_get)
    app.router.add_post("/api/her-notes", api_her_notes_post)
    app.router.add_get("/api/debug/clients", api_debug_clients)
    app.router.add_get("/manifest.json", manifest_json)
    app.router.add_get("/sw.js", service_worker)
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_post("/api/voice_enroll/start", api_voice_enroll_start)
    app.router.add_post("/api/voice_enroll/cancel", api_voice_enroll_cancel)
    app.router.add_post("/api/chat", api_chat)
    app.router.add_post("/api/voice", api_voice)
    app.router.add_get("/api/proactive", api_proactive)
    app.router.add_get("/api/history", api_history)
    app.router.add_get("/api/companion/status", api_companion_status)
    app.router.add_post("/api/companion/flush", api_companion_flush)
    app.router.add_get("/api/screen/state", screen_state)
    app.router.add_post("/api/screen/watch", screen_watch)
    app.router.add_get("/api/mood", api_mood)
    app.router.add_get("/api/she-state", api_she_state)
    app.router.add_get("/api/settings", api_settings)
    app.router.add_post("/api/look", api_look)
    app.router.add_get("/api/camera_source", api_camera_source_state)
    app.router.add_post("/api/live2d_arch", api_live2d_arch)
    app.router.add_post("/panel/frame", api_panel_frame)
    app.router.add_get("/panel/frame.png", api_panel_frame_png)
    app.router.add_get("/api/pico_probe", api_pico_probe)
    app.router.add_post("/api/pico_look", api_pico_look)
    app.router.add_post("/api/presence", api_presence)
    app.router.add_post("/api/jslog", api_jslog)
    app.router.add_post("/api/companion/toggle", api_companion_toggle)
    app.router.add_get("/api/companion/state", api_companion_state)
    app.router.add_post("/api/companion/panic", api_companion_panic)
    app.router.add_get("/cert/ca.cer", cert_cer)
    app.router.add_get("/cert/ca.mobileconfig", cert_mobileconfig)
    app.on_startup.append(_startup)
    app.on_cleanup.append(_cleanup)
    app.router.add_get("/static/{tail:.*}", static_files)
    print(f"TA视频通话: http://{HOST}:{PORT}")
    if TLS_READY:
        print(f"TA视频通话(HTTPS): https://{HOST}:{SSL_PORT}")
    try:
        asyncio.run(_serve(app))
    except KeyboardInterrupt:
        pass


async def _serve(app):
    """同一个 app 同时挂在 http 和 https 两个端口上。

    手机（尤其 iPhone）只有在 https 页面里才肯给麦克风，
    所以 8003 给电脑用 http，8004 给手机用 https。
    """
    runner = web.AppRunner(app)
    await runner.setup()
    sites = [web.TCPSite(runner, HOST, PORT)]
    if TLS_READY:
        sites.append(web.TCPSite(runner, HOST, SSL_PORT, ssl_context=_ssl_context()))
    for site in sites:
        await site.start()
    stop = asyncio.Event()
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except (NotImplementedError, RuntimeError):
                pass
    except Exception:  # noqa: BLE001
        pass
    try:
        await stop.wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    main()


