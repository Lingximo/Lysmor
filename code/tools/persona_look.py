# -*- coding: utf-8 -*-
"""你要她"看一下"时才用视觉模型（她的自由玩不再用视觉）

用法：
  python persona_look.py                 # 看整个屏幕
  python persona_look.py --x 120 --y 340 # 看某一点周围
  python persona_look.py --q "屏幕上有什么程序"  # 自定义问题
"""
import base64
import io
import json
import sys
import os
import time

ROOT = r"D:\你的数据目录"
OLLAMA = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3-vl:4b"
LOG = os.path.join(ROOT, "state", "persona", "look_log.jsonl")

try:
    import requests
except Exception:  # noqa: BLE001
    requests = None


def _shot(x=None, y=None, w=380, h=260):
    from PIL import ImageGrab
    import pyautogui
    sw, sh = pyautogui.size()
    if x is None:
        img = ImageGrab.grab()
    else:
        left = max(0, min(sw - 20, int(x) - w // 2))
        top = max(0, min(sh - 20, int(y) - h // 2))
        img = ImageGrab.grab(bbox=(left, top, min(sw, left + w), min(sh, top + h)))
        img = img.resize((img.width * 2, img.height * 2))
    if img.width > 1400:
        img.thumbnail((1400, 1400))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=78)
    return base64.b64encode(buf.getvalue()).decode()


def main():
    args = sys.argv[1:]
    x = y = None
    q = "描述这块屏幕上看到的内容：开着哪些程序窗口、桌面上有什么、值得注意的东西。简洁一点。"
    if "--x" in args and "--y" in args:
        x = float(args[args.index("--x") + 1])
        y = float(args[args.index("--y") + 1])
        q = "这是屏幕上一块放大的区域。说清：这是什么（图标/按钮/文字/空白）、名字或内容是什么。"
    if "--q" in args:
        q = args[args.index("--q") + 1]
    b64 = _shot(x, y)
    if requests is None:
        print("没有 requests")
        return 1
    try:
        rr = requests.post(OLLAMA, json={
            "model": MODEL, "prompt": q, "images": [b64], "stream": False,
            "options": {"temperature": 0.2, "num_predict": 2200}}, timeout=240)
        j = rr.json()
        raw = (j.get("response") or "").strip() or (j.get("thinking") or "").strip()
        for opener, closer in (("{", "}"), ("[", "]")):
            a = raw.find(opener); b = raw.rfind(closer)
            if a >= 0 and b > a:
                try:
                    raw = json.dumps(json.loads(raw[a:b + 1]), ensure_ascii=False, indent=1)
                    break
                except Exception:
                    pass
    except Exception as exc:  # noqa: BLE001
        print("看不了：%s" % exc)
        return 1
    print(raw[:2000])
    try:
        with io.open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "x": x, "y": y, "q": q, "answer": raw[:2000]},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
