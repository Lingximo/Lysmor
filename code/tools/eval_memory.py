# -*- coding: utf-8 -*-
"""离线评估：给定问题，看"该想起的记忆"有没有进 top-k。

用 bge-m3（本机 ollama）对全部记忆做一次向量缓存，然后逐题算余弦。
只读数据库，不写任何东西。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

import numpy as np
import requests

DB = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
      r"\core\data\plugin_data\astrbot_plugin_livingmemory\livingmemory.db")
CACHE = r"D:\你的数据目录\logs\memory_eval_cache.npz"
API = "http://127.0.0.1:11434/api/embeddings"
MODEL = "bge-m3"

QUESTIONS = [
    ("我们认识那天你叫我什么", "TA"),
    ("我最爱吃什么", "水煮肉片"),
    ("你昨晚睡得好吗", "睡"),
    ("你渴了会怎么办", "饮水机"),
    ("你画过哪些画", "画"),
    ("你画的那颗心", "心"),
    ("你画的TA", "鱼"),
    ("你喂你吃了什么", "水煮肉片"),
    ("你生病的时候", "生病"),
    ("你喜欢喝什么", "奶茶"),
    ("你给你倒水", "水"),
    ("你熬夜了吗", "熬"),
    ("你住的房间", "宿舍"),
    ("你叫什么名字", "伴侣"),
    ("你给你买奶茶", "奶茶"),
]


def embed(text: str):
    r = requests.post(API, json={"model": MODEL, "prompt": text}, timeout=60)
    r.raise_for_status()
    return np.array(r.json()["embedding"], dtype=np.float32)


def load_docs():
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    rows = con.execute("select id, text, created_at from documents order by id").fetchall()
    con.close()
    return rows


def build_cache(rows):
    if os.path.exists(CACHE):
        z = np.load(CACHE, allow_pickle=True)
        if len(z["ids"]) == len(rows):
            return z["ids"], z["vecs"]
    vecs = []
    for i, (_, text, _) in enumerate(rows):
        vecs.append(embed((text or "")[:1000]))
        if (i + 1) % 50 == 0:
            print("embed %d/%d" % (i + 1, len(rows)), flush=True)
    ids = np.array([r[0] for r in rows])
    m = np.stack(vecs)
    np.savez_compressed(CACHE, ids=ids, vecs=m)
    return ids, m


def main():
    rows = load_docs()
    texts = {r[0]: (r[1] or "") for r in rows}
    ids, mat = build_cache(rows)
    mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-8)
    hit5 = hit10 = 0
    miss = []
    for q, kw in QUESTIONS:
        qv = embed(q)
        qv = qv / (np.linalg.norm(qv) + 1e-8)
        sims = mat @ qv
        order = np.argsort(-sims)[:10]
        top10 = [int(ids[i]) for i in order]
        found5 = any(kw in texts.get(i, "") for i in top10[:5])
        found10 = any(kw in texts.get(i, "") for i in top10)
        hit5 += found5
        hit10 += found10
        if not found10:
            miss.append((q, kw))
    n = len(QUESTIONS)
    print("recall@5  = %d/%d = %.0f%%" % (hit5, n, 100.0 * hit5 / n))
    print("recall@10 = %d/%d = %.0f%%" % (hit10, n, 100.0 * hit10 / n))
    for q, kw in miss:
        print("  漏:", q, "→", kw)


if __name__ == "__main__":
    main()
