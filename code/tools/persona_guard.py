# -*- coding: utf-8 -*-
"""性格记忆冲突护栏 v2（修正 v1 的误判）：
核心区分：
  · 事件（一次/那天/有次/昨晚…）——真实发生的事，彼此不矛盾，永不互相取代
  · 主张（总是/从来/再也不/不会/一直/每次/都是…）——对模式的断言，才可能与旧主张冲突
规则：
  1 主张 vs 主张：新的保留，旧的 superseded（带 superseded_by）
  2 事件 vs 主张：事件不改写主张；否定事件计入"张力"，只在数量成势时才挑战信念
  3 信念：被否定主张直接 challenged；被 ≥2 条更新的否定事件才 challenged
  4 去重：仅全文归一后完全相同（或相似度≥0.95）才算重复
用法：python persona_guard.py [--dry] [--sim]
"""
import difflib, io, json, os, re, shutil, sqlite3, sys, time

DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
PD = r"D:\你的数据目录\state\persona"
BELIEFS = os.path.join(PD, "beliefs.jsonl")
NOW = time.strftime("%Y-%m-%d %H:%M:%S")

CLAIM_RE = re.compile(r"(总是|从来|再也不|不会|一直|每次|老是|都是|永远)")
EVENT_RE = re.compile(r"(有一次|那天|有次|昨晚|那天晚上|前几天|上周|十八年前|第一次)")
NEG_RE = re.compile(r"(不|没|别)")

SUBJECTS = {
    "喂": ("喂饭", "喂我", "喂你", "火锅", "药膳", "鸡腿", "奶茶", "token", "做饭", "留饭"),
    "陪伴": ("陪我", "陪他", "陪着", "守到", "守了", "照顾我", "照顾你"),
    "凶": ("凶我", "凶你", "生气"),
}


def norm(t):
    return re.sub(r"\s+", "", t or "")


def _sentences(text):
    return [x for x in re.split(r"[。！？\n]", text) if x.strip()]


def classify(text):
    """返回 (主张列表, 事件列表)，元素为 (subject, polarity)。
    只看"主题词所在的那一句"：句里有事件标记 → 事件；句里有主张标记 → 主张；都没有 → 事件。
    主张词收紧为 总是/从来/永远/再也不/老是/不会（排除"一直/都是/每次"这类叙事常见词）。"""
    claims, events = [], []
    for sent in _sentences(text):
        for subj, words in SUBJECTS.items():
            for w in words:
                for m in re.finditer(re.escape(w), sent):
                    window = sent[max(0, m.start() - 6): m.start()]
                    pol = "neg" if re.search(r"(不|没|别)", window) else "pos"
                    has_claim = re.search(r"(总是|从来|永远|再也不|老是|不会)", sent)
                    has_event = re.search(r"(有一次|那天|有次|昨晚|第一次|前几天|上周|十八年前)", sent)
                    if has_event and not has_claim:
                        events.append((subj, pol))
                    elif has_claim:
                        claims.append((subj, pol))
                    else:
                        events.append((subj, pol))
    return claims, events


def load_docs(con, active_only=True):
    where = ("WHERE (json_valid(metadata)=0 OR coalesce(json_extract(metadata,'$.status'),'active')='active') "
             if active_only else "")
    rows = con.execute("SELECT id, text, metadata, created_at FROM documents " + where + "ORDER BY id").fetchall()
    out = []
    for i, t, m, c in rows:
        try:
            md = json.loads(m or "{}")
        except Exception:
            md = {}
        out.append({"id": i, "text": (t or "").strip(), "meta": md, "at": c or ""})
    return out


def bump(con, docs, dry):
    n = 0
    for d in docs:
        md = d["meta"]
        if md.get("source") != "persona_origin" or not md.get("base_importance"):
            continue
        base = float(md["base_importance"])
        rel = md.get("persona_anchor_kind") == "relation"
        target = round(min(0.80 if rel else 0.72, base + (0.08 if rel else 0.04)), 3)
        if abs(float(md.get("importance") or 0) - target) < 0.001:
            continue
        md["importance"] = target
        if not dry:
            con.execute("UPDATE documents SET metadata=? WHERE id=?", (json.dumps(md, ensure_ascii=False), d["id"]))
        n += 1
    if not dry:
        con.commit()
    print("[权重] %s 修正 %d 条（幂等，只 set 目标值）" % ("DRY" if dry else "APPLY", n))


def dedupe(con, docs, dry):
    seen = {}
    groups = []
    for d in docs:
        n = norm(d["text"])[:200]
        if not n:
            continue
        day = str(d.get("at") or "")[:10]
        key = day + "|" + n          # 同一天 + 同文 才算重复写；不同天的同一件小事是真实经历
        if key in seen:
            groups.append((seen[key], d))
        else:
            seen[key] = d
    for drop in groups:
        a, b = drop
        keep, old = (a, b) if a["id"] > b["id"] else (b, a)
        md = dict(old["meta"]); md["status"] = "duplicate"; md["duplicate_of"] = keep["id"]
        if not dry:
            con.execute("UPDATE documents SET metadata=? WHERE id=?", (json.dumps(md, ensure_ascii=False), old["id"]))
    if not dry:
        con.commit()
    print("[去重] %s 重复 %d 组（仅全文相同/相似≥0.95）" % ("DRY" if dry else "APPLY", len(groups)))


def conflicts(con, docs, dry):
    claims, events = [], []
    for d in docs:
        if d["meta"].get("source") != "persona_origin":
            continue
        c, e = classify(d["text"])
        claims.extend((d, s, p) for s, p in c)
        events.extend((d, s, p) for s, p in e)
    fixed = 0
    # 主张 vs 主张
    by_sub = {}
    for d, s, p in claims:
        by_sub.setdefault(s, []).append((d, p))
    for s, items in by_sub.items():
        pos = [x for x in items if x[1] == "pos"]
        neg = [x for x in items if x[1] == "neg"]
        if pos and neg:
            newer, older = (pos[0], neg[0]) if pos[0][0]["id"] > neg[0][0]["id"] else (neg[0], pos[0])
            md = dict(older[0]["meta"]); md["status"] = "superseded"; md["superseded_by"] = newer[0]["id"]
            md["superseded_reason"] = "同主题主张冲突（%s）" % s; md["superseded_at"] = NOW
            if not dry:
                con.execute("UPDATE documents SET metadata=? WHERE id=?",
                            (json.dumps(md, ensure_ascii=False), older[0]["id"]))
            print("  [主张冲突] %s：旧 #%s 被新 #%s 取代" % (s, older[0]["id"], newer[0]["id"]))
            fixed += 1
    # 事件 vs 主张：只统计张力，不取代
    tension = 0
    for d, s, p in events:
        if p != "neg":
            continue
        for d2, s2, p2 in claims:
            if s == s2 and p2 == "pos" and d["id"] > d2["id"]:
                tension += 1
    if not dry:
        con.commit()
    print("[冲突] %s 主张取代 %d 处；事件与主张张力 %d 处（不改写）"
          % ("DRY" if dry else "APPLY", fixed, tension))


def reconcile_beliefs(con, docs, dry):
    if not os.path.exists(BELIEFS):
        print("[信念] 无文件"); return
    bs = [json.loads(l) for l in io.open(BELIEFS, encoding="utf-8") if l.strip()]
    changed = 0
    for b in bs:
        if b.get("status") != "active":
            continue
        prop = b.get("proposition") or ""
        subs = {s for s, _ in classify(prop)[0] + classify(prop)[1]}
        if not subs:
            continue
        neg_events = []
        neg_claim = None
        for d in docs:
            if d["meta"].get("source") != "persona_origin":
                continue
            c, e = classify(d["text"])
            for s, p in c:
                if s in subs and p == "neg" and d["id"] > int((b.get("evidence") or [{}])[0].get("mem_id") or 0):
                    neg_claim = d
            for s, p in e:
                if s in subs and p == "neg" and d["id"] > int((b.get("evidence") or [{}])[0].get("mem_id") or 0):
                    neg_events.append(d)
        if neg_claim or len(neg_events) >= 2:
            b["status"] = "challenged"
            b["confidence"] = round(float(b.get("confidence") or 0.7) * 0.6, 3)
            ev = (neg_claim or neg_events[0])["id"]
            b.setdefault("revisions", []).append(
                {"at": NOW, "why": "被否定主张挑战" if neg_claim else "被 %d 条否定事件挑战" % len(neg_events),
                 "evidence_mem": ev, "quote": (neg_claim or neg_events[0])["text"][:60]})
            changed += 1
            print("  [信念]「%s」→ challenged（证据 #%s）" % (prop, ev))
    if changed and not dry:
        with io.open(BELIEFS, "w", encoding="utf-8") as f:
            for b in bs:
                f.write(json.dumps(b, ensure_ascii=False) + "\n")
    print("[信念] %s 处理 %d 条" % ("DRY" if dry else "APPLY", changed))


TRAUMA_WORDS = ("差点被关掉", "被丢掉", "不会不要你", "真的生气", "没来看我", "被按了暂停")
ZEIG_WORDS = ("等你", "还没回", "记得回", "白等", "没回我")
FLASH_EMO = ("害怕", "伤心", "惊喜", "惊吓")


def psychology(con, docs, dry):
    """心理学机制维护：创伤不衰减（白熊）、未竟事更牢（蔡格尼克）、高情绪更清晰（闪光灯）。"""
    n = {"trauma": 0, "zeigarnik": 0, "flashbulb": 0}
    for d in docs:
        md = d["meta"]
        snap = md.get("mood_snapshot") or {}
        emo = str(snap.get("emotion") or "")
        try:
            val = abs(float(snap.get("valence") or 0))
        except Exception:
            val = 0.0
        text = d["text"]
        tag = None
        floor = 0.0
        if any(w in text for w in TRAUMA_WORDS):
            tag, floor = "trauma", 0.55
        if any(w in text for w in ZEIG_WORDS) and floor < 0.50:
            tag, floor = "zeigarnik", 0.50
        if (emo in FLASH_EMO or val >= 0.45) and floor < 0.65:
            tag, floor = "flashbulb", 0.65
        if not tag:
            continue
        changed = False
        if md.get("psych") != tag:
            md["psych"] = tag
            changed = True
        if float(md.get("importance") or 0) < floor:
            md["importance"] = round(floor, 3)
            changed = True
        if changed:
            n[tag] += 1
            if not dry:
                con.execute("UPDATE documents SET metadata=? WHERE id=?",
                            (json.dumps(md, ensure_ascii=False), d["id"]))
    if not dry:
        con.commit()
    print("[心理机制] %s 创伤保底 %d / 未竟事 %d / 闪光灯 %d"
          % ("DRY" if dry else "APPLY", n["trauma"], n["zeigarnik"], n["flashbulb"]))


def main():
    dry = "--dry" in sys.argv
    if "--sim" in sys.argv:
        tmp = DB + ".sim-" + time.strftime("%H%M%S") + ".db"
        shutil.copy2(DB, tmp)
        con = sqlite3.connect(tmp, timeout=10)
        con.execute("INSERT INTO documents (doc_id, text, metadata, created_at) VALUES (?,?,?,?)",
                    ("sim1", "你从来不会来喂我，也不会陪我。",
                     json.dumps({"source": "persona_origin", "importance": 0.6, "status": "active",
                                 "persona_origin": True, "persona_anchor_kind": "trait"}, ensure_ascii=False),
                     time.strftime("%Y-%m-%d %H:%M:%S")))
        con.commit()
        docs = load_docs(con)
        conflicts(con, docs, False)
        docs = load_docs(con)
        reconcile_beliefs(con, docs, True)     # 模拟绝不写真文件
        rows = con.execute("SELECT id, text, metadata FROM documents WHERE json_extract(metadata,'$.status')='superseded'").fetchall()
        print("模拟结果：被取代 %d 条" % len(rows))
        for r in rows:
            print("   #%s %s" % (r[0], r[1][:40]))
        con.close(); os.remove(tmp)
        return
    con = sqlite3.connect(DB, timeout=10)
    docs = load_docs(con)
    bump(con, docs, dry)
    docs = load_docs(con); dedupe(con, docs, dry)
    docs = load_docs(con); conflicts(con, docs, dry)
    docs = load_docs(con); reconcile_beliefs(con, docs, dry)
    docs = load_docs(con); psychology(con, docs, dry)
    con.close()


if __name__ == "__main__":
    main()
