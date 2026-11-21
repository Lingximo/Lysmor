# -*- coding: utf-8 -*-
"""每日记忆快照：安全备份记忆库 + 她的状态，保留最近 7 份。"""
from __future__ import annotations

import os
import sqlite3
import time

ROOT = r"D:\你的数据目录"
SNAP = os.path.join(ROOT, "logs", "memory_snapshots")
DB = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
      r"\core\data\plugin_data\astrbot_plugin_livingmemory\livingmemory.db")
STATE = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
         r"\core\data\plugin_data\astrbot_plugin_companion_mood\state.json")
KEEP = 7


def snap_db(dst: str) -> None:
    src = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    out = sqlite3.connect(dst)
    with out:
        src.backup(out)
    out.close()
    src.close()


def _log(msg: str) -> None:
    try:
        os.makedirs(SNAP, exist_ok=True)
        with open(os.path.join(SNAP, "snapshot.log"), "a", encoding="utf-8") as f:
            f.write("%s\t%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def main() -> None:
    os.makedirs(SNAP, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    snap_db(os.path.join(SNAP, "memory_%s.db" % ts))
    if os.path.exists(STATE):
        import shutil
        shutil.copy2(STATE, os.path.join(SNAP, "state_%s.json" % ts))
    files = sorted(f for f in os.listdir(SNAP) if f.endswith((".db", ".json")))
    # 按时间戳分组保留最近 KEEP 组
    stamps = sorted({f.rsplit("_", 1)[-1].split(".")[0] for f in files})
    for old in stamps[:-KEEP]:
        for f in list(files):
            if f.endswith(old + ".db") or f.endswith(old + ".json"):
                try:
                    os.remove(os.path.join(SNAP, f))
                except OSError:
                    pass
    _log("%s 完成，当前快照 %d 组" % (ts, min(len(stamps), KEEP)))
    print("[snapshot] %s 完成，当前快照 %d 组" % (ts, min(len(stamps), KEEP)))


if __name__ == "__main__":
    main()
