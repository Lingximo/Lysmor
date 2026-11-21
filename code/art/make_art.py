# -*- coding: utf-8 -*-
"""TA画画：ComfyUI 出成品，再生成笔画过程视频，并写入画廊索引。

B 方案：
- 画廊/成品：ComfyUI 的完整手绘风成图
- QQ：先发笔画过程视频，再发成品
- 过程是笔画回放，不冒充“AI 逐笔生成”
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GALLERY = ROOT / "gallery"
PROCESS = ROOT / "process"
GALLERY.mkdir(parents=True, exist_ok=True)
PROCESS.mkdir(parents=True, exist_ok=True)

API = "http://127.0.0.1:8188"
MODEL = "animagine-xl-4.0.safetensors"
COMFY_ROOT = Path(r"E:\ComfyUI视频制作\ComfyUI (1)")
COMFY_PY = COMFY_ROOT / "ComfyUI" / ".venv" / "Scripts" / "python.exe"
COMFY_MAIN = COMFY_ROOT / "ComfyUI" / "main.py"
EXTRA_PATHS = Path(
    r"C:\你的用户\AppData\Roaming\Comfy Desktop"
    r"\instance-model-paths\inst-1792255860058.yaml"
)
COMFY_OUT = Path(r"E:\Comfy-Desktop\ComfyUI-Shared\output")
COMFY_IN = Path(r"E:\Comfy-Desktop\ComfyUI-Shared\input")
COMFY_LOG = Path(r"D:\你的数据目录\logs\comfyui-art.log")

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

_server_proc: subprocess.Popen | None = None


def _get_json(path: str, timeout: float = 10.0):
    with urllib.request.urlopen(API + path, timeout=timeout) as r:
        return json.load(r)


def _post_json(path: str, payload: dict, timeout: float = 30.0):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def _server_up() -> bool:
    try:
        _get_json("/system_stats", timeout=4)
        return True
    except Exception:
        return False


def ensure_comfy() -> bool:
    """返回 True 表示这次是脚本自己启动的。"""
    global _server_proc
    if _server_up():
        return False
    if not COMFY_PY.exists() or not COMFY_MAIN.exists():
        raise RuntimeError("ComfyUI 路径不存在")
    if not (Path(r"E:\Comfy-Desktop\ComfyUI-Shared\models\checkpoints") / MODEL).exists():
        raise RuntimeError("模型不存在：" + MODEL)
    COMFY_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = open(COMFY_LOG, "a", encoding="utf-8", buffering=1)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    _server_proc = subprocess.Popen(
        [
            str(COMFY_PY), str(COMFY_MAIN),
            "--listen", "127.0.0.1", "--port", "8188",
            "--extra-model-paths-config", str(EXTRA_PATHS),
            "--output-directory", str(COMFY_OUT),
            "--input-directory", str(COMFY_IN),
            "--preview-method", "none",
            "--disable-auto-launch",
            "--disable-all-custom-nodes",
        ],
        cwd=str(COMFY_MAIN.parent),
        stdout=log,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    for _ in range(120):
        if _server_up():
            return True
        if _server_proc.poll() is not None:
            raise RuntimeError("ComfyUI 启动失败，见 " + str(COMFY_LOG))
        time.sleep(1)
    raise RuntimeError("ComfyUI 启动超时")


def stop_comfy(started: bool) -> None:
    global _server_proc
    try:
        _post_json("/free", {"unload_models": True, "free_memory": True})
    except Exception:
        pass
    if started and _server_proc is not None:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(_server_proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=15,
            )
        except Exception:
            try:
                _server_proc.terminate()
            except Exception:
                pass
        _server_proc = None


def workflow(prompt: str, seed: int) -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": MODEL}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 768, "height": 1024, "batch_size": 1}},
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": 28, "cfg": 5.5,
                "sampler_name": "euler_ancestral", "scheduler": "normal",
                "denoise": 1.0, "model": ["1", 0],
                "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
            },
        },
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "companion_art", "images": ["6", 0]}},
    }


def _wait_job(prompt_id: str, timeout: float = 600.0) -> dict:
    start = time.time()
    while time.time() - start < timeout:
        h = _get_json("/history/" + urllib.parse.quote(prompt_id))
        if prompt_id in h:
            return h[prompt_id]
        time.sleep(1)
    raise TimeoutError("ComfyUI 出图超时")


def _download(image: dict, target: Path) -> None:
    q = urllib.parse.urlencode({
        "filename": image["filename"],
        "subfolder": image.get("subfolder", ""),
        "type": image.get("type", "output"),
    })
    with urllib.request.urlopen(API + "/view?" + q, timeout=90) as r:
        target.write_bytes(r.read())


def _pick_mood() -> tuple[str, dict]:
    path = Path(r"C:\你的用户\.astrbot_launcher\instances"
                r"\<BOT_INSTANCE>\core\data\plugin_data"
                r"\astrbot_plugin_companion_mood\state.json")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "calm", {}
    v = float(state.get("valence", 0) or 0)
    sad = float(state.get("sadness", 0) or 0)
    anger = float(state.get("anger", 0) or 0)
    fear = float(state.get("fear", 0) or 0)
    if v >= 0.15 and sad < 0.45 and anger < 0.35 and fear < 0.45:
        mood = "good"
    elif v <= -0.12 or sad >= 0.5 or anger >= 0.4 or fear >= 0.5:
        mood = "bad"
    else:
        mood = "calm"
    return mood, state


def _append_index(item: dict) -> None:
    path = GALLERY / "index.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            data = []
    except Exception:
        data = []
    data.append(item)
    data = data[-200:]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def generate(idea: str, title: str = "", source: str = "qq") -> dict:
    started = ensure_comfy()
    try:
        art_id = time.strftime("%Y%m%d-%H%M%S") + "-" + str(random.randint(100, 999))
        seed = random.randint(1, 2**31 - 1)
        # 2026-11-07：scene: 前缀 → 画"不是她"的东西（食物/房间/窗外/梦），不拼角色
        if str(idea).startswith("scene:"):
            _body = str(idea)[len("scene:"):].strip()
            prompt = f"{QUALITY}, {STYLE}, {_body}, detailed composition"
        else:
            prompt = f"{QUALITY}, {STYLE}, {CHAR}, {idea}, detailed composition"
        res = _post_json("/prompt", {"prompt": workflow(prompt, seed), "client_id": "companion-art"})
        if res.get("node_errors"):
            raise RuntimeError("工作流错误：" + json.dumps(res["node_errors"], ensure_ascii=False)[:400])
        pid = res["prompt_id"]
        hist = _wait_job(pid)
        images = hist.get("outputs", {}).get("7", {}).get("images", [])
        if not images:
            raise RuntimeError("没有拿到图片：" + json.dumps(hist, ensure_ascii=False)[:500])

        final = GALLERY / f"{art_id}_final.png"
        _download(images[0], final)

        raw_video = PROCESS / f"{art_id}_raw.mp4"
        stroke_final = PROCESS / f"{art_id}_stroke.png"
        subprocess.run(
            [
                str(COMFY_PY), str(ROOT / "stroke_paint.py"),
                str(final),
                "--out", str(stroke_final),
                "--video", str(raw_video),
                "--no-lines",
            ],
            check=True,
            timeout=600,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        h264 = raw_video.with_name(raw_video.stem + "_h264.mp4")
        process = PROCESS / f"{art_id}_process.mp4"
        if h264.exists():
            shutil.copy2(h264, process)
        elif raw_video.exists():
            shutil.copy2(raw_video, process)
        else:
            raise RuntimeError("没有生成过程视频")

        mood, state = _pick_mood()
        item = {
            "id": art_id,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "title": title or idea[:24],
            "idea": idea,
            "prompt": prompt,
            "seed": seed,
            "image": str(final),
            "process": str(process),
            "source": source,
            "mood": mood,
            "caption": title or idea[:40],
            "mood_valence": round(float(state.get("valence", 0) or 0), 3),
        }
        _append_index(item)
        return item
    finally:
        stop_comfy(started)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--idea", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--source", default="qq")
    args = ap.parse_args()
    item = generate(args.idea, args.title, args.source)
    print(json.dumps(item, ensure_ascii=False))


if __name__ == "__main__":
    main()
