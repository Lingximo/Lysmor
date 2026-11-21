# -*- coding: utf-8 -*-
"""TA的专属网页 · 端口 8001

它只做一件事：把网页上的一句话送进 AstrBot 的聊天接口，把她的话原样流回来。
- 走的是她**真正的大脑**（人设 / 记忆 / 模型都是原来那套）
- 不经过 QQ，所以不会碰账号
- 只在本机监听，带口令；不联网、不开公网

启动：
    python D:\\你的数据目录\\webchat\\server.py
打开：
    http://127.0.0.1:8001/?t=<gate_token.txt 里的口令>
"""
import base64
import io
import sys

sys.path.insert(0, r"D:\你的数据目录\lab\tts")
sys.path.insert(0, r"D:\你的数据目录\lab\hands")
try:
    import hands_client
except Exception:  # noqa: BLE001
    hands_client = None
try:
    import local_tts
except Exception:  # noqa: BLE001
    local_tts = None
sys.path.insert(0, r"D:\你的数据目录\lab\game")
try:
    import playbook
except Exception:  # noqa: BLE001
    playbook = None
import json
import os
import sys
import subprocess
import threading
import time

import mimetypes
import re
import uuid
import requests
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
MEM = r"D:\你的数据目录"
INST = (r"C:\你的用户\.astrbot_launcher\instances"
        r"\<BOT_INSTANCE>")
CFG = os.path.join(INST, "core", "data", "cmd_config.json")
GATE = os.path.join(MEM, "gate_token.txt")
AVATAR = os.path.join(MEM, "brainviz", "static", "avatar.png")
ATTACH = os.path.join(INST, "core", "data", "attachments")   # 她的表情包就存在这
UPLOADS = os.path.join(HERE, "uploads")                     # 你发来的图，落在这里

AST = "http://127.0.0.1:8012"
PORT = int(os.environ.get("WEBCHAT_PORT", "8001"))
HOST = os.environ.get("WEBCHAT_HOST", "0.0.0.0")   # 手机要能连，所以绑所有网卡（有口令）
KEY_FILE = os.path.join(HERE, "key.txt")
SESSION_ID = "user"
PUSH_FILE = os.path.join(HERE, "push_queue.jsonl")   # 她的主动消息队列
PUSH_LOCK = threading.Lock()
USERNAME = "<你的QQ号>"      # 你的 QQ 号：她靠这个认出"是你"

_token_cache = {"tok": "", "at": 0.0}


REQUIRE_TOKEN = False   # 2026-11-06 部署者要求：不要口令了（只在本机/局域网/蒲公英内可达）


def gate_token():
    if not REQUIRE_TOKEN:
        return ""
    try:
        with io.open(GATE, encoding="utf-8-sig") as f:
            return f.read().strip()
    except OSError:
        return ""


def jwt_token():
    """每 5 分钟换一次 AstrBot 的面板令牌。"""
    if _token_cache["tok"] and time.time() - _token_cache["at"] < 300:
        return _token_cache["tok"]
    import datetime
    import jwt
    with io.open(CFG, encoding="utf-8-sig") as f:
        secret = json.load(f)["dashboard"]["jwt_secret"]
    tok = jwt.encode(
        {"username": "astrbot",
         "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)},
        secret, algorithm="HS256")
    tok = tok.decode() if isinstance(tok, bytes) else tok
    _token_cache["tok"] = tok
    _token_cache["at"] = time.time()
    return tok


def describe_image(raw):
    """让本机 qwen3-vl:4b 看一眼图，给一句话描述。

    qwen3 是"思考型"模型：token 预算不够时全花在思考上，response 会是空的。
    所以按 500 / 900 / 1400 递增重试，拿到第一段非空回答就用。
    """
    payload = {
        "model": "qwen3-vl:4b",
        "prompt": "这张图里有什么？用一句中文说。",
        "images": [base64.b64encode(raw).decode()],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2, "num_predict": 500},
    }
    for budget in (500, 900, 1400):
        payload["options"]["num_predict"] = budget
        try:
            r = requests.post("http://127.0.0.1:11434/api/generate", json=payload, timeout=120)
            if r.status_code != 200:
                continue
            out = str((r.json() or {}).get("response") or "")
            out = re.sub(r"(?is)<think>.*?</think>", "", out)
            out = re.sub(r"(?is)<think>.*$", "", out).replace("</think>", "")
            out = " ".join(out.split())
            if out:
                return out[:120]
        except Exception:  # noqa: BLE001
            continue
    return ""

def auth_header():
    """优先用 API Key（这样才能以你的 QQ 号身份说话），没有才退回面板令牌。"""
    try:
        with io.open(KEY_FILE, encoding="utf-8-sig") as f:
            key = f.read().strip()
        if key:
            return "Bearer " + key
    except OSError:
        pass
    return "Bearer " + jwt_token()





class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a):
        pass

    def _access(self):
        """记一行访问日志（只记路径，不记口令），用来判断手机到底有没有连上。"""
        try:
            path = (urlparse(self.path).path or "/")[:40]
            ip = self.client_address[0]
            line = "%s %-15s %s\n" % (time.strftime("%H:%M:%S"), ip, path)
            with io.open(os.path.join(MEM, "logs", "8001.access.log"), "a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:  # noqa: BLE001
            pass

    def handle_error(self, request, client_address):
        """浏览器关页面时的 ConnectionReset 不写进日志（只是噪声）。"""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)

    # ---------------------------------------------------------------- helpers
    def _raw(self, data, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:  # noqa: BLE001
            pass

    def _static(self, name):
        # 2026-11-06：先把开头的 / 去掉，否则 join 会把它当成绝对路径（manifest/icon 404 就是这来的）
        name = str(name or "").lstrip("\\/")
        path = os.path.normpath(name)
        full = os.path.join(STATIC, path)
        if not os.path.abspath(full).startswith(os.path.abspath(STATIC)) or not os.path.isfile(full):
            return self._raw(b"not found", "text/plain; charset=utf-8", 404)
        ext = os.path.splitext(full)[1].lower()
        ctype = {".html": "text/html; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8",
                 ".png": "image/png", ".jpg": "image/jpeg",
                 ".svg": "image/svg+xml"}.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            self._raw(f.read(), ctype)

    # ---------------------------------------------------------------- routes
    def do_GET(self):  # noqa: N802
        self._access()
        u = urlparse(self.path)
        if u.path == "/avatar.png":
            if os.path.isfile(AVATAR):
                with open(AVATAR, "rb") as f:
                    return self._raw(f.read(), "image/png")
            return self._raw(b"", "image/png", 404)
        if u.path.startswith("/p/"):
            return self._proxy_site(u.path)
        if u.path.startswith("/img/"):
            return self._img(u.path[len("/img/"):])
        if u.path == "/doodle":
            with open(os.path.join(STATIC, "doodle.html"), "rb") as fh:
                return self._raw(fh.read(), "text/html; charset=utf-8")
        if u.path == "/api/doodles":
            return self._raw(json.dumps(_doodle_list(), ensure_ascii=False).encode("utf-8"),
                             "application/json; charset=utf-8")
        if u.path.startswith("/art/"):
            return self._art(u.path[len("/art/"):])
        if u.path == "/api/health":
            return self._raw(json.dumps({"ok": True, "session": SESSION_ID,
                                         "ts": int(time.time())}).encode(),
                             "application/json; charset=utf-8")
        if u.path == "/api/push":
            q = parse_qs(u.query)
            since = int((q.get("since") or ["0"])[0] or 0)
            items = self._push_read(since)
            last = items[-1]["seq"] if items else since
            return self._raw(json.dumps({"items": items, "last": last}, ensure_ascii=False).encode("utf-8"),
                             "application/json; charset=utf-8")
        if u.path == "/api/qq":
            # 2026-11-07：断电重启后 QQ 掉线、她的主动消息静默失败，页面上要看得到。
            # 判断方式：OneBot 端口上有没有已建立的连接（够用，不依赖 NapCat 的 token）
            online = False
            try:
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-NetTCPConnection -LocalPort 8011 -State Established "
                     "-ErrorAction SilentlyContinue | Measure-Object).Count"],
                    capture_output=True, text=True, timeout=8)
                online = int((out.stdout or "0").strip() or 0) > 0
            except Exception:  # noqa: BLE001
                online = False
            return self._raw(json.dumps({"online": online, "ts": int(time.time())}).encode(),
                             "application/json; charset=utf-8")
        if u.path in ("", "/"):
            return self._static("index.html")
        return self._static(u.path)


    # ---------------------------------------------------------------- 主动消息队列
    def _push_read(self, since):
        items = []
        try:
            with open(PUSH_FILE, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if int(rec.get("seq") or 0) > since:
                        items.append(rec)
        except FileNotFoundError:
            pass
        return items[-50:]

    def _push_append(self, text):
        text = (text or "").strip()
        if not text:
            return 0
        with PUSH_LOCK:
            seq = 0
            try:
                with open(PUSH_FILE, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            seq = max(seq, int(json.loads(line).get("seq") or 0))
                        except Exception:
                            continue
            except FileNotFoundError:
                pass
            seq += 1
            rec = {"seq": seq, "ts": int(time.time()), "text": text}
            with open(PUSH_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            return seq

    def _proxy_site(self, path):
        """把 8005 / 8006 挂到 8001 下面（蒲公英只放行了少数端口）。"""
        parts = path.split("/")
        port = parts[2] if len(parts) > 2 else ""
        if port not in ("8005", "8006"):
            return self._raw(b"not found", "text/plain; charset=utf-8", 404)
        rest = "/" + "/".join(parts[3:])
        try:
            r = requests.get("http://127.0.0.1:%s%s" % (port, rest), timeout=30)
        except Exception:
            return self._raw(b"upstream error", "text/plain; charset=utf-8", 502)
        data = r.content
        ctype = r.headers.get("Content-Type") or "application/octet-stream"
        if any(k in ctype for k in ("text/html", "text/css", "javascript", "application/json")):
            txt = data.decode("utf-8", "replace")
            prefix = "/p/%s" % port
            txt = re.sub(r"""(["'(])/(?=[A-Za-z_])""", lambda m: m.group(1) + prefix + "/", txt)
            data = txt.encode("utf-8")
        return self._raw(data, ctype)

    def _img(self, name):
        """她的表情包：直接从 AstrBot 的 attachments 目录读（同机、只读、最快）。"""
        name = os.path.basename(name.split("?")[0])
        full = os.path.join(ATTACH, name)
        if not os.path.abspath(full).startswith(os.path.abspath(ATTACH)) or not os.path.isfile(full):
            return self._raw(b"", "image/webp", 404)
        ctype = mimetypes.guess_type(full)[0] or "image/webp"
        with open(full, "rb") as f:
            return self._raw(f.read(), ctype)

    def _art(self, name):
        """她画的画：art/gallery 下的成品/草稿。"""
        name = os.path.basename(name.split("?")[0])
        gal = r"D:\你的数据目录\art\gallery"
        full = os.path.join(gal, name)
        if not os.path.isfile(full):
            return self._raw(b"", "image/jpeg", 404)
        ctype = mimetypes.guess_type(full)[0] or "image/jpeg"
        with open(full, "rb") as f:
            return self._raw(f.read(), ctype)

    def do_POST(self):  # noqa: N802
        self._access()
        if urlparse(self.path).path == "/api/push":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception:
                payload = {}
            seq = self._push_append(payload.get("text"))
            return self._raw(json.dumps({"ok": bool(seq), "seq": seq}).encode(),
                             "application/json; charset=utf-8")
        if not urlparse(self.path).path == "/api/send":
            return self._raw(b"not found", "text/plain; charset=utf-8", 404)

        # 口令：?t=... 或 X-Gate 头
        want = gate_token()
        if want:
            have = (parse_qs(urlparse(self.path).query).get("t") or [""])[0] or \
                   self.headers.get("X-Gate", "")
            if have != want:
                return self._raw(json.dumps({"ok": False, "error": "bad token"}).encode(),
                                 "application/json; charset=utf-8", 403)

        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._raw(b'{"ok":false}', "application/json", 400)
        text = str(body.get("text") or "").strip()
        img_b64 = str(body.get("image_b64") or "").strip()
        if not text and not img_b64:
            return self._raw(b'{"ok":false}', "application/json", 400)

        # 有图就拼成 AstrBot 认识的消息片段：plain + image(path)
        message = text
        art_file = ""

        # 2026-11-20 部署者要求：不给她调用软件功能的权限，只让她亲手用鼠标键盘。
        # 所以这里不再自动执行 open_app/volume/media/draw 这类高层动作；
        # 她要用电脑就去"自己玩电脑"里亲手点（tools/persona_freeplay.py → /hand）。
        if False and hands_client is not None:
            try:
                act = hands_client.parse(text)
            except Exception:  # noqa: BLE001
                act = None
            if act:
                res = hands_client.call(act)
                message = hands_client.hint_text(act, res) + "\n" + text
                # 2026-11-10：画完把成品推到页面上
                try:
                    import re as _re2
                    _m = _re2.search(r"sketch_[0-9_]+\.[a-z]+", str(res.get("result") or ""))
                    if _m:
                        art_file = _m.group(0)
                except Exception:
                    pass

        # 教她玩游戏：先让她用自己的话复述逻辑，回复完再存进玩法笔记
        teach_quote = ""
        if playbook is not None:
            try:
                if playbook.is_teaching(text):
                    teach_quote = text
                    message = ("（你在教你玩绝区零：%s）先用你自己的话总结：什么情况、怎么做、为什么（必须带一句\u201c因为\u2026\u201d），"
                               "再跟他说一句你记住了。不要背原话，要讲逻辑。" % text)
            except Exception as exc:  # noqa: BLE001
                print("[教学] 识别失败:", exc)

        # "看看我"这类话：用电脑上的 E4 取一帧，把看到的内容带上
        if any(k in text for k in ("看看我", "看看你", "看着我", "看看你")):
            try:
                rr = requests.get("http://127.0.0.1:8016/look", timeout=120)
                desc = str((rr.json() or {}).get("desc") or "").strip() if rr.status_code == 200 else ""
                if desc:
                    message = ("（电脑摄像头看到：%s）\n%s" % (desc, text)).strip()
            except Exception as exc:  # noqa: BLE001
                print("[网页] 取画面失败:", exc)

        if img_b64:
            try:
                raw = base64.b64decode(img_b64.split(",")[-1], validate=False)
            except Exception:
                return self._raw(b'{"ok":false,"error":"image decode"}', "application/json", 400)
            if len(raw) > 12 * 1024 * 1024:
                return self._raw(b'{"ok":false,"error":"image too large"}', "application/json", 400)
            head = raw[:12]
            ext = ".png" if head[:8] == b"\x89PNG\r\n\x1a\n" else (".gif" if head[:6] in (b"GIF87a", b"GIF89a") else ".jpg")
            os.makedirs(UPLOADS, exist_ok=True)
            name = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6] + ext
            path = os.path.join(UPLOADS, name)
            with open(path, "wb") as fh:
                fh.write(raw)
            # 先让本机视觉模型看一眼，再把"她看到的"当文字带上；
            # 不直接把图片塞给对话模型（deepseek-flash 看不了，会回"我看不到图"）。
            desc = describe_image(raw)
            note = ("（你把一张图举到你眼前，你看清了：%s）" % desc) if desc else "（你把一张图举到你眼前，但你没看清）"
            message = (text + "\n" + note).strip() if text else note

        payload = {"message": message, "session_id": SESSION_ID,
                   "platform_id": "webchat", "username": USERNAME,
                   "enable_streaming": True}
        try:
            r = requests.post(AST + "/api/v1/chat",
                              headers={"Authorization": auth_header(),
                                       "Content-Type": "application/json"},
                              json=payload, timeout=120, stream=True)
        except Exception as exc:  # noqa: BLE001
            return self._raw(json.dumps({"ok": False, "error": "AstrBot 连不上：%s" % exc},
                                        ensure_ascii=False).encode(),
                             "application/json; charset=utf-8", 502)

        if r.status_code != 200:
            return self._raw(json.dumps({"ok": False, "error": "HTTP %d" % r.status_code}).encode(),
                             "application/json; charset=utf-8", 502)

        # 把 SSE 原样转给浏览器（chunked）
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def push(chunk: bytes):
            self.wfile.write(("%X\r\n" % len(chunk)).encode() + chunk + b"\r\n")
            self.wfile.flush()

        final_text = ""
        plain_acc = ""
        try:
            for line in r.iter_lines(decode_unicode=True):
                if line is None:
                    continue
                if not line:
                    continue
                if not line.startswith("data: "):
                    continue
                try:
                    ev = json.loads(line[6:])
                except ValueError:
                    continue
                kind = ev.get("type")
                if kind == "plain":
                    piece = ev.get("data") or ""
                    plain_acc += piece
                    push(json.dumps({"t": piece}, ensure_ascii=False).encode() + b"\n")
                elif kind == "image":
                    # 她的表情包：流里给的是文件名，页面再用 /img/<name> 取真图
                    push(json.dumps({"img": str(ev.get("data") or "").replace("[IMAGE]", "")}, ensure_ascii=False).encode() + b"\n")
                elif kind == "complete":
                    final_text = str(ev.get("data") or "") or plain_acc
                    push(json.dumps({"done": True, "text": ev.get("data") or ""},
                                    ensure_ascii=False).encode() + b"\n")
                elif kind == "error":
                    push(json.dumps({"error": str(ev.get("data"))}, ensure_ascii=False).encode() + b"\n")
        except Exception as exc:  # noqa: BLE001
            try:
                push(json.dumps({"error": "stream broken: %s" % exc}, ensure_ascii=False).encode() + b"\n")
            except Exception:  # noqa: BLE001
                pass
        finally:
            # 文本齐了就合成语音，作为最后一条推给页面
            if not final_text:
                final_text = plain_acc
            if teach_quote and final_text and playbook is not None:
                try:
                    rule = playbook.add(summary=final_text, quote=teach_quote)
                    print("[教学] 已记住玩法 %s（键位 %s）" % (rule["id"], rule["keys"]))
                    try:
                        import json as _json
                        _pf = r"D:\你的数据目录\video\pending_memories.json"
                        try:
                            with open(_pf, encoding="utf-8") as _f:
                                _items = _json.load(_f)
                            if not isinstance(_items, list):
                                _items = []
                        except Exception:  # noqa: BLE001
                            _items = []
                        _items.append({"summary": final_text, "importance": 0.55,
                                       "source": "game_teach", "time": time.time()})
                        with open(_pf, "w", encoding="utf-8") as _f:
                            _json.dump(_items, _f, ensure_ascii=False, indent=2)
                    except Exception as exc:  # noqa: BLE001
                        print("[教学] 写记忆队列失败:", exc)
                except Exception as exc:  # noqa: BLE001
                    print("[教学] 存档失败:", exc)
            if final_text and local_tts is not None:
                try:
                    import re as _re
                    spoken = _re.sub(r"[（(][^）)]{0,12}[）)]", "", final_text)
                    spoken = _re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", spoken).strip()
                    import asyncio as _asyncio
                    mp3 = _asyncio.run(local_tts.edge_mp3(spoken or final_text)) \
                        or local_tts.synth_mp3(spoken or final_text)
                    if mp3:
                        push(json.dumps({"voice": base64.b64encode(mp3).decode()},
                                        ensure_ascii=False).encode() + b"\n")
                        print("[语音] 已合成 %.0f KB" % (len(mp3) / 1024))
                    else:
                        print("[语音] 合成返回空")
                except Exception as exc:  # noqa: BLE001
                    print("[语音] 合成失败:", exc)
            if art_file:
                try:
                    push(json.dumps({"art": "/art/" + art_file}, ensure_ascii=False).encode() + b"\n")
                    print("[画画] 推成品到页面：", art_file)
                except Exception:  # noqa: BLE001
                    pass
            try:
                r.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except Exception:  # noqa: BLE001
                pass


GALLERY = r"D:\你的数据目录\art\gallery"


def _ink_ok(path, pencil=True):
    """判断是不是一张正常的画：铅笔看深色线条，成品看浅色块；整窗截图不要。"""
    try:
        from PIL import Image
        im = Image.open(path).convert("L")
        w, h = im.size
        if w > 2000 and h > 1000:
            return False          # 旧版整窗截图
        if w < 120 or h < 60:
            return False
        hist = im.histogram()
        total = float(w * h)
        if pencil:
            ratio = sum(hist[:90]) / total          # 深色像素
            if not (0.0004 <= ratio <= 0.15):
                return False
            # 贴边 = 画被画布截断（旧版没留边距），不要
            px = im.load()
            band_y = max(2, h // 50)
            band_x = max(2, w // 50)
            edge_ink = 0
            for y in range(band_y):
                for x in range(0, w, 3):
                    if px[x, y] < 90:
                        edge_ink += 1
            for x in range(0, w, 3):
                for y in range(h - band_y, h):
                    if px[x, y] < 90:
                        edge_ink += 1
            for x in range(band_x):
                for y in range(0, h, 3):
                    if px[x, y] < 90:
                        edge_ink += 1
            for x in range(w - band_x, w):
                for y in range(0, h, 3):
                    if px[x, y] < 90:
                        edge_ink += 1
            return edge_ink < 4
        ratio = (total - sum(hist[236:])) / total   # 非白像素
        return 0.004 <= ratio <= 0.85
    except Exception:
        return False


def _doodle_list():
    """陪玩时画的简笔画：doodle_*（铅笔）和 sketch_*（上色成品）配对。"""
    try:
        names = os.listdir(GALLERY)
    except Exception:
        return []
    doodles, sketches = [], []
    for n in names:
        if not n.lower().endswith((".jpg", ".png")):
            continue
        if n.startswith("doodle_"):
            doodles.append(n)
        elif n.startswith("sketch_"):
            sketches.append(n)
    doodles.sort(reverse=True)
    sketches.sort(reverse=True)

    def ts(name):
        digits = "".join(ch for ch in name if ch.isdigit())
        return digits[:14]

    out = []
    used = set()
    for d in doodles:
        if not _ink_ok(os.path.join(GALLERY, d)):
            continue
        t = ts(d)
        color = ""
        best = None
        for sk in sketches:
            if sk in used:
                continue
            if ts(sk) >= t and (not best or ts(sk) < ts(best)):
                best = sk
        if best:
            used.add(best)
            color = best if _ink_ok(os.path.join(GALLERY, best), pencil=False) else ""
        out.append({"time": t, "doodle": d, "sketch": color})
    # 没有草稿的成品不单独列（多半是调试残渣）
    out.sort(key=lambda x: x["time"], reverse=True)
    return out


def lan_ip():
    """本机在局域网里的地址（给手机用）。"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    tok = gate_token()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    os.makedirs(UPLOADS, exist_ok=True)
    print("TA的网页已启动："
          "  本机  http://127.0.0.1:%d/?t=%s"
          "  手机  http://%s:%d/?t=%s" % (PORT, tok, lan_ip(), PORT, tok))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
