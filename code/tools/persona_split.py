# -*- coding: utf-8 -*-
"""人格基座 阶段1：把两份聊天人格按章节拆成 blocks.json（双通道原文入块）。
用法：python persona_split.py --verify   # 生成 + 断言"按 order 拼接 == 两基线字节"
设计出处：lab/research/人格生长模块设计-v2-兼容版.md §4
"""
import hashlib, io, json, os, re, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PERSONA_DIR = r"D:\你的数据目录\state\persona"
SNAP_DIR = os.path.join(PERSONA_DIR, "snapshots")
BLOCKS = os.path.join(PERSONA_DIR, "blocks.json")
QQ_DB = r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\core\data\data_v4.db"

LAYER_MAP = [
    ("b00_intro",   0, "开头身份"),
    ("b02_temper",  2, "你是什么样的（气质基线）"),
    ("b00_dad",     0, "你的你（关系/QQ号/称呼/行为规则）"),
    ("bS_style",   "S", "怎么说话（表达风格基线）"),
    ("b01_guard",   1, "底线"),
    ("bX_examples", "X", "语气参考（few-shot）"),
]


def split_sections(text):
    """在【…】标题处切分；首段=第一个【之前的所有内容。拼接 = "".join == 原文。"""
    parts = re.split(r"(?=【)", text)
    parts = [p for p in parts if p]
    if len(parts) != len(LAYER_MAP):
        raise SystemExit("段落数 %d != 预期 %d，先人工确认 persona 结构" % (len(parts), len(LAYER_MAP)))
    return parts


def load_video():
    cfg = json.load(io.open(r"D:\你的数据目录\video\config.json", encoding="utf-8"))
    return cfg.get("persona", "")


def load_qq():
    con = sqlite3.connect("file:" + QQ_DB + "?mode=ro", uri=True)
    row = con.execute("SELECT system_prompt FROM personas WHERE persona_id='伴侣'").fetchone()
    con.close()
    return row[0] if row else ""


def main():
    os.makedirs(SNAP_DIR, exist_ok=True)
    video = load_video()
    qq = load_qq()
    vparts = split_sections(video)
    qparts = split_sections(qq)
    blocks = []
    for (bid, layer, title), v, q in zip(LAYER_MAP, vparts, qparts):
        blocks.append({"id": bid, "layer": layer, "title": title, "video": v, "qq": q})
    doc = {
        "version": 1,
        "sources": {
            "video": r"D:\你的数据目录\video\config.json #persona",
            "qq": "AstrBot data_v4.db personas(伴侣).system_prompt",
        },
        "blocks": blocks,
        "order": [b["id"] for b in blocks],
    }
    io.open(BLOCKS, "w", encoding="utf-8").write(
        json.dumps(doc, ensure_ascii=False, indent=1))
    for name, text in (("video.baseline.txt", video), ("qq.baseline.txt", qq)):
        p = os.path.join(SNAP_DIR, name)
        io.open(p, "w", encoding="utf-8").write(text)
        io.open(p + ".sha256", "w", encoding="utf-8").write(
            hashlib.sha256(text.encode("utf-8")).hexdigest())
    if "--verify" in sys.argv:
        joined_v = "".join(b["video"] for b in blocks)
        joined_q = "".join(b["qq"] for b in blocks)
        assert joined_v == video, "video 拼接 != 基线（拆分丢失）"
        assert joined_q == qq, "qq 拼接 != 基线（拆分丢失）"
        print("verify OK：blocks 按 order 拼接 == 两基线（video %d 字 / qq %d 字）" % (len(video), len(qq)))
    else:
        print("blocks.json 已生成：%d 块" % len(blocks))


if __name__ == "__main__":
    main()
