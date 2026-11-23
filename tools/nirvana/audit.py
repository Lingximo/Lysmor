# -*- coding: utf-8 -*-
"""灾后复活 · 环境体检（换新电脑用）

回答一个问题：「这台机器和备份包里的环境差多少？差的东西怎么补？」

用法：
    python audit.py            # 人看的表
    python audit.py --json     # 给程序解析
    python audit.py --quiet    # 只打印 FAIL / WARN

退出码：
    0 = 核心项都齐（可能有可选缺失，如画画）
    1 = 有核心缺失，先补再恢复
    2 = 连数据目录都没有（典型新电脑，先跑 restore.py）
"""

import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
EXPECTED = {}
try:
    with open(os.path.join(BASE, "expected_env.json"), encoding="utf-8") as f:
        EXPECTED = json.load(f)
except Exception:  # noqa: BLE001
    pass

ROOT = EXPECTED.get("root", r"D:\你的数据目录")
LAUNCHER = EXPECTED.get("bot_launcher", r"C:\你的机器人框架")
INSTANCE_ID = EXPECTED.get("bot_instance", "")
STARTUP = EXPECTED.get("startup", r"C:\你的用户\CompanionStartup")
IM_PATH = EXPECTED.get("im_path", r"D:\你的IM\IM.exe")
NAPCAT_APP = EXPECTED.get("napcat_app", r"D:\你的NapCat\app")

RESULTS = []


def add(level, name, detail, hint="", optional=False):
    RESULTS.append({"level": level, "name": name, "detail": detail,
                    "hint": hint, "optional": optional})


def run(cmd, timeout=12):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return (p.stdout or "") + (p.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return "ERR:%s" % exc


def check_os():
    expect = EXPECTED.get("os", "Windows 10/11 x64")
    if platform.system() != "Windows":
        add("FAIL", "操作系统", "%s（不是 Windows）" % platform.system(), expect)
        return
    add("OK", "操作系统", platform.platform(), "需要 %s" % expect)


def check_python():
    want = EXPECTED.get("python", "3.12.x")
    v = "%d.%d.%d" % sys.version_info[:3]
    ok = (sys.version_info[:2] == (3, 12))
    add("OK" if ok else "FAIL", "Python", v, "需要 %s（python.org，勾选 Add to PATH）" % want)


def check_bot():
    want = EXPECTED.get("bot_framework", "")
    core = os.path.join(LAUNCHER, "instances", INSTANCE_ID, "core") if INSTANCE_ID else LAUNCHER
    pyproj = os.path.join(core, "pyproject.toml")
    if not os.path.isdir(core):
        add("FAIL", "机器人框架", "未找到 %s" % core, "复制整个框架到同路径，或按其官方文档重装")
        return
    actual = ""
    try:
        with open(pyproj, encoding="utf-8") as f:
            m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
            actual = m.group(1) if m else ""
    except Exception:  # noqa: BLE001
        pass
    if actual:
        add("OK" if (not want or actual == want) else "WARN", "机器人框架版本", actual,
            "期望 %s；版本不一致插件可能不兼容" % want)
    else:
        add("WARN", "机器人框架版本", "读不到", "期望 %s" % want)


def check_venv():
    venv = os.path.join(LAUNCHER, "instances", INSTANCE_ID, "venv", "Scripts", "python.exe") \
        if INSTANCE_ID else ""
    if not venv or not os.path.exists(venv):
        add("WARN", "机器人 venv", "未找到 %s" % (venv or "(未配置实例)"),
            "复制整个框架（含 venv）到同路径；或重建 venv 并 pip install -r requirements.txt")
        return
    add("OK", "机器人 venv", run([venv, "--version"]).strip() or venv)


def check_ollama():
    models = set()
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
        for m in data.get("models") or []:
            models.add(str(m.get("name") or ""))
    except Exception:  # noqa: BLE001
        out = run(["ollama", "list"])
        for line in out.splitlines()[1:]:
            if line.strip():
                models.add(line.split()[0])
    if not models:
        add("FAIL", "Ollama", "服务 11434 不可用，或 ollama 不在 PATH",
            "安装 Ollama 并启动 ollama serve")
        return
    want = EXPECTED.get("ollama_models") or []
    missing = [m for m in want if not any(x == m or x.startswith(m + ":") for x in models)]
    if missing:
        add("FAIL", "Ollama 模型", "缺: %s" % ", ".join(missing),
            "ollama pull %s" % "；ollama pull ".join(missing))
    else:
        add("OK", "Ollama 模型", ", ".join(want), "视觉/记忆检索齐全")


def check_ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        add("WARN", "ffmpeg", "不在 PATH", "装 essentials 构建，把 bin 加进 PATH（语音要）")
        return
    out = run([exe, "-version"])
    add("OK", "ffmpeg", (out.splitlines()[0] if out else "ffmpeg")[:80])


def check_im():
    if not os.path.exists(IM_PATH):
        add("WARN", "IM 客户端", "未找到 %s" % IM_PATH, "自行安装并**扫码登录**；本项目不包含 IM 本体")
        return
    ps = "(Get-Item -LiteralPath '%s').VersionInfo.FileVersion" % IM_PATH
    out = run(["powershell", "-NoProfile", "-Command", ps]).strip()
    add("OK", "IM 客户端", out or "存在", "版本自行选择；本项目不锁版本")


def check_napcat():
    if not os.path.isdir(NAPCAT_APP):
        add("WARN", "协议接入", "未找到 %s" % NAPCAT_APP, "按其官方文档安装")
        return
    add("OK", "协议接入", "存在")


def check_startup():
    need = ["start.ps1", "start-im.ps1"]
    missing = [n for n in need if not os.path.exists(os.path.join(STARTUP, n))]
    if missing:
        add("WARN", "启动脚本", "缺: %s" % ", ".join(missing), "从备份包 startup/ 恢复")
    else:
        add("OK", "启动脚本", "start / start-im")


def expected_docs():
    latest = os.path.join(ROOT, "backup", "out", "latest.json")
    try:
        with open(latest, encoding="utf-8") as f:
            n = int(json.load(f)["memory"]["documents"])
            if n > 0:
                return n
    except Exception:  # noqa: BLE001
        pass
    return int(EXPECTED.get("memory_docs") or 0)


def check_data():
    if not os.path.isdir(ROOT):
        add("FAIL", "数据目录", "不存在（典型新电脑）",
            "先跑 restore.py --file <备份包>，再回来看这条")
        return
    db = os.path.join(ROOT, "memory", "memory.db")
    if not os.path.exists(db):
        add("FAIL", "记忆库", "缺 %s" % db, "restore.py 恢复记忆")
    else:
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
            docs = con.execute("select count(*) from documents").fetchone()[0]
            integ = con.execute("pragma integrity_check").fetchone()[0]
            con.close()
            want = expected_docs()
            if integ != "ok":
                add("FAIL", "记忆库", "%d 条，integrity=%s" % (docs, integ), "恢复/备份")
            elif want and docs < want:
                add("WARN", "记忆库", "%d 条（期望 %d）" % (docs, want), "可能用了旧包")
            else:
                add("OK", "记忆库", "%d 条，integrity=ok" % docs)
        except Exception as exc:  # noqa: BLE001
            add("FAIL", "记忆库", "读不了: %s" % exc, "恢复记忆库")
    plugins = os.path.join(LAUNCHER, "instances", INSTANCE_ID, "core", "data", "plugins") \
        if INSTANCE_ID else os.path.join(LAUNCHER, "data", "plugins")
    if plugins and os.path.isdir(plugins):
        mine = [d for d in os.listdir(plugins) if os.path.isdir(os.path.join(plugins, d))]
        want = int(EXPECTED.get("plugins") or 0)
        add("OK" if (not want or len(mine) >= want) else "WARN", "插件",
            "%d 个" % len(mine), "期望 %d 个；restore.py 会铺 plugins/" % want)
    else:
        add("WARN", "插件", "插件目录不存在", "先建机器人框架，再 restore.py")
    tasks = os.path.join(ROOT, "tools", "tasks")
    if os.path.isdir(tasks):
        n = len([x for x in os.listdir(tasks) if x.endswith(".xml")])
        add("OK" if n >= 1 else "WARN", "计划任务清单", "%d 个 XML" % n, "用 schtasks 导入")
    else:
        add("WARN", "计划任务清单", "缺 tools\\tasks", "restore.py 恢复")


def check_comfy():
    candidates = [
        r"D:\ComfyUI\main.py",
        r"D:\Comfy-Desktop\ComfyUI\main.py",
    ]
    if any(os.path.exists(p) for p in candidates):
        add("OK", "画画（可选）", "已安装（按需启动）", "", optional=True)
    else:
        add("WARN", "画画（可选）", "未安装（不影响聊天/记忆）", "要画画再装 ComfyUI + 模型", optional=True)


def main():
    if sys.stdout is not None:  # pythonw 下是 None
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    as_json = "--json" in sys.argv
    quiet = "--quiet" in sys.argv

    check_os()
    check_python()
    check_bot()
    check_venv()
    check_ollama()
    check_ffmpeg()
    check_im()
    check_napcat()
    check_startup()
    check_data()
    check_comfy()

    fails = [r for r in RESULTS if r["level"] == "FAIL"]
    warns = [r for r in RESULTS if r["level"] == "WARN"]

    if as_json:
        print(json.dumps({"results": RESULTS, "fail": len(fails), "warn": len(warns)},
                         ensure_ascii=False, indent=2))
    else:
        if not quiet:
            print("== 环境体检 ==")
            print("机器：%s\n" % platform.platform())
        for r in RESULTS:
            if quiet and r["level"] == "OK":
                continue
            mark = {"OK": "[OK]  ", "WARN": "[WARN]", "FAIL": "[FAIL]"}[r["level"]]
            print("%s %-12s %s" % (mark, r["name"], r["detail"]))
            if r["hint"] and r["level"] != "OK":
                print("        -> %s" % r["hint"])
        if not quiet:
            print("\n结果：FAIL=%d WARN=%d" % (len(fails), len(warns)))
            if fails:
                print("先补 FAIL 项，再跑 restore.py / check.py。")
            else:
                print("核心项齐全；可以 restore.py --file <备份包> 接回来。")

    if fails:
        return 1
    if not os.path.isdir(ROOT):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
