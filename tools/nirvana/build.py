# -*- coding: utf-8 -*-
"""灾后复活 · 打包（通用版）

把"重建一个 AI 伴侣"需要的全部原创文件打成整包：
  记忆库（含快照）、代码、配置、状态、启动脚本、交接文档。
不打包：模型权重、第三方软件、日志、缓存、备份本身。

用法：
    python build.py
产物：
    <数据目录>\\backup\\out\\backup_YYYYMMDD_HHMMSS.tar.gz + latest.json

部署说明：
    把 tools\\ 整个目录拷进你的数据目录后运行；下面三处路径按实际改。
"""

import glob
import hashlib
import io
import json
import os
import sqlite3
import sys
import tarfile
import tempfile
import time
import shutil

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

OUT = os.path.join(ROOT, "backup", "out")

# 来源目录 → 包内位置（与本仓库 services/ 布局一致，按你的实际目录增删）
SOURCES = [
    (os.path.join(ROOT, "memory"), "memory"),
    (os.path.join(ROOT, "services"), "services"),
    (os.path.join(ROOT, "tools"), "tools"),
    (os.path.join(ROOT, "docs"), "docs-root"),
    (os.path.join(ROOT, "scripts"), "scripts"),
    (os.path.join(ROOT, "config"), "config/app"),
    (os.path.join(ROOT, "state"), "state"),
    (STARTUP, "startup"),
]

# 插件只挑你自己的（留空前缀 = 全部；示例：("my_plugin_", "companion_")）
PLUGIN_DIR = os.path.join(BOT_DATA, "plugins")
PLUGIN_PREFIXES = ()

# 机器人框架的主配置，必进包
CONFIG_FILES = [
    (os.path.join(BOT_DATA, "config.json"), "config/bot/config.json"),
]
PLUGIN_DATA = os.path.join(BOT_DATA, "plugin_data")

# 永远不打包的目录 / 后缀
SKIP_DIRS = {"__pycache__", ".git", "node_modules", "backups", "backup",
             "out", "logs", "tmp", "staging", "models", "installers"}
SKIP_SUFFIX = (".pyc", ".log", ".tmp", ".crdownload", "-wal", "-shm")


def skip(name):
    if name in SKIP_DIRS:
        return True
    if name.endswith(SKIP_SUFFIX):
        return True
    if ".bak-" in name or name.endswith(".bak"):
        return True
    return False


def snapshot_db(src, dst):
    """用 SQLite 自带备份接口快照，避免边写边拷拷出半个事务。"""
    con = sqlite3.connect("file:%s?mode=ro" % src.replace("\\", "/"), uri=True)
    out = sqlite3.connect(dst)
    try:
        con.backup(out)
    finally:
        out.close()
        con.close()


def local_complete_snapshot():
    """打包时顺手在本地留一份完整快照，只保留最新一份。"""
    live = os.path.join(ROOT, "memory", "memory.db")
    if not os.path.exists(live):
        return None
    backup_dir = os.path.join(ROOT, "memory", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    final = os.path.join(backup_dir, "memory_complete_%s.db" % stamp)
    tmp = final + ".tmp"
    try:
        snapshot_db(live, tmp)
        os.replace(tmp, final)
    except Exception as exc:  # noqa: BLE001
        print(t('nirvana.complete_local_backup_failed_s') % str(exc)[:80])
        return None
    for p in glob.glob(os.path.join(backup_dir, "memory_complete_*.db")):
        if os.path.abspath(p) == os.path.abspath(final):
            continue
        try:
            os.remove(p)
            for suffix in ("-wal", "-shm"):
                side = p + suffix
                if os.path.exists(side):
                    os.remove(side)
        except OSError:
            pass
    print(t('nirvana.complete_local_backup_s') % os.path.basename(final))
    return final


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def db_stats():
    """记忆库统计（若没有 documents 表会自动跳过）。"""
    db = os.path.join(ROOT, "memory", "memory.db")
    if not os.path.exists(db):
        return {}
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
        out = {
            "documents": con.execute("select count(*) from documents").fetchone()[0],
            "integrity": con.execute("pragma integrity_check").fetchone()[0],
        }
        con.close()
        return out
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}


def collect():
    """返回 [(绝对路径, 包内路径), ...]"""
    items = []
    for src, arc in SOURCES:
        if not os.path.isdir(src):
            continue
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames[:] = [d for d in dirnames if not skip(d)]
            for fn in filenames:
                if skip(fn):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, src)
                items.append((full, arc + "/" + rel.replace("\\", "/")))

    if os.path.isdir(PLUGIN_DIR):
        for name in sorted(os.listdir(PLUGIN_DIR)):
            if PLUGIN_PREFIXES and not name.startswith(PLUGIN_PREFIXES):
                continue
            pdir = os.path.join(PLUGIN_DIR, name)
            if not os.path.isdir(pdir):
                continue
            for dirpath, dirnames, filenames in os.walk(pdir):
                dirnames[:] = [d for d in dirnames if not skip(d)]
                for fn in filenames:
                    if skip(fn):
                        continue
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, PLUGIN_DIR)
                    items.append((full, "plugins/" + rel.replace("\\", "/")))

    for full, arc in CONFIG_FILES:
        if os.path.exists(full):
            items.append((full, arc))

    if os.path.isdir(PLUGIN_DATA):
        for dirpath, dirnames, filenames in os.walk(PLUGIN_DATA):
            dirnames[:] = [d for d in dirnames if not skip(d)]
            for fn in filenames:
                if skip(fn):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, PLUGIN_DATA)
                items.append((full, "state/plugin_data/" + rel.replace("\\", "/")))

    for fn in sorted(os.listdir(ROOT)):
        full = os.path.join(ROOT, fn)
        if os.path.isfile(full) and fn.lower().endswith(".md"):
            items.append((full, "docs-root/" + fn))
    return items


IGNORE_TOP = {"logs", "models", "backup"}


def coverage_warnings():
    """打包前提醒：根目录下有没有了、却没进 SOURCES 的目录。"""
    covered = {os.path.basename(os.path.normpath(src)) for src, _ in SOURCES}
    warned = []
    for name in sorted(os.listdir(ROOT)):
        p = os.path.join(ROOT, name)
        if not os.path.isdir(p):
            continue
        if name in covered or name in IGNORE_TOP:
            continue
        if name.startswith("backup-") or name.startswith("framework-backup-"):
            continue
        warned.append(name)
    if warned:
        print(t('nirvana.directories_not_included_s_add_new_feature') % ", ".join(warned))
    return warned


def prune_local_packs(keep=1):
    """本地只留最新 keep 个整包；latest.json 指向的永远不删。"""
    try:
        with open(os.path.join(OUT, "latest.json"), encoding="utf-8") as f:
            current = os.path.basename(json.load(f).get("path") or "")
    except Exception:  # noqa: BLE001
        current = ""
    packs = sorted(glob.glob(os.path.join(OUT, "backup_*.tar.gz")))
    keep_set = set()
    if current:
        keep_set.add(os.path.join(OUT, current))
    for p in reversed(packs):
        if len(keep_set) >= keep:
            break
        keep_set.add(p)
    removed = 0
    for p in packs:
        if p in keep_set:
            continue
        try:
            os.remove(p)
            removed += 1
        except Exception as exc:  # noqa: BLE001
            print(t('nirvana.cannot_remove_old_archive_s_s') % (os.path.basename(p), str(exc)[:40]))
    if removed:
        print(t('nirvana.local_cleanup_removed_d_old_archives') % removed)


def main():
    if sys.stdout is not None:  # pythonw 下是 None
        sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(OUT, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    name = "backup_%s.tar.gz" % stamp
    target = os.path.join(OUT, name)
    descriptor, partial = tempfile.mkstemp(prefix=".backup-", suffix=".tmp", dir=OUT)
    os.close(descriptor)

    items = collect()
    coverage_warnings()
    manifest = {
        "name": "companion-backup",
        "created_at": stamp,
        "created_ts": time.time(),
        "memory": db_stats(),
        "files": [],
        "note": t('nirvana.the_archive_may_contain_keys_and_credentials'),
    }
    print(t('nirvana.collected_d_files_creating_archive') % len(items))

    total = 0
    stage = tempfile.mkdtemp(prefix="backup-stage-", dir=os.path.join(ROOT, "backup"))
    try:
        with tarfile.open(partial, "w:gz", compresslevel=6) as tar:
            for extra in ("README.md", "INSTALL.md", "requirements.txt"):
                path = os.path.join(ROOT, "tools", extra)
                if os.path.isfile(path):
                    items.append((path, extra))
            for index, (full, arc) in enumerate(items):
                snap = os.path.join(stage, str(index))
                database = full.lower().endswith((".db", ".sqlite", ".sqlite3"))
                if database:
                    try:
                        snapshot_db(full, snap)
                    except Exception as exc:  # noqa: BLE001
                        raise RuntimeError(t('nirvana.database_snapshot_failed') % arc) from exc
                else:
                    shutil.copyfile(full, snap)
                size = os.path.getsize(snap)
                total += size
                tar.add(snap, arcname=arc)
                entry = {"path": arc, "size": size, "sha256": sha256(snap)}
                if database:
                    entry["snapshot"] = True
                manifest["files"].append(entry)
            raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            info = tarfile.TarInfo("manifest.json")
            info.size = len(raw)
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(raw))
        os.replace(partial, target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if os.path.exists(partial):
            os.remove(partial)

    size = os.path.getsize(target)
    local_complete_snapshot()
    final_sha = sha256(target)
    print(t('nirvana.completed_s') % target)
    print(t('nirvana.original_f_mb_compressed_f_mb_d') % (total / 1e6, size / 1e6, len(items)))
    print(t('nirvana.memories_s') % json.dumps(manifest["memory"], ensure_ascii=False))
    print("sha256：%s" % final_sha)

    with open(os.path.join(OUT, "latest.json"), "w", encoding="utf-8") as f:
        json.dump({"path": target, "name": name, "size": size,
                   "sha256": final_sha, "created": stamp,
                   "memory": manifest["memory"], "files": len(items)},
                  f, ensure_ascii=False, indent=2)

    prune_local_packs(keep=1)
    return target


if __name__ == "__main__":
    main()
