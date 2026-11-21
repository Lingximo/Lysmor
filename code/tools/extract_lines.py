# -*- coding: utf-8 -*-
"""把线稿/骨骼图抽成矢量笔迹（供星星沿线铺）

用法：
  python extract_lines.py                 # 旧：从 target.jpg 抓暗线
  python extract_lines.py --lineart       # 线稿模式（白底黑线，直接取黑线）
  python extract_lines.py --skeleton      # 骨骼图（取暗线，含骨架/肌肉线）

输出：
  hub/static/lines.json         （target 暗线）
  hub/static/lines_lineart.json （线稿）
  hub/static/lines_skel.json    （骨骼）
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image

BASE = r"D:\你的数据目录\hub\static"


def box_blur(a, r):
    k = 2 * r + 1
    p = np.pad(a, r, mode="edge")
    c = np.cumsum(p, axis=0)
    c = np.vstack([np.zeros((1, c.shape[1]), dtype=c.dtype), c])
    out = (c[k:] - c[:-k]) / k
    c2 = np.cumsum(out, axis=1)
    c2 = np.hstack([np.zeros((c2.shape[0], 1), dtype=c2.dtype), c2])
    return (c2[:, k:] - c2[:, :-k]) / k


def thin(mask_thick):
    """简单细化：反复腐蚀端点，直到单像素宽（用邻域计数近似）"""
    m = mask_thick.copy()
    for _ in range(24):
        p = np.pad(m.astype(np.uint8), 1, mode="constant")
        cnt = sum(p[1 + dy:1 + dy + m.shape[0], 1 + dx:1 + dx + m.shape[1]]
                  for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0))
        edge = m & (cnt <= 3)
        nxt = m & ~(edge & (cnt <= 2))
        if nxt.sum() == m.sum():
            break
        m = nxt
    return m


def trace(mask, min_len):
    h, w = mask.shape
    seen = np.zeros((h, w), dtype=bool)
    nb = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    chains = []
    ys, xs = np.nonzero(mask)
    for sy, sx in zip(ys, xs):
        if seen[sy, sx]:
            continue
        chain = [(int(sx), int(sy))]
        seen[sy, sx] = True
        cx, cy = int(sx), int(sy)
        while True:
            nxt = None
            for dy, dx in nb:
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    nxt = (nx, ny)
                    break
            if nxt is None:
                break
            cx, cy = nxt
            seen[cy, cx] = True
            chain.append((cx, cy))
            if len(chain) > 9000:
                break
        if len(chain) >= min_len:
            chains.append(chain)
    return chains


def smooth(pts, k=5):
    if len(pts) <= k:
        return pts
    out = []
    h = k // 2
    for i in range(len(pts)):
        a, b = max(0, i - h), min(len(pts), i + h + 1)
        out.append((sum(p[0] for p in pts[a:b]) / (b - a), sum(p[1] for p in pts[a:b]) / (b - a)))
    return out


def simplify(pts, eps=1.2):
    if len(pts) < 3:
        return pts
    x0, y0 = pts[0]
    x1, y1 = pts[-1]
    dx, dy = x1 - x0, y1 - y0
    n = math.hypot(dx, dy)
    idx, best = -1, -1.0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        d = abs(dy * px - dx * py + x1 * y0 - y1 * x0) / n if n else math.hypot(px - x0, py - y0)
        if d > best:
            idx, best = i, d
    if best <= eps:
        return [pts[0], pts[-1]]
    return simplify(pts[: idx + 1], eps)[:-1] + simplify(pts[idx:], eps)


def merge_ends(items, gap=6.0, rounds=8):
    merged = True
    r = 0
    while merged and r < rounds:
        merged = False
        r += 1
        used = [False] * len(items)
        out = []
        for i in range(len(items)):
            if used[i]:
                continue
            cur = items[i]
            for _ in range(64):
                joined = False
                for j in range(len(items)):
                    if j == i or used[j]:
                        continue
                    b = items[j]
                    a1 = cur["pts"][-1]
                    for rev in (0, 1):
                        pb = b["pts"][0] if rev == 0 else b["pts"][-1]
                        if math.hypot(a1[0] - pb[0], a1[1] - pb[1]) < gap:
                            cur["pts"] += (b["pts"] if rev == 0 else list(reversed(b["pts"])))
                            used[j] = True
                            joined = True
                            break
                    if joined:
                        break
                if not joined:
                    break
            used[i] = True
            out.append(cur)
        items = out
    return items


def run(src, out, mode, tw=960):
    im = Image.open(src).convert("RGB")
    w = tw
    h = max(2, round(im.height * tw / im.width))
    im = im.resize((w, h), Image.LANCZOS)
    gray = np.asarray(im.convert("L"), dtype=np.float32) / 255.0

    if mode == "lineart":
        # 白底黑线：直接取黑线（不做细化，避免被切碎）
        mask = gray < 0.62
        min_len = 10
    else:
        # 暗线：比周围暗的细线
        local = box_blur(gray, 4)
        rel = gray / np.maximum(local, 1e-3)
        mask = (rel < 0.972) & (gray < 0.88)
        mask = thin(mask)
        min_len = 12

    chains = trace(mask, min_len)
    print("[%s] 链 %d" % (mode, len(chains)))

    items = []
    for ch in chains:
        vals = [gray[min(h - 1, p[1]), min(w - 1, p[0])] for p in ch]
        if mode != "lineart" and (float(np.mean(vals)) > 0.88 or float(np.mean(vals)) < 0.16):
            continue
        pts = simplify(smooth(ch, 7), 1.1)
        if len(pts) < 3:
            continue
        length = sum(math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]) for i in range(1, len(pts)))
        if length < 14:
            continue
        items.append({"kind": 1, "tone": int(round(float(np.mean(vals)) * 3)), "pts": pts})

    items = merge_ends(items, gap=7.0)
    print("[%s] 合并后 %d 条" % (mode, len(items)))

    strokes = []
    for it in items:
        flat = [it["kind"], it["tone"]]
        for (x, y) in it["pts"]:
            flat.append(int(round(x)))
            flat.append(int(round(y)))
        if len(flat) >= 8:
            strokes.append(flat)

    data = {"W": int(w), "H": int(h), "strokes": strokes}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    npts = sum((len(s) - 2) // 2 for s in strokes)
    print("[%s] 输出 %s：笔画 %d，顶点 %d，%.1f KB"
          % (mode, os.path.basename(out), len(strokes), npts, os.path.getsize(out) / 1024))


def main():
    args = sys.argv[1:]
    if "--lineart" in args:
        run(os.path.join(BASE, "lineart.jpg"), os.path.join(BASE, "lines_lineart.json"), "lineart")
    elif "--skeleton" in args:
        run(os.path.join(BASE, "skeleton.jpg"), os.path.join(BASE, "lines_skel.json"), "skeleton")
    else:
        run(os.path.join(BASE, "target.jpg"), os.path.join(BASE, "lines.json"), "dark")


if __name__ == "__main__":
    main()
