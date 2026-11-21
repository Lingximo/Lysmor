import base64, io, json, sys, time
from PIL import Image
import urllib.request

img = Image.open(r"D:\dev\pico_latest.png").convert("RGB")
img.thumbnail((640, 640))
buf = io.BytesIO(); img.save(buf, "JPEG", quality=85)
b64 = base64.b64encode(buf.getvalue()).decode()

prompts = [
    "这是戴在头上的眼镜拍到的第一视角照片。用一句话说清楚：看到了什么、谁、什么环境、什么颜色。",
    "请只输出一句对这张图片的客观中文描述，不要解释，不要复述要求。",
    "画面里有什么？用一句中文回答。",
    "用一句中文描述这张照片里的场景。",
    "Describe this image in one short Chinese sentence.",
]
for p in prompts:
    payload = {
        "model": "qwen3-vl:4b", "prompt": p, "images": [b64],
        "stream": False, "think": False, "keep_alive": "10m",
        "options": {"temperature": 0.2, "num_predict": 50, "num_ctx": 4096},
    }
    req = urllib.request.Request("http://127.0.0.1:11434/api/generate",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.loads(r.read())
        text = (body.get("response") or "").strip()
        print("PROMPT:", p)
        print("TIME:", round(time.time() - t, 2), "RESP:", repr(text))
        print("---")
    except Exception as e:
        print("ERR", e)
