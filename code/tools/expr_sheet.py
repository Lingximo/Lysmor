import os
import subprocess
import time

from PIL import Image, ImageDraw, ImageFont

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
OUT = r"D:\你的数据目录\logs\expr"
os.makedirs(OUT, exist_ok=True)

ITEMS = [
    ("", "平静（无表情）"),
    ("exp02_three_mouth", "三瓣嘴 / 吐舌头"),
    ("exp02_grit", "咬牙 / 龇牙"),
    ("exp03_dark", "黑化 / 坏笑"),
    ("exp04_blush", "脸红 / 害羞"),
    ("exp05_oo", "O 形嘴 / 困"),
    ("exp05_brackets", "弯眼笑"),
    ("exp06_xx", "XX 眼 / 哭"),
    ("exp07_drool", "流口水"),
    ("exp08_omouth", "惊讶张嘴"),
    ("exp08_worry", "委屈 / 皱眉"),
    ("exp08_chestnut", "嘟嘴 / 包子脸"),
    ("exp11_tail_hide", "尾巴隐藏"),
    ("exp12_ear_hide", "耳朵隐藏"),
    ("exp13_watermark_hide", "水印隐藏"),
]

shots = []
for name, label in ITEMS:
    path = os.path.join(OUT, (name or "neutral") + ".png")
    if not os.path.exists(path):
        url = "http://127.0.0.1:8003/static/live2d/preview.html?expr=" + name
        subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--window-size=620,760", "--virtual-time-budget=9000",
                        "--screenshot=" + path, url],
                       capture_output=True, timeout=60)
        time.sleep(0.3)
    shots.append((path, label, name))

font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 22)
small = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 16)

cell_w, cell_h = 300, 420
cols, rows = 4, 4
pad = 14
sheet = Image.new("RGB", (cols * cell_w + pad * (cols + 1),
                          rows * (cell_h + 54) + pad * (rows + 1)), (10, 16, 28))
draw = ImageDraw.Draw(sheet)

for i, (path, label, name) in enumerate(shots):
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        continue
    # 裁脸：模型在 620x760 居中的上半部分
    face = im.crop((120, 90, 500, 470)).resize((cell_w, cell_h), Image.LANCZOS)
    r, c = divmod(i, cols)
    x = pad + c * (cell_w + pad)
    y = pad + r * (cell_h + 54 + pad)
    sheet.paste(face, (x, y))
    draw.text((x + 6, y + cell_h + 6), label, fill=(225, 235, 250), font=font)
    if name:
        draw.text((x + 6, y + cell_h + 32), name, fill=(120, 140, 165), font=small)

out = r"D:\你的数据目录\logs\expressions_sheet.jpg"
sheet.save(out, "JPEG", quality=90)
print("saved", out, sheet.size)
