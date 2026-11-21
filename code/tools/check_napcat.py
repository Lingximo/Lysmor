"""NapCat 登录状态检查（只读，不自动弹二维码）。

用法:
  python D:\\你的数据目录\\tools\\check_napcat.py          # 只看状态
  python D:\\你的数据目录\\tools\\check_napcat.py --qr     # 未登录时生成并打开二维码
"""
import hashlib
import json
import sys

import requests

CONFIG = r"D:\Napcat\app\config\webui.json"
BASE = "http://127.0.0.1:8013"
QR_OUT = r"C:\你的用户\CompanionStartup\napcat-qr.png"


def client():
    token = json.load(open(CONFIG, encoding="utf-8-sig"))["token"]
    digest = hashlib.sha256((token + ".napcat").encode()).hexdigest()
    r = requests.post(f"{BASE}/api/auth/login", json={"hash": digest}, timeout=10).json()
    cred = r["data"]["Credential"]
    return {"Authorization": "Bearer " + cred}


def main():
    want_qr = "--qr" in sys.argv
    headers = client()
    st = requests.post(f"{BASE}/api/QQLogin/CheckLoginStatus", headers=headers, timeout=15).json()
    data = st.get("data") or {}
    print("isLogin:", data.get("isLogin"))
    qr = data.get("qrcodeurl") or ""
    print("qrcodeurl:", (qr[:60] + "...") if qr else "(empty)")
    for k in ("uin", "nick", "avatarUrl", "online", "status", "msg"):
        if k in data:
            print(f"{k}:", data[k])
    if data.get("isLogin"):
        print("QQ 已登录")
        return 0
    print("QQ 未登录")
    if want_qr:
        if not qr:
            requests.post(f"{BASE}/api/QQLogin/RefreshQRcode", headers=headers, timeout=20)
            st = requests.post(f"{BASE}/api/QQLogin/CheckLoginStatus", headers=headers, timeout=15).json()
            qr = (st.get("data") or {}).get("qrcodeurl") or ""
        if qr:
            import os
            import qrcode
            img = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                                box_size=12, border=4)
            img.add_data(qr)
            img.make(fit=True)
            img.make_image(fill_color="black", back_color="white").save(QR_OUT)
            print("已生成二维码:", QR_OUT)
            os.startfile(QR_OUT)
        else:
            print("拿不到二维码 URL")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
