# -*- coding: utf-8 -*-
"""灾后复活 · 应急包

为什么要它：恢复脚本本身也装在数据目录里——电脑坏了，工具跟着没了。
所以把「整包 + 恢复脚本 + 说明书」复制成一个小文件夹，拷到 U 盘/移动硬盘。

用法：
    python kit.py              # 只生成到 backup\\out\\kit
    python kit.py --usb E:\\   # 顺便复制到 U 盘根目录
"""

import os
import shutil
import sys

from pathlib import Path

for _parent in Path(__file__).resolve().parents:
    if (_parent / "i18n.py").is_file():
        sys.path.insert(0, str(_parent))
        break
else:
    sys.path.insert(0, r"D:\你的数据目录")
from i18n import ROOT as I18N_ROOT, t

ROOT = r"D:\你的数据目录"                       # 部署时按实际改
NIRVANA = os.path.join(ROOT, "tools")
OUT = os.path.join(ROOT, "backup", "out")
KIT = os.path.join(OUT, "kit")
FILES = ["README.md", "restore.py", "check.py", "build.py",
         "upload.py", "kit.py", "audit.py", "export_env.py",
         "expected_env.json", "requirements.txt"]



def main():
    if sys.stdout is not None:  # pythonw 下是 None
        sys.stdout.reconfigure(encoding="utf-8")
    with open(os.path.join(OUT, "latest.json"), encoding="utf-8") as f:
        import json
        latest = json.load(f)
    tar_path = latest["path"]
    if not os.path.exists(tar_path):
        print(t('nirvana.latest_archive_not_found_run_build_py'))
        return 1

    if os.path.isdir(KIT):
        shutil.rmtree(KIT, ignore_errors=True)
    os.makedirs(KIT, exist_ok=True)

    for name in FILES:
        src = os.path.join(NIRVANA, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(KIT, name))
    for name in ("i18n.py", "i18n.js"):
        shutil.copy2(I18N_ROOT / name, os.path.join(KIT, name))
    shutil.copytree(I18N_ROOT / "locales", os.path.join(KIT, "locales"))
    tasks_src = os.path.join(NIRVANA, "tasks")
    if os.path.isdir(tasks_src):
        shutil.copytree(tasks_src, os.path.join(KIT, "tasks"))
    shutil.copy2(tar_path, os.path.join(KIT, os.path.basename(tar_path)))
    with open(os.path.join(KIT, "1-先看我.bat"), "w", encoding="utf-8") as f:
        f.write(t('nirvana.kit_batch_instructions'))

    files = []
    for dirpath, _, filenames in os.walk(KIT):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            files.append((os.path.relpath(full, KIT), os.path.getsize(full)))
    total = sum(size for _, size in files)
    print(t('nirvana.emergency_kit_created_s') % KIT)
    for rel, size in sorted(files):
        print("  %-34s %8.1f MB" % (rel, size / 1e6))
    print(t('nirvana.total_f_mb') % (total / 1e6))

    if "--usb" in sys.argv:
        dest = sys.argv[sys.argv.index("--usb") + 1].rstrip("\\/")
        target = os.path.join(dest, "companion-kit")
        if not os.path.isdir(dest):
            print(t('nirvana.usb_drive_path_does_not_exist_s') % dest)
            return 1
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(KIT, target)
        print(t('nirvana.copied_to_usb_drive_s') % target)
    else:
        print(t('nirvana.next_copy_the_entire_backup_out_kit'))
    return 0


if __name__ == "__main__":
    sys.exit(main())
