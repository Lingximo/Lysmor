"""TA耳朵：SenseVoice（sherpa-onnx）为主，faster-whisper 兜底。

    ears = Ears()
    text = ears.transcribe(pcm_float32_16k)
    text, ok = ears.transcribe_scored(pcm)

为什么换：
    whisper large-v3-turbo 对中文人名经常听岔，而且噪声上会"编内容"；
    SenseVoice 中文专用，40 秒音频 0.9 秒出结果（约 44 倍实时），
    加载 0.8 秒（whisper 要 3 秒以上）。

要点：
  · 模型吃 float32（-1~1），16k 单声道
  · 噪声上 SenseVoice 会输出韩文"그."这类碎片 → 用"必须含中文"来挡
  · 旧 whisper 仅在 SenseVoice 不可用时兜底
"""
from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SV_DIR = os.path.join(HERE, "sensevoice")
SV_MODEL = os.path.join(SV_DIR, "model.int8.onnx")
SV_TOKENS = os.path.join(SV_DIR, "tokens.txt")

WHISPER_DIR = os.path.join(HERE, "models")
PYLIBS = os.path.join(HERE, "pylibs")

if os.path.isdir(PYLIBS) and PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)

CUDA_HINT = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Programs", "Ollama", "lib", "ollama", "cuda_v12",
)

# 热词一律不用（2026-11-08）：会让静音段复读出"TA、TA"
HOTWORDS = ""
NAME_FIX = {}   # 同音替换已关闭（2026-11-09）


def fix_names(text: str) -> str:
    if not text or not NAME_FIX:
        return text
    out = text
    for wrong, right in NAME_FIX.items():
        out = out.replace(wrong, right)
    return out


def _prepare_path() -> None:
    if os.path.isdir(CUDA_HINT) and CUDA_HINT not in os.environ.get("PATH", ""):
        os.environ["PATH"] = CUDA_HINT + os.pathsep + os.environ.get("PATH", "")


def _cjk_count(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


class Ears:
    def __init__(self, device: str | None = None):
        _prepare_path()
        self.backend = None
        self.sv = None
        self.whisper = None

        if os.path.exists(SV_MODEL) and os.path.exists(SV_TOKENS):
            try:
                import sherpa_onnx

                self.sv = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=SV_MODEL, tokens=SV_TOKENS, num_threads=4, use_itn=True,
                )
                self.backend = "sensevoice"
                print("[ASR] SenseVoice 已加载")
            except Exception as exc:  # noqa: BLE001
                print("[ASR] SenseVoice 加载失败:", exc)

        if self.sv is None:
            self._load_whisper(device)

    def _load_whisper(self, device: str | None) -> None:
        from faster_whisper import WhisperModel

        order = [device] if device else ["cuda", "cpu"]
        for dev in order:
            try:
                self.whisper = WhisperModel(
                    WHISPER_DIR, device=dev,
                    compute_type="float16" if dev == "cuda" else "int8")
                self.backend = "whisper-%s" % dev
                print("[ASR] whisper 兜底已加载（%s）" % dev)
                return
            except Exception as exc:  # noqa: BLE001
                print("[ASR] whisper %s 加载失败：%s" % (dev, exc))
        raise RuntimeError("没有可用的语音模型")

    # ---------------- 识别 ----------------

    def transcribe(self, pcm) -> str:
        wave = self._as_float(pcm)
        if wave is None:
            return ""
        if self.sv is not None:
            try:
                s = self.sv.create_stream()
                s.accept_waveform(16000, wave)
                self.sv.decode_stream(s)
                return fix_names((s.result.text or "").strip())
            except Exception as exc:  # noqa: BLE001
                print("[ASR] SenseVoice 识别失败，改用 whisper:", exc)
                if self.whisper is None:
                    self._load_whisper(None)
        segs, _info = self.whisper.transcribe(
            wave, language="zh", beam_size=5, vad_filter=True)
        return fix_names("".join(seg.text for seg in segs).strip())

    def transcribe_scored(self, pcm):
        """返回 (文本, 是否可信)。

        SenseVoice 没有直接概率，用"必须像中文"来挡噪声：
        少于 2 个汉字 → 不可信（噪声常出现"그."这种碎片）。
        """
        text = self.transcribe(pcm)
        if not text:
            return "", False
        if self.sv is not None:
            return text, _cjk_count(text) >= 2
        return text, True

    def transcribe_file(self, path: str) -> str:
        import wave

        with wave.open(path) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        return self.transcribe(pcm)

    @staticmethod
    def _as_float(pcm):
        if pcm is None:
            return None
        if isinstance(pcm, (bytes, bytearray)):
            if len(pcm) < 2:
                return None
            arr = np.frombuffer(bytes(pcm), dtype="<i2").astype(np.float32) / 32768.0
        else:
            arr = np.asarray(pcm)
            if arr.dtype != np.float32:
                arr = arr.astype(np.float32)
            if arr.size and float(np.abs(arr).max()) > 1.5:
                arr = arr / 32768.0
        if arr.size < 1600:
            return None
        return np.ascontiguousarray(arr)


if __name__ == "__main__":
    import time

    ears = Ears()
    t0 = time.time()
    print(ears.transcribe_file(r"D:\你的数据目录\lab\voice\samples\sample01.wav")[:80])
    print("用时 %.2fs" % (time.time() - t0))
