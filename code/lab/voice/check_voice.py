"""认声：录 3 秒，输出 {"who","score","margin"}，只打印不接服务。

用法：
    python check_voice.py                    # 麦克风
    python check_voice.py --wav x.wav        # 用现成文件（测试）
    python check_voice.py --loop 10          # 连续 10 次

判定（先按 TTS 实测定的，接真人前要再校一次）：
    score >= 0.75 且 margin >= 0.10  → 认作本人
    score >= 0.65                    → 不确定（上层按"一票"处理）
    否则                              → 不是登记过的人
声纹只当"身份提示"，不当凭证（不用于开门锁/支付/授权）。
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
THRESH_KNOWN = 0.75
THRESH_MAYBE = 0.65
MIN_MARGIN = 0.10



def roles() -> dict:
    try:
        return {k: v.get("role", "family")
                for k, v in json.load(open(os.path.join(PEOPLE, "people.json"), encoding="utf-8")).items()}
    except Exception:
        return {}

def load() -> dict:
    if not os.path.isfile(NPZ):
        return {}
    z = np.load(NPZ, allow_pickle=False)
    return {k: z[k] for k in z.files}


def judge(vec, people: dict) -> dict:
    if not people:
        return {"who": None, "score": 0.0, "margin": 0.0, "reason": "no_enrollment"}
    scores = sorted(((cosine(vec, v), k) for k, v in people.items()), reverse=True)
    best, who = scores[0]
    second = scores[1][0] if len(scores) > 1 else 0.0
    margin = best - second
    if best >= THRESH_KNOWN and margin >= MIN_MARGIN:
        state = "known"
    elif best >= THRESH_MAYBE:
        state = "maybe"
    else:
        state = "stranger"
    return {"who": who if best >= THRESH_MAYBE else None,
            "role": roles().get(who, "family") if best >= THRESH_MAYBE else "guest",
            "score": round(best, 3), "margin": round(margin, 3),
            "state": state, "runner_up": scores[1][1] if len(scores) > 1 else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", default="")
    ap.add_argument("--loop", type=int, default=1)
    ap.add_argument("--seconds", type=int, default=3)
    ap.add_argument("--device", type=int, default=None)
    args = ap.parse_args()

    people = load()
    if not people:
        print("还没登记任何人，先跑 enroll_voice.py")
        return 1
    enc = SpeakerEncoder()

    for _ in range(max(1, args.loop)):
        if args.wav:
            vec = enc.embed_wav(args.wav)
        else:
            import sounddevice as sd
            pcm = sd.rec(int(args.seconds * 16000), samplerate=16000, channels=1,
                         dtype="float32", device=args.device)
            sd.wait()
            vec = enc.embed_pcm(pcm.ravel())
        print(json.dumps(judge(vec, people), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
