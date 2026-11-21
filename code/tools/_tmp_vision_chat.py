import base64, io, json, time
from PIL import Image
import urllib.request

img = Image.open(r"D:\dev\pico_latest.png").convert("RGB")
img.thumbnail((640, 640))
buf = io.BytesIO(); img.save(buf, "JPEG", quality=85)
b64 = base64.b64encode(buf.getvalue()).decode()
p = "请只输出一句对这张图片的客观中文描述，不要解释，不要复述要求。"
payload = {
    "model": "qwen3-vl:4b",
    "messages": [{"role": "user", "content": p, "images": [b64]}],
    "stream": False, "think": False, "keep_alive": "10m",
    "options": {"temperature": 0.2, "num_predict": 120, "num_ctx": 4096},
}
req = urllib.request.Request("http://127.0.0.1:11434/api/chat",
                             data=json.dumps(payload).encode(),
                             headers={"Content-Type": "application/json"})
t = time.time()
with urllib.request.urlopen(req, timeout=90) as r:
    body = json.loads(r.read())
print("TIME", round(time.time()-t,2))
print("MSG", repr((body.get("message") or {}).get("content")))
print("THINK", repr((body.get("message") or {}).get("thinking")))
print("BODY", {k: body.get(k) for k in ("done_reason","eval_count","total_duration")})
