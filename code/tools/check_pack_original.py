"""原创功能覆盖检查：她自己的东西有没有漏在灾后复活包外。

硬规则（2026-11-06 部署者定）：
    "以后我们编辑的原创功能都要完整写入 u 盘那个包"

判据很简单——只要 `D:\\你的数据目录` 下有**自己的目录没被 build.py 收进 SOURCES**，
或者 AstrBot 插件目录里有**她自己的插件没被 PLUGIN_PREFIXES / EXTRA_PLUGIN_PREFIXES 收进去**，
就算漏，退出码 1。

明确允许不进包的（不是她的原创，或本来就是临时/环境/备份）：
    logs / lab / models / out / backups / nirvana 里的包本身 / 旧快照目录
"""
from __future__ import annotations

import io
import os
import re
import sys

ROOT = r"D:\你的数据目录"
BUILD = os.path.join(ROOT, "nirvana", "build.py")
INSTANCE = r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\core\data"

# 允许不进包的目录（前缀匹配）
ALLOWED_PREFIXES = (
    "logs", "lab", "models", "framework-backup", "backup-livingmemory",
    "backup-", "trash", "tmp",
)

# 她自己的插件必须全部覆盖
MUST_COVER_PLUGIN_PREFIXES = (
    "astrbot_plugin_companion",
    "astrbot_plugin_livingmemory",
    "astrbot_plugin_qzone",
)


def read(path: str) -> str:
    return io.open(path, encoding="utf-8-sig").read()


def sources_of(build_src: str) -> tuple[set[str], set[str]]:
    """返回 (SOURCES 里覆盖的目录名, PLUGIN 前缀并集)。"""
    dirs: set[str] = set()
    for line in build_src.splitlines():
        m = re.search(r'os\.path\.join\(ROOT,\s*"([^"]+)"\)', line)
        if m:
            dirs.add(m.group(1))
    prefixes: set[str] = set()
    for block in ("PLUGIN_PREFIXES", "EXTRA_PLUGIN_PREFIXES", "HER_PLUGIN_PREFIXES"):
        m = re.search(rf"{block}\s*=\s*\((.*?)\)", build_src, re.S)
        if not m:
            continue
        for item in re.findall(r'"([^"]+)"', m.group(1)):
            if not item.startswith("#"):
                prefixes.add(item)
    return dirs, prefixes


def main() -> int:
    if not os.path.isfile(BUILD):
        print(f"[FAIL] 找不到 {BUILD}")
        return 1
    build_src = read(BUILD)
    covered, prefixes = sources_of(build_src)

    problems: list[str] = []

    # 1) 数据根目录
    for name in sorted(os.listdir(ROOT)):
        full = os.path.join(ROOT, name)
        if not os.path.isdir(full):
            continue
        if any(name.startswith(p) for p in ALLOWED_PREFIXES):
            continue
        if name == "nirvana":
            continue
        if name not in covered:
            problems.append(f"目录没进 SOURCES: {name}")

    # 2) 她的插件
    plug_dir = os.path.join(INSTANCE, "plugins")
    if os.path.isdir(plug_dir):
        for name in sorted(os.listdir(plug_dir)):
            if not os.path.isdir(os.path.join(plug_dir, name)):
                continue
            if not any(name.startswith(p) for p in MUST_COVER_PLUGIN_PREFIXES):
                continue
            if not any(name.startswith(p) for p in prefixes):
                problems.append(f"插件没进 PLUGIN_PREFIXES: {name}")

    if problems:
        print("[FAIL] 有原创功能没进包（硬规则 §2.11）：")
        for p in problems:
            print("   -", p)
        print("\n修法：改 nirvana/build.py 的 SOURCES / PLUGIN_PREFIXES，再重新打包。")
        return 1

    print("[OK] 原创功能全部在包里")
    print(f"     SOURCES 覆盖 {len(covered)} 个目录；插件前缀 {len(prefixes)} 条")
    return 0


JUNK_PATTERNS = (
    ".bak-", ".bak/", "__pycache__", ".pyc", "/logs/",
    # 2026-11-09：lab 里已经有她的原创功能（手/游戏/视觉/语音），不能再整目录拦；
    # 只拦真正的旧物和临时产物。
    "/lab/aiui/", "/lab/apk/", "/lab/models/", "/lab/_chk", "/lab/samples/",
    "/lab/debug/", "/lab/tts/piper/", "/lab/asr/pylibs/", "/lab/vision/pylibs/",
    "/staging/", ".tmp", "-wal", "-shm", ".crdownload",
)


def latest_pack() -> str | None:
    import glob
    packs = sorted(glob.glob(os.path.join(ROOT, "nirvana", "out", "nirvana_*.tar.gz")))
    return packs[-1] if packs else None


def check_junk() -> int:
    """包里不许有旧备份/缓存/日志/实验目录——U 盘那套永远是最新一套。"""
    import tarfile
    pack = latest_pack()
    if not pack:
        print("[FAIL] nirvana\\out 里没有包")
        return 1
    print("扫描", os.path.basename(pack))
    bad: list[str] = []
    with tarfile.open(pack, "r:gz") as tf:
        for name in tf.getnames():
            low = "/" + name.lower()
            if any(pat in low for pat in JUNK_PATTERNS):
                bad.append(name)
    if bad:
        print("[FAIL] 包里夹了旧/临时文件 %d 个：" % len(bad))
        for b in bad[:20]:
            print("   -", b)
        return 1
    print("[OK] 包里没有 .bak / __pycache__ / .pyc / logs / lab / staging")
    return 0


if __name__ == "__main__":
    if "--junk" in sys.argv:
        sys.exit(check_junk())
    sys.exit(main())
