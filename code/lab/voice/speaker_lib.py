"""TA的「听声识人」底层：WeSpeaker ResNet34（VoxCeleb）说话人向量。

只做计算，不做判断：
    spk = SpeakerEncoder()
    vec = spk.embed_wav("a.wav")      # np.float32(256)，已 L2 归一化
    vec = spk.embed_pcm(x_16k)        # 传 numpy float32 也行
    cosine(v1, v2)

前端：80 维 log-mel（16k / 25ms / 10ms / HTK mel / fmin0 fmax7600 / center），逐句均值归一化。
     2026-11-06 用 3 个 TTS 音色 × 2 句做过前端扫描：HTK + fmin0 + fmax7600 + center 分离度最好
     （同人 0.758 / 异人 0.354）；换前端前后差别很大，别随便改。
     WeSpeaker 的 onnx 导出就是吃 fbank，这里用 librosa 算，避免装 torch。

隔离：不开端口、不写 state/记忆、不占 8003 的音频设备（录音由调用方自己做）。
"""
from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(HERE)
PYLIBS = os.path.join(LAB, "vision", "pylibs")
MODEL = os.path.join(HERE, "models", "wespeaker_resnet34.onnx")

if os.path.isdir(PYLIBS) and PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)

import librosa  # noqa: E402
import onnxruntime as ort  # noqa: E402

SR = 16000
N_MELS = 80
WIN = 400      # 25ms
HOP = 160      # 10ms


def cosine(a, b) -> float:
    a = np.asarray(a, dtype=np.float32).ravel()
    b = np.asarray(b, dtype=np.float32).ravel()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return 0.0 if na == 0 or nb == 0 else float(np.dot(a, b) / (na * nb))


class SpeakerEncoder:
    def __init__(self, providers=None):
        if not os.path.isfile(MODEL):
            raise FileNotFoundError("缺模型：%s" % MODEL)
        so = ort.SessionOptions()
        so.log_severity_level = 3
        self._s = ort.InferenceSession(
            MODEL, so, providers=providers or ["CPUExecutionProvider"])
        self._in = self._s.get_inputs()[0].name

    @staticmethod
    def fbank(pcm: np.ndarray) -> np.ndarray:
        """16k 单声道 float32 -> (T, 80) log-mel，逐句均值归一化。"""
        pcm = np.asarray(pcm, dtype=np.float32).ravel()
        if pcm.size < WIN:
            pcm = np.pad(pcm, (0, WIN - pcm.size))
        mel = librosa.feature.melspectrogram(
            y=pcm, sr=SR, n_fft=WIN, hop_length=HOP,
            n_mels=N_MELS, fmin=0, fmax=7600, power=2.0,
            htk=True, center=True)
        feats = np.log(np.maximum(mel, 1e-10)).T  # (T, 80)
        feats = feats - feats.mean(axis=0, keepdims=True)
        return feats.astype(np.float32)

    def embed_pcm(self, pcm: np.ndarray) -> np.ndarray:
        feats = self.fbank(pcm)[None, ...]           # (1, T, 80)
        vec = self._s.run(None, {self._in: feats})[0].ravel().astype(np.float32)
        n = np.linalg.norm(vec)
        return vec / n if n else vec

    def embed_wav(self, path: str) -> np.ndarray:
        import soundfile as sf
        pcm, sr = sf.read(path, dtype="float32", always_2d=False)
        if pcm.ndim > 1:
            pcm = pcm.mean(axis=1)
        if sr != SR:
            pcm = librosa.resample(pcm, orig_sr=sr, target_sr=SR)
        return self.embed_pcm(pcm)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python speaker_lib.py a.wav [b.wav]")
        raise SystemExit(2)
    enc = SpeakerEncoder()
    va = enc.embed_wav(sys.argv[1])
    print("a: dim=%d" % va.size)
    if len(sys.argv) > 2:
        vb = enc.embed_wav(sys.argv[2])
        print("a vs b 相似度: %.3f" % cosine(va, vb))
