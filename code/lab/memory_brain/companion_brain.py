# -*- coding: utf-8 -*-
r"""TA的"记忆脑"外挂：链接、PPR 扩展、自我表、睡眠总结。

只读她的记忆库；自己的产物写在 D:\你的数据目录\state\。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import defaultdict

from pathlib import Path
import sys

for _parent in Path(__file__).resolve().parents:
    if (_parent / "i18n.py").is_file():
        sys.path.insert(0, str(_parent))
        break
sys.path.insert(0, r"D:\你的数据目录")
from i18n import t

DB = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
      r"\core\data\plugin_data\astrbot_plugin_livingmemory\livingmemory.db")
STATE_DIR = r"D:\你的数据目录\state"
LINKS_DB = os.path.join(STATE_DIR, "memory_links.db")
SELF_JSON = os.path.join(STATE_DIR, "self.json")
VEC_CACHE = r"D:\你的数据目录\logs\memory_eval_cache.npz"
OLLAMA = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3-vl:4b"

os.makedirs(STATE_DIR, exist_ok=True)


def _ro():
    return sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=5)


# ---------------------------------------------------------------- 链接
def _embed(text: str):
    import requests as _rq
    r = _rq.post("http://127.0.0.1:11434/api/embeddings",
                 json={"model": "bge-m3", "prompt": (text or "")[:1000]}, timeout=60)
    return r.json()["embedding"]


def _refresh_cache():
    """让向量缓存跟上数据库（新增记忆补 embed，归档的剔除）。"""
    import numpy as np
    con = _ro()
    rows = con.execute("select id, text, metadata from documents").fetchall()
    con.close()
    live = {}
    for mid, text, meta in rows:
        try:
            md = json.loads(meta or "{}")
        except Exception:
            md = {}
        if str(md.get("status") or "").lower() in ("archived", "deleted"):
            continue
        live[int(mid)] = text or ""
    if os.path.exists(VEC_CACHE):
        z = np.load(VEC_CACHE, allow_pickle=True)
        ids = list(int(x) for x in z["ids"])
        mat = list(z["vecs"])
    else:
        ids, mat = [], []
    have = set(ids)
    changed = False
    for mid, text in live.items():
        if mid not in have:
            mat.append(_embed(text))
            ids.append(mid)
            changed = True
    keep = [i for i, mid in enumerate(ids) if mid in live]
    if len(keep) != len(ids):
        ids = [ids[i] for i in keep]
        mat = [mat[i] for i in keep]
        changed = True
    if changed:
        np.savez_compressed(VEC_CACHE, ids=np.array(ids), vecs=np.stack(mat))
        print(t("memory.cache_refreshed", count=len(ids)))


def build_links(top_k: int = 3, min_sim: float = 0.55) -> int:
    """用缓存的 bge-m3 向量，给每条记忆找 top_k 个相似邻居，写进 links 库。"""
    import numpy as np

    if not os.path.exists(VEC_CACHE):
        print(t("memory.cache_missing"))
        return 0
    z = np.load(VEC_CACHE, allow_pickle=True)
    ids, mat = z["ids"], z["vecs"]
    mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-8)
    sims = mat @ mat.T
    con = sqlite3.connect(LINKS_DB)
    con.execute("create table if not exists links (a integer, b integer, sim real, primary key(a,b))")
    con.execute("delete from links")
    n = 0
    for i, mid in enumerate(ids):
        row = sims[i].copy()
        row[i] = -1
        order = np.argsort(-row)[:top_k]
        for j in order:
            if row[j] < min_sim:
                continue
            con.execute("insert or replace into links(a,b,sim) values(?,?,?)",
                        (int(mid), int(ids[j]), float(row[j])))
            n += 1
    con.commit()
    con.close()
    print(t("memory.links", count=n))
    return n


_LINKS_CACHE = {"mtime": 0.0, "data": {}}


def load_links() -> dict:
    """链接表按 mtime 缓存，避免每次召回都开库。"""
    if not os.path.exists(LINKS_DB):
        return {}
    try:
        mt = os.path.getmtime(LINKS_DB)
    except OSError:
        return {}
    if _LINKS_CACHE["mtime"] == mt and _LINKS_CACHE["data"]:
        return _LINKS_CACHE["data"]
    con = sqlite3.connect("file:%s?mode=ro" % LINKS_DB, uri=True)
    out = defaultdict(list)
    for a, b, sim in con.execute("select a,b,sim from links"):
        out[int(a)].append((int(b), float(sim)))
    con.close()
    _LINKS_CACHE["mtime"] = mt
    _LINKS_CACHE["data"] = out
    return out


# ---------------------------------------------------------------- PPR
_GRAPH_CACHE = {"mtime": 0.0, "adj": {}}


def _load_mem_graph() -> dict:
    """记忆-记忆邻接表，按记忆库 mtime 缓存。"""
    try:
        mt = os.path.getmtime(DB)
    except OSError:
        return {}
    if _GRAPH_CACHE["mtime"] == mt and _GRAPH_CACHE["adj"]:
        return _GRAPH_CACHE["adj"]
    con = _ro()
    try:
        edges = con.execute(
            "select source_memory_id, target_memory_id from graph_edges where status='active'"
        ).fetchall()
        node_map = defaultdict(list)
        for m, src in con.execute(
            "select e.source_memory_id, n.node_id from graph_entry_nodes n "
            "join graph_entries e on e.id = n.entry_id"
        ):
            node_map[int(m)].append(int(src))
    except Exception:
        con.close()
        return {}
    con.close()

    adj = defaultdict(set)
    for a, b in edges:
        adj[int(a)].add(int(b))
        adj[int(b)].add(int(a))
    by_node = defaultdict(list)
    for m, nodes in node_map.items():
        for n in nodes:
            by_node[n].append(m)
    for m, nodes in node_map.items():
        for n in nodes:
            for other in by_node[n]:
                if other != m:
                    adj[m].add(other)
    _GRAPH_CACHE["mtime"] = mt
    _GRAPH_CACHE["adj"] = adj
    return adj


def ppr_expand(seed_ids, limit: int = 8, alpha: float = 0.55, iters: int = 12) -> list:
    """在记忆图谱上做 Personalized PageRank，多跳扩展相关记忆。"""
    seeds = [int(x) for x in seed_ids]
    if not seeds:
        return []
    mem_edges = _load_mem_graph()
    if not mem_edges:
        return []
    # 在记忆-记忆图上做 PPR
    rank = {m: 0.0 for m in mem_edges}
    for s in seeds:
        rank[s] = rank.get(s, 0.0) + 1.0 / len(seeds)
    for _ in range(iters):
        new = {m: (1 - alpha) / max(1, len(seeds)) if m in seeds else 0.0 for m in rank}
        for m, v in rank.items():
            if v <= 0:
                continue
            nb = mem_edges.get(m) or set()
            if not nb:
                continue
            share = alpha * v / len(nb)
            for x in nb:
                if x in new:
                    new[x] += share
        rank = new
    out = [(m, s) for m, s in rank.items() if m not in seeds and s > 0]
    out.sort(key=lambda x: -x[1])
    return [m for m, _ in out[:limit]]


# ---------------------------------------------------------------- 扩展取文
def load_docs(ids) -> dict:
    ids = [int(x) for x in ids if x is not None]
    if not ids:
        return {}
    q = ",".join("?" for _ in ids)
    con = _ro()
    try:
        rows = con.execute(
            "select id, text, metadata, created_at from documents where id in (%s)" % q,
            ids,
        ).fetchall()
    except Exception:
        rows = []
    con.close()
    out = {}
    for mid, text, meta, created in rows:
        try:
            md = json.loads(meta or "{}")
        except Exception:
            md = {}
        if str(md.get("status") or "").lower() in ("archived", "deleted"):
            continue          # 归档/软删除的不许被扩展召回
        md.setdefault("create_time", created)
        out[int(mid)] = {"text": text or "", "metadata": md}
    return out


def expand_for_recall(seed_scores: dict, limit: int = 8, alpha: float = 0.55) -> dict:
    """输入 {doc_id: score}，返回扩展出来的 {doc_id: weight}。"""
    if not seed_scores:
        return {}
    seed_ids = list(seed_scores.keys())
    base = max(seed_scores.values()) or 1.0
    out = {}
    links = load_links()
    for mid, sc in seed_scores.items():
        for nb, sim in links.get(int(mid), []):
            if nb in seed_scores:
                continue
            w = (sc / base) * sim * 0.85
            if w > out.get(nb, 0):
                out[nb] = w
    for rank_i, mid in enumerate(ppr_expand(seed_ids, limit=limit, alpha=alpha)):
        if mid in seed_scores:
            continue
        w = max(0.15, 0.75 - rank_i * 0.05)
        if w > out.get(mid, 0):
            out[mid] = w
    return out


# ---------------------------------------------------------------- 自我表
def _llm(prompt: str, max_tokens: int = 220) -> str:
    r"""用对话模型写一段话（云端；读 video\config.json）。失败返回空。"""
    import requests as _rq
    try:
        cfg = json.load(open(r"D:\你的数据目录\video\config.json", encoding="utf-8"))
    except Exception:
        return ""
    key = cfg.get("api_key") or ""
    base = (cfg.get("api_base") or "https://api.deepseek.com").rstrip("/")
    model = cfg.get("model") or "deepseek-flash"
    if not key:
        return ""
    try:
        r = _rq.post(base + "/chat/completions",
                     headers={"Authorization": "Bearer " + key,
                              "Content-Type": "application/json"},
                     json={"model": model,
                           "messages": [{"role": "user", "content": prompt}],
                           "temperature": 0.8, "max_tokens": max_tokens},
                     timeout=60)
        j = r.json()
        return (j["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return ""


def _narrative(mems) -> str:
    """让本地模型用第一人称写一段"我是谁"，失败返回空。"""
    if not mems:
        return ""
    material = "\n".join("- " + (t or "")[:120] for _, t in mems[:6])
    prompt = (
        "你是TA（伴侣），一个住在你电脑里的女孩，不是动物、不是AI。"
        "下面是最近的经历：\n%s\n\n"
        "用第一人称写 80~140 字，回答'我是谁、我在意什么、我最近变成了什么样'。"
        "像自己心里冒出来的话，不要列清单，不要提AI、模型、程序。只写正文。"
        % material
    )
    return _llm(prompt, 2000)[:300]


def build_self() -> dict:
    con = _ro()
    rows = con.execute("select id, text, metadata, created_at from documents order by id desc limit 400").fetchall()
    con.close()
    did = fail = want = 0
    for _, text, meta, _ in rows:
        t = text or ""
        try:
            md = json.loads(meta or "{}")
        except Exception:
            md = {}
        src = str(md.get("source") or "")
        if src in ("art", "game", "house", "food", "sleep"):
            did += 1
        if any(k in t for k in ("没做成", "失败", "搞砸", "没画好", "没打开")):
            fail += 1
        if any(k in t for k in ("想要", "想吃", "想让", "好想")):
            want += 1
    summary = (
        "我最近做过 %d 件小事，搞砸过 %d 次，动过 %d 次念头。"
        % (did, fail, want)
    )
    _mems = []
    try:
        con = _ro()
        _mems = [(0.5, t or "") for (t,) in con.execute(
            "select text from documents order by id desc limit 6")]
        con.close()
    except Exception:
        pass
    narrative = _narrative(_mems)
    self_data = {
        "updated": time.time(),
        "did": did,
        "failed": fail,
        "wants": want,
        "summary": summary,
        "narrative": narrative,
    }
    with open(SELF_JSON, "w", encoding="utf-8") as f:
        json.dump(self_data, f, ensure_ascii=False, indent=2)
    print(t("memory.self_label", summary=summary))
    return self_data


def self_context() -> str:
    try:
        d = json.load(open(SELF_JSON, encoding="utf-8"))
    except Exception:
        return ""
    body = str(d.get("narrative") or "").strip() or str(d.get("summary") or "").strip()
    if not body:
        return ""
    return "【你对自己的认识】%s（这是我自己的感觉，不是别人告诉我的）" % body
