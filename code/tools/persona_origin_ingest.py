# -*- coding: utf-8 -*-
"""人设事件入记忆库（走官方管线）：
读 state/persona/persona_origin_events.jsonl（candidate），
用 video/bridge.append_pending 写进 pending_memories.json（source=persona_origin），
由 companion_video_bridge 插件每 20 秒消化 3 条 → livingmemory engine.add_memory。
本脚本只负责"喂进队列"，不直接写数据库、不碰任何提示词。
用法：python persona_origin_ingest.py [--dry] [--reset]
"""
import io, json, os, sys, time

sys.path.insert(0, r"D:\你的数据目录\video")
import bridge  # noqa: E402

EVENTS = r"D:\你的数据目录\state\persona\persona_origin_events.jsonl"
MOOD_STATE = ("C:/你的用户/.astrbot_launcher/instances/"
              "<BOT_INSTANCE>/core/data/plugin_data/"
              "astrbot_plugin_companion_mood/state.json")
DONE = r"D:\你的数据目录\state\persona\origin_ingested.json"
PENDING = r"D:\你的数据目录\video\pending_memories.json"


def load_events():
    evs = []
    for line in io.open(EVENTS, encoding="utf-8"):
        line = line.strip()
        if line:
            evs.append(json.loads(line))
    return evs


def load_done():
    try:
        return set(json.load(io.open(DONE, encoding="utf-8")))
    except Exception:
        return set()


def save_done(ids):
    io.open(DONE, "w", encoding="utf-8").write(json.dumps(sorted(ids), ensure_ascii=False, indent=1))


def _snap():
    try:
        st = json.load(io.open(MOOD_STATE, encoding="utf-8"))
    except Exception:
        return None
    return {"emotion": str(st.get("emotion_type") or ""),
            "valence": round(float(st.get("valence") or 0), 3),
            "energy": round(float(st.get("energy") or 0), 3),
            "hunger": round(float(st.get("hunger") or 0), 3),
            "thirst": round(float(st.get("thirst") or 0), 3),
            "irritability": round(float(st.get("irritability") or 0), 3),
            "clinginess": round(float(st.get("clinginess") or 0), 3),
            "scar": round(float(st.get("scar") or 0), 3),
            "at": time.strftime("%Y-%m-%d %H:%M:%S")}


def main():
    dry = "--dry" in sys.argv
    if "--reset" in sys.argv and os.path.exists(DONE):
        os.remove(DONE)
    evs = load_events()
    done = load_done()
    # 已入队但还没被插件消化的，也不要重复入队
    try:
        pend_ids = {it.get("origin_id") for it in bridge.load_pending() if it.get("origin_id")}
    except Exception:
        pend_ids = set()
    queued = 0
    for ev in evs:
        oid = ev["id"]
        if oid in done or oid in pend_ids:
            continue
        if ev.get("status") != "candidate":
            continue
        text = ev["text"]
        imp = float(ev.get("importance", 0.6))
        print(("DRY " if dry else "排队 ") + "%s imp=%.2f %s" % (oid, imp, text[:40]))
        if not dry:
            items = bridge.load_pending()
            items.append({"time": time.time(), "summary": text,
                          "importance": imp, "source": "persona_origin", "origin_id": oid,
                          "mood_snapshot": _snap()})
            bridge.save_pending(items)
            queued += 1
    if queued:
        print("已入队 %d 条（插件每 20 秒消化 3 条）" % queued)
    else:
        print("没有需要入队的（已完成 %d 条）" % len(done))


if __name__ == "__main__":
    main()
