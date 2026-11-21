# -*- coding: utf-8 -*-
"""Lysmor 桌面入口：先体检依赖服务（可视化）→ 缺失的自动拉起 → 打开总入口。

用法：
  python launch_with_check.py             正常启动（带体检窗口）
  python launch_with_check.py --no-gui    只打印体检结果，不弹窗
  python launch_with_check.py --no-launch 体检后不打开浏览器
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(ROOT, "config.json")


def load_cfg():
    try:
        with open(CFG_PATH, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def pythonw():
    exe = sys.executable or ""
    cand = exe.replace("python.exe", "pythonw.exe")
    return cand if os.path.exists(cand) else exe


def service_defs(cfg):
    data = cfg.get("data_dir") or os.path.join(ROOT, "code")
    ports = cfg.get("ports") or {}
    return [
        ("Hub 总入口", int(ports.get("hub") or 8009), os.path.join(data, "hub", "server.py")),
        ("网页聊天", int(ports.get("chat") or 8001), os.path.join(data, "webchat", "server.py")),
        ("视频通话", int(ports.get("video") or 8003), os.path.join(data, "video", "server.py")),
        ("生命面板", int(ports.get("life") or 8005), os.path.join(data, "lifeviz", "server.py")),
        ("记忆星图", int(ports.get("brain") or 8006), os.path.join(data, "brainviz", "server.py")),
        ("大平层", int(ports.get("house") or 8007), os.path.join(data, "houseviz", "server.py")),
    ]


def listening(port):
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass


def http_ok(port, timeout=2.0):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=timeout) as r:
            return 200 <= r.status < 500
    except Exception:  # noqa: BLE001
        return False


def start_service(name, script):
    if not script or not os.path.exists(script):
        return False
    try:
        subprocess.Popen([pythonw(), script],
                         cwd=os.path.dirname(script),
                         creationflags=0x00000008 | 0x08000000,
                         close_fds=True,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except Exception:  # noqa: BLE001
        return False


def check_all(services):
    results = []
    for name, port, script in services:
        ok = listening(port)
        started = False
        if not ok:
            started = start_service(name, script)
        results.append([name, port, ok, started])
    return results


def wait_recheck(results, seconds=12.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        all_ok = True
        for item in results:
            if not item[2]:
                if listening(item[1]):
                    item[2] = True
                else:
                    all_ok = False
        if all_ok:
            break
        time.sleep(0.8)
    return results


def open_entry(cfg):
    ports = cfg.get("ports") or {}
    hub = int(ports.get("hub") or 8009)
    token = cfg.get("gate_token") or ""
    url = "http://127.0.0.1:%d/" % hub
    if token:
        url += "?t=" + token
    webbrowser.open(url)


def print_status(results):
    for item in results:
        print(("OK  " if item[2] else "DOWN") + " %-8s :%d" % (item[0], item[1]))
    print("结果: %d/%d 在线" % (sum(1 for r in results if r[2]), len(results)))


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    gui = "--no-gui" not in sys.argv
    launch = "--no-launch" not in sys.argv

    cfg = load_cfg()
    services = service_defs(cfg)
    results = wait_recheck(check_all(services))
    total, up = len(results), sum(1 for r in results if r[2])

    if not gui:
        print_status(results)
        if up == total and launch:
            open_entry(cfg)
        return 0

    import tkinter as tk

    root = tk.Tk()
    root.title("Lysmor · 启动体检")
    root.configure(bg="#0d1524")
    root.geometry("440x380")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    tk.Label(root, text="🐟 Lysmor · 启动体检", bg="#0d1524", fg="#e8f1ff",
             font=("Microsoft YaHei UI", 14, "bold")).pack(pady=(16, 2))
    tk.Label(root, text="检查依赖服务，缺什么补什么", bg="#0d1524", fg="#7c8fa8",
             font=("Microsoft YaHei UI", 9)).pack()

    frame = tk.Frame(root, bg="#0d1524")
    frame.pack(fill="both", expand=True, padx=18, pady=10)
    row_labels = {}
    for i, item in enumerate(results):
        mark = tk.Label(frame, text="✅" if item[2] else "❌", bg="#0d1524",
                        fg="#37d67a" if item[2] else "#ff6b6b", width=3,
                        font=("Microsoft YaHei UI", 11), anchor="w")
        name = tk.Label(frame, text=item[0], bg="#0d1524",
                        fg="#c8d6e8" if item[2] else "#ff9b9b", width=12,
                        font=("Microsoft YaHei UI", 10), anchor="w")
        port = tk.Label(frame, text=":%d" % item[1], bg="#0d1524",
                        fg="#5f7590", font=("Consolas", 9), anchor="w")
        mark.grid(row=i, column=0, sticky="w", pady=2)
        name.grid(row=i, column=1, sticky="w", pady=2)
        port.grid(row=i, column=2, sticky="w", pady=2)
        row_labels[item[0]] = (mark, name)

    summary = tk.Label(root, text="", bg="#0d1524", fg="#9db1c8",
                       font=("Microsoft YaHei UI", 10, "bold"))
    summary.pack()

    def do_refresh():
        summary.configure(text="正在重新检查…")
        root.update()
        fresh = wait_recheck(check_all(services), seconds=4)
        for item in fresh:
            mk, nm = row_labels[item[0]]
            mk.configure(text="✅" if item[2] else "❌",
                         fg="#37d67a" if item[2] else "#ff6b6b")
            nm.configure(fg="#c8d6e8" if item[2] else "#ff9b9b")
        summary.configure(text="结果：%d/%d 在线" % (sum(1 for r in fresh if r[2]), total))
        results[:] = fresh

    def open_app():
        try:
            open_entry(cfg)
        finally:
            root.destroy()

    refresh_button = tk.Button(root, text="🔁 重新检查", command=do_refresh,
                               bg="#1c3a5e", fg="#d8e4f4", relief="flat",
                               font=("Microsoft YaHei UI", 10), padx=12, pady=4)
    refresh_button.pack(side="left", padx=(24, 6), pady=10)
    tk.Button(root, text="🚀 打开入口", command=open_app,
              bg="#1c3a5e", fg="#d8e4f4", relief="flat",
              font=("Microsoft YaHei UI", 10), padx=12, pady=4).pack(side="left", pady=10)
    tk.Button(root, text="关闭", command=root.destroy,
              bg="#0d1524", fg="#7c8fa8", relief="flat",
              font=("Microsoft YaHei UI", 10), padx=12, pady=4).pack(side="right", pady=10)

    do_refresh()
    if up == total:
        summary.configure(text="✅ 全部就绪，正在打开入口…")
        if launch:
            root.after(900, open_app)
    else:
        summary.configure(text="⚠️ 有服务未就绪，可点「重新检查」或「打开入口」")
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
