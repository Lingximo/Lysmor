import os
import re
import time

logs = [
    r"D:\你的数据目录\logs\video.out.log",
    r"D:\你的数据目录\logs\video.err.log",
    r"D:\你的数据目录\logs\hands.out.log",
    r"D:\你的数据目录\logs\hands.err.log",
    r"D:\你的数据目录\logs\webchat.err.log",
    r"D:\你的数据目录\logs\webchat.out.log",
    r"C:\你的用户\CompanionStartup\logs\astrbot.err.log",
    r"C:\你的用户\CompanionStartup\logs\astrbot.out.log",
]
pat = re.compile(r"(Traceback|ERROR|Error:|Exception|失败|超时|断开|拒绝|找不到|循环出错|gbk|空回复|broken|unhandled)", re.I)
for p in logs:
    if not os.path.exists(p):
        continue
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-1500:]
    except Exception:
        continue
    hits = [ln.rstrip() for ln in lines if pat.search(ln)]
    if not hits:
        continue
    print("\n===== %s  (%d hits)" % (os.path.basename(p), len(hits)))
    for ln in hits[-12:]:
        print("  " + ln[:230])
