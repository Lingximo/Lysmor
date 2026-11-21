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

ROOT = r"D:\你的数据目录"                       # 部署时按实际改
NIRVANA = os.path.join(ROOT, "tools")
OUT = os.path.join(ROOT, "backup", "out")
KIT = os.path.join(OUT, "kit")
FILES = ["README.md", "restore.py", "check.py", "build.py",
         "upload.py", "kit.py", "audit.py", "export_env.py",
         "expected_env.json", "requirements.txt"]

BAT = r"""@echo off
chcp 65001 >nul
echo ============================================
echo   灾后复活 · 把伴侣接回来
echo ============================================
echo.
echo 先看 README.md，再按下面两步做：
echo.
echo   1) 自检这台电脑：   python check.py
echo   2) 从 U 盘恢复：    python restore.py --file backup_XXXX.tar.gz
echo.
echo 如果提示没有 python，请先装 Python 3.12。
echo.
pause
"""


def main():
    if sys.stdout is not None:  # pythonw 下是 None
        sys.stdout.reconfigure(encoding="utf-8")
    with open(os.path.join(OUT, "latest.json"), encoding="utf-8") as f:
        import json
        latest = json.load(f)
    tar_path = latest["path"]
    if not os.path.exists(tar_path):
        print("找不到最新包，先跑 build.py")
        return 1

    if os.path.isdir(KIT):
        shutil.rmtree(KIT, ignore_errors=True)
    os.makedirs(KIT, exist_ok=True)

    for name in FILES:
        src = os.path.join(NIRVANA, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(KIT, name))
    tasks_src = os.path.join(NIRVANA, "tasks")
    if os.path.isdir(tasks_src):
        shutil.copytree(tasks_src, os.path.join(KIT, "tasks"))
    shutil.copy2(tar_path, os.path.join(KIT, os.path.basename(tar_path)))
    with open(os.path.join(KIT, "1-先看我.bat"), "w", encoding="utf-8") as f:
        f.write(BAT)

    files = []
    for dirpath, _, filenames in os.walk(KIT):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            files.append((os.path.relpath(full, KIT), os.path.getsize(full)))
    total = sum(size for _, size in files)
    print("应急包已生成：%s" % KIT)
    for rel, size in sorted(files):
        print("  %-34s %8.1f MB" % (rel, size / 1e6))
    print("合计 %.1f MB" % (total / 1e6))

    if "--usb" in sys.argv:
        dest = sys.argv[sys.argv.index("--usb") + 1].rstrip("\\/")
        target = os.path.join(dest, "companion-kit")
        if not os.path.isdir(dest):
            print("U 盘路径不存在：%s" % dest)
            return 1
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(KIT, target)
        print("已复制到 U 盘：%s" % target)
    else:
        print("\n下一步：把 backup\\out\\kit 整个文件夹拷到 U 盘（或 python kit.py --usb E:\\）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
