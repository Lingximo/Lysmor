# -*- coding: utf-8 -*-
"""ComfyUI 本地 API 的小规模测试：只用标准 SDXL 节点，不接 QQ/记忆/画廊。"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8188"
MODEL = "animagine-xl-4.0.safetensors"
OUT = Path(r"D:\你的数据目录\art\gallery")
MODEL_PATH = Path(r"E:\Comfy-Desktop\ComfyUI-Shared\models\checkpoints") / MODEL
EXPECTED_SIZE = 6938434056

NEG = (
    "lowres, bad anatomy, bad hands, extra fingers, fewer fingers, missing fingers, "
    "extra limbs, malformed hands, watermark, text, signature, logo, nsfw, blurry, "
    "jpeg artifacts, ugly, deformed"
)
QUALITY = "masterpiece, best quality, very aesthetic, absurdres"
STYLE = (
    "hand-drawn, traditional media, watercolor, colored pencil, ink sketch lines, "
    "visible paper texture, gentle imperfect linework, soft natural lighting"
)
CHAR = (
    "1girl, solo, blue hair, long wavy hair, blue eyes, navy blue maid dress, "
    "white apron with small whale emblem, white frilled headdress, blue hair ribbon, "
    "blue whale tail, ahoge"
)

PROMPTS = [
    {
        "name": "window_night",
        "text": (
            f"{QUALITY}, {STYLE}, {CHAR}, sitting on a windowsill, city night, "
            "looking out, gentle smile, quiet mood, detailed background"
        ),
        "seed": 1234,
    },
    {
        "name": "whale_plush",
        "text": (
            f"{QUALITY}, {STYLE}, {CHAR}, hugging a soft round blue whale plush toy "
            "with a white belly and small fins, her cozy room, evening, warm lamp light, "
            "soft smile, detailed interior, no helmet"
        ),
        "seed": 5678,
    },
    {
        "name": "gallery",
        "text": (
            f"{QUALITY}, {STYLE}, {CHAR}, standing in a cozy small art gallery, "
            "many framed watercolor paintings on the walls, wooden floor, holding a "
            "paintbrush, looking at a painting, calm mood, detailed interior"
        ),
        "seed": 9012,
    },
]


def wait_for_model() -> None:
    last = -1
    stable = 0
    for _ in range(3600):
        size = MODEL_PATH.stat().st_size if MODEL_PATH.exists() else 0
        if size >= EXPECTED_SIZE:
            print(f"model ready: {size}", flush=True)
            return
        if size == last:
            stable += 1
        else:
            stable = 0
            last = size
        if stable and stable % 30 == 0:
            print(f"waiting model: {size / 1e9:.2f}GB", flush=True)
        time.sleep(2)
    raise RuntimeError("model download timeout")


def workflow(prompt: str, seed: int) -> dict:
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": MODEL},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["1", 1]},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": NEG, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 768, "height": 1024, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 28,
                "cfg": 5.5,
                "sampler_name": "euler_ancestral",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "companion_art_test", "images": ["6", 0]},
        },
    }


def post_json(path: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)


def get_json(path: str) -> dict:
    with urllib.request.urlopen(API + path, timeout=30) as res:
        return json.load(res)


def wait_job(prompt_id: str, timeout: float = 600.0) -> dict:
    start = time.time()
    last_state = None
    while time.time() - start < timeout:
        h = get_json("/history/" + urllib.parse.quote(prompt_id))
        if prompt_id in h:
            return h[prompt_id]
        st = get_json("/queue")
        running = any(
            item[1] == prompt_id for item in st.get("queue_running", [])
        )
        state = "running" if running else "queued"
        if state != last_state:
            print(f"  {state}", flush=True)
            last_state = state
        time.sleep(1)
    raise TimeoutError(f"job timeout: {prompt_id}")


def get_image(image: dict, target: Path) -> None:
    q = urllib.parse.urlencode(
        {
            "filename": image["filename"],
            "subfolder": image.get("subfolder", ""),
            "type": image.get("type", "output"),
        }
    )
    with urllib.request.urlopen(API + "/view?" + q, timeout=60) as res:
        target.write_bytes(res.read())


def main() -> None:
    wait_for_model()
    OUT.mkdir(parents=True, exist_ok=True)
    # 等 ComfyUI 重新扫描到完整模型
    info = get_json("/object_info/CheckpointLoaderSimple")
    names = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    print("checkpoints:", names, flush=True)
    if MODEL not in names:
        raise RuntimeError(f"{MODEL} not in ComfyUI checkpoint list")

    for item in PROMPTS:
        print("\n=== " + item["name"] + " ===", flush=True)
        wf = workflow(item["text"], item["seed"])
        res = post_json("/prompt", {"prompt": wf, "client_id": "companion-art-test"})
        if res.get("node_errors"):
            raise RuntimeError(f"node_errors: {res['node_errors']}")
        pid = res["prompt_id"]
        print("prompt_id:", pid, flush=True)
        h = wait_job(pid)
        status = h.get("status", {})
        print("status:", status.get("status_str"), status.get("completed"), flush=True)
        outputs = h.get("outputs", {})
        images = outputs.get("7", {}).get("images", [])
        if not images:
            raise RuntimeError(f"no image output: {json.dumps(h, ensure_ascii=False)[:1000]}")
        target = OUT / f"test_{item['name']}.png"
        get_image(images[0], target)
        print("saved:", target, target.stat().st_size, flush=True)

    # 测试结束释放显存
    try:
        post_json("/free", {"unload_models": True, "free_memory": True})
        print("freed models", flush=True)
    except Exception as exc:
        print("free failed:", repr(exc), flush=True)


if __name__ == "__main__":
    main()
