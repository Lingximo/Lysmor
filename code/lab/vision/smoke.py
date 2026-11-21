# -*- coding: utf-8 -*-
"""冒烟测试：开摄像头 → 检测人脸 → 存一张调试图。

用途：确认"这条链路在这台机器上通"，不涉及认人。
用法：python lab\\vision\\smoke.py

2026-11-09：E4 走通用 UVC 驱动，枚举名是 "Integrated Camera"，
OpenCV 里 index 是 1（0 是 VC-005 采集卡，没接信号时是"无信号"画面）。
所以改用 face_lib.pick_camera() 自动挑真摄像头。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import face_lib  # noqa: E402
import cv2  # noqa: E402


def main():
    cap, label, idx = face_lib.pick_camera()
    if cap is None:
        print("没有可用的摄像头（可能被 8003 视频通话占用）")
        return 1

    print("摄像头 index=%d 后端=%s 打开成功" % (idx, label))
    ok, frame = False, None
    for _ in range(8):
        ok, frame = cap.read()
        if ok and frame is not None:
            break
        time.sleep(0.1)
    if not ok or frame is None:
        cap.release()
        print("读不到画面")
        return 1

    print("画面 %dx%d 亮度 %.0f" % (frame.shape[1], frame.shape[0], frame.mean()))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smoke.jpg")
    cv2.imwrite(out, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    print("已存:", out)

    det = face_lib.FaceDetector()
    faces = det.detect(frame)
    print("检出 %d 张脸" % len(faces))
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
