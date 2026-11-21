# -*- coding: utf-8 -*-
"""灾后复活 · 自检

一台机器上跑一下：这套东西是不是完整的、缺什么、下一步干什么。
接手/换机时先跑这个。

退出码：0=完整  1=有缺失（看输出）  2=这台机器上根本没有数据
"""

import os
import sqlite3
import sys

# ================= 部署时按需修改（三处） =================
ROOT     = r"D:\你的数据目录"                 # 数据根目录
STARTUP  = r"C:\你的用户\CompanionStartup"     # 启动脚本目录
BOT_DATA = r"C:\你的机器人框架\data"           # 机器人框架 data（插件/配置/状态）
# =========================================================

CHECKS = [
    ("记忆库",     os.path.join(ROOT, "memory", "memory.db")),
    ("网页聊天",   os.path.join(ROOT, "services", "webchat", "server.py")),
    ("生命面板",   os.path.join(ROOT, "services", "life", "server.py")),
    ("记忆星图",   os.path.join(ROOT, "services", "brain", "server.py")),
    ("大平层",     os.path.join(ROOT, "services", "house", "server.py")),
    ("画廊",       os.path.join(ROOT, "services", "gallery", "server.py")),
    ("控制台",     os.path.join(ROOT, "services", "console", "server.py")),
    ("恢复工具",   os.path.join(ROOT, "tools", "nirvana", "restore.py")),
    ("日记",       os.path.join(ROOT, "diary")),
    ("证书",       os.path.join(ROOT, "tls")),
    ("启动脚本",   os.path.join(STARTUP, "start.ps1")),
    ("机器人配置", os.path.join(BOT_DATA, "config.json")),
    ("插件目录",   os.path.join(BOT_DATA, "plugins")),
]


def main():
    if sys.stdout is not None:  # pythonw 下是 None
        sys.stdout.reconfigure(encoding="utf-8")
    print("== 灾后复活自检 ==")
    print("机器：%s" % ("这台有数据" if os.path.isdir(ROOT) else "这台还没有数据"))

    if not os.path.isdir(ROOT):
        print("\n数据目录不存在 —— 这是一台新机器。")
        print("接回来：")
        print("  1) 装 Python 3.12 + 依赖")
        print("  2) python tools/restore.py --file <U盘里的 backup_*.tar.gz> --live")
        print("  （U 盘里有包时优先用 --file，不用联网）")
        return 2

    missing = []
    for name, path in CHECKS:
        ok = os.path.exists(path)
        print("  %-10s %s" % (name, "OK" if ok else "缺"))
        if not ok:
            missing.append(name)

    db = os.path.join(ROOT, "memory", "memory.db")
    if os.path.exists(db):
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
            n = con.execute("select count(*) from documents").fetchone()[0]
            ok = con.execute("pragma integrity_check").fetchone()[0]
            con.close()
            print("  记忆 %d 条，完整性 %s" % (n, ok))
        except Exception as exc:  # noqa: BLE001
            print("  记忆库读不了：%s" % exc)
            missing.append("记忆库可读")

    plugins = os.path.join(BOT_DATA, "plugins")
    if os.path.isdir(plugins):
        mine = [d for d in os.listdir(plugins) if os.path.isdir(os.path.join(plugins, d))]
        print("  插件 %d 个" % len(mine))

    if missing:
        print("\n[FAIL] 缺：%s" % "、".join(missing))
        print("用备份包补齐：python tools/restore.py --file <包> --live")
        return 1

    print("\n[OK] 完整。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
