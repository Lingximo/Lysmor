"""看看这台机器上到底有几个摄像头、能不能被我打开。

新摄像头到了先跑这个，再决定怎么接：

    python list_cameras.py

判据（能不能用来「认人」）：
    · 至少要出现 **两个** 视频设备：一个彩色、一个红外
    · 两个都要能被 OpenCV 打开（UVC 免驱），且不是全黑
    · 只有一个彩色设备 → 只能做"看脸"，做不了防照片

输出里 `brightness` 是连续 5 帧的平均亮度：
    0.0 且不报错 = 设备在但没出流（虚拟摄像头/被占用/驱动问题）
    打不开 = 没暴露成 UVC，或者被别的程序占了
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PYLIBS = os.path.join(HERE, "pylibs")
if os.path.isdir(PYLIBS) and PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)

import cv2  # noqa: E402


def pnp_cameras():
    """从 Windows 设备列表里读摄像头名字（跟 OpenCV 的 index 不一定一一对应）。"""
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-PnpDevice -Class Camera,Media -Status OK | "
             "Select-Object -ExpandProperty FriendlyName"],
            capture_output=True, text=True, timeout=30)
        names = [l.strip() for l in out.stdout.splitlines() if l.strip()]
        return names
    except Exception:  # noqa: BLE001
        return []


def main() -> int:
    print("== 系统里的摄像头设备 ==")
    for n in pnp_cameras():
        print("  -", n)

    print("\n== 按 OpenCV index 试开（0~5）==")
    found = 0
    for idx in range(6):
        cap, label = None, "none"
        for backend, tag in ((cv2.CAP_MSMF, "MSMF"), (cv2.CAP_DSHOW, "DSHOW"), (cv2.CAP_ANY, "ANY")):
            c = cv2.VideoCapture(idx, backend)
            if c.isOpened():
                ok, frame = c.read()
                if ok and frame is not None:
                    cap, label = c, tag
                    break
            c.release()
        if cap is None:
            continue
        found += 1
        means, sats = [], []
        for _ in range(5):
            ok, f = cap.read()
            if ok and f is not None:
                means.append(round(float(f.mean()), 2))
                hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
                sats.append(float(hsv[:, :, 1].mean()))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        cap.release()
        colorfulness = round(sum(sats) / len(sats), 1) if sats else 0.0
        kind = "红外(灰)" if colorfulness < 12 and max(means or [0]) > 1 else "彩色"
        print("  index=%d  %s  %dx%d  亮度=%s  饱和度=%.1f  → %s"
              % (idx, label, w, h, means, colorfulness, kind))

    print("\n结论：")
    if found == 0:
        print("  一个都打不开 → 现在的摄像头不能用于认人（换 UVC 摄像头）")
        return 1
    if found == 1:
        print("  只有 1 个视频设备 → 能看脸，但没有红外，防不了照片")
        return 0
    print("  有 %d 个视频设备 → 如果是「彩色+红外」，就能做防照片的认人" % found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
