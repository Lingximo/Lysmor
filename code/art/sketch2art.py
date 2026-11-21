# -*- coding: utf-8 -*-
"""把她在画图里的草稿，交给 ComfyUI 上色成一张成品。

流程：草稿图 → 缩到 768 → 上传 ComfyUI → img2img（denoise 0.55）
     → 取回成品 → 存 art/gallery/sketch_<时间>.jpg

用法：
    python sketch2art.py --input doodle_xxx.jpg --pattern fish
"""
from __future__ import annotations

import argparse
import io
import os
import random
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_art  # noqa: E402

API = "http://127.0.0.1:8188"
CKPT = "animagine-xl-4.0.safetensors"
# 2026-11-10：草稿上色需要结构约束，否则模型会无视线稿自己画。
# SDXL scribble controlnet（xinsir），没有就退回 img2img。
CONTROLNET = "xinsir-scribble-sdxl.safetensors"
CN_PATH = r"E:\Comfy-Desktop\ComfyUI-Shared\models\controlnet\xinsir-scribble-sdxl.safetensors"
GALLERY = HERE / "gallery"

PROMPTS = {
    "fish": "a cute anime fish, children's picture book style, soft colors, clean white background, simple shapes, kawaii",
    "heart": "a cute anime heart, pastel colors, soft glow, clean white background, kawaii, simple shapes",
    "star": "a cute anime star, pastel colors, soft sparkle, clean white background, kawaii, simple shapes",
    "wave": "gentle anime ocean waves, pastel blue, clean white background, soft lines, children's picture book",
}
NEG = "photo, realistic, 3d, blurry, text, watermark, signature, ugly, deformed"


def _resize(path: Path, max_side: int = 768) -> Path:
    from PIL import Image
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    out = Path(os.environ.get("TEMP", ".")) / ("sketch_%d.jpg" % int(time.time() * 1000))
    img.save(out, "JPEG", quality=92)
    return out


def _upload(path: Path) -> str:
    with open(path, "rb") as f:
        r = requests.post(API + "/upload/image",
                          files={"image": (path.name, f, "image/jpeg")},
                          data={"overwrite": "true"}, timeout=60)
    r.raise_for_status()
    j = r.json()
    name = j.get("name") or path.name
    sub = j.get("subfolder") or ""
    return (sub + "/" + name) if sub else name


def _use_controlnet() -> bool:
    try:
        import os as _os
        return _os.path.getsize(CN_PATH) > 100 * 1024 * 1024
    except Exception:
        return False


def _workflow(image_name: str, prompt: str, seed: int, denoise: float) -> dict:
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["1", 1]}},
        "4": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "5": {"class_type": "VAEEncode", "inputs": {"pixels": ["4", 0], "vae": ["1", 2]}},
        "6": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
            "latent_image": ["5", 0], "seed": seed, "steps": 26, "cfg": 6.0,
            "sampler_name": "euler_ancestral", "scheduler": "karras",
            "denoise": denoise,
        }},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage", "inputs": {
            "filename_prefix": "companion_sketch", "images": ["7", 0]}},
    }
    if _use_controlnet():
        wf["9"] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": CONTROLNET}}
        wf["10"] = {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": ["2", 0], "negative": ["3", 0],
            "control_net": ["9", 0], "image": ["4", 0],
            "strength": 0.85, "start_percent": 0.0, "end_percent": 1.0,
        }}
        wf["6"]["inputs"]["positive"] = ["10", 0]
        wf["6"]["inputs"]["negative"] = ["10", 1]
        wf["6"]["inputs"]["denoise"] = 1.0
    return wf


def _vram_free_gb():
    try:
        import subprocess
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        return round(float(out.splitlines()[0]) / 1024.0, 2)
    except Exception:
        return None


def _game_running():
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            n = (p.info.get("name") or "").lower()
            if n in ("zenlesszonezero.exe", "yuanshen.exe", "starrail.exe"):
                return n
    except Exception:
        pass
    return ""


def _guard():
    """显存不够 / 有游戏在跑，就别让 ComfyUI 抢卡。"""
    game = _game_running()
    if game:
        raise RuntimeError("你在玩 %s，这次不抢显卡" % game)
    free = _vram_free_gb()
    if free is not None and free < 4.5:
        raise RuntimeError("显存只剩 %.1f GB，先不上色" % free)
    return free


def _free_comfy():
    """用完把模型从显存里卸掉。"""
    try:
        requests.post(API + "/free", json={"unload_models": True, "free_memory": True},
                      timeout=20)
    except Exception:
        pass


def run(sketch: Path, pattern: str = "fish", denoise: float = 0.55) -> dict:
    free0 = _guard()
    # 先看它是不是已经在跑（可能是 Comfy Desktop 启动的，不归 make_art 管）
    alive = False
    try:
        alive = requests.get(API + "/system_stats", timeout=5).status_code == 200
    except Exception:
        alive = False
    if not alive and not make_art.ensure_comfy():
        raise RuntimeError("ComfyUI 起不来")
    small = _resize(sketch)
    name = _upload(small)
    prompt = PROMPTS.get(pattern, PROMPTS["fish"])
    seed = random.randint(1, 2 ** 31 - 1)

    r = requests.post(API + "/prompt",
                      json={"prompt": _workflow(name, prompt, seed, denoise)}, timeout=60)
    r.raise_for_status()
    pid = r.json()["prompt_id"]

    deadline = time.time() + 300
    while time.time() < deadline:
        time.sleep(2)
        h = requests.get(API + "/history/" + pid, timeout=20).json()
        if pid in h and h[pid].get("outputs"):
            outs = h[pid]["outputs"]
            for node in outs.values():
                for img in node.get("images") or []:
                    q = {"filename": img["filename"], "subfolder": img.get("subfolder", ""),
                         "type": img.get("type", "output")}
                    d = requests.get(API + "/view", params=q, timeout=60)
                    if d.status_code == 200:
                        GALLERY.mkdir(parents=True, exist_ok=True)
                        ext = ".png" if d.content[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
                        out = GALLERY / ("sketch_%s%s" % (time.strftime("%Y%m%d_%H%M%S"), ext))
                        if ext == ".png":
                            # 统一存成 jpg，方便画廊/记忆使用
                            from PIL import Image as _Img
                            _img = _Img.open(io.BytesIO(d.content)).convert("RGB")
                            out = out.with_suffix(".jpg")
                            _img.save(out, "JPEG", quality=92)
                        else:
                            out.write_bytes(d.content)
                        _free_comfy()
                        return {"ok": True, "path": str(out), "seed": seed,
                                "prompt_id": pid, "pattern": pattern, "vram_free_before": free0}
        if h.get(pid, {}).get("status", {}).get("status_str") == "error":
            raise RuntimeError("ComfyUI 执行出错")
    raise RuntimeError("ComfyUI 超时")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--pattern", default="fish")
    ap.add_argument("--denoise", type=float, default=0.55)
    a = ap.parse_args()
    t0 = time.time()
    res = run(Path(a.input), a.pattern, a.denoise)
    print("完成 %.1fs：%s" % (time.time() - t0, res["path"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
