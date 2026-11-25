"""TA QQ 掉线守护 (qqwatch)

每 60 秒看一次 NapCat 的登录状态，分三种情况处理：

1. 一切正常         -> 什么都不做，只更新状态
2. NapCat 进程挂了  -> 自动拉起（start-napcat.ps1）
3. QQ 掉登录        -> 先试快速登录（有保存账号时）；不行就把二维码烧成图片，
                      持续自动刷新，并开一个手机能打开的网页
                      http://<局域网IP>:8008/ 让你扫码

设计原则：
- 只对 NapCat 的 WebUI 接口做“读 + 刷新二维码 / 快速登录 / 拉起进程”，
  绝不碰记忆库，绝不删任何东西。
- 单实例：8008 端口被占用就直接退出，交给已在跑的那个。
- 所有动作写日志，出问题能看到当时发生了什么。

用法:
  python watch.py              常驻
  python watch.py --once       只跑一轮（调试用）
  python watch.py --simulate   用假的“掉线”状态起一个页面（不调用刷新接口）
"""
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import qrcode
import requests
from PIL import Image, ImageDraw

ROOT = r"D:\你的数据目录\qqwatch"
NAP_APP = os.environ.get("NAPCAT_APP") or r"C:\NapCat\app"
NAP_WEBUI = os.environ.get("NAPCAT_WEBUI") or os.path.join(NAP_APP, "config", "webui.json")
STARTUP = r"C:\你的用户\CompanionStartup"
START_NAPCAT = os.path.join(STARTUP, "start-napcat.ps1")
QR_PATHS = [os.path.join(ROOT, "qr.png"), os.path.join(STARTUP, "napcat-qr.png")]
STATUS_FILE = os.path.join(ROOT, "status.json")
LOG_FILE = os.path.join(ROOT, "watch.log")
TOKEN_FILE = os.path.join(ROOT, "access_token.txt")
COOKIE_NAME = "companion_qr"

BASE = "http://127.0.0.1:8013"
PORT = 8008
POLL = 60              # 状态轮询间隔（秒）
QR_TTL = 100           # 二维码刷新间隔（QQ 的码两分钟左右过期）
QUICK_LOGIN_GAP = 600  # 两次快速登录尝试的最小间隔
AUTO_RELOGIN_MIN = 30      # 掉线满多少分钟就自动重启 QQ 重登
# 2026-11-06：腾讯把本机标成"风险设备（外挂）"，部署者决定**保号**。
# 关掉一切自动重登：掉线只记录，等人手动处理（/relogin 按钮仍然可用）。
# 想恢复自动重登：改成 True。
AUTO_RELOGIN_ENABLED = False
AUTO_RELOGIN_COOLDOWN = 2700  # 两次自动重登之间至少隔 45 分钟

_state = {
    "state": "init",        # ok / offline / napcat_down / starting
    "isLogin": None,
    "loginPhase": "",
    "qr_updated_at": 0,
    "lastCheck": 0,
    "note": "",
    "offlineSince": 0,
    "napcat_down_since": 0,
    "last_quick_try": 0,
    "quickLoginTries": 0,
    "last_auto_relogin": 0,
}
_lock = threading.Lock()


# ---------------------------------------------------------------- 日志 / 状态
def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1_000_000:
            os.replace(LOG_FILE, LOG_FILE + ".1")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def set_state(**kw):
    with _lock:
        _state.update(kw)
        _state["lastCheck"] = time.time()
        snapshot = dict(_state)
    try:
        tmp = STATUS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATUS_FILE)
    except OSError:
        pass
    return snapshot


def get_state():
    with _lock:
        return dict(_state)


# ---------------------------------------------------------------- 发送失败探测
# 2026-10-30 加：QQ 有时"还登录着"，但发消息被内核拒绝
#   （result -10003 / 身份验证失败 / retcode 1200）
# 这时 check_status 依然返回 isLogin=True，守护看不出来，
# 人只会觉得"她突然不理我了"。
ASTRBOT_LOG = r"C:\你的用户\CompanionStartup\logs\astrbot.out.log"
SEND_FAIL_MARKS = ("身份验证失败", "-10003", "retcode=1200")
SEND_FAIL_COOLDOWN = 1800          # 两次"发送失败重登"至少隔 30 分钟


def recent_send_failures():
    """读 AstrBot 日志「上次之后新增」的部分，返回 (次数, 最新时间戳)。

    2026-10-31 修三处（改之前这条探测一次都没生效过）：
      1) 日志行前面带 ANSI 颜色码（\\x1b[32m），从行首 re.match 找 [HH:MM:SS]
         永远匹配不上 → 改成按新增字节扫描，不做行首匹配。
      2) 日志里没有日期，昨天 20:07 会被算成今天 20:07（未来时间），
         旧失败会被反复当成新失败 → 只读 offset 之后的新增字节。
      3) 第一次运行 / 日志被轮转时从当前末尾开始，不追溯历史，
         避免守护一启动就误判成"发送失败"去重登。
    """
    try:
        size = os.path.getsize(ASTRBOT_LOG)
        offset = int(float(get_state().get("sendfail_offset") or 0))
        if offset <= 0 or offset > size:
            set_state(sendfail_offset=size)
            return 0, 0.0
        with open(ASTRBOT_LOG, "rb") as f:
            f.seek(offset)
            chunk = f.read()
    except (OSError, ValueError):
        return 0, 0.0

    if not chunk:
        return 0, 0.0
    end = chunk.rfind(b"\n")
    if end < 0:                      # 只写了半行，下轮再看
        return 0, 0.0
    set_state(sendfail_offset=offset + end + 1)

    hits = 0
    for line in chunk[: end + 1].decode("utf-8", "ignore").splitlines():
        if any(mark in line for mark in SEND_FAIL_MARKS):
            hits += 1
    return (hits, time.time()) if hits else (0, 0.0)


def handle_send_failures():
    """登录态还写着 True、但消息被内核拒（-10003 身份验证失败）时重登。

    必须放在「isLogin 为真」的分支里：出问题的时候 CheckLoginStatus
    恰好一直返回 True，掉线分支根本走不到（2026-10-31 实测）。
    """
    fails, latest = recent_send_failures()
    if not fails:
        return
    cooled = time.time() - float(get_state().get("last_sendfail_relogin") or 0) > SEND_FAIL_COOLDOWN
    if not cooled:
        log("检测到 %d 次发送被拒（冷却中，暂不重登）" % fails)
        return
    log("检测到 %d 次发送被拒（登录态还在但内核不认），主动重启重登" % fails)
    set_state(last_sendfail_ts=latest, last_sendfail_relogin=time.time())
    if restart_napcat():
        log("因发送失败触发的重登完成")


# ---------------------------------------------------------------- 访问口令
# 和其他页面共用同一个口令（D:\你的数据目录\gate_token.txt）
# 优先从仓库自带的 code/tools 找模块，再回退到配置时替换出来的数据目录
sys.path.insert(0, r"D:\你的数据目录\tools")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
try:
    import gate
except Exception:  # noqa: BLE001
    gate = None


# ---------------------------------------------------------------- NapCat 接口
# NapCat 的登录凭证缓存（2026-11-06：防 loginRate 撞满）
_HEADERS_CACHE = {"h": None, "at": 0.0}
# 上次"尝试换码"的时间（失败也要记，否则页面会每 3 秒重试一次，把 NapCat 打懵）
_LAST_QR_TRY = {"t": 0.0}


def webui_headers(timeout=10):
    """用 webui.json 里的 token 换一个临时 Bearer。拿不到返回 None。

    2026-11-06：加 5 分钟缓存。
    扫码页每 3 秒刷一次码，原来每次都重新登录，一分钟二十次，
    直接把 NapCat 的 loginRate 撞满（返回 "login rate limit"），
    之后换码全部失败——部署者看到的就是"刷不出二维码"。
    凭证本身是长期的，缓存 5 分钟不影响正确性。
    """
    now = time.time()
    if _HEADERS_CACHE["h"] and now - _HEADERS_CACHE["at"] < 300:
        return _HEADERS_CACHE["h"]
    try:
        with open(NAP_WEBUI, encoding="utf-8-sig") as f:
            token = json.load(f)["token"]
        digest = hashlib.sha256((token + ".napcat").encode()).hexdigest()
        r = requests.post(BASE + "/api/auth/login", json={"hash": digest}, timeout=timeout)
        cred = (r.json().get("data") or {}).get("Credential")
        if not cred:
            return None
        h = {"Authorization": "Bearer " + cred}
        _HEADERS_CACHE["h"] = h
        _HEADERS_CACHE["at"] = now
        return h
    except (requests.RequestException, OSError, ValueError, KeyError):
        return None


def invalidate_headers():
    """丢掉缓存的 Bearer。NapCat 重启/重登后旧凭证会失效，必须重新换一次。"""
    _HEADERS_CACHE["h"] = None
    _HEADERS_CACHE["at"] = 0.0


def call(headers, path, payload=None, timeout=20):
    r = requests.post(BASE + "/api/QQLogin/" + path, headers=headers,
                      json=payload or {}, timeout=timeout)
    return r.json()


def check_status(headers):
    try:
        body = call(headers, "CheckLoginStatus", timeout=15)
        return body.get("data") or {}
    except (requests.RequestException, ValueError):
        return None


def saved_uin(headers):
    """返回可快速登录的 QQ 号；没有保存账号就返回空串。"""
    for path in ("GetQuickLoginListNew", "GetQuickLoginList"):
        try:
            data = call(headers, path, timeout=15).get("data")
        except (requests.RequestException, ValueError):
            continue
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                uin = first.get("uin") or first.get("uinStr") or ""
                if uin:
                    return str(uin)
            elif first:
                return str(first)
    try:
        data = call(headers, "GetQuickLoginQQ", timeout=15).get("data")
        if isinstance(data, str) and data.strip():
            return data.strip()
    except (requests.RequestException, ValueError):
        pass
    return ""


def try_quick_login(headers, uin):
    try:
        result = call(headers, "SetQuickLogin", {"uin": uin}, timeout=30)
        return result.get("code") == 0
    except (requests.RequestException, ValueError):
        return False


def refresh_qr(headers):
    """换一张新码。

    2026-11-06：原来只读 CheckLoginStatus 里的 qrcodeurl，但 NapCat 刷新后
    状态接口有时还没跟上，就返回空 → 页面报"接口没返回链接"、码一直是旧的。
    现在优先用 RefreshQRcode 自己的返回值，再退回状态接口。
    """
    try:
        body = call(headers, "RefreshQRcode", timeout=25) or {}
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, dict):
            url = data.get("qrcodeurl") or ""
            if url:
                return url
        st = check_status(headers) or {}
        return st.get("qrcodeurl") or ""
    except (requests.RequestException, ValueError):
        return ""


# ---------------------------------------------------------------- 二维码
def render_qr(url):
    """把登录链接画成二维码，同时写到守护目录和老脚本的路径。"""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=12, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    label_h = 46
    canvas = Image.new("RGB", (img.width, img.height + label_h), "white")
    canvas.paste(img, (0, 0))
    draw = ImageDraw.Draw(canvas)
    text = "Companion QQ login  %s" % time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        tw = draw.textlength(text)
    except AttributeError:
        tw = len(text) * 6
    draw.text(((canvas.width - tw) / 2, img.height + 12), text, fill="black")

    for path in QR_PATHS:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            canvas.save(path)
        except OSError as exc:
            log("保存二维码失败 %s: %s" % (path, exc))
    return canvas


# ---------------------------------------------------------------- 拉起 NapCat
def napcat_alive():
    try:
        raw = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq NapCatWinBootMain.exe", "/NH"],
            capture_output=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout or b""
        return "NapCatWinBootMain" in raw.decode("gbk", "ignore")
    except (OSError, subprocess.SubprocessError):
        return False


def start_napcat():
    if not os.path.exists(START_NAPCAT):
        log("找不到启动脚本: %s" % START_NAPCAT)
        return False
    log("NapCat 不在运行，拉起 start-napcat.ps1")
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-WindowStyle", "Hidden", "-File", START_NAPCAT],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except OSError as exc:
        log("拉起失败: %s" % exc)
        return False


def _pids(imagename):
    try:
        raw = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq %s" % imagename, "/NH", "/FO", "CSV"],
            capture_output=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout or b""
        # 中文系统 tasklist 输出是 GBK，别按 UTF-8 解
        out = raw.decode("gbk", "ignore")
        pids = []
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[0].lower() == imagename.lower():
                pids.append(int(parts[1]))
        return pids
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def restart_napcat():
    """彻底重启 QQ/NapCat，并等它自动登录。

    关键经验（2026-10-29 实测）：只杀 NapCatWinBootMain 一棵树不够，
    残留的 QQ 子进程会让 QQ 登录服务卡死（二维码都刷不出来）。
    必须先 taskkill QQ.exe /T /F，确认清干净，再重新 launcher，
    这样 QQ 会用存下来的凭据自动登录，不需要扫码。
    """
    log("重启 QQ/NapCat（先彻底清干净）")
    for image in ("NapCatWinBootMain.exe", "QQ.exe"):
        subprocess.run(
            ["taskkill", "/IM", image, "/F", "/T"],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    time.sleep(4)

    left = _pids("QQ.exe")
    if left:
        log("仍有 QQ 残留进程: %s，再清一次" % left)
        for pid in left:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        time.sleep(3)

    bat = os.path.join(NAP_APP, "launcher.bat")
    if not os.path.exists(bat):
        log("找不到 launcher.bat")
        return False
    log("重新启动 launcher.bat")
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", bat],
            cwd=NAP_APP,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        log("重启失败: %s" % exc)
        return False

    # 等它用凭据自动登录（最多 60 秒）
    for i in range(12):
        time.sleep(5)
        headers = webui_headers(timeout=5)
        if not headers:
            continue
        st = check_status(headers)
        if st and st.get("isLogin"):
            log("自动登录成功（%d 秒），没有用扫码" % ((i + 1) * 5))
            set_state(state="ok", isLogin=True, loginPhase=st.get("loginPhase", ""),
                      note="自动登录成功", offlineSince=0, qr_updated_at=0)
            return True
    log("自动登录没完成，转二维码等你扫")
    return True


# ---------------------------------------------------------------- 一轮检查
def one_cycle():
    now = time.time()
    headers = webui_headers()
    if headers is None:
        if not get_state().get("napcat_down_since"):
            set_state(state="napcat_down", isLogin=None,
                      note="NapCat WebUI 不可达", napcat_down_since=now)
            log("NapCat WebUI 连不上（8013 可能没在听）")
        if not napcat_alive():
            set_state(state="starting", note="正在拉起 NapCat")
            start_napcat()
        return

    if get_state().get("napcat_down_since"):
        set_state(napcat_down_since=0)

    st = check_status(headers)
    if st is None:
        set_state(state="napcat_down", note="CheckLoginStatus 调用失败")
        return

    if st.get("isLogin"):
        prev = get_state().get("state")
        if prev != "ok":
            log("QQ 已登录（状态 %s -> ok）" % prev)
        set_state(state="ok", isLogin=True, loginPhase=st.get("loginPhase", ""),
                  note="TA在线", offlineSince=0, qr_updated_at=0)
        # 登录态还在，也可能发不出去（-10003）：每次确认在线时顺带看一眼
        handle_send_failures()
        return

    # ---------------- 掉线
    if not get_state().get("offlineSince"):
        log("检测到 QQ 掉登录: phase=%s offline=%s err=%s"
            % (st.get("loginPhase"), st.get("isOffline"), st.get("loginError")))
        set_state(offlineSince=now, qr_updated_at=0)

    # 先试快速登录（只有保存过账号才有效）
    # 2026-11-06 保号：AUTO_RELOGIN_ENABLED=False 时整段跳过，不再自动登录
    last_try = get_state().get("last_quick_try") or 0
    if AUTO_RELOGIN_ENABLED and now - last_try > QUICK_LOGIN_GAP:
        uin = saved_uin(headers)
        set_state(last_quick_try=now)
        if uin:
            log("尝试快速登录 %s" % uin)
            set_state(quickLoginTries=(get_state().get("quickLoginTries") or 0) + 1)
            if try_quick_login(headers, uin):
                for _ in range(20):
                    time.sleep(1.5)
                    if (check_status(headers) or {}).get("isLogin"):
                        log("快速登录成功，QQ 回来了")
                        set_state(state="ok", isLogin=True,
                                  note="快速登录成功", offlineSince=0)
                        return
                log("快速登录没成功，转二维码")
        else:
            log("没有保存的快速登录账号，只能用二维码")

    # 掉线满 30 分钟还没人扫码：自动重启 QQ + NapCat，试一次快速登录
    offline_min = (now - (get_state().get("offlineSince") or now)) / 60.0

    last_relogin = get_state().get("last_auto_relogin") or 0
    if (AUTO_RELOGIN_ENABLED and offline_min >= AUTO_RELOGIN_MIN
            and now - last_relogin >= AUTO_RELOGIN_COOLDOWN):
        set_state(last_auto_relogin=now)
        log("掉线已 %.0f 分钟，自动重启 QQ/NapCat 尝试重登" % offline_min)
        ok = restart_napcat()
        log("自动重登：%s" % ("已重启" if ok else "重启失败"))
        return

    # 二维码：过期了就换一张新的
    age = now - (get_state().get("qr_updated_at") or 0)
    if age > QR_TTL:
        url = refresh_qr(headers) or st.get("qrcodeurl") or ""
        if not url:
            # 同上：NapCat 重启后旧 Bearer 失效，重新认证再试一次
            invalidate_headers()
            headers = webui_headers()
            if headers is not None:
                st = check_status(headers) or st
                url = refresh_qr(headers) or st.get("qrcodeurl") or ""
        if url:
            first_time = not (get_state().get("qr_updated_at") or 0)
            render_qr(url)
            set_state(state="offline", isLogin=False,
                      loginPhase=st.get("loginPhase", ""),
                      qr_updated_at=time.time(), note="等待扫码")
            log("二维码已刷新（%s）" % time.strftime("%H:%M:%S"))
            if first_time:
                # 以前这里会把二维码弹到桌面（os.startfile），方便当场看到；
                # 现在不弹了：机器可能放在公共场合，弹图容易被人扫走账号。
                # 需要看码时手动打开 8008 页面，或者开环境变量 QQWATCH_OPEN_QR=1 恢复旧行为。
                if os.environ.get("QQWATCH_OPEN_QR", "0") == "1":
                    try:
                        os.startfile(QR_PATHS[1])
                    except OSError:
                        pass
                else:
                    log("二维码已就绪，未自动弹出（需要时开 8008 页面看）")
        else:
            set_state(state="offline", isLogin=False,
                      loginPhase=st.get("loginPhase", ""),
                      note="拿不到二维码，稍后重试")
    else:
        set_state(state="offline", isLogin=False,
                  loginPhase=st.get("loginPhase", ""),
                  note="等待扫码（二维码已就绪）")


# ---------------------------------------------------------------- 手机页面
def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TA QQ 登录</title>
<style>
  body {{ margin:0; font-family:-apple-system,"Microsoft YaHei",sans-serif;
         background:#0f1720; color:#e8f1f8; display:flex; align-items:center;
         justify-content:center; min-height:100vh; }}
  .card {{ background:#16222e; border-radius:20px; padding:26px 22px; width:min(92vw,420px);
           box-shadow:0 10px 40px rgba(0,0,0,.45); text-align:center; }}
  h1 {{ font-size:20px; margin:0 0 6px; }}
  .sub {{ color:#8fa6b8; font-size:13px; margin-bottom:18px; line-height:1.7; }}
  img {{ width:100%; max-width:320px; border-radius:14px; background:#fff; padding:8px; }}
  .ok {{ color:#5fe3a1; font-size:44px; margin:22px 0 8px; }}
  .bad {{ color:#ffb86b; font-size:12px; margin-top:14px; }}
  .meta {{ color:#77909f; font-size:12px; margin-top:16px; line-height:1.8; }}
  code {{ color:#9fd3ff; }}
  .btn {{ display:inline-block; margin-top:18px; padding:12px 22px; border-radius:999px;
          background:linear-gradient(135deg,#22d3ee,#38bdf8); color:#04131c;
          font-weight:600; text-decoration:none; font-size:15px; }}
  .btn:active {{ transform:scale(.97); }}
  .btn.ghost {{ background:transparent; color:#9fd3ff; border:1px solid #2b4a63; font-weight:500; }}
</style>
{refresh}
</head><body><div class="card">
{body}
<div class="meta">检查时间 {now} · 手机访问 <code>http://{ip}:{port}/</code></div>
</div>
<script>
(function(){{
  var img = document.getElementById('qr');
  var hint = document.getElementById('hint');
  var btn = document.getElementById('newqr');
  if(!img) return;
  var shown = img.getAttribute('data-ts') || '';
  function paint(ms){{
    if(!ms) return;
    if(String(ms) === shown && img.complete) return;
    shown = String(ms);
    img.src = '/qr.png?t=' + Math.round(ms/1000) + '&r=' + Date.now();
  }}
  function poll(){{
    fetch('/status.json', {{cache:'no-store'}}).then(function(r){{return r.json()}}).then(function(s){{
      if(s.isLogin){{ if(hint) hint.textContent = '已经登录了'; return; }}
      if(s.qr_updated_at) paint(Math.round(s.qr_updated_at*1000));
      if(hint && !hint.textContent) hint.textContent = s.note || '';
    }}).catch(function(){{}});
  }}
  if(btn) btn.addEventListener('click', function(ev){{
    ev.preventDefault();
    btn.style.opacity = '.6'; btn.textContent = '正在换码…';
    if(hint) hint.textContent = '正在向 NapCat 要一张新码…';
    fetch('/newqr.json', {{cache:'no-store'}}).then(function(r){{return r.json()}}).then(function(j){{
      if(j.ok){{
        if(j.already){{ if(hint) hint.textContent = '已经登录了，不用扫码'; return; }}
        paint(Math.round((j.qr_updated_at || Date.now()/1000)*1000));
        if(hint) hint.textContent = '新码已生成，扫这张就行';
      }} else {{
        if(hint) hint.textContent = j.error || '换码失败';
      }}
    }}).catch(function(){{ if(hint) hint.textContent = '换码请求失败（8008 没响应？）'; }})
      .then(function(){{ btn.style.opacity = '1'; btn.textContent = '这个码过期了，换一个'; }});
  }});
  setInterval(poll, 5000);
}})();
</script>
</body></html>
"""


def page_html():
    s = get_state()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    tok = gate.TOKEN if gate is not None else ""
    online = s.get("state") == "ok"
    if online:
        body = ("<h1>TA在线呀</h1>"
                "<div class='sub'>QQ 已登录，不用扫码。</div>"
                "<div class='ok'>♥</div>")
        refresh = '<meta http-equiv="refresh" content="15">'
        buttons = ("<a class='btn ghost' href='/relogin?t=%s'>重启并重登</a>" % tok)
    else:
        qr_at = s.get("qr_updated_at") or 0
        age = int(time.time() - qr_at) if qr_at else -1
        left = max(0, 120 - age) if age >= 0 else 0
        body = ("<h1>TA掉线了，帮帮我嘛</h1>"
                "<div class='sub'>用手机 QQ 扫下面的码，扫完我就回来了。<br>"
                "码约两分钟过期，过期就点下面那个按钮换一个。</div>"
                "<img id='qr' data-ts='%d' src='/qr.png?t=%d&r=%d' alt='QQ 登录二维码'>"
                "<div class='bad'>生成于 %s（%s 秒前，约剩 %s 秒）· 状态：%s</div>"
                "<div class='bad' id='hint'></div>"
                % (int(qr_at), int(qr_at), int(time.time()),
                   time.strftime("%H:%M:%S", time.localtime(qr_at)) if qr_at else "—",
                   age if age >= 0 else "—", left,
                   s.get("note") or s.get("state")))
        refresh = '<meta http-equiv="refresh" content="20">'
        buttons = ("<a class='btn' id='newqr' href='/newqr?t=%s'>这个码过期了，换一个</a>"
                   "<a class='btn ghost' href='/relogin?t=%s'>直接重启重登</a>"
                   % (tok, tok))
    return PAGE.format(refresh=refresh, body=body + buttons, now=now,
                       ip=lan_ip(), port=PORT)

class Handler(BaseHTTPRequestHandler):
    def _send(self, data, ctype, cache="no-store"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if gate is not None and gate.guard(self):
            return
        if self.path.startswith("/qr.png"):
            path = QR_PATHS[0]
            if not os.path.exists(path):
                self.send_error(404)
                return
            with open(path, "rb") as f:
                self._send(f.read(), "image/png")
            return
        if self.path.startswith("/newqr.json"):
            res = newqr_sync()
            self._send(json.dumps(res, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")
            return
        if self.path.startswith("/newqr"):
            # 2026-11-06：60 秒内的新码直接忽略换码请求。
            # 不然一次误触/旧标签页就能把刚生成的好码换掉，扫的人永远扫不到。
            # 另外失败也要退避 15 秒，否则页面会一直重试、把 NapCat 打成"没响应"。
            _st = get_state()
            _age = time.time() - (_st.get("qr_updated_at") or 0)
            _since_try = time.time() - _LAST_QR_TRY["t"]
            if _age < 60:
                log("换码请求忽略：当前码才 %.0f 秒，够扫" % _age)
            elif _since_try < 15:
                log("换码请求忽略：%.0f 秒前刚试过" % _since_try)
            else:
                log("收到换码请求")
                threading.Thread(target=force_newqr, daemon=True).start()
            tok = gate.TOKEN if gate is not None else ""
            # 2026-11-06：原来这里是 content='3' 自己重载自己，结果是
            # 每 3 秒换一次码（根本来不及扫）＋ 每 3 秒登录一次（撞满 loginRate）。
            # 改成 2 秒后回主页，主页只显示当前这张码，不再自动换。
            target = "/" + (("?t=" + tok) if tok else "")
            html = ("<!doctype html><meta charset='utf-8'>"
                    "<meta http-equiv='refresh' content='2;url=%s'>" % target +
                    "<body style='margin:0;background:#0f1720;color:#e8f1f8;"
                    "font-family:-apple-system,sans-serif;display:flex;align-items:center;"
                    "justify-content:center;min-height:100vh;text-align:center'>"
                    "<div><h2>正在换新码…</h2>"
                    "<p style='color:#8fa6b8'>两秒后回到二维码页，扫上面那张就行</p></div>")
            self._send(html.encode("utf-8"), "text/html; charset=utf-8")
            return
        if self.path.startswith("/relogin"):
            log("收到手动刷新二维码请求")
            threading.Thread(target=force_relogin, daemon=True).start()
            tok = gate.TOKEN if gate is not None else ""
            # 同上：不能自己重载自己，否则每 6 秒重启一次 QQ。
            target = "/" + (("?t=" + tok) if tok else "")
            html = ("<!doctype html><meta charset='utf-8'>"
                    "<meta http-equiv='refresh' content='10;url=%s'>" % target +
                    "<body style='margin:0;background:#0f1720;color:#e8f1f8;"
                    "font-family:-apple-system,sans-serif;display:flex;align-items:center;"
                    "justify-content:center;min-height:100vh;text-align:center'>"
                    "<div><h2>正在重启 QQ…</h2>"
                    "<p style='color:#8fa6b8'>大概 20~40 秒，10 秒后回二维码页看进度</p></div>")
            self._send(html.encode("utf-8"), "text/html; charset=utf-8")
            return
        if self.path.startswith("/status.json"):
            self._send(json.dumps(get_state(), ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")
            return
        self._send(page_html().encode("utf-8"), "text/html; charset=utf-8")

    def log_message(self, *args):
        pass


_QR_LOCK = threading.Lock()


def newqr_sync():
    """手动点「换一个」时同步换码，把结果直接返回给页面（HTTP 线程里跑，约 1~20 秒）。

    和后台线程 force_newqr 的区别：明确知道成功/失败，并把原因告诉页面；
    不加 60 秒"忽略"（那是防页面自动刷的），只保留 8 秒防连点。
    """
    now = time.time()
    with _QR_LOCK:
        gap = now - _LAST_QR_TRY["t"]
        if gap < 8:
            return {"ok": False, "error": "刚换过，等 %d 秒再换" % max(1, int(8 - gap))}
        _LAST_QR_TRY["t"] = now
        headers = None
        try:
            headers = webui_headers()
        except Exception:  # noqa: BLE001
            headers = None
        if headers is None:
            log("手动换码失败：NapCat WebUI 不可达")
            return {"ok": False, "error": "NapCat 没响应（8013 没在听或在启动），可以点「重启并重登」"}
        try:
            st = check_status(headers) or {}
            if st.get("isLogin"):
                set_state(state="ok", isLogin=True, note="已经在线了，不用扫码")
                return {"ok": True, "already": True, "qr_updated_at": 0}
            url = refresh_qr(headers)
            if not url:
                # NapCat 重启过的话旧 Bearer 会失效：清缓存重新认证再试一次
                invalidate_headers()
                headers = webui_headers()
                if headers is not None:
                    st_retry = check_status(headers) or {}
                    if st_retry.get("isLogin"):
                        set_state(state="ok", isLogin=True, note="已经在线了，不用扫码")
                        return {"ok": True, "already": True, "qr_updated_at": 0}
                    url = refresh_qr(headers) or st_retry.get("qrcodeurl") or ""
            if not url:
                log("手动换码失败：接口没返回链接")
                set_state(note="手动换码失败（NapCat 没给新码）")
                return {"ok": False, "error": "NapCat 没返回新码（QQ 可能卡住，点「重启并重登」）"}
            render_qr(url)
            ts = time.time()
            set_state(state="offline", isLogin=False, qr_updated_at=ts,
                      note="已换新码，等你扫")
            log("手动换码成功（%s）" % time.strftime("%H:%M:%S"))
            return {"ok": True, "qr_updated_at": ts}
        except Exception as exc:  # noqa: BLE001
            log("手动换码出错：%s" % exc)
            return {"ok": False, "error": "换码出错：%s" % exc}


def force_newqr():
    """离线时"换个新码"：只刷新登录二维码，不重启 QQ（比 /relogin 轻得多）。"""
    _LAST_QR_TRY["t"] = time.time()
    try:
        headers = webui_headers()
        if headers is None:
            log("换码失败：NapCat WebUI 不可达（可能正在启动）")
            set_state(note="QQ 正在启动，等它起来再换码")
            return
        st = check_status(headers) or {}
        if st.get("isLogin"):
            set_state(note="已经在线了，不用扫码")
            log("换码请求：已在线，跳过")
            return
        url = refresh_qr(headers)
        if url:
            render_qr(url)
            set_state(qr_updated_at=time.time(), note="已换新码，等你扫",
                      state="offline", isLogin=False)
            log("换码成功，新码已生成")
        else:
            # 可能刚好在重启中/已自动登录，再确认一次
            time.sleep(2)
            st2 = check_status(headers) or {}
            if st2.get("isLogin"):
                set_state(state="ok", isLogin=True, note="其实已经登录了")
                log("换码时发现已经登录，不用换")
            else:
                log("换码失败：接口没返回链接")
                set_state(note="换码失败，稍后再试")
    except Exception as exc:  # noqa: BLE001
        log("换码出错：%s" % exc)


def force_relogin():
    """手动刷新二维码：重启 QQ/NapCat，然后立刻查一次状态。"""
    try:
        set_state(state="offline", note="手动刷新中，正在重启 QQ…", qr_updated_at=time.time())
        ok = restart_napcat()
        log("手动刷新：重启 %s" % ("完成" if ok else "失败"))
        time.sleep(3)
        one_cycle()
    except Exception as exc:  # noqa: BLE001
        log("手动刷新出错：%s" % exc)


def serve():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ---------------------------------------------------------------- main
def port_free():
    s = socket.socket()
    try:
        s.bind(("0.0.0.0", PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def load_previous_state():
    """重启守护时把掉线起始时间接上，别让 30 分钟的计时从头开始。"""
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, ValueError):
        return
    keep = ("offlineSince", "last_auto_relogin", "qr_updated_at", "last_quick_try")
    with _lock:
        for key in keep:
            if key in snap:
                _state[key] = snap[key]


def main():
    if "--simulate" in sys.argv:
        set_state(state="offline", isLogin=False, note="模拟掉线",
                  qr_updated_at=time.time())
        render_qr("https://txz.qq.com/p?k=SIMULATEDONLY")
        serve()
        log("模拟页面: http://127.0.0.1:%d/" % PORT)
        try:
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            return 0

    if "--once" in sys.argv:
        one_cycle()
        print(json.dumps(get_state(), ensure_ascii=False, indent=2))
        return 0

    if not port_free():
        print("8008 已被占用，说明守护已经在跑，退出。")
        return 0

    load_previous_state()
    serve()
    log("qqwatch 启动，端口 %d，轮询 %d 秒" % (PORT, POLL))
    phone_url = "http://%s:%d/?t=%s" % (lan_ip(), PORT, gate.TOKEN if gate else "")
    log("手机扫码地址: %s" % phone_url)
    try:
        with open(os.path.join(ROOT, "手机扫码地址.txt"), "w", encoding="utf-8") as f:
            f.write(phone_url + "\n")
    except OSError:
        pass
    while True:
        try:
            one_cycle()
        except Exception as exc:  # noqa: BLE001 守护不能因为一次异常就死
            log("本轮异常: %s" % exc)
        time.sleep(POLL)


if __name__ == "__main__":
    if "--relogin" in sys.argv:
        log("手动触发：重启 QQ/NapCat 尝试重登")
        print("已重启" if restart_napcat() else "重启失败")
        sys.exit(0)
    sys.exit(main())

