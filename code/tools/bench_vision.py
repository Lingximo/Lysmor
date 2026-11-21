"""对比视觉模型：同一张图，看谁描述得准、谁更快。

用法:
  python bench_vision.py <图片> [模型1 模型2 ...]
"""
import base64
import io
import sys
import time

import requests
from PIL import Image

OLLAMA = "http://127.0.0.1:11434/api/generate"
PROMPT = (
    "用一句中文（不超过 40 字）描述这张图：里面有什么、在做什么、什么颜色、什么环境。"
    "看不清的就别编。只输出这句描述。"
)


def encode(path, max_side=896):
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True)
    return base64.b64encode(buf.getvalue()).decode(), img.size


def ask(model, b64):
    payload = {
        "model": model,
        "prompt": PROMPT,
        "images": [b64],
        "stream": False,
        "keep_alive": "10m",
        "options": {"temperature": 0.2, "num_predict": 80, "num_ctx": 4096},
    }
    t0 = time.time()
    r = requests.post(OLLAMA, json=payload, timeout=300)
    body = r.json()
    return (time.time() - t0), (body.get("response") or "").strip()


def main():
    path = sys.argv[1]
    models = sys.argv[2:] or ["qwen3-vl:4b"]
    b64, size = encode(path)
    print(f"图片: {path}  压缩后 {size[0]}x{size[1]}\n")
    for model in models:
        try:
            cost, text = ask(model, b64)
            print(f"【{model}】{cost:.1f}s")
            print(f"  {text or '(空)'}\n")
        except Exception as exc:  # noqa: BLE001
            print(f"【{model}】失败: {exc}\n")


if __name__ == "__main__":
    main()
