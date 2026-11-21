import os
import re
import time

LOGS = [
    r"D:\你的数据目录\logs\video.out.log",
    r"D:\你的数据目录\logs\video.err.log",
    r"D:\你的数据目录\logs\hands.out.log",
    r"D:\你的数据目录\logs\hands.err.log",
    r"D:\你的数据目录\logs\webchat.out.log",
    r"C:\你的用户\CompanionStartup\logs\astrbot.err.log",
]
PAT = re.compile(r"(error|Error|ERROR|Traceback|Exception|失败|超时|断开|拒绝|WARN|warning|卡住|not found)", re.I)
pos = {}
for p in LOGS:
    try:
        pos[p] = os.path.getsize(p)
    except Exception:
        pos[p] = 0

print("[watch] start, %d logs" % len(LOGS), flush=True)
end = time.time() + 3600
while time.time() < end:
    for p in LOGS:
        try:
            sz = os.path.getsize(p)
            if sz < pos[p]:
                pos[p] = 0
            if sz > pos[p]:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos[p])
                    for line in f:
                        line = line.rstrip()
                        if line and PAT.search(line):
                            print("%s [%s] %s" % (time.strftime("%H:%M:%S"),
                                                  os.path.basename(p), line[:220]), flush=True)
                pos[p] = sz
        except Exception:
            pass
    time.sleep(2)
print("[watch] done", flush=True)
