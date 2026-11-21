"""TA记忆大脑：只读可视化服务。

不写数据库、不改插件，只把 LivingMemory 的 graph_nodes / graph_edges
读出来给浏览器画图。默认只监听 127.0.0.1:8006。
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, r"D:\你的数据目录\tools")
import gate  # noqa: E402  共用访问口令

# 遗忘曲线参数直接复用 memoryrhythm，保证大脑里看到的和实际结算的一致
sys.path.insert(0, r"D:\你的数据目录\memoryrhythm")
try:
    import rhythm  # noqa: E402
except Exception:  # noqa: BLE001
    rhythm = None

DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
PORT = 8006


def db():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)


def _safe_db():
    """记忆库还没养成时返回 None，让接口返回空数据而不是 500。"""
    try:
        return db()
    except sqlite3.OperationalError:
        return None


def _json(value, default):
    try:
        return json.loads(value) if value else default
    except Exception:
        return default


def load_graph():
    con = _safe_db()
    if con is None:
        return [], []
    con.row_factory = sqlite3.Row
    nodes = []
    links = []
    try:
        rows = con.execute(
            "SELECT id, node_type, node_value, canonical_value, metadata "
            "FROM graph_nodes"
        ).fetchall()
        for row in rows:
            meta = _json(row["metadata"], {})
            raw = row["canonical_value"] or row["node_value"] or ""
            label = raw.strip()
            if row["node_type"] == "person":
                aliases = meta.get("aliases") or []
                if aliases:
                    label = str(aliases[0])
                sid = str(meta.get("sender_id") or "")
                if sid == "<你的QQ号>":
                    label = "你"
                elif sid == "<你的QQ号2>":
                    label = "TA"
            if len(label) > 46:
                label = label[:44] + "…"
            nodes.append(
                {
                    "id": row["id"],
                    "type": row["node_type"] or "topic",
                    "label": label,
                    "value": raw,
                    "meta": meta,
                }
            )
        ids = {n["id"] for n in nodes}
        edge_rows = con.execute(
            "SELECT source_node_id, target_node_id, relation_type, weight, status "
            "FROM graph_edges"
        ).fetchall()
        for row in edge_rows:
            if row["status"] not in (None, "", "active", "confirmed"):
                continue
            a, b = row["source_node_id"], row["target_node_id"]
            if a in ids and b in ids and a != b:
                links.append(
                    {
                        "source": a,
                        "target": b,
                        "type": row["relation_type"] or "related",
                        "weight": float(row["weight"] or 1.0),
                    }
                )
    finally:
        con.close()
    degree = {}
    for link in links:
        degree[link["source"]] = degree.get(link["source"], 0) + 1
        degree[link["target"]] = degree.get(link["target"], 0) + 1
    for node in nodes:
        node["degree"] = degree.get(node["id"], 0)
    return nodes, links


def load_stats():
    con = _safe_db()
    if con is None:
        return {"nodes": 0, "edges": 0, "documents": 0, "empty": True}
    try:
        def count(table):
            try:
                return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except Exception:
                return 0

        latest = con.execute(
            "SELECT text, created_at, metadata FROM documents ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "nodes": count("graph_nodes"),
            "edges": count("graph_edges"),
            "atoms": count("memory_atoms"),
            "memories": count("documents"),
            "latest": latest[0][:160] if latest else "",
            "latest_time": latest[1] if latest else "",
        }
    finally:
        con.close()


def load_recent(limit=6):
    con = _safe_db()
    if con is None:
        return []
    try:
        rows = con.execute(
            "SELECT id, text, created_at, metadata FROM documents ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for row in rows:
            meta = _json(row[3], {})
            out.append(
                {
                    "id": row[0],
                    "text": (row[1] or "")[:140],
                    "created_at": row[2],
                    "importance": meta.get("importance"),
                }
            )
        return out
    finally:
        con.close()


# ---------------------------------------------------------------- 脑区 / 遗忘
BRAIN_REGIONS = [
    ("brainstem", "脑干", "世界之魂", "#8ab4ff", "她的身份、承诺、最核心的设定"),
    ("amygdala", "杏仁核", "情绪核心", "#fb7185", "带喜怒哀乐的记忆，记得最久"),
    ("hippocampus", "海马体", "编码索引", "#67e8f9", "三天内刚形成、还在编码"),
    ("prefrontal", "前额叶", "检索决策", "#a78bfa", "被反复想起、路径已经固化"),
    ("scn", "视交叉上核", "静默节律", "#fbbf24", "很久没被碰过，正在安静淡出"),
    ("temporal", "颞叶", "社会关系", "#34d399", "人物与关系"),
    ("parietal", "顶叶", "因果线索", "#f472b6", "事实与话题"),
    ("association", "联合皮层", "扩展联想", "#94a3b8", "边角料，靠联想才捞得回来"),
]
REGION_BY_KEY = {r[0]: r for r in BRAIN_REGIONS}


def _ts(value):
    if not value:
        return time.time()
    try:
        return datetime.fromisoformat(str(value)[:19]).timestamp()
    except ValueError:
        return time.time()


def _stability(importance, accesses, sentiment):
    """记忆的"稳固度"（天）—— 数字越大越不容易忘。"""
    base = 6.0
    imp_factor = 0.6 + 2.4 * max(0.0, min(1.0, importance))
    review = 1.0 + 0.9 * math.log(1.0 + max(0.0, accesses))
    emo = 1.2 if sentiment in ("positive", "negative") else 1.0
    return base * imp_factor * review * emo


def _clarity(age_days, stability):
    """艾宾浩斯式清晰度：R = e^(-t/S)。"""
    return math.exp(-max(0.0, age_days) / max(0.5, stability))


def _regions_for(importance, age, accesses, sentiment, silent_days, kind):
    """决定这条记忆"住在"哪个脑区。

    顺序即优先级，每一条都有我们自己的依据：
      脑干   importance >= 0.95   她的身份、承诺、最核心的设定
      静默核 超过 7 天没被碰        正在安静淡出
      前额叶 被调用 >= 20 次        检索路径已经固化
      海马体 形成不到 1 天          还在编码
      杏仁核 带情绪                情绪的印记
      颞叶   涉及人物              社会关系
      顶叶   其余的事实/话题        因果线索
      联合皮层 其他                靠联想才捞得回来
    返回 (主脑区, 全部命中脑区)。
    """
    hits = []
    if importance >= 0.95:
        hits.append("brainstem")
    if silent_days > 7:
        hits.append("scn")
    if accesses >= 20:
        hits.append("prefrontal")
    if age < 1:
        hits.append("hippocampus")
    if sentiment in ("positive", "negative"):
        hits.append("amygdala")
    if kind == "person":
        hits.append("temporal")
    if kind in ("fact", "topic"):
        hits.append("parietal")
    if importance < 0.45:
        hits.append("association")
    if not hits:
        hits.append("association")
    return hits[0], hits


def _phase(importance, age):
    if importance >= 0.7:
        return "刻在心里"
    if age < 1:
        return "还新鲜"
    if importance >= 0.55:
        return "记得清楚"
    if importance >= 0.45:
        return "有点模糊"
    if importance >= 0.3:
        return "快忘了"
    return "几乎想不起"


def load_decay():
    """给"记忆大脑"的遗忘曲线面板用：每条记忆的清晰度 + 脑区归属。"""
    con = _safe_db()
    if con is None:
        return {"items": [], "empty": True}
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, text, created_at, metadata FROM documents"
        ).fetchall()
        now = time.time()
        items = []
        for row in rows:
            meta = _json(row["metadata"], {})
            imp = meta.get("importance")
            if imp is None:
                continue
            imp = float(imp)
            age = (now - _ts(row["created_at"])) / 86400.0
            accesses = float(meta.get("access_count") or 0)
            last = float(meta.get("last_access_time") or 0)
            sentiment = meta.get("sentiment")
            silent = (now - last) / 86400.0 if last else age
            stability = _stability(imp, accesses, sentiment)
            kind = "memory"
            try:
                topics = meta.get("topics") or []
                if any(str(t) in ("你", "家人") for t in topics):
                    kind = "person"
                elif topics:
                    kind = "topic"
            except Exception:  # noqa: BLE001
                pass
            protected = imp >= 0.7
            clarity = 1.0 if protected else _clarity(age, stability)
            region, region_list = _regions_for(
                imp, age, accesses, sentiment, silent, kind
            )
            drop_today = 0.0
            if rhythm is not None and not protected:
                try:
                    drop_today = rhythm.explain(
                        imp, age, accesses, last, sentiment
                    )["drop"]
                except Exception:  # noqa: BLE001
                    drop_today = 0.0
            summary = (meta.get("canonical_summary") or row["text"] or "")[:160]
            items.append(
                {
                    "id": row["id"],
                    "summary": summary.replace("\n", " "),
                    "importance": round(imp, 3),
                    "age_days": round(age, 2),
                    "accesses": accesses,
                    "silent_days": round(silent, 1),
                    "sentiment": sentiment or "",
                    "stability": round(stability, 1),
                    "clarity": round(clarity, 4),
                    "protected": protected,
                    "phase": _phase(imp, age),
                    "region": region,
                    "regions": region_list,
                    "drop_today": round(drop_today, 5),
                }
            )
    finally:
        con.close()

    # 按清晰度排，"最危险"的在前
    items.sort(key=lambda x: (x["protected"], x["clarity"]))

    regions = []
    for key, name, role, color, hint in BRAIN_REGIONS:
        group = [i for i in items if i["region"] == key]
        if not group:
            continue
        regions.append(
            {
                "key": key,
                "name": name,
                "role": role,
                "color": color,
                "hint": hint,
                "count": len(group),
                "avg_clarity": round(
                    sum(i["clarity"] for i in group) / len(group), 3
                ),
            }
        )

    phases = {}
    for item in items:
        phases[item["phase"]] = phases.get(item["phase"], 0) + 1

    # 三条参考曲线：左边这条是"没人想起的小事"，右边是"刻在心里的"
    profiles = [
        {"name": "没被想起的小事", "importance": 0.45, "accesses": 0,
         "sentiment": "", "stability": round(_stability(0.45, 0, ""), 1)},
        {"name": "想起过几次", "importance": 0.5, "accesses": 5,
         "sentiment": "", "stability": round(_stability(0.5, 5, ""), 1)},
        {"name": "带情绪的", "importance": 0.6, "accesses": 2,
         "sentiment": "positive", "stability": round(_stability(0.6, 2, "positive"), 1)},
        {"name": "常被想起的重要事", "importance": 0.69, "accesses": 10,
         "sentiment": "positive", "stability": round(_stability(0.69, 10, "positive"), 1)},
    ]

    return {
        "model": {
            "base_rate": 0.008,
            "protected": 0.7,
            "floor": 0.05,
            "cleanup_days": 30,
            "cleanup_importance": 0.45,
            "max_daily_drop": 0.03,
        },
        "items": items,
        "regions": regions,
        "phases": phases,
        "profiles": profiles,
        "count": len(items),
        "avg_clarity": round(
            sum(i["clarity"] for i in items) / len(items), 3
        ) if items else 0,
        "today_drop": round(sum(i["drop_today"] for i in items), 4),
        "generated_at": now,
    }


def search_nodes(query):
    q = (query or "").strip()
    if not q:
        return []
    con = _safe_db()
    if con is None:
        return []
    try:
        rows = con.execute(
            "SELECT id, node_type, node_value, canonical_value FROM graph_nodes "
            "WHERE node_value LIKE ? OR canonical_value LIKE ? LIMIT 20",
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
        return [
            {
                "id": r[0],
                "type": r[1],
                "label": (r[3] or r[2] or "")[:80],
            }
            for r in rows
        ]
    finally:
        con.close()


def node_detail(node_id):
    con = _safe_db()
    if con is None:
        return {"error": "no memory yet"}
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT * FROM graph_nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if not row:
            return {"error": "not found"}
        edges = con.execute(
            "SELECT e.relation_type, n.id, n.node_type, n.canonical_value, n.node_value "
            "FROM graph_edges e JOIN graph_nodes n ON "
            "(n.id = CASE WHEN e.source_node_id = ? THEN e.target_node_id ELSE e.source_node_id END) "
            "WHERE e.source_node_id = ? OR e.target_node_id = ? LIMIT 30",
            (node_id, node_id, node_id),
        ).fetchall()
        return {
            "id": row["id"],
            "type": row["node_type"],
            "value": row["canonical_value"] or row["node_value"],
            "meta": _json(row["metadata"], {}),
            "neighbors": [
                {
                    "id": e[1],
                    "type": e[2],
                    "label": (e[3] or e[4] or "")[:100],
                    "relation": e[0],
                }
                for e in edges
            ],
        }
    finally:
        con.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if gate.guard(self):
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/graph":
                nodes, links = load_graph()
                return self._send_json({"nodes": nodes, "links": links})
            if path == "/api/stats":
                return self._send_json(load_stats())
            if path == "/api/decay":
                return self._send_json(load_decay())
            if path == "/api/recent":
                return self._send_json({"items": load_recent()})
            if path == "/api/search":
                q = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
                return self._send_json({"items": search_nodes(q)})
            if path == "/api/node":
                raw = urllib.parse.parse_qs(parsed.query).get("id", ["0"])[0]
                return self._send_json(node_detail(int(raw)))
            if path in ("/", "/index.html"):
                return self._serve_file("index.html", "text/html; charset=utf-8")
            if path == "/app.js":
                return self._serve_file("app.js", "application/javascript; charset=utf-8")
            if path == "/style.css":
                return self._serve_file("style.css", "text/css; charset=utf-8")
            if path == "/avatar.png":
                return self._serve_file("avatar.png", "image/png")
            return self._send_json({"error": "not found"}, 404)
        except Exception as exc:
            return self._send_json({"error": str(exc)}, 500)

    def _serve_file(self, name, mime):
        full = os.path.join(STATIC, name)
        if not os.path.isfile(full):
            return self._send_json({"error": "missing " + name}, 404)
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    os.makedirs(STATIC, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"TA记忆大脑: http://127.0.0.1:{PORT}  (局域网需口令)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
