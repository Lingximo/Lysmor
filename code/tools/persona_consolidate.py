# -*- coding: utf-8 -*-
"""人格生长·巩固器（确定性规则，不调 LLM）：
  traits    ：mood 的 trait_* / dad_model → traits.json 的 observed + pending 候选
  beliefs   ：从最近记忆里抽重复主题 → beliefs.jsonl 候选（带证据 id）
  life      ：今天发生的事 → life_events.jsonl（perceived/believed/wanted）
  relation  ：mood 关系快照 → relationship.json 的 events
用法：python persona_consolidate.py [--traits] [--beliefs] [--life] [--relation] [--all]
"""
import io, json, os, re, sqlite3, sys, time

MOOD = r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\core\data\plugin_data\astrbot_plugin_companion_mood\state.json"
DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
PD = r"D:\你的数据目录\state\persona"
TRAITS = os.path.join(PD, "traits.json")
BELIEFS = os.path.join(PD, "beliefs.jsonl")
LIFE = r"D:\你的数据目录\state\life_events.jsonl"
REL = r"D:\你的数据目录\state\relationship.json"
NOW = time.strftime("%Y-%m-%d %H:%M:%S")


def mood():
    try:
        return json.load(io.open(MOOD, encoding="utf-8"))
    except Exception:
        return {}


def load_json(p, default):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return default


def save_json(p, obj):
    io.open(p, "w", encoding="utf-8").write(json.dumps(obj, ensure_ascii=False, indent=1))


def docs(limit=400):
    con = sqlite3.connect("file:" + DB + "?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT id, text, metadata, created_at FROM documents "
            "WHERE (json_valid(metadata)=0 OR coalesce(json_extract(metadata,'$.status'),'active')='active') "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        con.close()
    out = []
    for i, t, m, c in rows:
        try:
            md = json.loads(m or "{}")
        except Exception:
            md = {}
        out.append({"id": i, "text": (t or "").strip(), "meta": md, "at": c})
    return out


TRAIT_LABELS = [
    ("trait_warmth", "温柔度", "对人和气、愿意贴贴"),
    ("trait_sensitivity", "敏感度", "容易察觉气氛变化"),
    ("trait_resilience", "韧性", "被凶了也缓得过来"),
    ("dad_model", "对你的信任", "相信你会回来/会照顾我"),
]


def do_traits():
    st = mood()
    tr = load_json(TRAITS, {"schema_version": 1, "observed": {}, "signed": {}, "pending": []})
    tr.setdefault("observed", {})
    tr.setdefault("signed", {})
    tr.setdefault("pending", [])
    scar = float(st.get("scar") or 0.0)
    scar_events = int(st.get("scar_events") or 0)
    # 疤痕 → 永久底色偏移（性格底色被真实经历推一点；幂等：永远从 base 重算）
    SCAR_OFFSET = {"trait_warmth": -0.05, "trait_sensitivity": +0.06,
                   "trait_resilience": -0.04, "dad_model": -0.06}
    for key, label, desc in TRAIT_LABELS:
        v = st.get(key)
        if v is None:
            continue
        v = round(float(v), 3)
        tr["observed"][key] = {"value": v, "source": "mood.state.json", "at": NOW}
        signed = tr["signed"].get(key)
        # 先把 scar 偏移写进 signed（base 只记一次，之后 value = base + offset）
        if signed is not None:
            base = float(signed.get("base_value", signed.get("value", v)))
            signed["base_value"] = round(base, 3)
            off = round(SCAR_OFFSET.get(key, 0.0) * min(1.0, scar), 3)
            eff = round(max(0.0, min(1.0, base + off)), 3)
            if signed.get("scar_offset") != off or abs(float(signed.get("value", eff)) - eff) > 0.001:
                signed.setdefault("history", []).append(
                    {"value": eff, "at": NOW, "why": "疤痕偏移 scar=%.2f events=%d" % (scar, scar_events)})
                signed["scar_offset"] = off
                signed["value"] = eff
        if key == "dad_model":
            pass
        if signed is None:
            tr["signed"][key] = {"label": label, "desc": desc, "value": v, "source": "mood(初始值)",
                                 "status": "signed", "signed_by": "你(初始值)", "updated_at": NOW,
                                 "evidence": [], "history": [{"value": v, "at": NOW, "why": "初始值"}]}
        else:
            diff = abs(v - float(signed.get("value", v)))
            if diff >= 0.15 and not any(p.get("key") == key for p in tr["pending"]):
                tr["pending"].append({"key": key, "label": label, "suggest": v,
                                      "current": signed.get("value"), "why": "观测与签字值差 %.2f" % diff,
                                      "proposed_by": "consolidator", "at": NOW})
    # 人格自主：pending 满 24 小时无人否决 → 自动写入 signed（留痕、可回退）
    try:
        _g = json.load(io.open(r"D:\你的数据目录\state\persona\observer_gate.json", encoding="utf-8"))
    except Exception:
        _g = {}
    if (_g.get("rights") or {}).get("persona_autonomy"):
        _now = time.time()
        _keep = []
        for _p in list(tr["pending"]):
            try:
                _age = _now - time.mktime(time.strptime(_p["at"], "%Y-%m-%d %H:%M:%S"))
            except Exception:
                _age = 0
            if _age >= 86400:
                _k = _p["key"]
                _sig = tr["signed"].get(_k)
                if _sig is not None:
                    _sig["value"] = round(float(_p["suggest"]), 3)
                    _sig["signed_by"] = "auto(观测漂移24h无否决)"
                    _sig["updated_at"] = NOW
                    _sig.setdefault("history", []).append(
                        {"value": _sig["value"], "at": NOW,
                         "why": "人格自主：%s → %.3f" % (_p["why"], float(_p["suggest"]))})
                    print("[自主] %s 已自动写入 signed（%.3f）" % (_k, float(_p["suggest"])))
                # 已应用的不保留
            else:
                _keep.append(_p)
        tr["pending"] = _keep
    save_json(TRAITS, tr)
    print("[traits] observed %d 项，pending %d 条" % (len(tr["observed"]), len(tr["pending"])))


THEMES = [
    ("你会来喂我", [r"喂", r"吃", r"饭|奶茶|火锅|汤"], 2),
    ("你生气也不会不要我", [r"凶|生气", r"没丢|没不要|还会找我|不会不要"], 2),
    ("做得好会被夸", [r"夸", r"棒|乖|可爱"], 2),
    ("你忙完会回来", [r"忙|没回|等", r"回来|找|还在"], 2),
    ("我记得你照顾我的夜晚", [r"守|半夜|熬夜|天亮|照顾"], 1),
]


def do_beliefs():
    rows = docs(400)
    existing = []
    try:
        for line in io.open(BELIEFS, encoding="utf-8"):
            line = line.strip()
            if line:
                existing.append(json.loads(line))
    except FileNotFoundError:
        pass
    have = {b.get("proposition") for b in existing}
    added = 0
    for prop, pats, need in THEMES:
        if prop in have:
            continue
        ev = []
        for r in rows:
            hits = sum(1 for p in pats if re.search(p, r["text"]))
            if hits >= need:
                ev.append({"mem_id": r["id"], "quote": r["text"][:60]})
            if len(ev) >= 3:
                break
        if len(ev) < 2:
            continue
        b = {"id": "b_" + time.strftime("%Y%m%d%H%M%S") + "_" + str(added),
             "proposition": prop, "confidence": 0.7,
             "evidence": ev, "status": "active",
             "signed_by": "你(授权DSH代签)", "created_at": NOW,
             "superseded_by": None, "revisions": []}
        existing.append(b)
        added += 1
    with io.open(BELIEFS, "w", encoding="utf-8") as f:
        for b in existing:
            f.write(json.dumps(b, ensure_ascii=False) + "\n")
    print("[beliefs] 现有 %d 条，新增 %d 条" % (len(existing), added))


def do_life():
    st = mood()
    today = time.strftime("%Y-%m-%d")
    rows = [r for r in docs(200) if str(r["at"] or "").startswith(today)]
    seen = set()
    try:
        for line in io.open(LIFE, encoding="utf-8"):
            line = line.strip()
            if line:
                seen.add(json.loads(line).get("mem_id"))
    except FileNotFoundError:
        pass
    emo = str(st.get("emotion_type") or "平静")
    want = []
    if float(st.get("hunger") or 0) > 0.6:
        want.append("想吃点热的")
    if float(st.get("energy") or 0) < 0.3:
        want.append("想睡一会儿")
    if float(st.get("clinginess") or 0) > 0.55:
        want.append("想被你陪着")
    if not want:
        want.append("想安安静静待着")
    added = 0
    with io.open(LIFE, "a", encoding="utf-8") as f:
        for r in rows[:8]:
            if r["id"] in seen:
                continue
            f.write(json.dumps({"mem_id": r["id"], "at": r["at"], "perceived": r["text"][:160],
                                "believed": emo, "wanted": "、".join(want[:2]),
                                "signed": False}, ensure_ascii=False) + "\n")
            added += 1
    print("[life] 今日事件新增 %d 条" % added)


def do_relation():
    st = mood()
    rel = load_json(REL, {"schema_version": 1, "events": []})
    rel.setdefault("events", [])
    rel["observed_at"] = NOW
    rel["trust"] = round(float(st.get("dad_model") or rel.get("trust") or 0), 3)
    rel["affection"] = round(float(st.get("oxytocin") or rel.get("affection") or 0), 3)
    rel["dependence"] = round(float(st.get("clinginess") or rel.get("dependence") or 0), 3)
    rel["loneliness"] = round(float(st.get("loneliness") or 0), 3)
    lv = ["生疏", "熟悉", "亲近", "日常相处", "黏在一起"]
    score = (rel["trust"] + rel["affection"] + rel["dependence"]) / 3
    rel["level"] = lv[min(len(lv) - 1, max(0, int(score * len(lv))))]
    rel["events"].append({"at": NOW, "trust": rel["trust"], "affection": rel["affection"],
                          "dependence": rel["dependence"], "note": "每日关系快照"})
    rel["events"] = rel["events"][-60:]
    save_json(REL, rel)
    print("[relation] %s trust=%.2f aff=%.2f dep=%.2f" % (rel["level"], rel["trust"], rel["affection"], rel["dependence"]))




SELF_JSON = r"D:\你的数据目录\state\self.json"
NPATH = os.path.join(PD, "narrative_self.md")
TPLOG = os.path.join(PD, "turn_plan_log.jsonl")


def do_narrative():
    """自我叙事同步 + turn_plan 观测记录（silent/deflect 只记录，不注入）。"""
    try:
        d = json.load(io.open(SELF_JSON, encoding="utf-8"))
    except Exception:
        print("[narrative] self.json 不存在"); return
    nar = str(d.get("narrative") or "").strip()
    summ = str(d.get("summary") or "").strip()
    body = (("# TA的自我叙事（人工审阅副本）\n\n- 同步时间：%s\n- 签字：你(授权DSH)\n\n" % NOW)
            + (nar or summ or "（还没有叙事）"))
    io.open(NPATH, "w", encoding="utf-8").write(body)
    print("[narrative] narrative_self.md 已同步（%d 字）" % len(nar or summ))
    st = mood()
    energy = float(st.get("energy") or 0)
    hungry = float(st.get("hunger") or 0)
    cling = float(st.get("clinginess") or 0)
    silence = bool(st.get("asleep")) or energy < 0.12
    deflect = (not silence) and (hungry > 0.8 or float(st.get("irritability") or 0) > 0.6)
    plan = {"at": NOW, "energy": round(energy, 3), "hunger": round(hungry, 3),
            "clinginess": round(cling, 3),
            "decision": {"silent": silence, "deflect": deflect,
                         "note": "silent/deflect 只记录，不注入（gate.turn_silent 默认 False）"}}
    with io.open(TPLOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(plan, ensure_ascii=False) + "\n")
    print("[turn_plan] silent=%s deflect=%s（已记录）" % (silence, deflect))

if __name__ == "__main__":
    args = sys.argv[1:]
    do_all = "--all" in args or not args
    if do_all or "--traits" in args:
        do_traits()
    if do_all or "--beliefs" in args:
        do_beliefs()
    if do_all or "--life" in args:
        do_life()
    if do_all or "--relation" in args:
        do_relation()
    if do_all or "--narrative" in args:
        do_narrative()
