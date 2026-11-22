# -*- coding: utf-8 -*-
"""灾后复活 · 导出重装需要的东西

1. requirements.txt —— 这台机器上验证过的 Python 包版本
2. tasks/*.xml —— 计划任务，新电脑可以 schtasks /create /xml 导回去

产物落在 <数据目录>\\tools\\，build.py 会把 requirements.txt 打进包里。
"""

import os
import subprocess
import sys

from pathlib import Path

for _parent in Path(__file__).resolve().parents:
    if (_parent / "i18n.py").is_file():
        sys.path.insert(0, str(_parent))
        break
else:
    sys.path.insert(0, r"D:\你的数据目录")
from i18n import t

ROOT = r"D:\你的数据目录"                       # 部署时按实际改
NIRVANA = os.path.join(ROOT, "tools")
PY = r"C:\你的机器人框架\venv\Scripts\python.exe"  # 部署时按实际改
TASKS = ["Companion-Backup", "Companion-Watchdog",
         "Companion-MemoryHealth", "Companion-MemoryRhythm"]


def main():
    if sys.stdout is not None:  # pythonw 下是 None
        sys.stdout.reconfigure(encoding="utf-8")

    out = subprocess.run([PY, "-m", "pip", "freeze"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    freeze = out.stdout or ""
    path = os.path.join(NIRVANA, "requirements.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(t('nirvana.versions_verified_on_this_machine_reinstallation_reference'))
        f.write(freeze)
    print(t('nirvana.requirements_txt_d_lines') % len(freeze.splitlines()))

    task_dir = os.path.join(NIRVANA, "tasks")
    os.makedirs(task_dir, exist_ok=True)
    ok = 0
    for name in TASKS:
        r = subprocess.run(["schtasks", "/query", "/tn", name, "/xml"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0 and r.stdout.strip():
            with open(os.path.join(task_dir, name + ".xml"), "w", encoding="utf-8") as f:
                f.write(r.stdout)
            ok += 1
    print(t('nirvana.scheduled_tasks_exported_d_d') % (ok, len(TASKS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
