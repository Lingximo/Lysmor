# -*- coding: utf-8 -*-
"""每天 04:00：先跑巩固器（账本/叙事），再跑护栏（权重幂等/去重/冲突/信念调和）。"""
import subprocess, sys
venv = sys.executable
for args in (["persona_consolidate.py", "--all"], ["persona_reflect.py"], ["persona_guard.py"], ["she_state.py"], ["check_snapshot_coverage.py"]):
    cmd = [venv, "-X", "utf8", r"D:\\你的数据目录\\tools\\" + args[0]] + args[1:]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("[%s] rc=%s" % (args[0], r.returncode))
    print((r.stdout or "")[-800:])
