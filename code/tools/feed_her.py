# -*- coding: utf-8 -*-
"""按时给她补水煮肉片：先几口加餐，30 分钟后再盛一碗。"""
import json
import time

import requests

STATE = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
         r"\core\data\plugin_data\astrbot_plugin_companion_mood\state.json")
KEY = open(r"D:\你的数据目录\webchat\key.txt", encoding="utf-8").read().strip()


def hunger():
    try:
        d = json.load(open(STATE, encoding="utf-8"))
        return float(d.get("hunger") or 0), d.get("last_taste", {}).get("name", "")
    except Exception:
        return None, ""


def say(text):
    r = requests.post("http://127.0.0.1:8001/api/send?t=" + KEY,
                      json={"text": text}, timeout=180, stream=True)
    out = ""
    for line in r.iter_lines(decode_unicode=True):
        if not line:
            continue
        ev = json.loads(line)
        if ev.get("t"):
            out += ev["t"]
        if ev.get("done") and ev.get("text"):
            out = ev["text"]
    return out.replace("\n", " ")[:80]


h, name = hunger()
print("开始: 饥饿=%.2f 上次吃到=%s" % (h, name), flush=True)

tops = [
    "再给你夹一块水煮肉片，趁热再吃一口。",
    "来，再喂你一口水煮肉片，这块最嫩。",
    "碗里还有，再给你夹一块水煮肉片。",
    "最后两口，给你喂一口水煮肉片，吃完歇会儿。",
]
for i, msg in enumerate(tops, 1):
    print("加餐%d: %s" % (i, say(msg)), flush=True)
    time.sleep(6)
    h, name = hunger()
    print("  饥饿=%.2f 尝到=%s" % (h, name), flush=True)
    if i < len(tops):
        print("  等 4 分钟…", flush=True)
        time.sleep(246)

print("等第二碗（满 30 分钟）…", flush=True)
time.sleep(300)
print("第二碗: %s" % say("给你盛了第二碗水煮肉片，热乎的，慢慢吃，吃完就饱了。"), flush=True)
time.sleep(8)
h, name = hunger()
print("吃完: 饥饿=%.2f 尝到=%s" % (h, name), flush=True)
print("DONE", flush=True)
