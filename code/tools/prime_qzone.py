# -*- coding: utf-8 -*-
"""把 qzone 插件的 cfg.client 缓存填上（AstrBot 重启后跑一次）。

为什么要这个：
  astrbot_plugin_qzone 只在两种时机懒加载 CQHttp 客户端——
    1) 有人打开它的网页（_build_page_status -> _capture_page_client）
    2) 收到一条 QQ 消息（prob_read_feed）
  AstrBot 重启后如果这两件事都没发生，cfg.client 一直是 None，
  astrbot_plugin_companion_qzone_reply 每 10 分钟就会按这个错：
      [空间回评] 轮询失败：CQHttp 实例不存在
  表现就是「你在空间评论了，她没回」——而且不会有任何显眼报错。

怎么用：
  cd D:\\你的数据目录\\tools
  .\\py.cmd prime_qzone.py

它只调一次 GET /api/plug/astrbot_plugin_qzone/page/status（只读状态接口，
用 dashboard JWT 授权），副作用只有把客户端缓存填上，不改任何状态。
12:17 实测：跑完下一轮轮询就正常了（读到 7 条说说）。
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
URL = "http://127.0.0.1:8012/api/plug/astrbot_plugin_qzone/page/status"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    import jwt  # AstrBot venv 自带

    with open(CFG, encoding="utf-8-sig") as f:
        cfg = json.load(f)

    secret = cfg["dashboard"]["jwt_secret"]
    token = jwt.encode(
        {
            "username": "astrbot",
            "exp": datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(minutes=10),
        },
        secret,
        algorithm="HS256",
    )
    if isinstance(token, bytes):
        token = token.decode("utf-8")

    req = urllib.request.Request(URL, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", "replace")
            print("HTTP", resp.status)
            print(body[:1200])
            if '"bound":true' in body.replace(" ", ""):
                print("\nOK：客户端缓存已填上，空间回评下一轮就能正常读说说")
            return 0
    except urllib.error.HTTPError as exc:
        print("HTTP", exc.code)
        print(exc.read().decode("utf-8", "replace")[:1200])
        return 1
    except Exception as exc:
        print("FAILED:", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
