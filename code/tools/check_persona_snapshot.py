# -*- coding: utf-8 -*-
import hashlib, io, json, os, sqlite3, sys
SNAP = r"D:\你的数据目录\state\persona\snapshots"
BLOCKS = r"D:\你的数据目录\state\persona\blocks.json"
def sha(t): return hashlib.sha256(t.encode("utf-8")).hexdigest()
def main():
    ok = True
    cfg = json.load(io.open(r"D:\你的数据目录\video\config.json", encoding="utf-8"))
    v = cfg.get("persona", "")
    vs = io.open(os.path.join(SNAP, "video.baseline.txt"), encoding="utf-8").read()
    if v != vs: print("video 人格与基线 DIFF"); ok = False
    else: print("video 人格 == 基线 (%d 字)" % len(v))
    db = r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\core\data\data_v4.db"
    con = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
    q = con.execute("SELECT system_prompt FROM personas WHERE persona_id='伴侣'").fetchone()[0]
    con.close()
    qs = io.open(os.path.join(SNAP, "qq.baseline.txt"), encoding="utf-8").read()
    if q != qs: print("QQ 人格与基线 DIFF"); ok = False
    else: print("QQ 人格 == 基线 (%d 字)" % len(q))
    blk = json.load(io.open(BLOCKS, encoding="utf-8"))
    jv = "".join(b["video"] for b in blk["blocks"]); jq = "".join(b["qq"] for b in blk["blocks"])
    if jv != vs or jq != qs: print("blocks 拼接 != 基线"); ok = False
    else: print("blocks 按 order 拼接 == 两基线")
    gate = json.load(io.open(r"D:\你的数据目录\state\persona\observer_gate.json", encoding="utf-8-sig"))
    print("observer_gate.mode =", gate.get("mode"))
    print("RESULT:", "OK" if ok else "DIFF")
    sys.exit(0 if ok else 1)
if __name__ == "__main__":
    main()
