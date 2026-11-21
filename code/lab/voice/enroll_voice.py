"""声纹登记：录 3~5 段，存说话人向量（不存音频）。

用法：
    python enroll_voice.py --name dad --seconds 5 --segments 4
    python enroll_voice.py --name dad --wav a.wav --wav b.wav      # 用现成文件（测试）

规则（写死在这里，别绕过）：
    · 登记和识别必须**同一支麦克风**，换麦精度会断崖式下跌；
    · 只存 embedding（256 维）和名字，**不存音频**；
    · 输出 lab\\voice\\people\\voices.npz + people.json。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from speaker_lib import SpeakerEncoder, cosine  # noqa: E402

PEOPLE = os.path.join(HERE, "people")
NPZ = os.path.join(PEOPLE, "voices.npz")
JSON = os.path.join(PEOPLE, "people.json")


def record(seconds: int, dev=None) -> np.ndarray:
    import sounddevice as sd
    print("  录 %d 秒…（现在说话）" % seconds)
    pcm = sd.rec(int(seconds * 16000), samplerate=16000, channels=1,
                 dtype="float32", device=dev)
    sd.wait()
    return pcm.ravel()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--segments", type=int, default=4)
    ap.add_argument("--seconds", type=int, default=5)
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--wav", action="append", default=[])
    ap.add_argument("--role", default="family", choices=["owner", "family", "guest"])
    args = ap.parse_args()

    os.makedirs(PEOPLE, exist_ok=True)
    enc = SpeakerEncoder()

    vecs = []
    if args.wav:
        for w in args.wav:
            vecs.append(enc.embed_wav(w))
            print("  + %s" % os.path.basename(w))
    else:
        for i in range(args.segments):
            pcm = record(args.seconds, args.device)
            vecs.append(enc.embed_pcm(pcm))

    vecs = np.stack(vecs)
    # 段间一致性：低于 0.5 说明录音环境太差或人换了，直接拒绝入库
    sims = [cosine(vecs[i], vecs[j]) for i in range(len(vecs)) for j in range(i + 1, len(vecs))]
    inner = float(np.mean(sims)) if sims else 1.0
    print("段间一致性: %.3f" % inner)
    if inner < 0.5:
        print("[拒绝] 这几段不像同一个人（或噪声太大），换个安静地方重录")
        return 1

    mean = vecs.mean(axis=0)
    mean = mean / np.linalg.norm(mean)

    data = {}
    meta = {}
    if os.path.isfile(NPZ):
        old = np.load(NPZ, allow_pickle=False)
        data = {k: old[k] for k in old.files}
    if os.path.isfile(JSON):
        meta = json.load(open(JSON, encoding="utf-8"))
    data[args.name] = mean
    meta[args.name] = {"segments": len(vecs), "inner_sim": round(inner, 3),
                       "mic_device": args.device, "role": args.role,
                       "updated": __import__("time").strftime("%Y-%m-%d %H:%M")}
    np.savez(NPZ, **data)
    json.dump(meta, open(JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("已登记 %s（%d 段，一致性 %.3f）→ %s" % (args.name, len(vecs), inner, NPZ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
