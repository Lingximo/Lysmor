# -*- coding: utf-8 -*-
"""灾后复活 · 自检

一台机器上跑一下：这套东西是不是完整的、缺什么、下一步干什么。
接手/换机时先跑这个。

退出码：0=完整  1=有缺失（看输出）  2=这台机器上根本没有数据
"""

import os
import sqlite3
import sys

from pathlib import Path

for _parent in Path(__file__).resolve().parents:
    if (_parent / "i18n.py").is_file():
        sys.path.insert(0, str(_parent))
        break
else:
    sys.path.insert(0, r"D:\你的数据目录")
from i18n import t

# ================= 部署时按需修改（三处） =================
ROOT     = r"D:\你的数据目录"                 # 数据根目录
STARTUP  = r"C:\你的用户\CompanionStartup"     # 启动脚本目录
BOT_DATA = r"C:\你的机器人框架\data"           # 机器人框架 data（插件/配置/状态）
# =========================================================

CHECKS = [
    (t('nirvana.memory_database'),     os.path.join(ROOT, "memory", "memory.db")),
    (t('nirvana.webchat'),   os.path.join(ROOT, "services", "webchat", "server.py")),
    (t('nirvana.life_panel'),   os.path.join(ROOT, "services", "life", "server.py")),
    (t('nirvana.memory_graph'),   os.path.join(ROOT, "services", "brain", "server.py")),
    (t('nirvana.house'),     os.path.join(ROOT, "services", "house", "server.py")),
    (t('nirvana.gallery'),       os.path.join(ROOT, "services", "gallery", "server.py")),
    (t('nirvana.console'),     os.path.join(ROOT, "services", "console", "server.py")),
    (t('nirvana.recovery_tools'),   os.path.join(ROOT, "tools", "nirvana", "restore.py")),
    (t('nirvana.diary'),       os.path.join(ROOT, "diary")),
    (t('nirvana.certificates'),       os.path.join(ROOT, "tls")),
    (t('nirvana.startup_scripts'),   os.path.join(STARTUP, "start.ps1")),
    (t('nirvana.bot_config'), os.path.join(BOT_DATA, "config.json")),
    (t('nirvana.plugin_directory'),   os.path.join(BOT_DATA, "plugins")),
]


def main():
    if sys.stdout is not None:  # pythonw 下是 None
        sys.stdout.reconfigure(encoding="utf-8")
    print(t('nirvana.recovery_self_check'))
    print(t('nirvana.machine_s_114004') % (t('nirvana.data_exists_on_this_machine') if os.path.isdir(ROOT) else t('nirvana.no_data_on_this_machine_yet')))

    if not os.path.isdir(ROOT):
        print(t('nirvana.data_directory_does_not_exist_this_is'))
        print(t('nirvana.recovery_steps'))
        print(t('nirvana.install_python_and_dependencies'))
        print(t('nirvana.python_tools_restore_py_file_backup_tar'))
        print(t('nirvana.use_file_for_a_usb_backup_no'))
        return 2

    missing = []
    for name, path in CHECKS:
        ok = os.path.exists(path)
        print("  %-10s %s" % (name, "OK" if ok else t('nirvana.missing')))
        if not ok:
            missing.append(name)

    db = os.path.join(ROOT, "memory", "memory.db")
    if os.path.exists(db):
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
            n = con.execute("select count(*) from documents").fetchone()[0]
            ok = con.execute("pragma integrity_check").fetchone()[0]
            con.close()
            print(t('nirvana.d_memories_integrity_s') % (n, ok))
        except Exception as exc:  # noqa: BLE001
            print(t('nirvana.cannot_read_memory_database_s') % exc)
            missing.append(t('nirvana.memory_database_readability'))

    plugins = os.path.join(BOT_DATA, "plugins")
    if os.path.isdir(plugins):
        mine = [d for d in os.listdir(plugins) if os.path.isdir(os.path.join(plugins, d))]
        print(t('nirvana.d_plugins') % len(mine))

    if missing:
        print(t('nirvana.fail_missing_s') % "、".join(missing))
        print(t('nirvana.restore_missing_items_python_tools_restore_py'))
        return 1

    print(t('nirvana.ok_complete'))
    return 0


if __name__ == "__main__":
    sys.exit(main())
