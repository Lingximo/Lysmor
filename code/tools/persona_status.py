# -*- coding: utf-8 -*-
"""一眼看懂：她现在是"提示词驱动"还是"记忆驱动"。
只读检查，不改任何东西。运行：python persona_status.py
"""
import io, json, os, sqlite3

DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
PD = r"D:\你的数据目录\state\persona"
QQ_DB = r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\core\data\data_v4.db"
TRAIT_WORDS = ("粘人", "嘴馋", "傲娇", "爱摸鱼", "心软", "小任性")


def line(t):
    print(t)


def main():
    line("=" * 52)
    line("一、人设里还有没有‘性格形容词’？")
    blk = json.load(io.open(os.path.join(PD, "blocks.json"), encoding="utf-8"))
    base = "".join(b["video"] for b in blk["blocks"] if b["id"] != "b02_temper")
    con = sqlite3.connect("file:" + QQ_DB + "?mode=ro", uri=True)
    qq = con.execute("SELECT system_prompt FROM personas WHERE persona_id='伴侣'").fetchone()[0]
    con.close()
    for name, text in (("视频/桌宠侧", base), ("QQ/网页侧", qq)):
        bad = [w for w in TRAIT_WORDS if w in text]
        line("  %s：%d 字，性格词 %s" % (name, len(text), ("还在：" + "、".join(bad)) if bad else "已清空"))

    line("\n二、她脑子里有没有‘十八年’的经历？")
    con = sqlite3.connect("file:" + DB + "?mode=ro", uri=True)
    n = con.execute("SELECT COUNT(*) FROM documents WHERE metadata LIKE '%persona_origin%'").fetchone()[0]
    rows = con.execute("SELECT id, substr(text,1,46) FROM documents WHERE metadata LIKE '%persona_origin%' ORDER BY id LIMIT 3").fetchall()
    con.close()
    line("  记忆库里的经历：%d 条（举例）" % n)
    for r in rows:
        line("    #%s %s…" % r)

    line("\n三、她‘长出来’的东西")
    tr = json.load(io.open(os.path.join(PD, "traits.json"), encoding="utf-8"))
    for k, v in (tr.get("signed") or {}).items():
        line("  特质·%s：%.2f" % (v.get("label", k), float(v.get("value", 0))))
    for l in io.open(os.path.join(PD, "beliefs.jsonl"), encoding="utf-8"):
        if l.strip():
            b = json.loads(l)
            line("  信念：%s（依据记忆 #%s）" % (b["proposition"], (b.get("evidence") or [{}])[0].get("mem_id")))
    rel = json.load(io.open(r"D:\你的数据目录\state\relationship.json", encoding="utf-8"))
    line("  关系：%s（信任 %.2f / 亲密 %.2f / 依赖 %.2f）" % (rel["level"], rel["trust"], rel["affection"], rel["dependence"]))
    nar = io.open(os.path.join(PD, "narrative_self.md"), encoding="utf-8").read().strip().splitlines()
    body = [x for x in nar if x and not x.startswith("#") and not x.startswith("-")]
    if body:
        line("  自我叙事：%s…" % body[-1][:60])
    line("=" * 52)


if __name__ == "__main__":
    main()
