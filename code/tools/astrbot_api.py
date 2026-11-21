# -*- coding: utf-8 -*-
"""调 AstrBot dashboard API（自动签 JWT）。只做转发，不带业务逻辑。

用法：
  .\\py.cmd astrbot_api.py GET  /api/plugin/get
  .\\py.cmd astrbot_api.py POST /api/plugin/off {"name":"astrbot_plugin_bilibili_daily"}
  .\\py.cmd astrbot_api.py POST /api/plugin/off @C:\\path\\body.json

  实在引号不好转义时，就用 @文件 传 JSON body（cmd 里带 {} 很容易被吃掉）。

注意：
  - 只有 /api/* 这些 dashboard 路由需要 JWT；插件自己的 /api/plug/<route> 也走这套。
  - 本机回环调用，不经过防火墙，也不用口令。
  - 停/启用插件用 /api/plugin/off、/api/plugin/on（会调 terminate() 并写进
    data/shared_preferences.json 的 inactivated_plugins，重启也保持停用）。
"""
import datetime
import json
import sys
import urllib.error
import urllib.request

CFG = (
    r"C:\你的用户\.astrbot_launcher\instances"
    r"\<BOT_INSTANCE>\core\data\cmd_config.json"
)
BASE = "http://127.0.0.1:8012"


def make_token() -> str:
    import jwt

    with open(CFG, encoding="utf-8-sig") as f:
        cfg = json.load(f)
    tok = jwt.encode(
        {
            "username": "astrbot",
            "exp": datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(minutes=10),
        },
        cfg["dashboard"]["jwt_secret"],
        algorithm="HS256",
    )
    return tok.decode("utf-8") if isinstance(tok, bytes) else tok


def main(argv: list) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) < 2:
        print(__doc__)
        return 2

    method = argv[0].upper()
    path = argv[1]
    body = None
    if len(argv) >= 3:
        raw = argv[2]
        if raw.startswith("@"):
            with open(raw[1:], encoding="utf-8-sig") as f:
                raw = f.read()
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            print("JSON 解析失败:", exc)
            print("原始参数:", raw[:300])
            return 2

    data = None
    headers = {"Authorization": f"Bearer {make_token()}"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        BASE + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", "replace")
            print("HTTP", resp.status)
            try:
                print(json.dumps(json.loads(text), ensure_ascii=False, indent=2))
            except json.JSONDecodeError:
                print(text[:3000])
            return 0
    except urllib.error.HTTPError as exc:
        print("HTTP", exc.code)
        print(exc.read().decode("utf-8", "replace")[:3000])
        return 1
    except Exception as exc:
        print("FAILED:", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
