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

from pathlib import Path

for _parent in Path(__file__).resolve().parents:
    if (_parent / "i18n.py").is_file():
        sys.path.insert(0, str(_parent))
        break
else:
    sys.path.insert(0, r"D:\你的数据目录")
from i18n import t

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
        add("FAIL", t('nirvana.os'), t('nirvana.s_not_windows') % platform.system(), expect)
        return
    add("OK", t('nirvana.os'), platform.platform(), t('nirvana.requires_s') % expect)


def check_python():
    want = EXPECTED.get("python", "3.12.x")
    v = "%d.%d.%d" % sys.version_info[:3]
    ok = (sys.version_info[:2] == (3, 12))
    add("OK" if ok else "FAIL", "Python", v, t('nirvana.requires_s_python_org_enable_add_to') % want)


def check_bot():
    want = EXPECTED.get("bot_framework", "")
    core = os.path.join(LAUNCHER, "instances", INSTANCE_ID, "core") if INSTANCE_ID else LAUNCHER
    pyproj = os.path.join(core, "pyproject.toml")
    if not os.path.isdir(core):
        add("FAIL", t('nirvana.bot_framework'), t('nirvana.not_found_s') % core, t('nirvana.copy_the_complete_framework_to_the_same'))
        return
    actual = ""
    try:
        with open(pyproj, encoding="utf-8") as f:
            m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
            actual = m.group(1) if m else ""
    except Exception:  # noqa: BLE001
        pass
    if actual:
        add("OK" if (not want or actual == want) else "WARN", t('nirvana.bot_framework_version'), actual,
            t('nirvana.expected_s_plugins_may_be_incompatible_with') % want)
    else:
        add("WARN", t('nirvana.bot_framework_version'), t('nirvana.unavailable'), t('nirvana.expected_s') % want)


def check_venv():
    venv = os.path.join(LAUNCHER, "instances", INSTANCE_ID, "venv", "Scripts", "python.exe") \
        if INSTANCE_ID else ""
    if not venv or not os.path.exists(venv):
        add("WARN", t('nirvana.bot_virtual_environment'), t('nirvana.not_found_s') % (venv or t('nirvana.instance_not_configured')),
            t('nirvana.copy_the_complete_framework_including_venv_to'))
        return
    add("OK", t('nirvana.bot_virtual_environment'), run([venv, "--version"]).strip() or venv)


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
        add("FAIL", "Ollama", t('nirvana.service_on_port_is_unavailable_or_ollama'),
            t('nirvana.install_ollama_and_start_ollama_serve'))
        return
    want = EXPECTED.get("ollama_models") or []
    missing = [m for m in want if not any(x == m or x.startswith(m + ":") for x in models)]
    if missing:
        add("FAIL", t('nirvana.ollama_models'), t('nirvana.missing_s') % ", ".join(missing),
            "ollama pull %s" % "；ollama pull ".join(missing))
    else:
        add("OK", t('nirvana.ollama_models'), ", ".join(want), t('nirvana.vision_and_memory_retrieval_models_available'))


def check_ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        add("WARN", "ffmpeg", t('nirvana.not_on_path'), t('nirvana.install_the_essentials_build_and_add_bin'))
        return
    out = run([exe, "-version"])
    add("OK", "ffmpeg", (out.splitlines()[0] if out else "ffmpeg")[:80])


def check_im():
    if not os.path.exists(IM_PATH):
        add("WARN", t('nirvana.im_client'), t('nirvana.not_found_s') % IM_PATH, t('nirvana.install_separately_and_sign_in_with_the'))
        return
    ps = "(Get-Item -LiteralPath '%s').VersionInfo.FileVersion" % IM_PATH
    out = run(["powershell", "-NoProfile", "-Command", ps]).strip()
    want = EXPECTED.get("im_version", "")
    if want and out and out != want:
        add("WARN", t('nirvana.im_version'), out, t('nirvana.expected_s_do_not_upgrade_automatically') % want)
    else:
        add("OK", t('nirvana.im_client'), out or t('nirvana.present'), t('nirvana.pinned_version_s') % want)


def check_napcat():
    if not os.path.isdir(NAPCAT_APP):
        add("WARN", t('nirvana.protocol_adapter'), t('nirvana.not_found_s') % NAPCAT_APP, t('nirvana.install_using_its_official_documentation'))
        return
    lock = os.path.abspath(os.path.join(NAPCAT_APP, "..", "version-lock.json"))
    actual = ""
    try:
        with open(lock, encoding="utf-8-sig") as f:
            actual = str(json.load(f).get("version") or "")
    except Exception:  # noqa: BLE001
        pass
    add("OK", t('nirvana.protocol_adapter'), actual or t('nirvana.present'))


def check_startup():
    need = ["start.ps1", "start-im.ps1"]
    missing = [n for n in need if not os.path.exists(os.path.join(STARTUP, n))]
    if missing:
        add("WARN", t('nirvana.startup_scripts'), t('nirvana.missing_s') % ", ".join(missing), t('nirvana.restore_startup_from_the_backup'))
    else:
        add("OK", t('nirvana.startup_scripts'), "start / start-im")


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
        add("FAIL", t('nirvana.data_directory'), t('nirvana.missing_usually_a_new_computer'),
            t('nirvana.run_restore_py_file_backup_first_then'))
        return
    db = os.path.join(ROOT, "memory", "memory.db")
    if not os.path.exists(db):
        add("FAIL", t('nirvana.memory_database'), t('nirvana.missing_s_32754') % db, t('nirvana.restore_memories_with_restore_py'))
    else:
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
            docs = con.execute("select count(*) from documents").fetchone()[0]
            integ = con.execute("pragma integrity_check").fetchone()[0]
            con.close()
            want = expected_docs()
            if integ != "ok":
                add("FAIL", t('nirvana.memory_database'), t('nirvana.d_records_integrity_s') % (docs, integ), t('nirvana.restore_backup'))
            elif want and docs < want:
                add("WARN", t('nirvana.memory_database'), t('nirvana.d_records_expected_d') % (docs, want), t('nirvana.an_older_backup_may_have_been_used'))
            else:
                add("OK", t('nirvana.memory_database'), t('nirvana.d_records_integrity_ok') % docs)
        except Exception as exc:  # noqa: BLE001
            add("FAIL", t('nirvana.memory_database'), t('nirvana.cannot_read_s') % exc, t('nirvana.restore_the_memory_database'))
    plugins = os.path.join(LAUNCHER, "instances", INSTANCE_ID, "core", "data", "plugins") \
        if INSTANCE_ID else os.path.join(LAUNCHER, "data", "plugins")
    if plugins and os.path.isdir(plugins):
        mine = [d for d in os.listdir(plugins) if os.path.isdir(os.path.join(plugins, d))]
        want = int(EXPECTED.get("plugins") or 0)
        add("OK" if (not want or len(mine) >= want) else "WARN", t('nirvana.plugins'),
            t('nirvana.d_items') % len(mine), t('nirvana.expected_d_restore_py_restores_plugins') % want)
    else:
        add("WARN", t('nirvana.plugins'), t('nirvana.plugin_directory_is_missing'), t('nirvana.install_the_bot_framework_first_then_run'))
    tasks = os.path.join(ROOT, "tools", "tasks")
    if os.path.isdir(tasks):
        n = len([x for x in os.listdir(tasks) if x.endswith(".xml")])
        add("OK" if n >= 1 else "WARN", t('nirvana.scheduled_task_inventory'), t('nirvana.d_xml_files') % n, t('nirvana.import_using_schtasks'))
    else:
        add("WARN", t('nirvana.scheduled_task_inventory'), t('nirvana.missing_tools_tasks'), t('nirvana.restore_using_restore_py'))


def check_comfy():
    candidates = [
        r"D:\ComfyUI\main.py",
        r"D:\Comfy-Desktop\ComfyUI\main.py",
    ]
    if any(os.path.exists(p) for p in candidates):
        add("OK", t('nirvana.drawing_optional'), t('nirvana.installed_start_when_needed'), "", optional=True)
    else:
        add("WARN", t('nirvana.drawing_optional'), t('nirvana.not_installed_chat_and_memory_remain_available'), t('nirvana.install_comfyui_and_models_when_drawing_is'), optional=True)


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
            print(t('nirvana.environment_audit'))
            print(t('nirvana.machine_s') % platform.platform())
        for r in RESULTS:
            if quiet and r["level"] == "OK":
                continue
            mark = {"OK": "[OK]  ", "WARN": "[WARN]", "FAIL": "[FAIL]"}[r["level"]]
            print("%s %-12s %s" % (mark, r["name"], r["detail"]))
            if r["hint"] and r["level"] != "OK":
                print("        -> %s" % r["hint"])
        if not quiet:
            print(t('nirvana.result_fail_d_warn_d') % (len(fails), len(warns)))
            if fails:
                print(t('nirvana.resolve_fail_items_first_then_run_restore'))
            else:
                print(t('nirvana.core_requirements_are_available_restore_with_restore'))

    if fails:
        return 1
    if not os.path.isdir(ROOT):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
