"""TA各个页面共用的访问口令。

规则很简单：
  - 本机（127.0.0.1 / ::1）随便看，不用口令
  - 局域网里必须带口令：`?t=口令`，或者之前种下的 cookie
  - 口令只存在本机文件里，扫到的链接不带口令就是 403

所有页面共用同一个口令，文件在 D:\\你的数据目录\\gate_token.txt
"""
import os
import secrets
from urllib.parse import parse_qs, urlparse

TOKEN_PATH = r"D:\你的数据目录\gate_token.txt"
COOKIE_NAME = "companion_gate"
LOCAL_ADDRS = ("127.0.0.1", "::1")

DENY_HTML = (
    "<!doctype html><meta charset='utf-8'>"
    "<body style='font-family:sans-serif;background:#0f1720;color:#e8f1f8;"
    "padding:60px;text-align:center'>"
    "<h2>需要访问口令</h2>"
    "<p style='color:#8fa6b8'>这些页面只给你的电脑和手机看。<br>"
    "口令在电脑的 <code>D:\\你的数据目录\\gate_token.txt</code>，"
    "地址后面加 <code>?t=口令</code> 就行。</p>"
)


def get_token():
    try:
        with open(TOKEN_PATH, encoding="utf-8-sig") as f:
            token = f.read().strip().lstrip("\ufeff")
        if token:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(16)
    try:
        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(token + "\n")
    except OSError:
        pass
    return token


TOKEN = get_token()


def check(handler):
    """返回 (是否放行, 是否需要先种 cookie)。"""
    if handler.client_address[0] in LOCAL_ADDRS:
        return True, False
    given = (parse_qs(urlparse(handler.path).query).get("t") or [""])[0]
    if given and secrets.compare_digest(given, TOKEN):
        return True, True
    cookie = handler.headers.get("Cookie") or ""
    for part in cookie.split(";"):
        key, _, value = part.strip().partition("=")
        if key == COOKIE_NAME and value and secrets.compare_digest(value, TOKEN):
            return True, False
    return False, False


def deny(handler):
    body = DENY_HTML.encode("utf-8")
    handler.send_response(403)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def redirect_with_cookie(handler):
    """口令对上了：种一年期 cookie，然后跳到不带参数的地址。"""
    clean = urlparse(handler.path).path or "/"
    handler.send_response(302)
    handler.send_header(
        "Set-Cookie",
        "%s=%s; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax"
        % (COOKIE_NAME, TOKEN),
    )
    handler.send_header("Location", clean)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def guard(handler):
    """在 do_GET 开头调用：返回 True 表示已经处理完（拒绝或跳转），直接 return。"""
    allowed, need_cookie = check(handler)
    if not allowed:
        deny(handler)
        return True
    # 接口调用带 ?t= 时不要跳转，否则前端拿不到 JSON
    if need_cookie and not urlparse(handler.path).path.startswith("/api/"):
        redirect_with_cookie(handler)
        return True
    return False
