# -*- coding: utf-8 -*-
"""她学游戏的地方：playbook（玩法笔记）

部署者 2026-11-09：
  "教她玩游戏的相关记忆是要记下来的，不是那种死记硬背，
   而是懂逻辑后能自己玩。"

所以这里存两层：
  ① quote     你原话（证据，不丢）
  ② summary   她自己用话复述的"什么时候/怎么做/为什么"（她理解的逻辑）
再抽一份 keys（键位/术语），以后真上手时用得上。

文件：lab\\game\\playbook.json（人可读，改坏了删掉即可）
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "playbook.json")

TEACH_RE = re.compile(r"(教你|记住|记一下|学一下|要这样|应该这样|玩法|打法|操作是|连招)")
GAME_RE = re.compile(r"(绝区零|zzz|游戏|按键|操作|闪避|攻击|技能|连招|大招|敌人|boss|打怪)", re.I)
KEY_RE = re.compile(r"\b(Shift|Ctrl|Alt|Space|Tab|Esc|Enter|[WASDwasd]|[JKLUIOPjkluiopEQeq])\b")


def _load() -> dict:
    try:
        with open(FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("rules"), list):
            return data
    except Exception:  # noqa: BLE001
        pass
    return {"rules": [], "updated": 0}


def _save(data: dict) -> None:
    data["updated"] = time.time()
    os.makedirs(HERE, exist_ok=True)
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, FILE)


def _clean_summary(text: str) -> str:
    """去掉尾巴上的"记住了"和表情，只留逻辑本身。"""
    t = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text or "")
    t = re.sub(r"(记住了|记住啦|知道啦)[\s\S]*$", "", t)
    return t.strip()


def is_teaching(text: str) -> bool:
    t = text or ""
    return bool(TEACH_RE.search(t) and GAME_RE.search(t)) and len(t) <= 300


def extract_keys(text: str) -> list:
    return sorted({m.group(1).upper() for m in KEY_RE.finditer(text or "")})


def add(summary: str, quote: str = "", topic: str = "绝区零", keys=None) -> dict:
    """存一条玩法：她自己的理解 + 你原话。"""
    data = _load()
    rule = {
        "id": uuid.uuid4().hex[:8],
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ts": time.time(),
        "topic": topic,
        "summary": _clean_summary(summary)[:600],
        "quote": (quote or "").strip()[:600],
        "keys": keys if keys is not None else extract_keys((quote or "") + " " + (summary or "")),
        "hits": 0,
    }
    # 同义重复就不再加
    for old in data["rules"]:
        if old.get("summary") and rule["summary"] and old["summary"][:60] == rule["summary"][:60]:
            old["at"] = rule["at"]
            old["quote"] = rule["quote"] or old.get("quote", "")
            _save(data)
            return old
    data["rules"].append(rule)
    data["rules"] = data["rules"][-300:]
    _save(data)
    return rule


def _tokens(text: str) -> set:
    """中文按 2 字滑窗，英文按整词 —— 这样"红盾怎么办"能匹配到"红盾"。"""
    grams = set()
    for w in re.findall(r"[A-Za-z]{2,}", text or ""):
        grams.add(w.lower())
    for seg in re.findall(r"[\u4e00-\u9fff]+", text or ""):
        for i in range(len(seg) - 1):
            grams.add(seg[i:i + 2])
    return grams


def _score(rule: dict, query: str) -> float:
    q = _tokens(query)
    if not q:
        return 0.0
    text = (rule.get("summary", "") + rule.get("quote", "") + " ".join(rule.get("keys", [])))
    t = _tokens(text)
    hit = len(q & t)
    return hit / max(3.0, len(q))


def search(query: str, limit: int = 3) -> list:
    data = _load()
    scored = [(_score(r, query), r) for r in data["rules"]]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: (x[0], x[1].get("ts", 0)), reverse=True)
    out = [r for _, r in scored[:limit]]
    if out:
        data["rules"] = data["rules"]
        for r in out:
            r["hits"] = int(r.get("hits") or 0) + 1
        _save(data)
    return out


def recent(limit: int = 5) -> list:
    data = _load()
    return list(reversed(data["rules"][-limit:]))


def render(limit: int = 5, query: str = "") -> str:
    rules = search(query, limit) if query else recent(limit)
    if not rules:
        return ""
    lines = []
    for r in rules:
        keys = ("，键位：" + "/".join(r["keys"])) if r.get("keys") else ""
        lines.append("- %s%s" % (r.get("summary", ""), keys))
    return "\n".join(lines)


def stats() -> dict:
    data = _load()
    return {"rules": len(data["rules"]), "updated": data.get("updated", 0), "path": FILE}


if __name__ == "__main__":
    print(stats())
    print(render(3))
