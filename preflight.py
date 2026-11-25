# -*- coding: utf-8 -*-
"""装机前自检（纯标准库，不依赖任何第三方包）

用法：
    python preflight.py            # 检查并给出下一步
    python preflight.py --json     # 机器可读输出

检查项：
  1. Python 版本（需要 3.12+）
  2. pip 是否可用
  3. 核心依赖是否装上（aiohttp / Pillow / requests / numpy / qrcode / PyJWT / cryptography）
  4. config.json 是否已生成
  5. ffmpeg 是否在 PATH（可选，视频功能需要）

退出码：
  0 全部就绪
  2 Python 版本过低
  3 缺核心依赖
  4 其它阻断问题（pip 缺失等）
"""

import importlib
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
MIN_PY = (3, 12)

CORE = [
    ("aiohttp", "aiohttp"),
    ("Pillow", "PIL"),
    ("requests", "requests"),
    ("numpy", "numpy"),
    ("qrcode", "qrcode"),
    ("PyJWT", "jwt"),
    ("cryptography", "cryptography"),
]

results = []


def add(name, ok, detail, fix=""):
    results.append({"name": name, "ok": ok, "detail": detail, "fix": fix})


def check_python():
    ok = sys.version_info[:2] >= MIN_PY
    detail = "Python %d.%d.%d" % sys.version_info[:3]
    add("Python 版本", ok, detail, "安装 Python 3.12+ 并勾选 Add to PATH" if not ok else "")


def check_pip():
    try:
        import pip  # noqa: F401

        add("pip", True, "可用", "")
    except Exception:
        add("pip", False, "不可用", "重装 Python 时勾选 pip，或执行 python -m ensurepip")


def check_deps():
    missing = []
    for pkg, mod in CORE:
        try:
            importlib.import_module(mod)
        except Exception:
            missing.append(pkg)
    if missing:
        add("核心依赖", False, "缺少 " + "、".join(missing), "python -m pip install -r requirements.txt")
    else:
        add("核心依赖", True, "齐全", "")


def check_config():
    p = os.path.join(ROOT, "config.json")
    if os.path.isfile(p):
        add("config.json", True, "已存在", "")
    else:
        add("config.json", False, "还没有配置", "双击 一键配置.cmd 完成配置（会自动生成）")


def check_ffmpeg():
    exe = shutil.which("ffmpeg")
    add("ffmpeg（可选）", bool(exe), exe or "未找到", "视频功能需要；可先跳过" if not exe else "")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    check_python()
    check_pip()
    check_deps()
    if "--no-config" not in sys.argv:
        check_config()
    check_ffmpeg()

    if "--json" in sys.argv:
        print(json.dumps({"ok": all(r["ok"] for r in results if "可选" not in r["name"]), "results": results}, ensure_ascii=False))
        return 0

    print("=" * 58)
    print(" Lysmor 装机自检")
    print("=" * 58)
    for r in results:
        mark = "OK  " if r["ok"] else "FAIL"
        print("[%s] %-14s %s" % (mark, r["name"], r["detail"]))
        if not r["ok"] and r["fix"]:
            print("        → %s" % r["fix"])

    blocking = [r for r in results if not r["ok"] and "可选" not in r["name"]]
    print("-" * 58)
    if not blocking:
        print("结论：环境就绪，可以双击 打开入口.cmd 或 一键配置.cmd。")
        return 0
    print("结论：还有 %d 项没就绪，按上面的 → 处理完再跑一次。" % len(blocking))
    if not results[0]["ok"]:
        return 2
    if not results[2]["ok"]:
        return 3
    return 4


if __name__ == "__main__":
    sys.exit(main())

