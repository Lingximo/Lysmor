# -*- coding: utf-8 -*-
r"""夜间记忆脑：建链接 → 更新自我表 → 写一段睡眠总结（本地模型）。

只读她的记忆库；产物写 state\ 和记忆队列（不会改人设/日记）。
"""
from __future__ import annotations

import json
import os
import sys
import time

import requests

sys.path.insert(0, r"D:\你的数据目录\lab\memory_brain")
import companion_brain as brain  # noqa: E402

OLLAMA = brain.OLLAMA
MODEL = brain.MODEL
MEMDB = brain.DB
PENDING = r"D:\你的数据目录\video\pending_memories.json"


def _recent_memories(hours: int = 24, limit: int = 8):
    import sqlite3
    con = sqlite3.connect("file:%s?mode=ro" % MEMDB, uri=True)
    rows = con.execute(
        "select text, metadata, created_at from documents "
        "where datetime(created_at) > datetime('now', ?) "
        "order by id desc limit ?",
        ("-%d hours" % hours, limit * 4),
    ).fetchall()
    con.close()
    out = []
    for text, meta, created in rows:
        try:
            md = json.loads(meta or "{}")
        except Exception:
            md = {}
        if str(md.get("source") or "") == "sleep":
            continue          # 别拿"睡前回想"再喂给下一次睡前回想
        imp = float(md.get("importance", 0.5) or 0.5)
        if imp >= 0.45:
            out.append((imp, text or ""))
        if len(out) >= limit:
            break
    return out


def _sleep_note(mems) -> str:
    if not mems:
        return ""
    material = "\n".join("- " + t[:160] for _, t in mems)
    prompt = (
        "这是TA今天经历的一些事：\n%s\n\n"
        "用她的第一人称，写一段 80~120 字的'睡前回想'："
        "像人在半睡半醒时把今天过一遍，可以有情绪，但不要列清单、不要提AI。"
        % material
    )
    try:
        txt = brain._llm(prompt, 240)
    except Exception as e:  # noqa: BLE001
        print("sleep note failed:", e)
        txt = ""
    if not txt:
        # 本地模型没给出内容时，用模板兜底（不编造，只把今天的事串起来）
        bits = []
        for _, t in mems[:6]:
            line = (t or "").strip().split("\n")[0]
            if line.startswith("睡前把今天过了一遍："):
                line = line.split("：", 1)[-1]
            if line and line not in bits:
                bits.append(line[:40])
            if len(bits) >= 3:
                break
        if not bits:
            return ""
        return "睡前把今天过了一遍：" + "；".join(bits) + "。想着这些，眼皮越来越沉。"
    return txt


def _queue_memory(text: str, importance: float, source: str) -> None:
    try:
        items = []
        if os.path.exists(PENDING):
            with open(PENDING, encoding="utf-8") as f:
                items = json.load(f)
                if not isinstance(items, list):
                    items = []
        items.append({"summary": text, "importance": importance,
                      "source": source, "time": time.time()})
        with open(PENDING, "w", encoding="utf-8") as f:
            json.dump(items[-200:], f, ensure_ascii=False, indent=2)
        print("queued:", source, text[:40])
    except Exception as e:  # noqa: BLE001
        print("queue failed:", e)


def main():
    print("== brain nightly ==")
    brain.build_links()
    brain.build_self()
    # 开机补跑时可能是白天：只重建链接/自我表，不写"睡前回想"
    import datetime
    hour = datetime.datetime.now().hour
    if hour >= 22 or hour < 8:
        mems = _recent_memories()
        note = _sleep_note(mems)
        if note:
            _queue_memory(note, 0.5, "sleep")
    else:
        print("白天补跑：跳过睡前回想")
    print("done")


if __name__ == "__main__":
    main()
