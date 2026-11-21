# -*- coding: utf-8 -*-
"""C. 她此刻的"状态向量"：身体 + 关系 + 自我（特质/信念/叙事） + 记忆，合成一份 she_state.json。
这是回复/陪玩/桌宠共用的单一事实来源（未来新功能都读它，不各写各的）。
用法：python she_state.py [--check]
"""
import io, json, os, sqlite3, sys, time

MOOD = r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\core\data\plugin_data\astrbot_plugin_companion_mood\state.json"
DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
OUT = r"D:\你的数据目录\state\she_state.json"
PD = r"D:\你的数据目录\state\persona"
REL = r"D:\你的数据目录\state\relationship.json"


def _f(st, k, d=0.0):
    try:
        return round(float(st.get(k) or d), 3)
    except Exception:
        return d


def build():
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    st = {}
    try:
        st = json.load(io.open(MOOD, encoding="utf-8"))
    except Exception:
        pass
    rel = {}
    try:
        rel = json.load(io.open(REL, encoding="utf-8"))
    except Exception:
        pass
    tr = {"signed": {}}
    try:
        tr = json.load(io.open(os.path.join(PD, "traits.json"), encoding="utf-8"))
    except Exception:
        pass
    beliefs = []
    try:
        beliefs = [json.loads(l) for l in io.open(os.path.join(PD, "beliefs.jsonl"), encoding="utf-8") if l.strip()]
    except Exception:
        pass
    mem = {"last_id": 0, "origin_active": 0, "total_active": 0}
    try:
        con = sqlite3.connect("file:" + DB + "?mode=ro", uri=True, timeout=5)
        mem["total_active"] = con.execute(
            "SELECT COUNT(*) FROM documents WHERE (json_valid(metadata)=0 OR coalesce(json_extract(metadata,'$.status'),'active')='active')").fetchone()[0]
        mem["origin_active"] = con.execute(
            "SELECT COUNT(*) FROM documents WHERE metadata LIKE '%persona_origin%' AND (json_valid(metadata)=0 OR coalesce(json_extract(metadata,'$.status'),'active')='active')").fetchone()[0]
        r = con.execute("SELECT MAX(id) FROM documents").fetchone()
        mem["last_id"] = int(r[0] or 0)
        con.close()
    except Exception:
        pass
    doc = {
        "schema_version": 1,
        "generated_at": now,
        "stale_after_sec": 300,
        "body": {
            "emotion": str(st.get("emotion_type") or ""),
            "valence": _f(st, "valence"),
            "energy": _f(st, "energy"),
            "hunger": _f(st, "hunger"),
            "thirst": _f(st, "thirst"),
            "irritability": _f(st, "irritability"),
            "clinginess": _f(st, "clinginess"),
            "loneliness": _f(st, "loneliness"),
            "scar": _f(st, "scar"),
            "asleep": bool(st.get("asleep")),
        },
        "relation": {
            "level": str(rel.get("level") or ""),
            "trust": round(float(rel.get("trust") or 0), 3),
            "affection": round(float(rel.get("affection") or 0), 3),
            "dependence": round(float(rel.get("dependence") or 0), 3),
        },
        "self": {
            "traits": {k: {"label": v.get("label"), "value": float(v.get("value", 0)),
                           "scar_offset": float(v.get("scar_offset", 0))}
                       for k, v in (tr.get("signed") or {}).items() if v.get("label")},
            "beliefs_active": [b["proposition"] for b in beliefs if b.get("status") == "active"],
            "beliefs_total": len(beliefs),
        },
        "memory": mem,
    }
    io.open(OUT, "w", encoding="utf-8").write(json.dumps(doc, ensure_ascii=False, indent=1))
    return doc


def check():
    try:
        d = json.load(io.open(OUT, encoding="utf-8"))
        age = time.time() - time.mktime(time.strptime(d["generated_at"], "%Y-%m-%d %H:%M:%S"))
    except Exception:
        print("RESULT: MISSING"); sys.exit(1)
    ok = d.get("schema_version") == 1 and "body" in d and "relation" in d and "self" in d and "memory" in d
    fresh = age <= max(300, d.get("stale_after_sec", 300) * 4)
    print("RESULT: %s | age %.0fs | 身体=%s 关系=%s 特质=%d 信念=%d/%d 记忆last=%s origin=%d"
          % ("OK" if (ok and fresh) else "STALE", age,
             d["body"]["emotion"], d["relation"]["level"],
             len(d["self"]["traits"]),
             len(d["self"]["beliefs_active"]), d["self"]["beliefs_total"],
             d["memory"]["last_id"], d["memory"]["origin_active"]))
    sys.exit(0 if (ok and fresh) else 1)


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    else:
        build()
        check()
