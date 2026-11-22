# -*- coding: utf-8 -*-
"""打开入口（日常用）

双击 打开入口.cmd 即可：
  1. 还没配置过 → 自动打开"配置向导"页面
  2. 已配置 → 启动核心服务（已在跑的自动跳过），然后打开 Hub 总入口页

测试用：python open_entry.py --no-browser（只起服务不开浏览器）
"""

import json
import os
import socket
import subprocess
import sys
import time
import webbrowser
from i18n import t

ROOT = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.join(ROOT, "code")
CFG_PATH = os.path.join(ROOT, "config.json")

# (显示名, 脚本相对路径, 端口配置键)
MODULES = [
    ("Hub", "hub/server.py", "hub"),
    ("setup.label.webchat", "webchat/server.py", "chat"),
    ("setup.label.video", "video/server.py", "video"),
    ("setup.label.life", "lifeviz/server.py", "life"),
    ("setup.label.brain", "brainviz/server.py", "brain"),
]


def load_cfg():
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def listening(port):
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except Exception:
        return False


def service_pythonw():
    """返回 (pythonw 路径, 环境变量)：用底层 pythonw 避免控制台弹窗，
    同时把 venv 的 site-packages 注入，保证第三方库可用。"""
    exe = sys.executable or ""
    base = os.path.dirname(exe)
    venv = os.path.dirname(base)
    env = dict(os.environ)
    cand = exe.replace("python.exe", "pythonw.exe")
    cfg_path = os.path.join(venv, "pyvenv.cfg")
    if os.path.exists(cfg_path):
        sp = os.path.join(venv, "Lib", "site-packages")
        if os.path.isdir(sp):
            old = env.get("PYTHONPATH") or ""
            env["PYTHONPATH"] = sp + (os.pathsep + old if old else "")
        try:
            for line in open(cfg_path, encoding="utf-8", errors="ignore"):
                if line.lower().startswith("home"):
                    home = line.split("=", 1)[1].strip()
                    real = os.path.join(home, "pythonw.exe")
                    if os.path.exists(real):
                        cand = real
                    break
        except OSError:
            pass
    return (cand if os.path.exists(cand) else exe), env


def start(script, port):
    if listening(port):
        return False
    DETACHED = 0x00000008 | 0x08000000          # DETACHED_PROCESS | CREATE_NO_WINDOW（不弹黑窗口）
    pyw, env = service_pythonw()
    subprocess.Popen([pyw, script],
                     cwd=os.path.dirname(script),
                     creationflags=DETACHED,
                     close_fds=True,
                     stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL,
                     env=env)
    return True


def open_url(url):
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)


def run_and_print_check():
    try:
        import configure
        fails = warns = 0
        for c in configure.check_setup():
            if c["level"] == "fail":
                fails += 1
            elif c["level"] == "warn":
                warns += 1
        print(t('setup.entry.check_result') % (fails, warns))
    except Exception as exc:  # noqa: BLE001
        print(t('setup.entry.check_failed') % exc)


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = load_cfg()
    if not cfg:
        print(t('setup.entry.not_configured'))
        if not listening(8090):
            start(os.path.join(ROOT, "setup", "server.py"), 8090)
        time.sleep(1.0)
        open_url("http://127.0.0.1:8090/?auto=check")
        return 0

    ports = cfg.get("ports") or {}
    started = []
    for name, rel, key in MODULES:
        if name.startswith("setup."):
            name = t(name)
        script = os.path.join(CODE, rel)
        if not os.path.exists(script):
            continue
        port = int(ports.get(key) or 8000)
        if start(script, port):
            started.append(name)
            time.sleep(0.8)

    # 大平层需要 plan.json（新用户可先放一个通用布局）
    house_script = os.path.join(CODE, "houseviz", "server.py")
    if os.path.exists(house_script) and os.path.exists(os.path.join(CODE, "houseviz", "plan.json")):
        port = int(ports.get("house") or 8007)
        if start(house_script, port):
            started.append(t('setup.label.house'))

    print(t('setup.entry.started') % ("、".join(started) if started else t('setup.entry.all_running')))
    run_and_print_check()

    # 打开"体检页"：全绿自动进总入口，有黄/红灯就停在体检页提示怎么修
    if not listening(8090):
        start(os.path.join(ROOT, "setup", "server.py"), 8090)
    time.sleep(1.0)
    open_url("http://127.0.0.1:8090/?auto=check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
