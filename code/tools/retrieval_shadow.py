# -*- coding: utf-8 -*-
"""学习式检索 · Phase 0 shadow 埋点（只记录，不改任何行为）

目的：给"什么时候该查记忆"攒数据。每个检索决策点追加一行 JSON 到
数据目录的 logs/retrieval_shadow.jsonl，字段：
  - 上下文特征（query 是否提过去/线索词/时间词/问句、长度）
  - 当时身体状态（情绪、精力、饥饿…）
  - 结果（查回了多少条、来源通道）

原则：任何异常都吞掉，绝不因此影响主流程；只 append、不读不删。
"""

import json
import os
import re
import time

LOG = r"D:\你的数据目录\logs\retrieval_shadow.jsonl"
MOOD = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
        r"\core\data\plugin_data\astrbot_plugin_companion_mood\state.json")

# 判断"该不该查"用的轻量特征（纯规则，不调模型）
CUE_WORDS = (
    "昨天", "前天", "上次", "之前", "以前", "还记得", "记得", "当时", "那天",
    "前几天", "上周", "上个月", "去年", "第一", "当初", "生日", "纪念",
    "说过", "答应", "承诺", "名字", "是谁", "我叫", "叫我",
)
TIME_WORDS = ("今天", "明天", "昨天", "早上", "中午", "晚上", "现在", "几点", "多久", "刚才", "刚刚")
PAST_RE = re.compile(r"记得|还记得|之前|以前|上次|那天|当时|说过|答应|承诺|是谁|名字|叫")


def _mood():
    try:
        d = json.load(open(MOOD, encoding="utf-8"))
        return {k: d.get(k) for k in
                ("emotion_type", "valence", "energy", "hunger", "thirst",
                 "irritability", "clinginess", "asleep")}
    except Exception:  # noqa: BLE001
        return {}


def features(q):
    """从一句 query 里抠出"要不要查"的线索特征。"""
    q = str(q or "").strip()
    return {
        "len": len(q),
        "has_past": bool(PAST_RE.search(q)),
        "has_cue": any(w in q for w in CUE_WORDS),
        "has_time": any(w in q for w in TIME_WORDS),
        "has_question": ("?" in q or "？" in q or "吗" in q or "呢" in q or "么" in q),
    }


def log(point, **kw):
    """追加一条 shadow 记录。任何异常都静默吞掉。"""
    try:
        rec = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "ts": round(time.time(), 3), "point": point}
        rec.update(kw)
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    log("self_test", query="你昨天答应过我什么？", features=features("你昨天答应过我什么？"), mood=_mood())
    print("shadow 自测写入完成 ->", LOG)
