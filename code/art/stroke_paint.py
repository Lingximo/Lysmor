# -*- coding: utf-8 -*-
"""把一张参考图“用笔画重新画一遍”，并输出过程视频。

这不是把原图贴上去：颜色按区域重新铺成短笔触，线稿用 Canny 轮廓重新描。
最终图会有手绘/水彩的损失感，但每一笔都是真实画出来的。
"""
from __future__ import annotations

import argparse
import math
import subprocess
from pathlib import Path

import cv2
import numpy as np

PAPER = (238, 241, 243)  # BGR，暖白纸


def paper_canvas(h: int, w: int) -> np.ndarray:
    rng = np.random.default_rng(20261102)
    base = np.full((h, w, 3), PAPER, dtype=np.float32)
    grain = rng.normal(0, 2.6, (h, w, 1)).astype(np.float32)
    base += grain
    # 很淡的纸纤维
    for _ in range(90):
        y = int(rng.integers(0, h))
        x0 = int(rng.integers(0, w))
        length = int(rng.integers(w // 12, w // 3))
        c = float(rng.normal(0, 4))
        cv2.line(base, (x0, y), (min(w - 1, x0 + length), y), (c, c, c), 1, cv2.LINE_AA)
    return np.clip(base, 0, 255).astype(np.uint8)


def jitter_color(bgr, rng):
    out = []
    for v in bgr:
        out.append(int(np.clip(v + rng.normal(0, 4.5), 0, 255)))
    return tuple(out)


def split_runs(row: np.ndarray):
    xs = np.flatnonzero(row)
    if len(xs) == 0:
        return []
    cuts = np.where(np.diff(xs) > 1)[0] + 1
    return [xs[a:b] for a, b in zip(np.r_[0, cuts], np.r_[cuts, len(xs)])]


def build_strokes(img: np.ndarray, cluster_count: int = 16):
    """返回 (strokes, line_strokes, underpainting)。"""
    h, w = img.shape[:2]
    rng = np.random.default_rng(20261102)

    # 颜色聚类：宁可多一些，底层更接近原图；笔触只负责纹理
    small = cv2.resize(img, (max(1, w // 2), max(1, h // 2)), interpolation=cv2.INTER_AREA)
    z = small.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 18, 1.0)
    _, labels, centers = cv2.kmeans(
        z, cluster_count, None, criteria, 4, cv2.KMEANS_PP_CENTERS
    )
    labels = labels.reshape(small.shape[:2])
    labels = cv2.resize(labels.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)

    clusters = []
    for k in range(cluster_count):
        mask = (labels == k).astype(np.uint8) * 255
        if int(mask.sum()) < 255 * 20:
            continue
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        bgr = tuple(int(v) for v in centers[k])
        lum = 0.114 * bgr[0] + 0.587 * bgr[1] + 0.299 * bgr[2]
        clusters.append((lum, bgr, mask))

    # 浅色先铺，深色后压，最后描线
    clusters.sort(key=lambda t: -t[0])

    # 底层铺色：所有像素都要有颜色，不能漏掉小色块，否则会露白纸
    under = paper_canvas(h, w)
    for _, bgr, mask in clusters:
        m = mask > 0
        if not m.any():
            continue
        under[m] = (under[m].astype(np.float32) * 0.18 + np.array(bgr) * 0.82).astype(np.uint8)
    # 未覆盖到的零碎像素用原图补一下，保证底层完整
    unassigned = np.ones((h, w), dtype=bool)
    for _, _, mask in clusters:
        unassigned &= ~(mask > 0)
    if unassigned.any():
        blurred = cv2.bilateralFilter(img, 7, 35, 35)
        under[unassigned] = blurred[unassigned]
    under = cv2.bilateralFilter(under, 5, 28, 28)

    strokes = []
    for _, bgr, mask in clusters:
        for y in range(0, h, 6):
            for run in split_runs(mask[y] > 0):
                if len(run) < 3:
                    continue
                pos = 0
                while pos < len(run):
                    seg_len = int(rng.integers(6, 15))
                    seg = run[pos : pos + seg_len]
                    pos += max(1, seg_len - int(rng.integers(2, 5)))
                    if len(seg) < 3:
                        continue
                    pts = []
                    for x in seg:
                        pts.append(
                            (
                                int(x + rng.normal(0, 0.6)),
                                int(y + rng.normal(0, 1.0)),
                            )
                        )
                    strokes.append(
                        {
                            "kind": "paint",
                            "pts": pts,
                            "color": jitter_color(bgr, rng),
                            "width": int(rng.integers(2, 6)),
                        }
                    )

    # 线稿：只留长轮廓，轻轻描一下；不再满脸碎线
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(gray, 50, 115)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    line_strokes = []
    for c in contours:
        if cv2.arcLength(c, False) < 150:
            continue
        approx = cv2.approxPolyDP(c, 1.8, False)
        pts = approx.reshape(-1, 2)
        if len(pts) < 3:
            continue
        sampled = []
        step = max(1, len(pts) // 16)
        for p in pts[::step]:
            sampled.append(
                (
                    int(p[0] + rng.normal(0, 0.4)),
                    int(p[1] + rng.normal(0, 0.4)),
                )
            )
        if len(sampled) >= 2:
            line_strokes.append(
                {
                    "kind": "line",
                    "pts": sampled,
                    "color": (86, 88, 96),
                    "width": 1,
                }
            )
    line_strokes.sort(key=lambda s: -len(s["pts"]))
    return strokes, line_strokes[:45], under



def draw_stroke(canvas, s):
    pts = np.array(s["pts"], dtype=np.int32).reshape(-1, 1, 2)
    cv2.polylines(
        canvas, [pts], False, s["color"], s["width"], cv2.LINE_AA
    )
    # 笔尖的小圆点，增加手绘的顿笔感
    if len(pts) >= 1 and s["kind"] == "line":
        x, y = int(pts[-1][0][0]), int(pts[-1][0][1])
        cv2.circle(canvas, (x, y), max(1, s["width"] // 2), s["color"], -1, cv2.LINE_AA)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--out", default=r"D:\你的数据目录\art\gallery\stroke_sample.png")
    ap.add_argument("--video", default=r"D:\你的数据目录\art\process\stroke_sample.mp4")
    ap.add_argument("--width", type=int, default=512)
    ap.add_argument("--no-lines", action="store_true", help="不额外描线，保留底层线稿")
    args = ap.parse_args()
    args = ap.parse_args()

    img = cv2.imread(args.image)
    if img is None:
        raise SystemExit("cannot read " + args.image)
    h, w = img.shape[:2]
    if w > args.width:
        nh = int(h * args.width / w)
        img = cv2.resize(img, (args.width, nh), interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]

    paint, lines, under = build_strokes(img)
    if args.no_lines:
        lines = []
    print(f"paint strokes={len(paint)} line strokes={len(lines)}", flush=True)

    canvas = under.copy()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.video).parent.mkdir(parents=True, exist_ok=True)

    writer = cv2.VideoWriter(
        args.video, cv2.VideoWriter_fourcc(*"mp4v"), 24, (w, h)
    )
    if not writer.isOpened():
        raise SystemExit("cannot open video writer")

    total = len(paint) + len(lines)
    every = max(1, total // 140)
    count = 0
    frame_hold = 3
    for s in paint + lines:
        draw_stroke(canvas, s)
        count += 1
        if count % every == 0:
            for _ in range(frame_hold):
                writer.write(canvas)
    # 收尾：定格 1 秒
    for _ in range(24):
        writer.write(canvas)
    writer.release()

    cv2.imwrite(args.out, canvas)
    print("saved", args.out, Path(args.out).stat().st_size, flush=True)
    print("video", args.video, Path(args.video).stat().st_size, flush=True)

    # 转 H.264，方便 QQ/手机播放
    try:
        h264 = str(Path(args.video).with_name(Path(args.video).stem + "_h264.mp4"))
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", args.video, "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", h264,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("h264", h264, Path(h264).stat().st_size, flush=True)
    except Exception as exc:
        print("h264 failed:", repr(exc), flush=True)


if __name__ == "__main__":
    main()
