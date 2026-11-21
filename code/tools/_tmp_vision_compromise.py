import base64, io, json, time
from PIL import Image
import urllib.request

img = Image.open(r"D:\dev\pico_latest.png").convert("RGB")
img.thumbnail((640, 640))
buf = io.BytesIO(); img.save(buf, "JPEG", quality=85)
b64 = base64.b64encode(buf.getvalue()).decode()

tests = [
    ("直接回答：这张照片里有什么？", 240),
    ("只描述画面，不分析。用一句中文。", 240),
    ("请只输出一句对这张图片的客观中文描述，不要解释，不要复述要求。", 300),
    ("请只输出一句对这张图片的客观中文描述，不要解释，不要复述要求。", 330),
]
for p, n in tests:
    payload = {"model": "qwen3-vl:4b", "prompt": p, "images": [b64],
               "stream": False, "think": False, "keep_alive": "10m",
               "options": {"temperature": 0.2, "num_predict": n, "num_ctx": 4096}}
    req = urllib.request.Request("http://127.0.0.1:11434/api/generate",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=90) as r:
        body = json.loads(r.read())
    resp = (body.get("response") or "").strip()
    think = (body.get("thinking") or "").strip()
    print("PROMPT", p, "N", n, "TIME", round(time.time()-t,2))
    print("RESP", repr(resp[:220]))
    print("THINK_TAIL", repr(think[-80:]))
    print("---")
