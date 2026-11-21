"""认人：摄像头循环，输出 {"who","score","margin"}，只打印不接服务。

用法：
    python check.py                       # 摄像头 index 0
    python check.py --cam 1 --loop 20
    python check.py --image a.jpg         # 单张图（测试）

判定：1:N 阈值 0.45（宁可认不出，不可认错）；margin < 0.08 视为不确定。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import face_lib  # noqa: E402
from face_lib import FaceDetector, cosine, open_camera, pick_camera  # noqa: E402

PEOPLE = os.path.join(HERE, "people")
NPZ = os.path.join(PEOPLE, "faces.npz")
THRESH_KNOWN = 0.45
MIN_MARGIN = 0.08


def load() -> dict:
    if not os.path.isfile(NPZ):
        return {}
    z = np.load(NPZ, allow_pickle=False)
    return {k: z[k] for k in z.files}


def judge(vec, people: dict) -> dict:
    # 2026-11-09：同一个人可以有多个样子（不戴眼镜/戴眼镜/扎头发），
    # 按"人"取最高分，再和"第二个人"比 margin，否则会被自己的别名挤成陌生人。
    return face_lib.identify(vec, people, THRESH_KNOWN, MIN_MARGIN)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--loop", type=int, default=0)
    ap.add_argument("--image", default="")
    args = ap.parse_args()

    people = load()
    if not people:
        print("还没登记任何人，先跑 enroll.py")
        return 1
    det = FaceDetector()

    if args.image:
        import cv2
        img = cv2.imread(args.image)
        faces = det.detect(img)
        if not faces:
            print(json.dumps({"who": None, "reason": "no_face"}))
            return 0
        print(json.dumps(judge(det.embed(img, faces[0]), people), ensure_ascii=False))
        return 0

    import cv2
    if args.cam is None:
        cap, label, _idx = pick_camera()
    else:
        cap, label = open_camera(args.cam)
    if cap is None:
        print("打不开摄像头 index=%d（MSMF/DSHOW/默认都试过了）" % args.cam)
        return 1
    print("摄像头后端: %s" % label)
    n = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.2)
                continue
            if frame.mean() < 1.0:
                print(json.dumps({"who": None, "reason": "black_frame"}))
                time.sleep(1)
                continue
            faces = det.detect(frame)
            if faces:
                print(json.dumps(judge(det.embed(frame, faces[0]), people), ensure_ascii=False))
            else:
                print(json.dumps({"who": None, "reason": "no_face"}))
            n += 1
            if args.loop and n >= args.loop:
                break
            time.sleep(0.5)
    finally:
        cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
