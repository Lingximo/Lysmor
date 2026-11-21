# -*- coding: utf-8 -*-
"""轻量记忆召回：给空间/视频/主动消息这类“不走 livingmemory 钩子”的场景用。

只读 livingmemory.db，不写、不改、不删。
优先按关键词找，找不到就退回最近几条，保证永远不会把她的嘴封死。
"""

import json
import os
import sqlite3
import time

NUDGE_TS = r"D:\你的数据目录\state\persona\recall_nudge_ts.json"


def _maybe_nudge():
    """QQ 侧（空间/主动消息）召回命中最重要记忆时，也轻轻碰一下身体：
    与视频侧同一通道，冷却用文件（跨进程共享，5 分钟）。"""
    try:
        con = _connect()
        try:
            rows = con.execute(
                "select text, metadata from documents "
                "WHERE (json_valid(metadata) = 0 "
                " OR coalesce(json_extract(metadata, '$.status'), 'active') = 'active') "
                "ORDER BY id DESC LIMIT 6").fetchall()
        finally:
            con.close()
        imp, top = 0.0, ""
        for text, meta in rows:
            try:
                imp = max(imp, float((json.loads(meta or "{}")).get("importance") or 0))
            except Exception:
                pass
            if not top and text:
                top = (text or "").strip()
        if imp < 0.70 or not top:
            return
        now = time.time()
        try:
            last = float(json.load(open(NUDGE_TS, encoding="utf-8")).get("at") or 0)
        except Exception:
            last = 0.0
        if now - last < 300:
            return
        with open(NUDGE_TS, "w", encoding="utf-8") as f:
            json.dump({"at": now}, f)
        path = r"D:\你的数据目录\video\mood_events.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"text": "我忽然想起：" + top[:80], "t": now}, ensure_ascii=False) + "\n")
    except Exception:
        pass

DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
MAX_CHARS = 160

# 2026-11-05 补：和记忆库的归档规则保持一致。
# 归档（status=archived）的记忆已经被移出召回索引，这里再按 id/时间硬取，
# 就会出现"QQ 那头想不起、空间和主动消息却翻出来说过"的错位——
# video/server.py 早就过滤了，这里漏了（见灾后复活 §44）。
ACTIVE = ("(json_valid(metadata) = 0 "
          " OR coalesce(json_extract(metadata, '$.status'), 'active') = 'active')")


def _connect():
    return sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True,
                           timeout=2.0)


def _row_to_text(row):
    text, meta, created = row
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    try:
        m = json.loads(meta or "{}")
    except Exception:
        m = {}
    try:
        imp = float(m.get("importance", 0.0) or 0.0)
    except Exception:
        imp = 0.0
    if imp < 0.12:
        return ""
    day = str(created or "")[:10]
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rstrip() + "…"
    return ("[%s] %s" % (day, text)) if day else text


def recent(limit=3, query=None):
    """返回最近的记忆摘要列表；任何异常都返回 []。"""
    out = []
    seen = set()
    try:
        con = _connect()
        try:
            rows = []
            q = (query or "").strip()
            if q:
                like = "%" + q[:40] + "%"
                try:
                    rows = list(con.execute(
                        "select text, metadata, created_at from documents "
                        "where text like ? and " + ACTIVE + " "
                        "order by created_at desc limit ?",
                        (like, max(1, limit))))
                except sqlite3.Error:
                    rows = []
            if len(rows) < limit:
                more = list(con.execute(
                    "select text, metadata, created_at from documents "
                    "where " + ACTIVE + " "
                    "order by created_at desc limit ?", (max(4, limit * 2),)))
                rows.extend(more)
            for row in rows:
                line = _row_to_text(row)
                if not line or line in seen:
                    continue
                seen.add(line)
                out.append(line)
                if len(out) >= limit:
                    break
        finally:
            con.close()
    except Exception:
        return []
    return out


def context(limit=3, query=None, header=None):
    """拼成可直接塞进 system prompt 的段落；没有记忆时返回空串。"""
    lines = recent(limit=limit, query=query)
    _maybe_nudge()
    # 钉子（点名锚+承诺+72h原话）：常驻注入，不占召回预算
    try:
        import nails as _nails
        _nb = _nails.nails_block()
    except Exception:  # noqa: BLE001
        _nb = ""
    if not lines and not _nb:
        return ""
    head = header or ("# 你记得的最近的事（你自己的经历，不是设定；不要逐条复述，"
                      "但怎么影响你说话，由你自己决定）")
    out = head + "\n" + "\n".join("- " + x for x in lines)
    if _nb:
        out = "[钉子] " + _nb + "\n" + out
    return out


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else None
    print(context(limit=5, query=q))
