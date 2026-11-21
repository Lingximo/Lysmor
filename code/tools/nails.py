# -*- coding: utf-8 -*-
"""钉子（Nails）：点名锚 + 承诺 + 72h 原话 —— 常驻注入、永不截断、不占召回预算。

「超脑」里"钉子"= 她叫什么、她答应过什么、他最近说过的话。这些是身份/关系的
硬锚点，不能因为记忆预算紧张就被砍掉。

只读/只写自己的 state/persona/nails.json，不碰记忆库，不改任何记忆正文。
"""

import json
import os
import time

NAILS = r"D:\你的数据目录\state\persona\nails.json"
QUOTE_TTL = 72 * 3600.0      # 原话保留 72 小时
PROMISE_DEFAULT_DAYS = 3.0   # 承诺默认 3 天过期

NAME_WORDS = ("TA", "伴侣", "小家伙", "搭档", "助手")
PROMISE_WORDS = (
    "答应", "承诺", "记住了", "我记下", "我会", "我明天", "我今晚", "我周末",
    "下次", "回头", "等会儿", "几点叫你", "喊你", "叫你起床", "给你买", "陪你去",
    "等着我", "等我",
)
LONG_PROMISE = ("下周", "月底", "周末", "下个月", "放假", "回来")


def _load():
    try:
        return json.load(open(NAILS, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"names": [], "promises": [], "quotes": []}


def _save(d):
    try:
        os.makedirs(os.path.dirname(NAILS), exist_ok=True)
        with open(NAILS, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:  # noqa: BLE001
        pass


def _prune(d, now):
    d["promises"] = [p for p in d.get("promises", []) if float(p.get("until") or 0) > now][:20]
    d["quotes"] = [q for q in d.get("quotes", []) if now - float(q.get("at") or 0) < QUOTE_TTL][:10]
    d["names"] = d.get("names", [])[-12:]
    return d


def ingest(text, who="user", now=None):
    """从一句话里抠点名锚 / 承诺 / 原话。纯规则，不调模型。返回是否新增。"""
    now = now or time.time()
    t = str(text or "").strip()
    if not t:
        return False
    d = _prune(_load(), now)
    changed = False
    if who == "user":
        for n in NAME_WORDS:
            if n in t and n not in d["names"]:
                d["names"].append(n)
                changed = True
        # 原话：你说的短句（不是提问/命令），作"他最近说过的话"
        if 4 <= len(t) <= 60 and not t.endswith(("？", "?", "！", "!")) \
                and not t.startswith(("打开", "关闭", "重启", "查", "看下", "帮我")) \
                and not t.startswith("我忽然想起"):
            key = "".join(t.split())
            dup = any("".join(str(q.get("text") or "").split()) == key
                      for q in d.get("quotes", []))
            if not dup:
                d["quotes"].append({"text": t, "at": now})
                d["quotes"] = d["quotes"][-10:]
                changed = True
    # 承诺（谁说的都算，主要是她答应你的）
    if any(w in t for w in PROMISE_WORDS) and len(t) <= 80:
        days = PROMISE_DEFAULT_DAYS
        if any(w in t for w in LONG_PROMISE):
            days = 7.0
        key = "".join(t[:80].split())
        dup = any("".join(str(p.get("text") or "").split()) == key
                  for p in d.get("promises", []))
        if not dup:
            d["promises"].append({"text": t[:80], "at": now, "until": now + days * 86400})
            d["promises"] = d["promises"][-20:]
            changed = True
    if changed:
        _save(d)
    return changed


def nails_block(now=None):
    """拼成一段常驻注入（字数受控，绝不因预算被截断）。"""
    now = now or time.time()
    d = _prune(_load(), now)
    parts = []
    if d.get("names"):
        parts.append("你这样叫过我：" + "、".join(d["names"]))
    for p in d.get("promises", [])[:5]:
        parts.append("我答应过：" + str(p.get("text", "")))
    for q in d.get("quotes", [])[-3:]:
        parts.append("他最近说过：" + str(q.get("text", "")))
    return "；".join(parts)


if __name__ == "__main__":
    print(nails_block())
