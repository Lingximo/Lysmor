# -*- coding: utf-8 -*-
"""疤痕升级：从一个数字，升级成"一组带记忆的疤"。

原来的 scar 只是一个 0~1 的数字（濒死才升），记的是"有没有疤"，不是"哪条疤"。
这里扫记忆库，把"深刻负面"的记忆找出来，形成 state/scars.json：
每条疤 = 一段记忆 + 时间 + 深度。只读记忆库，只写自己的文件。
"""
import io
import json
import os
import sqlite3
import time

ROOT = r"D:\你的数据目录"
OUT = os.path.join(ROOT, "state", "scars.json")
DB = os.path.join(ROOT, "livingmemory", "livingmemory.db")

# 深刻负面的门槛
MIN_IMPORTANCE = 0.60
MAX_VALENCE = -0.30
SCAR_SOURCES = ("scar",)   # 濒死印记（source=scar）无条件算疤


def _scan():
    scars = []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True,
                              timeout=5)
        for mid, text, m in con.execute(
                "SELECT id, text, metadata FROM documents ORDER BY created_at DESC LIMIT 400"):
            try:
                md = json.loads(m or "{}")
            except Exception:  # noqa: BLE001
                continue
            src = md.get("source")
            imp = float(md.get("importance") or 0)
            vs = (md.get("mood_snapshot") or {}).get("valence")
            vs = float(vs) if vs is not None else 0.0
            is_scar = src in SCAR_SOURCES
            deep_neg = imp >= MIN_IMPORTANCE and vs <= MAX_VALENCE
            if not (is_scar or deep_neg):
                continue
            depth = round(min(1.0, 0.6 * imp + 0.4 * abs(vs)), 3)
            scars.append({
                "id": int(mid),
                "text": str(text or "")[:120],
                "source": src,
                "depth": max(depth, 0.70 if is_scar else depth),
                "at": str(md.get("create_time") or ""),
            })
        con.close()
    except Exception:  # noqa: BLE001
        pass
    # 疤深的排前面，最多 12 条
    scars.sort(key=lambda x: -float(x.get("depth") or 0))
    return scars[:12]


def main():
    scars = _scan()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    try:
        with io.open(OUT, "w", encoding="utf-8") as f:
            json.dump({"scars": scars, "n": len(scars), "at": time.strftime("%Y-%m-%d %H:%M:%S")},
                      f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass
    print("疤痕升级：找到 %d 条带记忆的疤" % len(scars))
    for s in scars[:3]:
        print("  depth=%.2f %s" % (s["depth"], s["text"][:40]))


if __name__ == "__main__":
    main()
