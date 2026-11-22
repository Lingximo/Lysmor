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
    "state/plugin_data": os.path.join(BOT_DATA, "plugin_data"),
    "config/bot/config.json": os.path.join(BOT_DATA, "config.json"),
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
        members = tar.getmembers()
        names = set()
        for member in members:
            if member.name in names:
                bad.append((member.name, t('nirvana.duplicate_archive_path')))
            names.add(member.name)
        expected = {item["path"] for item in manifest["files"]}
        if len(expected) != len(manifest["files"]):
            bad.append(("manifest.json", t('nirvana.duplicate_manifest_path')))
        # Older packs include these recovery instructions outside the manifest.
        legacy_extras = {"manifest.json", "README.md", "INSTALL.md", "requirements.txt"}
        for member in members:
            if member.isfile() and member.name not in expected | legacy_extras:
                bad.append((member.name, t('nirvana.unlisted_file')))
            if not member.isfile() and not member.isdir():
                bad.append((member.name, t('nirvana.unsupported_member')))
        for item in manifest["files"]:
            try:
                f = tar.extractfile(item["path"])
                if f is None:
                    bad.append((item["path"], t('nirvana.missing_55403')))
                    continue
                with f:
                    h = hashlib.file_digest(f, "sha256").hexdigest()
                if h != item["sha256"]:
                    bad.append((item["path"], t('nirvana.hash_mismatch')))
            except KeyError:
                bad.append((item["path"], t('nirvana.not_in_archive')))
    return bad


def extract(tar_path, dest):
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(dest, filter="data")
    print(t('nirvana.extracted_to_s') % dest)


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
        arc = os.path.relpath(src, stage).replace(os.sep, "/")
        exists = os.path.exists(target)
        tag = t('nirvana.overwrite') if exists else t('nirvana.create')
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
        extra = (t('nirvana.d_extra_old_files_in_the_destination') % stale) if stale else ""
        print("  %-8s %s%s" % (tag, target, extra))
        if live:
            if os.path.isdir(src):
                if arc == "state":
                    os.makedirs(target, exist_ok=True)
                    for name in os.listdir(src):
                        if name == "plugin_data":
                            continue
                        source = os.path.join(src, name)
                        destination = os.path.join(target, name)
                        if os.path.isdir(source):
                            shutil.copytree(source, destination, dirs_exist_ok=True)
                        else:
                            shutil.copy2(source, destination)
                else:
                    shutil.copytree(src, target, dirs_exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(src, target)
    if live and stale_total:
        print(t('nirvana.note_merging_preserves_d_extra_old_files') % stale_total)
        print(t('nirvana.for_an_exact_restore_back_up_and'))
    return plan


def memory_check(path):
    db = os.path.join(path, "memory", "memory.db")
    if not os.path.exists(db):
        return t('nirvana.memory_database_not_found')
    con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
    n = con.execute("select count(*) from documents").fetchone()[0]
    ok = con.execute("pragma integrity_check").fetchone()[0]
    con.close()
    return t('nirvana.d_memories_integrity_s_226443') % (n, ok)


def main():
    if sys.stdout is not None:  # pythonw 下是 None
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]

    if "--list" in args or "--cloud" in args:
        print(t('nirvana.cloud_downloads_require_a_cloud_drive_integration'))
        print(t('nirvana.use_a_usb_local_archive_python_restore'))
        return 1

    tar_path = None
    auto = "--auto" in args
    if "--file" in args:
        tar_path = args[args.index("--file") + 1]

    if not tar_path or not os.path.exists(tar_path):
        print(t('nirvana.restore_usage'))
        return 1

    print(t('nirvana.archive_s_f_mb') % (tar_path, os.path.getsize(tar_path) / 1e6))
    manifest = read_manifest(tar_path)
    print(t('nirvana.created_s_memories_s') % (manifest.get("created_at"),
                                     json.dumps(manifest.get("memory"), ensure_ascii=False)))

    print(t('nirvana.verifying_each_file'))
    bad = verify(tar_path, manifest)
    if bad:
        print(t('nirvana.fail_d_files_do_not_match_stopping') % len(bad))
        for p, why in bad[:10]:
            print("   %s  %s" % (why, p))
        return 1
    print(t('nirvana.ok_all_d_files_verified') % len(manifest["files"]))

    if auto and not os.path.isdir(ROOT):
        print(t('nirvana.no_existing_data_on_this_machine_restoring'))
        args.append("--live")
    elif auto:
        print(t('nirvana.existing_data_found_auto_will_not_overwrite'))

    live = "--live" in args
    stamp = time.strftime("%Y%m%d_%H%M%S")
    if os.path.isdir("D:\\"):                       # 有 D 盘放 D 盘，没有就放用户目录
        stage = os.path.join("D:\\", "companion_restore_" + stamp)
    else:
        stage = os.path.join(os.path.expanduser("~"), "companion_restore_" + stamp)
    extract(tar_path, stage)
    print(t('nirvana.after_extraction_s') % memory_check(stage))

    print(t('nirvana.restore_destinations'))
    place(stage, live=False)
    if live:
        print(t('nirvana.writing_files'))
        place(stage, live=True)
        print(t('nirvana.next_steps'))
        print(t('nirvana.install_dependencies_see_requirements_txt_instructions_in'))
        print(t('nirvana.run_check_py_to_identify_missing_items'))
    else:
        print(t('nirvana.no_live_extracted_to_staging_only_existing'))
    return 0


if __name__ == "__main__":
    sys.exit(main())
