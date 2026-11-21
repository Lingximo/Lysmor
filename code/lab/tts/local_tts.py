"""本地语音合成（piper），全项目共用。

    from local_tts import synth_pcm, synth_ogg, synth_mp3
    pcm = synth_pcm("TA，我在呢")        # 16k 单声道 PCM16 bytes
    ogg = synth_ogg("...")                 # ogg/opus，给 AIUI 的 AudioPlayer

设计：
  · piper 模型只加载一次（约 3 秒），之后每句约 0.1 秒
  · 任何一步失败返回 None，调用方自己退回 edge-tts
  · 不写 state、不开端口，纯计算
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave

MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "piper",
                     "zh_CN-huayan-medium.onnx")

_voice = None
_tried = False


def _get_voice():
    global _voice, _tried
    if _tried:
        return _voice
    _tried = True
    try:
        from piper import PiperVoice
        if os.path.exists(MODEL):
            _voice = PiperVoice.load(MODEL)
            print("[本地TTS] piper 已加载")
        else:
            print("[本地TTS] 模型不存在：", MODEL)
    except Exception as exc:  # noqa: BLE001
        print("[本地TTS] 加载失败:", exc)
        _voice = None
    return _voice


def available() -> bool:
    return _get_voice() is not None and shutil.which("ffmpeg") is not None


def _wav(text: str) -> str | None:
    voice = _get_voice()
    if not voice:
        return None
    try:
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        with wave.open(path, "wb") as wf:
            voice.synthesize_wav(text, wf)
        return path
    except Exception as exc:  # noqa: BLE001
        print("[本地TTS] 合成失败:", exc)
        return None


def synth_pcm(text: str, sr: int = 16000) -> bytes | None:
    """返回 16k 单声道 PCM16 bytes。"""
    path = _wav(text)
    if not path:
        return None
    try:
        fd, out = tempfile.mkstemp(suffix=".pcm")
        os.close(fd)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                        "-ar", str(sr), "-ac", "1", "-f", "s16le", out],
                       check=True, timeout=60)
        with open(out, "rb") as f:
            data = f.read()
        os.unlink(out)
        return data or None
    except Exception as exc:  # noqa: BLE001
        print("[本地TTS] 转 PCM 失败:", exc)
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def synth_ogg(text: str, bitrate: str = "24k") -> bytes | None:
    """返回 ogg/opus bytes（AIUI AudioPlayer 用）。"""
    path = _wav(text)
    if not path:
        return None
    try:
        fd, out = tempfile.mkstemp(suffix=".ogg")
        os.close(fd)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                        "-c:a", "libopus", "-b:a", bitrate, "-ar", "24000",
                        "-ac", "1", "-f", "ogg", out],
                       check=True, timeout=60)
        with open(out, "rb") as f:
            data = f.read()
        os.unlink(out)
        return data or None
    except Exception as exc:  # noqa: BLE001
        print("[本地TTS] 转 OGG 失败:", exc)
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def synth_mp3(text: str) -> bytes | None:
    path = _wav(text)
    if not path:
        return None
    try:
        fd, out = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                        "-c:a", "libmp3lame", "-q:a", "4", out],
                       check=True, timeout=60)
        with open(out, "rb") as f:
            data = f.read()
        os.unlink(out)
        return data or None
    except Exception as exc:  # noqa: BLE001
        print("[本地TTS] 转 MP3 失败:", exc)
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


if __name__ == "__main__":
    import time

    t0 = time.time()
    pcm = synth_pcm("TA，我在呢，今天过得怎么样")
    print("PCM %s 字节，用时 %.2fs" % (len(pcm or b""), time.time() - t0))


# ---------------- edge-tts：音色更年轻，用作首选 ----------------
EDGE_VOICE = "zh-CN-XiaoyiNeural"   # 少女音
EDGE_RATE = "+4%"                  # 视频里那个声音（2026-11-10 最终）
EDGE_PITCH = "+15Hz"                # 视频里那个声音（2026-11-10 最终）


async def edge_mp3(text: str, voice: str = EDGE_VOICE,
                   rate: str = EDGE_RATE, pitch: str = EDGE_PITCH) -> bytes | None:
    """edge 合成 mp3；失败返回 None（调用方退回本地 piper）。"""
    try:
        import edge_tts
        com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        buf = bytearray()
        async for chunk in com.stream():
            if chunk.get("type") == "audio":
                buf.extend(chunk["data"])
        return bytes(buf) or None
    except Exception as exc:  # noqa: BLE001
        print("[本地TTS] edge 失败:", exc)
        return None


async def edge_pcm16k(text: str, voice: str = EDGE_VOICE,
                      rate: str = EDGE_RATE, pitch: str = EDGE_PITCH) -> bytes | None:
    mp3 = await edge_mp3(text, voice, rate, pitch)
    if not mp3:
        return None
    try:
        import tempfile
        fd, src = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        with open(src, "wb") as f:
            f.write(mp3)
        fd, dst = tempfile.mkstemp(suffix=".pcm")
        os.close(fd)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                        "-ar", "16000", "-ac", "1", "-f", "s16le", dst],
                       check=True, timeout=60)
        with open(dst, "rb") as f:
            data = f.read()
        os.unlink(src)
        os.unlink(dst)
        return data or None
    except Exception as exc:  # noqa: BLE001
        print("[本地TTS] edge 转 PCM 失败:", exc)
        return None


def synth_pcm_fast(text: str) -> bytes | None:
    """本地 piper，语速 +15%（无法改音色时的兜底）。"""
    voice = _get_voice()
    if not voice:
        return None
    try:
        from piper import SynthesisConfig
        cfg = SynthesisConfig(length_scale=0.87)
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        with wave.open(path, "wb") as wf:
            voice.synthesize_wav(text, wf, syn_config=cfg)
        fd, out = tempfile.mkstemp(suffix=".pcm")
        os.close(fd)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                        "-ar", "16000", "-ac", "1", "-f", "s16le", out],
                       check=True, timeout=60)
        with open(out, "rb") as f:
            data = f.read()
        os.unlink(path)
        os.unlink(out)
        return data or None
    except Exception as exc:  # noqa: BLE001
        print("[本地TTS] piper 加速合成失败:", exc)
        return synth_pcm(text)

async def edge_ogg(text: str, voice: str = EDGE_VOICE,
                   rate: str = EDGE_RATE, pitch: str = EDGE_PITCH) -> bytes | None:
    """edge 合成 ogg/opus（AIUI AudioPlayer 用）。"""
    mp3 = await edge_mp3(text, voice, rate, pitch)
    if not mp3:
        return None
    try:
        import tempfile
        fd, src = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        with open(src, "wb") as f:
            f.write(mp3)
        fd, dst = tempfile.mkstemp(suffix=".ogg")
        os.close(fd)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                        "-c:a", "libopus", "-b:a", "24k", "-ar", "24000",
                        "-ac", "1", "-f", "ogg", dst], check=True, timeout=60)
        with open(dst, "rb") as f:
            data = f.read()
        os.unlink(src)
        os.unlink(dst)
        return data or None
    except Exception as exc:  # noqa: BLE001
        print("[本地TTS] edge 转 OGG 失败:", exc)
        return None

