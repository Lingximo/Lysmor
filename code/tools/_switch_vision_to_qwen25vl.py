import json
import os
import shutil
import time

ROOT = r"D:\你的数据目录"
OLD = "qwen3-vl:4b"
NEW = "qwen2.5vl:3b"
STAMP = time.strftime("%Y%m%d-%H%M%S")

FILES = [
    os.path.join(ROOT, "lab", "game", "controller.py"),
    os.path.join(ROOT, "lab", "pico", "eye_server_8804.py"),
    os.path.join(ROOT, "lab", "vision", "eye.py"),
    os.path.join(ROOT, "lab", "wear", "server.py"),
    os.path.join(ROOT, "screen", "server.py"),
    os.path.join(ROOT, "webchat", "server.py"),
]

for path in FILES:
    if not os.path.exists(path):
        print("SKIP missing", path)
        continue
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if OLD not in text:
        print("SKIP no old model", path)
        continue
    shutil.copy2(path, path + ".bak-before-qwen25vl-" + STAMP)
    text = text.replace(OLD, NEW)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    print("OK", path)

cfg_path = os.path.join(ROOT, "video", "config.json")
with open(cfg_path, encoding="utf-8") as f:
    cfg = json.load(f)
shutil.copy2(cfg_path, cfg_path + ".bak-before-qwen25vl-" + STAMP)
cfg["vision_model"] = NEW
cfg.setdefault("vision_fallback", "qwen3-vl:4b")
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
print("OK", cfg_path)

print("DONE")
