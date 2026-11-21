# -*- coding: utf-8 -*-
"""TA的眼睛：从 E4 取一帧 → 看看有没有人脸 → 让视觉模型说一句话。

用法：
    python lab\\vision\\eye.py            # 取一帧，打印结果
    python lab\\vision\\eye.py --save out.jpg

对外：
    look()              返回 dict：{"ok", "desc", "faces", "bright", "frame"(jpg bytes)}
    describe_file(path) 给一张图做同样的事

原则：
  · 只读，不写记忆、不改状态
  · 摄像头占用会互相抢：取完立刻 release
"""
from __future__ import annotations

import base64
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PYLIBS = os.path.join(HERE, "pylibs")
if os.path.isdir(PYLIBS) and PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)

import cv2  # noqa: E402
import face_lib  # noqa: E402

OLLAMA = "http://127.0.0.1:11434/api/generate"
VL_MODEL = "qwen3-vl:4b"

PROMPT = (
    "你是TA，正在通过摄像头看你。"
    "用一句中文说你看到什么：人在做什么、环境是什么样子。"
    "不要提图片、模型、AI，不要分行。"
)


def _b64(jpg_bytes: bytes) -> str:
    return base64.b64encode(jpg_bytes).decode()


def describe_jpeg(jpg_bytes: bytes, prompt: str = PROMPT) -> str:
    import re

    import requests

    # 注意：不要传 think=False + 很小的 num_predict，
    # 那样模型会把预算全用在思考上，返回空字符串（踩过）。
    payload = {
        "model": VL_MODEL,
        "prompt": prompt,
        "images": [_b64(jpg_bytes)],
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 900},
    }
    try:
        r = requests.post(OLLAMA, json=payload, timeout=180)
        if r.status_code != 200:
            return ""
        out = str((r.json() or {}).get("response") or "")
        if not out.strip():
            # 思考把预算吃光时会返回空，加一次更大预算重试
            payload["options"]["num_predict"] = 1400
            r2 = requests.post(OLLAMA, json=payload, timeout=180)
            if r2.status_code == 200:
                out = str((r2.json() or {}).get("response") or "")
        out = re.sub(r"(?is)<think>.*?</think>", "", out)
        out = re.sub(r"(?is)<think>.*$", "", out).replace("</think>", "")
        return " ".join(out.split())[:200]
    except Exception as exc:  # noqa: BLE001
        print("[眼睛] 描述失败:", exc)
        return ""


def grab_frame(width: int = 1280, height: int = 720):
    """取一帧；返回 (frame, meta)。frame 为 None 表示没摄像头。"""
    cap, label, idx = face_lib.pick_camera(width=width, height=height)
    if cap is None:
        return None, {"backend": "none", "index": -1}
    try:
        ok, frame = False, None
        for _ in range(8):
            ok, frame = cap.read()
            if ok and frame is not None and frame.mean() > 3:
                break
            time.sleep(0.08)
        meta = {"backend": label, "index": idx}
        return (frame, meta) if ok and frame is not None else (None, meta)
    finally:
        cap.release()


def _shrink(frame, max_w: int = 960):
    """缩到 960 宽再送模型：视觉模型对分辨率不敏感，但速度差很多。"""
    try:
        h, w = frame.shape[:2]
        if w <= max_w:
            return frame
        scale = max_w / float(w)
        return cv2.resize(frame, (max_w, int(h * scale)), interpolation=cv2.INTER_AREA)
    except Exception:  # noqa: BLE001
        return frame


def look(prompt: str = PROMPT) -> dict:
    frame, meta = grab_frame()
    if frame is None:
        return {"ok": False, "error": "没取到画面", "faces": 0, **meta}

    bright = float(frame.mean())
    faces = 0
    try:
        det = face_lib.FaceDetector()
        faces = len(det.detect(frame))
    except Exception as exc:  # noqa: BLE001
        print("[眼睛] 人脸检测失败:", exc)

    ok, buf = cv2.imencode(".jpg", _shrink(frame), [int(cv2.IMWRITE_JPEG_QUALITY), 78])
    jpg = buf.tobytes() if ok else b""
    desc = describe_jpeg(jpg, prompt) if jpg else ""
    return {
        "ok": bool(desc),
        "desc": desc,
        "faces": faces,
        "bright": bright,
        "frame": jpg,
        **meta,
    }


def describe_file(path: str, prompt: str = PROMPT) -> str:
    with open(path, "rb") as f:
        data = f.read()
    return describe_jpeg(data, prompt)


if __name__ == "__main__":
    save = None
    if "--save" in sys.argv:
        i = sys.argv.index("--save")
        if i + 1 < len(sys.argv):
            save = sys.argv[i + 1]
    t0 = time.time()
    r = look()
    print("后端=%s index=%s 人脸=%d 亮度=%.0f 耗时=%.1fs" % (
        r.get("backend"), r.get("index"), r.get("faces", 0), r.get("bright", 0),
        time.time() - t0))
    print("她说:", r.get("desc") or ("（失败：%s）" % r.get("error")))
    if save and r.get("frame"):
        with open(save, "wb") as f:
            f.write(r["frame"])
        print("已存:", save)
