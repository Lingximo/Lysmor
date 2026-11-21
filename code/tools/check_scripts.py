# -*- coding: utf-8 -*-
"""脚本体检：.cmd 必须 CRLF + 纯 ASCII，.ps1 必须 UTF-8 BOM（或纯 ASCII）。

Why: 2026-11-05 早上 DSH 打不开，双击桌面「修复打不开.cmd」也没反应——
那个 .cmd 是用 LF 行尾写的，cmd.exe 按 CRLF 解析，会把行拆碎，
报一堆 "'ocal' is not recognized"。修脚本因此形同虚设（灾后复活 §51）。

用法（在 D:\\你的数据目录\\tools 下）：
    .\\py.cmd check_scripts.py
    .\\py.cmd check_scripts.py --fix-crlf     # 只把 .cmd 的行尾补成 CRLF
"""
import os
import sys

ROOT = r"D:\你的数据目录"
EXTRA = [
    r"C:\你的用户\Desktop",
    r"C:\你的用户\Desktop\TA哦\TA驱动器",
    r"C:\你的用户\CompanionStartup",
]
SKIP_DIRS = {"__pycache__", "node_modules", ".git", "out", "backups", "logs"}
# App internals (DSH / Electron) are not ours to police.
SKIP_PATH_PARTS = (r"\resources\app.asar", r"\resources\runtime", r"\node_modules\\", r"\.dsh\\")

problems = []


def has_bom(b):
    return b[:3] == b"\xef\xbb\xbf"


def non_ascii(b):
    for ch in b:
        if ch > 127:
            return True
    return False


def check_file(path, fix=False):
    try:
        with open(path, "rb") as f:
            b = f.read()
    except OSError as exc:
        problems.append(("READ-FAIL", path, str(exc)[:60]))
        return False
    ext = os.path.splitext(path)[1].lower()
    lf = b.count(b"\n")
    crlf = b.count(b"\r\n")
    lone_lf = lf - crlf
    if ext in (".cmd", ".bat"):
        if lone_lf > 0:
            if fix:
                nb = b.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                with open(path, "wb") as f:
                    f.write(nb)
                problems.append(("FIXED-CRLF", path, "%d 行是 LF" % lone_lf))
                return True
            problems.append(("LF-ONLY", path, "%d 行是 LF，cmd 会解析错乱" % lone_lf))
            return False
        if non_ascii(b) and b"chcp 65001" not in b.lower():
            problems.append(("NON-ASCII", path, "含非 ASCII 字节且没有 chcp 65001（echo 会乱码）"))
            return False
    if ext == ".ps1":
        if not has_bom(b) and non_ascii(b):
            problems.append(("PS1-NO-BOM", path, "有中文但没 BOM，PowerShell 5.1 会吃行"))
            return False
    return True


def walk(base):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        low = dirpath.lower()
        if any(part in low for part in SKIP_PATH_PARTS):
            continue
        for fn in filenames:
            if fn.lower().endswith((".cmd", ".bat", ".ps1")):
                yield os.path.join(dirpath, fn)


def main():
    fix = "--fix-crlf" in sys.argv
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    targets = []
    for base in [ROOT] + EXTRA:
        if os.path.isdir(base):
            targets.extend(walk(base))
    seen, uniq = set(), []
    for p in targets:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    ok = 0
    for p in sorted(uniq):
        if check_file(p, fix=fix):
            ok += 1
    print("检查了 %d 个脚本，没问题 %d 个。" % (len(uniq), ok))
    if problems:
        print("\n有问题的：")
        for kind, path, why in problems:
            print("  [%s] %s\n        %s" % (kind, path, why))
        return 1
    print("全部合格 ✅（.cmd=CRLF+ASCII，.ps1=BOM 或纯 ASCII）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
