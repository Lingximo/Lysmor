import base64, io, json, time
from PIL import Image
import urllib.request

img = Image.open(r"D:\dev\pico_latest.png").convert("RGB")
img.thumbnail((640, 640))
buf = io.BytesIO(); img.save(buf, "JPEG", quality=85)
b64 = base64.b64encode(buf.getvalue()).decode()
p = "请只输出一句对这张图片的客观中文描述，不要解释，不要复述要求。"
for n in (80, 120):
    payload = {"model": "qwen3-vl:4b", "prompt": p, "images": [b64],
               "stream": False, "think": False, "raw": True,
               "keep_alive": "10m",
               "options": {"temperature": 0.2, "num_predict": n, "num_ctx": 4096}}
    req = urllib.request.Request("http://127.0.0.1:11434/api/generate",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.loads(r.read())
        print("N", n, "TIME", round(time.time()-t,2), "RESP", repr((body.get("response") or "")[:200]))
        print("THINK", repr((body.get("thinking") or "")[:100]))
    except Exception as e:
        print("ERR", e)
