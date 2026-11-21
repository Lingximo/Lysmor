import base64, io, json, time
from PIL import Image
import urllib.request

img = Image.open(r"D:\dev\pico_latest.png").convert("RGB")
img.thumbnail((640, 640))
buf = io.BytesIO(); img.save(buf, "JPEG", quality=85)
b64 = base64.b64encode(buf.getvalue()).decode()
p = "请只输出一句对这张图片的客观中文描述，不要解释，不要复述要求。"
for extra in (
    {"chat_template_kwargs": {"enable_thinking": False}},
    {"enable_thinking": False},
    {"think": False, "chat_template_kwargs": {"enable_thinking": False}},
):
    payload = {"model": "qwen3-vl:4b",
               "messages": [{"role": "user", "content": p, "images": [b64]}],
               "stream": False, "keep_alive": "10m",
               "options": {"temperature": 0.2, "num_predict": 80, "num_ctx": 4096}}
    payload.update(extra)
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.loads(r.read())
        print("EXTRA", extra, "TIME", round(time.time()-t,2))
        print("MSG", repr((body.get("message") or {}).get("content")))
        print("THINK", repr((body.get("message") or {}).get("thinking"))[:120])
    except Exception as e:
        print("ERR", extra, e)
    print("---")
