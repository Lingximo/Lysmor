# -*- coding: utf-8 -*-
"""屏幕分镜观察 —— 采样 → 打分 → 只在"值得看"的时候出一张宫格。

三条判据（借 dsh-see-now 的思路，比"固定间隔"稳得多）：

1. **切点**：分数够高，而且是相对前几帧的尖峰（`s >= 12` 且 `s > 2.5 × 前帧`）。
   只用绝对阈值会在本来就热闹的画面里疯狂触发，只用尖峰又会在低分区误报。
2. **运动积分**：`acc += 每帧分数`，攒够 `REF_SCORE × fps × integralSeconds` 才出一个采样点。
   画面动得快就密集出帧，静止就永远攒不够 —— 这才是"按运动量给帧"。
3. **兜底**：一直没出帧、但画面确实在动，隔一段时间给一张，免得模型以为没更新。

去重：和上一张刚留下的帧差得太近（< 8）就不留，除非它是切点或兜底帧。

对外仍然只产出 state.json / event.json，主程序和陪玩面板不用改。
"""

import json
import os
import time

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- 采样与打分
SCAN_W, SCAN_H = 64, 36     # 打分网格：比整帧小 200 倍，4 点平均降噪

# ---------------------------------------------------------------- 调度参数（0–255 刻度，1 fps）
SAMPLE_SECONDS = 1.0        # 主循环 step 的间隔；打分按 1 fps 标定，别改成别的值
CUT_ABS = 12.0              # 切点的绝对下限
CUT_SPIKE = 2.5             # 还要是相对尖峰：> 2.5 倍前帧
REF_SCORE = 8.0             # "中等强度画面"每帧的分数（标定值）
INTEGRAL_SECONDS = 8.0      # 中等强度画面攒够这么多秒算一个采样点
MIN_GAP = 8.0               # 两次出图最短间隔（硬上限，防止刷屏）
FLOOR_SECONDS = 25.0        # 一直没出图、但画面在动：兜底给一张
FLOOR_MIN_SCORE = 2.0       # 兜底也要求画面确实在动
DUP_MIN = 8.0               # 和上一张留下的帧差小于这个就不留

MAX_FRAMES = 12             # 环形缓冲
SNAPSHOT_SECONDS = 2.0      # 缓冲区里每隔这么久留一帧（只决定"留哪些"，不决定"何时出图"）
CELLS_PER_SHEET = 9         # 一张宫格最多 9 格（3×3）：图价按张算，多留一帧几乎免费
SHEET_COLS = 3
CELL_W = 520
SHEET_MAX_W = 1620

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\arial.ttf",
)


def _font(size=24):
    for path in _FONT_CANDIDATES:
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def grid_hsv(img, size=(SCAN_W, SCAN_H)):
    """缩到 64×36 再转 HSV。PIL 的 BOX 重采样等于把每格平均，比逐点采样快。"""
    small = img.convert("RGB").resize(size, Image.BOX)
    data = small.tobytes()
    out = []
    for i in range(0, len(data), 3):
        r, g, b = data[i], data[i + 1], data[i + 2]
        rn, gn, bn = r / 255.0, g / 255.0, b / 255.0
        mx = max(rn, gn, bn)
        mn = min(rn, gn, bn)
        d = mx - mn
        h = 0.0
        if d:
            if mx == rn:
                h = ((gn - bn) / d) % 6
            elif mx == gn:
                h = (bn - rn) / d + 2
            else:
                h = (rn - gn) / d + 4
            h *= 60.0
        sat = 0.0 if mx == 0 else (d / mx) * 255.0
        out.append((h / 360.0 * 255.0, sat, mx * 255.0))
    return out


def score_pair(prev, cur):
    """两帧 HSV 的加权绝对差均值，0–255。

    色相按环形处理（350° 和 10° 只差 20°），并且低饱和像素的色相降权
    —— 灰的、黑的、白的本来就没有"颜色"可言，只看明暗就行。
    """
    if not prev or not cur:
        return 255.0
    total = 0.0
    for (h1, s1, v1), (h2, s2, v2) in zip(prev, cur):
        dh = abs(h2 - h1)
        hue = min(dh, 255.0 - dh)
        weight = min(s1, s2) / 255.0
        total += hue * weight + abs(s2 - s1) + abs(v2 - v1)
    return total / (len(cur) * 3)


def build_sheet(frames, cols=SHEET_COLS):
    """把若干帧拼成一张带编号/时间的宫格图。frames: [(ts, PIL.Image), ...]"""
    if not frames:
        return None, []
    frames = frames[-CELLS_PER_SHEET:]
    rows = (len(frames) + cols - 1) // cols
    cell_w = min(CELL_W, SHEET_MAX_W // cols)
    src_w, src_h = frames[0][1].size
    cell_h = max(110, int(cell_w * src_h / max(src_w, 1)))
    sheet = Image.new("RGB", (cell_w * cols, cell_h * rows), (12, 14, 20))
    draw = ImageDraw.Draw(sheet)
    font = _font(22)
    meta = []
    for idx, (ts, img) in enumerate(frames):
        r, c = divmod(idx, cols)
        cell = img.convert("RGB").resize((cell_w, cell_h), Image.BILINEAR)
        x, y = c * cell_w, r * cell_h
        sheet.paste(cell, (x, y))
        label = "#%d  %s" % (idx + 1, time.strftime("%H:%M:%S", time.localtime(ts)))
        for dx, dy in ((2, 2), (0, 0)):
            draw.text((x + 9 + dx, y + 7 + dy), label, font=font,
                      fill=(0, 0, 0) if (dx, dy) == (2, 2) else (255, 232, 120))
        draw.rectangle([x, y, x + cell_w - 1, y + cell_h - 1], outline=(60, 70, 90))
        meta.append({"cell": idx + 1, "time": round(ts, 3),
                     "clock": time.strftime("%H:%M:%S", time.localtime(ts))})
    return sheet, meta


class SceneWatcher:
    """grab() -> (title, PIL.Image | None)；describe(sheet, meta) -> dict（失败抛异常）。"""

    def __init__(self, grab, describe, log=print, now=None):
        self.grab = grab
        self.describe = describe
        self.log = log
        self.clock = now or time.time
        self._prev_hsv = None
        self._prev_score = 0.0
        self._last_kept_hsv = None
        self._frames = []
        self._acc = 0.0
        self._last_emit = 0.0
        self._seeded = False
        self.stats = {"samples": 0, "cuts": 0, "marks": 0, "floors": 0,
                      "calls": 0, "dup_skipped": 0, "score_max": 0.0}

    # ------------------------------------------------------------ 主循环一步
    def step(self, now=None):
        now = now or self.clock()
        title, img = self.grab()
        self.stats["samples"] += 1
        if img is None:
            return {"action": "no-window", "title": title}

        hsv = grid_hsv(img)
        score = 0.0 if self._prev_hsv is None else score_pair(self._prev_hsv, hsv)
        self._prev_hsv = hsv
        self.stats["score_max"] = round(max(self.stats["score_max"], score), 1)

        if not self._seeded:
            self._seeded = True
            self._frames.append((now, img))
            self._last_snap = now
            self._last_emit = now
            self._prev_score = score
            return {"action": "seed", "title": title, "score": round(score, 1)}

        # 缓冲区按时间铺满：宫格要能代表"最近这一段"，不能只有出图那一两格。
        # 留帧节奏和出图节奏是两件事，这里只管留。
        if now - self._last_snap >= SNAPSHOT_SECONDS:
            self._frames.append((now, img))
            if len(self._frames) > MAX_FRAMES:
                self._frames.pop(0)
            self._last_snap = now

        # ---------- 判据 1：切点（绝对下限 + 相对尖峰）----------
        cut = (score >= CUT_ABS
               and score > CUT_SPIKE * max(1.0, self._prev_score)
               and (now - self._last_emit) >= MIN_GAP)

        # ---------- 判据 2：运动积分 ----------
        self._acc += score
        need = REF_SCORE * 1.0 * INTEGRAL_SECONDS      # 采样 1 fps
        mark = (not cut) and self._acc >= need and (now - self._last_emit) >= MIN_GAP

        # ---------- 判据 3：兜底 ----------
        floor = (not cut and not mark and (now - self._last_emit) >= FLOOR_SECONDS
                 and score >= FLOOR_MIN_SCORE)

        via = "cut" if cut else ("mark" if mark else ("floor" if floor else ""))

        # ---------- 去重 ----------
        if via and via != "cut" and via != "floor" and self._last_kept_hsv is not None:
            if score_pair(self._last_kept_hsv, hsv) < DUP_MIN:
                self.stats["dup_skipped"] += 1
                via = ""
                self._prev_score = score
                return {"action": "dup", "title": title, "score": round(score, 1)}

        if not via:
            self._prev_score = score
            return {"action": "skip", "title": title, "score": round(score, 1)}

        if via == "cut":
            self.stats["cuts"] += 1
            self._acc = 0.0          # 切点之后重新攒：跨刀那一帧的分数不算运动
        elif via == "mark":
            self.stats["marks"] += 1
            self._acc = 0.0
        else:
            self.stats["floors"] += 1

        # 出图这一帧一定进缓冲区（切点那一帧不能被 2 秒快照节拍漏掉），
        # 但如果刚好刚快照过，就别重复加同一个时刻
        if not self._frames or self._frames[-1][0] != now:
            self._frames.append((now, img))
            if len(self._frames) > MAX_FRAMES:
                self._frames.pop(0)

        # 只出一张图：先攒够 2 帧才有"变化"可言
        if len(self._frames) < 2:
            self._prev_score = score
            return {"action": "skip", "title": title, "score": round(score, 1)}

        sheet, meta = build_sheet(self._frames)
        self._last_emit = now
        self.stats["calls"] += 1
        try:
            obj = self.describe(sheet, meta, title)
        except Exception as exc:  # noqa: BLE001
            self.log("describe failed: %s" % str(exc)[:160])
            self._prev_score = score
            return {"action": "describe-failed", "title": title, "reason": via,
                    "error": str(exc)[:160], "cells": meta, "score": round(score, 1)}

        # 看过的帧不再带着；只留最新一帧当种子，避免下一张重复描述旧画面
        self._last_kept_hsv = hsv
        self._frames = self._frames[-1:]
        self._prev_score = score
        return {"action": "described", "title": title, "reason": via, "cells": meta,
                "score": round(score, 1), "obj": obj, "sheet": sheet}


def describe_prompt(cell_count, title=""):
    head = ""
    if title:
        # 不给标题它会瞎猜游戏名（实测把桌面猜成《原神》）；
        # 但给了又容易照抄标题当答案，所以必须说明"标题只是用来确认，不是答案"
        head = ("窗口标题是「%s」，只用来确认这是什么程序，**不是描述内容**。\n" % title)
    return (
        head
        + "看图：这是同一个游戏窗口最近几十秒的连续画面，每格左上角是时间。\n"
        "用一到两句话说他此刻在做什么、画面里有什么；有没有出现死亡或胜利。\n"
        "不要提“截图/帧/格/这组图”，不要描述排版，不要说“用户”，不要分析过程。"
    )


# ---------------------------------------------------------------- 自测
if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")

    def make(color, label):
        im = Image.new("RGB", (640, 360), color)
        d = ImageDraw.Draw(im)
        d.text((40, 40), label, font=_font(64), fill=(255, 255, 255))
        return im

    # 12 帧：3 帧菜单 → 1 帧切点 → 4 帧对局（画面在动）→ 4 帧静止
    seq = ([make((20, 40, 80), "MENU")] * 3
           + [make((200, 30, 30), "CUT")]
           + [make((20 + i * 6, 90, 40), "PLAY") for i in range(4)]
           + [make((60, 60, 60), "IDLE")] * 4)

    calls = []
    idx = {"i": 0}

    def grab():
        i = idx["i"]
        idx["i"] += 1
        return ("自测窗口", seq[i] if i < len(seq) else None)

    def describe(sheet, meta, title=""):
        calls.append([m["clock"] for m in meta])
        return {"summary": "从菜单进入对局", "event": "none", "scene": "对局"}

    w = SceneWatcher(grab, describe)
    t = 1000.0
    for _ in range(len(seq)):
        r = w.step(t)
        t += 1.0
        print("score=%-6s %-16s %s" % (r.get("score"), r["action"], r.get("reason") or ""))
    print("\n统计：", w.stats)
    print("调用次数：", len(calls), " 每张格数：", [len(c) for c in calls])
    assert w.stats["cuts"] >= 1, "切点没识别出来"
    assert len(calls) <= 3, "出图太频繁"
    print("自测通过")
