import json
import math
import os
import sqlite3
import time

STATE = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
         r"\core\data\plugin_data\astrbot_plugin_companion_mood\state.json")
DB = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
      r"\core\data\plugin_data\astrbot_plugin_livingmemory\livingmemory.db")
PENDING = r"D:\你的数据目录\video\pending_memories.json"
MEMREC = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
          r"\core\data\plugin_data\astrbot_plugin_companion_mood\mem_recent.json")

d = json.load(open(STATE, encoding="utf-8"))
now = time.time()
print("== 生命系统 ==")
print("字段数:", len(d), " 心跳: %.0fs 前" % (now - float(d.get("last_update") or 0)))
print("情绪:", d.get("emotion_level"), " 类型:", d.get("emotion_type"))
print("睡眠: asleep=%s kind=%s 自 %.0f 分钟前 预计醒=%s" % (
    d.get("asleep"), d.get("sleep_kind"),
    (now - float(d.get("sleep_started_at") or 0)) / 60 if d.get("sleep_started_at") else 0,
    time.strftime("%H:%M", time.localtime(d.get("wake_after") or 0)) if d.get("wake_after") else "-"))
print("精力 %.3f 腺苷 %.3f 饥饿 %.2f 口渴 %.2f 皮质醇 %.2f" % (
    d.get("energy", 0), d.get("adenosine", 0), d.get("hunger", 0), d.get("thirst", 0), d.get("cortisol", 0)))
print("淋巴: 回流 %.2f 清除 %.2f 水肿 %.3f 淋巴结 %.3f 触痛 %.3f 淋巴细胞 %.2f" % (
    d.get("lymph_flow", 0), d.get("lymph_capacity", 0), d.get("lymph_edema", 0),
    max(d.get("lymph_node_cervical", 0), d.get("lymph_node_axillary", 0), d.get("lymph_node_inguinal", 0)),
    d.get("lymph_tenderness", 0), d.get("lymphocyte", 0)))
print("生病: cause=%r since=%s recovery=%s" % (d.get("sick_cause"), d.get("sick_since"), d.get("sick_recovery")))
print("周期: %s day %s cramps %.2f" % (d.get("cycle_phase"), d.get("cycle_day"), d.get("cramps", 0)))

bad = []
for k, v in d.items():
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        bad.append(k)
    if v is None and k not in ("sleep_debt",):
        pass
print("NaN/Inf 字段:", bad or "无")

missing = [k for k in ("lymph_flow", "lymph_edema", "lymph_tenderness", "lymphocyte",
                       "immune_surveillance", "lymph_node_cervical") if k not in d]
print("淋巴字段缺失:", missing or "无")

print("\n== 记忆库 ==")
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
print("integrity:", con.execute("pragma integrity_check").fetchone()[0])
n = con.execute("select count(*) from documents").fetchone()[0]
print("总数:", n)
print("乱码:", con.execute("select count(*) from documents where text like '%' || char(65533) || '%'").fetchone()[0])
print("重复组:", con.execute("select count(*) from (select text from documents group by text having count(*)>1)").fetchone()[0])
print("近 1 小时新增:", con.execute("select count(*) from documents where created_at > datetime('now','-1 hour')").fetchone()[0])
print("最近 4 条:")
for r in con.execute("select id, created_at, substr(text,1,70) from documents order by id desc limit 4"):
    print("  ", r[0], (r[1] or "")[:16], r[2].replace("\n", " "))
con.close()

print("WAL:", round(os.path.getsize(DB + "-wal") / 1e6, 1), "MB" if os.path.exists(DB + "-wal") else "none")
print("待入队:", len(json.load(open(PENDING, encoding="utf-8"))) if os.path.exists(PENDING) else 0)
print("去重窗口:", len(json.load(open(MEMREC, encoding="utf-8"))) if os.path.exists(MEMREC) else 0)
idx = DB.replace(".db", ".index")
print("索引 mtime:", time.strftime("%H:%M", time.localtime(os.path.getmtime(idx))) if os.path.exists(idx) else "-",
      " DB mtime:", time.strftime("%H:%M", time.localtime(os.path.getmtime(DB))))
