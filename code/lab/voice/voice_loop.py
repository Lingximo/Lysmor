"""免手对话：听见你 → 认关键词 → 交给她（deepseek-flash）→ 念出来。

不用打字、不用点网页。链路：

    麦克风 → VAD 静音切句 → faster-whisper 转写 → 关键词判断（"TA"）
        → 调她的正式对话接口（她自己的模型生成回复）
        → edge-tts 合成 → 喇叭播放

红线（§74.2）：**只有"听见"和"发声"是本地模型；回复正文永远来自她（deepseek-flash）**。

用法：
    python voice_loop.py --file a.wav        # 处理一个音频文件（测试用）
    python voice_loop.py --mic               # 麦克风连续听
    python voice_loop.py --mic --speak       # 连回复也念出来
    python voice_loop.py --mic --no-wake     # 不要求喊"TA"，听到就说

隔离：不开端口、不写她的 state/记忆；只调用她已有的 HTTP 接口。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(LAB, "vision", "pylibs"))
sys.path.insert(0, os.path.join(LAB, "asr", "pylibs"))
sys.path.insert(0, os.path.join(LAB, "asr"))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

HER_API = "http://127.0.0.1:8001/api/send"
WAKE_WORDS = ("TA", "TA", "伴侣", "TATA", "在吗", "小家伙")
SR = 16000


# ---------------- 听 ----------------
def load_wav(path: str):
    import soundfile as sf
    pcm, sr = sf.read(path, dtype="float32", always_2d=False)
    if getattr(pcm, "ndim", 1) > 1:
        pcm = pcm.mean(axis=1)
    if sr != SR:
        import librosa
        pcm = librosa.resample(pcm, orig_sr=sr, target_sr=SR)
    return pcm.astype(np.float32)


def record(seconds: float, device=None):
    import sounddevice as sd
    pcm = sd.rec(int(seconds * SR), samplerate=SR, channels=1, dtype="float32", device=device)
    sd.wait()
    return pcm.ravel()


def vad_split(pcm, threshold=0.5, min_speech=0.4):
    """用 silero-vad 把长音频切成"有人在说话"的段。"""
    import onnxruntime as ort
    model = os.path.join(HERE, "models", "silero_vad.onnx")
    if not os.path.isfile(model):
        return [(pcm, 0.0, len(pcm) / SR)]
    s = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
    state = np.zeros((2, 1, 128), dtype=np.float32)
    probs = []
    n = 512
    for i in range(0, len(pcm) - n, n):
        feed = {}
        for meta in s.get_inputs():
            if "state" in meta.name:
                feed[meta.name] = state
            elif meta.name == "sr":
                feed[meta.name] = np.array(SR, dtype=np.int64)
            else:
                feed[meta.name] = pcm[i:i + n].reshape(1, -1).astype(np.float32)
        out = s.run(None, feed)
        probs.append(float(np.array(out[0]).ravel()[0]))
        if len(out) > 1:
            state = np.array(out[1], dtype=np.float32)
    probs = np.array(probs)
    if probs.size == 0:
        return [(pcm, 0.0, len(pcm) / SR)]
    on = probs > threshold
    segs, start = [], None
    for i, flag in enumerate(on):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            segs.append((start, i))
            start = None
    if start is not None:
        segs.append((start, len(on)))
    merged = []
    for a, b in segs:
        if merged and (a - merged[-1][1]) * n / SR < 0.5:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    out = []
    for a, b in merged:
        if (b - a) * n / SR >= min_speech:
            out.append((pcm[a * n:b * n], a * n / SR, b * n / SR))
    return out or [(pcm, 0.0, len(pcm) / SR)]


# ---------------- 说 ----------------
def speak(text: str, voice: str = "zh-CN-XiaoxiaoNeural"):
    """用 edge-tts 合成并播放。她自己的声音配置以后从她的配置读。"""
    import asyncio
    import tempfile
    sys.path.insert(0, r"D:\你的数据目录\lab\tts")
    import local_tts
    if local_tts.available():
        mp3 = local_tts.synth_mp3(text)
        if mp3:
            with open(tmp, "wb") as f:
                f.write(mp3)
            return
    import edge_tts
    import sounddevice as sd
    import soundfile as sf

    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
    try:
        asyncio.run(edge_tts.Communicate(text, voice).save(tmp))
        import subprocess
        wav = tmp + ".wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp,
                        "-ar", str(SR), "-ac", "1", wav], check=True)
        pcm, sr = sf.read(wav, dtype="float32")
        sd.play(pcm, sr)
        sd.wait()
    finally:
        for p in (tmp, tmp + ".wav"):
            try:
                os.unlink(p)
            except OSError:
                pass


# ---------------- 她的回复 ----------------
def ask_her(text: str, timeout: float = 120.0) -> str:
    """走她正常的对话接口；回复正文只由她的模型生成。"""
    import requests
    out = ""
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
            if ev.get("done"):
                break
    return out.strip()


def has_wake(text: str) -> bool:
    return any(w in (text or "") for w in WAKE_WORDS)


# ---------------- 主流程 ----------------
def handle(pcm, *, require_wake=True, speak_reply=False, ears=None):
    import asr_lib
    ears_model = asr_lib.Ears()
    text = ears_model.transcribe(pcm)
    if not text:
        return {"heard": "", "woke": False, "reply": ""}
    woke = (not require_wake) or has_wake(text)
    result = {"heard": text, "woke": woke, "reply": ""}
    if woke:
        result["reply"] = ask_her(text)
        if speak_reply and result["reply"]:
            speak(result["reply"])
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="")
    ap.add_argument("--mic", action="store_true")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--speak", action="store_true")
    ap.add_argument("--no-wake", action="store_true")
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--window", type=float, default=20.0)
    args = ap.parse_args()

    require_wake = not args.no_wake
    if args.file:
        pcm = load_wav(args.file)
        for seg, a, b in vad_split(pcm):
            print("[%0.1f~%0.1f] " % (a, b), end="")
            print(json.dumps(handle(seg, require_wake=require_wake,
                                    speak_reply=args.speak), ensure_ascii=False))
        return 0

    if args.mic:
        window_until = 0.0
        print("在听…（说“TA”叫醒她；之后 %d 秒内不用再喊。Ctrl+C 退出）" % args.window)
        try:
            while True:
                pcm = record(args.seconds, args.device)
                for seg, a, b in vad_split(pcm):
                    warming = time.time() < window_until
                    r = handle(seg, require_wake=(require_wake and not warming),
                               speak_reply=args.speak)
                    if r["heard"]:
                        print(json.dumps(r, ensure_ascii=False))
                    if r["woke"]:
                        window_until = time.time() + args.window
        except KeyboardInterrupt:
            print("\n停了")
        return 0

    print("用法：--file a.wav 或 --mic")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
