"""生成"TA页面 · 手机访问"二维码卡片，方便你直接扫。"""
import os

import qrcode
from PIL import Image, ImageDraw, ImageFont

TOKEN = open(r"D:\你的数据目录\gate_token.txt", encoding="utf-8-sig").read().strip()
IP = "192.168.1.5"
OUT = r"C:\你的用户\Desktop\TA手机访问.png"

ITEMS = [
    ("装证书（先做这个）", f"http://{IP}:8003/static/cert-help.html"),
    ("视频通话 HTTPS", f"https://{IP}:8004/"),
    ("记忆大脑", f"http://{IP}:8006/?t={TOKEN}"),
    ("TA生命状态", f"http://{IP}:8005/?t={TOKEN}"),
    ("和TA视频（电脑/安卓）", f"http://{IP}:8003/"),
    ("QQ 掉线扫码", f"http://{IP}:8008/?t={TOKEN}"),
]

FONT = r"C:\Windows\Fonts\msyh.ttc"


def main():
    qr_size, label_h, cell_w, margin, title_h = 200, 34, 300, 20, 62
    cols, rows = 2, 3
    w = margin * 2 + cell_w * cols
    h = title_h + margin + (qr_size + label_h) * rows + margin + 26
    canvas = Image.new("RGB", (w, h), "#0f1720")
    draw = ImageDraw.Draw(canvas)

    title_font = ImageFont.truetype(FONT, 24)
    label_font = ImageFont.truetype(FONT, 16)
    hint_font = ImageFont.truetype(FONT, 13)

    title = "TA · 手机访问（只给你）"
    tw = draw.textlength(title, font=title_font)
    draw.text(((w - tw) / 2, 16), title, fill="#e8f1f8", font=title_font)

    for i, (label, url) in enumerate(ITEMS):
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                           box_size=10, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        img = img.resize((qr_size, qr_size))
        col, row = i % cols, i // cols
        x = margin + col * cell_w + (cell_w - qr_size) / 2
        y = title_h + margin + row * (qr_size + label_h)
        canvas.paste(img, (int(x), int(y)))
        lw = draw.textlength(label, font=label_font)
        color = "#fdba74" if "证书" in label else "#9fd3ff"
        draw.text((margin + col * cell_w + (cell_w - lw) / 2, y + qr_size + 7),
                  label, fill=color, font=label_font)

    hint = "iPhone 先扫第一个装证书，再扫第二个；安卓电脑可直接用 HTTP"
    hw = draw.textlength(hint, font=hint_font)
    draw.text(((w - hw) / 2, h - margin - 2), hint, fill="#77909f", font=hint_font)

    canvas.save(OUT)
    print("已生成:", OUT, canvas.size)
    os.startfile(OUT)


if __name__ == "__main__":
    main()
