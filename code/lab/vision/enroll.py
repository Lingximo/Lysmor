"""人脸登记：摄像头前拍若干个姿势，只存 512 维向量，不存照片。

用法：
    python enroll.py --name dad --shots 6
    python enroll.py --name dad --image a.jpg --image b.jpg     # 用现成图（测试）

输出：lab\\vision\\people\\faces.npz + people.json
规则：不存原始照片；同一个人的向量取平均后归一化。
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

from face_lib import FaceDetector, cosine, open_camera, pick_camera  # noqa: E402

PEOPLE = os.path.join(HERE, "people")
NPZ = os.path.join(PEOPLE, "faces.npz")
JSON = os.path.join(PEOPLE, "people.json")


def grab(shots: int, cam: int) -> list:
    import cv2
    if cam is None:
        cap, label, _idx = pick_camera()
    else:
        cap, label = open_camera(cam)
    if cap is None:
        raise RuntimeError("打不开摄像头 index=%d（MSMF/DSHOW/默认都试过了）" % cam)
    print("  摄像头后端: %s" % label)
    out = []
    try:
        for i in range(shots):
            print("  第 %d/%d 张：看着镜头（换一点点角度）" % (i + 1, shots))
            time.sleep(1.2)
            ok, frame = cap.read()
            if ok and frame is not None:
                out.append(frame)
    finally:
        cap.release()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--shots", type=int, default=6)
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--image", action="append", default=[])
    ap.add_argument("--role", default="family", choices=["owner", "family", "guest"])
    args = ap.parse_args()

    os.makedirs(PEOPLE, exist_ok=True)
    det = FaceDetector()

    frames = []
    if args.image:
        import cv2
        for p in args.image:
            img = cv2.imread(p)
            if img is not None:
                frames.append(img)
    else:
        frames = grab(args.shots, args.cam)

    vecs = []
    for f in frames:
        faces = det.detect(f)
        if not faces:
            continue
        v = det.embed(f, faces[0])
        if v is not None:
            vecs.append(v)
    if len(vecs) < 2:
        print("[拒绝] 有效人脸不足 2 张（检测到 %d），检查摄像头/光线" % len(vecs))
        return 1

    vecs = np.stack(vecs)
    sims = [cosine(vecs[i], vecs[j]) for i in range(len(vecs)) for j in range(i + 1, len(vecs))]
    inner = float(np.mean(sims)) if sims else 1.0
    print("张间一致性: %.3f（低于 0.4 说明拍的不是同一个人或太糊）" % inner)
    if inner < 0.4:
        print("[拒绝] 一致性太低，重拍")
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
    meta[args.name] = {"shots": len(vecs), "inner_sim": round(inner, 3), "role": args.role,
                       "updated": time.strftime("%Y-%m-%d %H:%M")}
    np.savez(NPZ, **data)
    json.dump(meta, open(JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("已登记 %s（%d 张，一致性 %.3f）" % (args.name, len(vecs), inner))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
