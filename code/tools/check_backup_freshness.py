"""检查本地完整备份是否还在、是否过期（只读，不写记忆）。

背景：2026-10-30 发现 LivingMemory 插件每天 00:05 的清理逻辑会无差别删掉
backups 目录里除「最新一份」以外的所有 .db，把 make_backup.py 生成的
livingmemory_complete_*.db 每晚悄悄清掉，于是「唯一完整备份」消失了，
而所有检查都还是绿的。这个脚本专门盯这件事，且不关心是谁删的。

判定：
  - 没有任何 livingmemory_complete_*.db        -> FAIL
  - 最新那份 integrity != ok                   -> FAIL
  - 最新那份超过 60 小时没更新（灾后复活每 2 天刷新一次） -> FAIL
  - 条数比运行库少                             -> 只提示，不算失败
    （记忆是白天陆续写进去的，凌晨备份当然会少几条）

用法:
  python check_backup_freshness.py          # 一行结论
  python check_backup_freshness.py --json   # 给程序用

退出码：0 = 正常；1 = 需要人看一眼
"""
import glob
import json
import os
import sqlite3
import sys
import time

# Windows 控制台默认 GBK，打印 emoji 会 UnicodeEncodeError 把输出打断
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
BACKUP_DIR = r"D:\你的数据目录\livingmemory\backups"
MAX_AGE_HOURS = 60.0


def doc_count(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        docs = con.execute("select count(*) from documents").fetchone()[0]
        return integrity, docs
    finally:
        con.close()


def main():
    as_json = "--json" in sys.argv
    result = {
        "backup": None,
        "age_hours": None,
        "docs": None,
        "live_docs": None,
        "integrity": None,
        "ok": False,
        "reason": "",
    }

    try:
        live_integrity, result["live_docs"] = doc_count(DB)
        if live_integrity != "ok":
            result["reason"] = f"运行库 integrity={live_integrity}"
    except Exception as exc:  # noqa: BLE001
        result["reason"] = f"读运行库失败: {exc}"

    files = glob.glob(os.path.join(BACKUP_DIR, "livingmemory_complete_*.db"))
    if not files:
        result["reason"] = result["reason"] or "没有任何完整备份（complete_*.db 不见了）"
    else:
        newest = max(files, key=os.path.getmtime)
        result["backup"] = os.path.basename(newest)
        result["age_hours"] = round((time.time() - os.path.getmtime(newest)) / 3600, 1)
        try:
            integrity, docs = doc_count(newest)
            result["integrity"] = integrity
            result["docs"] = docs
            if integrity != "ok":
                result["reason"] = result["reason"] or f"备份 integrity={integrity}"
            elif result["age_hours"] > MAX_AGE_HOURS:
                result["reason"] = (
                    result["reason"]
                    or f"备份已经 {result['age_hours']}h 没更新（>{MAX_AGE_HOURS}h）"
                )
            else:
                result["ok"] = not result["reason"]
        except Exception as exc:  # noqa: BLE001
            result["reason"] = result["reason"] or f"读备份失败: {exc}"

    if as_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        if result["ok"]:
            note = ""
            if result["docs"] is not None and result["docs"] < (result["live_docs"] or 0):
                note = f" （比运行库少 {result['live_docs'] - result['docs']} 条，正常）"
            print(
                "backup=%s age=%sh docs=%s live=%s integrity=%s%s"
                % (
                    result["backup"],
                    result["age_hours"],
                    result["docs"],
                    result["live_docs"],
                    result["integrity"],
                    note,
                )
            )
        else:
            print(f"❌ {result['reason']} | {json.dumps(result, ensure_ascii=False)}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
