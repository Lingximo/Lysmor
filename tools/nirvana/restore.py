# -*- coding: utf-8 -*-
r"""灾后复活 · 接回来

换新电脑后，用它把整套东西从备份包里接回来。

    python restore.py --file <备份包路径>            # 先解到恢复目录，只打印落点
    python restore.py --file <备份包路径> --live     # 确认后正式铺回原位
    python restore.py --file <备份包路径> --auto     # 这台还没有数据时自动铺回

默认不覆盖：解到 <盘>:\companion_restore_<时间>\ 让你先验，
确认没问题再加 --live。

云端下载：本文件只实现"本地包恢复"。要接网盘自动拉包，
在 upload.py 的"网盘接口"处接你自己的云 API（见 upload.py 顶部说明）。
"""

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import time

# ================= 部署时按需修改（三处） =================
ROOT     = r"D:\你的数据目录"                 # 数据根目录
STARTUP  = r"C:\你的用户\CompanionStartup"     # 启动脚本目录
BOT_DATA = r"C:\你的机器人框架\data"           # 机器人框架 data（插件/配置/状态）
# =========================================================

# 包里的位置 → 本机落点（与 build.py 的 SOURCES 对应）
MOUNTS = {
    "memory":      os.path.join(ROOT, "memory"),
    "services":    os.path.join(ROOT, "services"),
    "tools":       os.path.join(ROOT, "tools"),
    "state":       os.path.join(ROOT, "state"),
    "docs-root":   ROOT,
    "scripts":     os.path.join(ROOT, "scripts"),
    "startup":     STARTUP,
    "plugins":     os.path.join(BOT_DATA, "plugins"),
    "config/bot":  os.path.join(BOT_DATA, "config"),
    "config/app":  os.path.join(ROOT, "config"),
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(tar_path):
    with tarfile.open(tar_path, "r:gz") as tar:
        member = tar.getmember("manifest.json")
        return json.loads(tar.extractfile(member).read().decode("utf-8"))


def verify(tar_path, manifest):
    bad = []
    with tarfile.open(tar_path, "r:gz") as tar:
        for item in manifest["files"]:
            try:
                f = tar.extractfile(item["path"])
                if f is None:
                    bad.append((item["path"], "缺失"))
                    continue
                h = hashlib.sha256(f.read()).hexdigest()
                if h != item["sha256"]:
                    bad.append((item["path"], "hash 不符"))
            except KeyError:
                bad.append((item["path"], "包里没有"))
    return bad


def extract(tar_path, dest):
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tar:
        try:
            tar.extractall(dest, filter="data")
        except TypeError:          # Python < 3.12
            tar.extractall(dest)
    print("已解到：%s" % dest)


def place(stage, live=False):
    """把解出来的东西放到本机位置。live=False 只打印计划。"""
    plan = []
    for arc, target in MOUNTS.items():
        src = os.path.join(stage, arc.replace("/", os.sep))
        if not os.path.exists(src):
            continue
        plan.append((src, target))
    stale_total = 0
    for src, target in plan:
        exists = os.path.exists(target)
        tag = "覆盖" if exists else "新建"
        stale = 0
        if exists and os.path.isdir(src) and os.path.isdir(target):
            keep = set()
            for root, _dirs, files in os.walk(src):
                rel = os.path.relpath(root, src)
                for fn in files:
                    keep.add(os.path.normpath(os.path.join(rel, fn)))
            for root, _dirs, files in os.walk(target):
                rel = os.path.relpath(root, target)
                for fn in files:
                    if os.path.normpath(os.path.join(rel, fn)) not in keep:
                        stale += 1
            stale_total += stale
        extra = ("  <- 目标里另有 %d 个旧文件不会被删" % stale) if stale else ""
        print("  %-8s %s%s" % (tag, target, extra))
        if live:
            if os.path.isdir(src):
                shutil.copytree(src, target, dirs_exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(src, target)
    if live and stale_total:
        print("\n  注意：合并覆盖不会删目标里多出来的 %d 个旧文件。" % stale_total)
        print("  想要和包完全一致，先把目标目录备份后清空，再 --live。")
    return plan


def memory_check(path):
    db = os.path.join(path, "memory", "memory.db")
    if not os.path.exists(db):
        return "没找到记忆库"
    con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
    n = con.execute("select count(*) from documents").fetchone()[0]
    ok = con.execute("pragma integrity_check").fetchone()[0]
    con.close()
    return "记忆 %d 条，完整性 %s" % (n, ok)


def main():
    if sys.stdout is not None:  # pythonw 下是 None
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]

    if "--list" in args or "--cloud" in args:
        print("云端下载需要先接网盘接口：见 upload.py 顶部说明。")
        print("现在请用 U 盘/本地包：python restore.py --file <包路径> [--live]")
        return 1

    tar_path = None
    auto = "--auto" in args
    if "--file" in args:
        tar_path = args[args.index("--file") + 1]

    if not tar_path or not os.path.exists(tar_path):
        print("用法：restore.py --file <包路径> [--live | --auto]")
        return 1

    print("包：%s（%.1f MB）" % (tar_path, os.path.getsize(tar_path) / 1e6))
    manifest = read_manifest(tar_path)
    print("打包时间：%s   记忆：%s" % (manifest.get("created_at"),
                                     json.dumps(manifest.get("memory"), ensure_ascii=False)))

    print("正在逐个校验文件…")
    bad = verify(tar_path, manifest)
    if bad:
        print("[FAIL] 有 %d 个文件对不上，停止：" % len(bad))
        for p, why in bad[:10]:
            print("   %s  %s" % (why, p))
        return 1
    print("[OK] %d 个文件全部校验通过" % len(manifest["files"]))

    if auto and not os.path.isdir(ROOT):
        print("\n这台电脑上还没有数据，直接铺回原位")
        args.append("--live")
    elif auto:
        print("\n这台电脑上已有数据，--auto 不覆盖；要真覆盖请显式加 --live")

    live = "--live" in args
    stamp = time.strftime("%Y%m%d_%H%M%S")
    if os.path.isdir("D:\\"):                       # 有 D 盘放 D 盘，没有就放用户目录
        stage = os.path.join("D:\\", "companion_restore_" + stamp)
    else:
        stage = os.path.join(os.path.expanduser("~"), "companion_restore_" + stamp)
    extract(tar_path, stage)
    print("解包后：%s" % memory_check(stage))

    print("\n要放到这些位置：")
    place(stage, live=False)
    if live:
        print("\n开始写入…")
        place(stage, live=True)
        print("\n下一步：")
        print("  1) 装依赖（见包里的 requirements.txt / 说明书）")
        print("  2) 跑 check.py 看还缺什么")
    else:
        print("\n（没加 --live，只是解到恢复目录，没动现有文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
