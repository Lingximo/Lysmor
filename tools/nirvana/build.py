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
import time

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
        print("  ! 本地完整备份失败：%s" % str(exc)[:80])
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
    print("本地完整备份：%s" % os.path.basename(final))
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
        print("  ! 这些目录没进包：%s（新功能目录？请加进 SOURCES）" % ", ".join(warned))
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
            print("  ! 旧包删不掉：%s (%s)" % (os.path.basename(p), str(exc)[:40]))
    if removed:
        print("本地清理：删掉 %d 个旧包" % removed)


def main():
    if sys.stdout is not None:  # pythonw 下是 None
        sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(OUT, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    name = "backup_%s.tar.gz" % stamp
    target = os.path.join(OUT, name)

    items = collect()
    coverage_warnings()
    manifest = {
        "name": "companion-backup",
        "created_at": stamp,
        "created_ts": time.time(),
        "memory": db_stats(),
        "files": [],
        "note": "包里可能含密钥与账号凭据：只放自己的私有云盘/U 盘，不要外传。",
    }
    print("收集到 %d 个文件，开始打包…" % len(items))

    total = 0
    stage = os.path.join(ROOT, "backup", "staging")
    os.makedirs(stage, exist_ok=True)
    with tarfile.open(target, "w:gz", compresslevel=6) as tar:
        for full, arc in items:
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            total += size
            if full.lower().endswith((".db", ".sqlite", ".sqlite3")):
                snap = os.path.join(stage, arc.replace("/", "__"))
                try:
                    snapshot_db(full, snap)
                    tar.add(snap, arcname=arc)
                    manifest["files"].append({"path": arc, "size": os.path.getsize(snap),
                                              "sha256": sha256(snap), "snapshot": True})
                except Exception as exc:  # noqa: BLE001
                    print("  ! 快照失败，退回原文件：%s (%s)" % (arc, str(exc)[:60]))
                    tar.add(full, arcname=arc)
                    manifest["files"].append({"path": arc, "size": size, "sha256": sha256(full)})
                continue
            tar.add(full, arcname=arc)
            manifest["files"].append({"path": arc, "size": size, "sha256": sha256(full)})

        for extra in ("README.md", "INSTALL.md", "requirements.txt"):
            p = os.path.join(ROOT, "tools", extra)
            if os.path.exists(p):
                tar.add(p, arcname=extra)
        raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(raw)
        info.mtime = int(time.time())
        tar.addfile(info, io.BytesIO(raw))

    size = os.path.getsize(target)
    try:
        import shutil as _sh
        _sh.rmtree(stage, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
    local_complete_snapshot()
    final_sha = sha256(target)
    print("完成：%s" % target)
    print("原始 %.1f MB  →  压缩后 %.1f MB  （%d 个文件）" % (total / 1e6, size / 1e6, len(items)))
    print("记忆：%s" % json.dumps(manifest["memory"], ensure_ascii=False))
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
