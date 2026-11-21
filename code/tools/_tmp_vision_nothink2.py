import base64, io, json, time
from PIL import Image
import urllib.request

img = Image.open(r"D:\dev\pico_latest.png").convert("RGB")
img.thumbnail((640, 640))
buf = io.BytesIO(); img.save(buf, "JPEG", quality=85)
b64 = base64.b64encode(buf.getvalue()).decode()
for p in [
    "用一句中文描述这张照片里的场景。/no_think",
    "用一句中文描述这张照片里的场景。不要思考，直接回答。",
    "/no_think 用一句中文描述这张照片里的场景。",
]:
    payload = {"model": "qwen3-vl:4b", "prompt": p, "images": [b64],
               "stream": False, "think": False, "keep_alive": "10m",
               "options": {"temperature": 0.2, "num_predict": 90, "num_ctx": 4096}}
    req = urllib.request.Request("http://127.0.0.1:11434/api/generate",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read())
    print("PROMPT", p)
    print("TIME", round(time.time()-t,2), "RESP", repr((body.get("response") or "")[:200]))
    print("THINK", repr((body.get("thinking") or "")[:100]))
