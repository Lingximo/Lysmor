# -*- coding: utf-8 -*-
"""可视化配置向导（本地网页）

双击 一键配置.cmd 会启动本服务并打开浏览器：
  页面里填表 → 点"一键应用" → 服务器调用 configure.apply_config() 完成全部改写。

接口：
  GET  /api/defaults    -> 默认值（页面预填用）
  POST /api/configure   -> {data_dir, user_dir, qq, qq2, bot_instance, gate_token, ports{...}}
                            -> {ok, files, repl, config_path}
  GET  /                -> 向导页面（仅本机，无需口令）
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import configure  # noqa: E402

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
PORT = int(os.environ.get("SETUP_PORT") or 8090)
HOST = os.environ.get("SETUP_HOST") or "127.0.0.1"

MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}


def normalize(cfg):
    d = configure.DEFAULTS
    out = {
        "data_dir": str(cfg.get("data_dir") or d["data_dir"]),
        "user_dir": str(cfg.get("user_dir") or d["user_dir"]),
        "qq": str(cfg.get("qq") or d["qq"]),
        "qq2": str(cfg.get("qq2") or d["qq2"]),
        "bot_instance": str(cfg.get("bot_instance") or d["bot_instance"]),
        "gate_token": str(cfg.get("gate_token") or ""),
        "llm": {
            "provider": str((cfg.get("llm") or {}).get("provider") or d["llm"]["provider"]),
            "api_key": str((cfg.get("llm") or {}).get("api_key") or ""),
            "base_url": str((cfg.get("llm") or {}).get("base_url") or d["llm"]["base_url"]),
            "model": str((cfg.get("llm") or {}).get("model") or d["llm"]["model"]),
        },
        "bot_panel": int(cfg.get("bot_panel") or d["bot_panel"]),
        "fish_qq": str(cfg.get("fish_qq") or ""),
        "ports": {},
    }
    if not out["gate_token"]:
        out["gate_token"] = __import__("secrets").token_urlsafe(18)
    for num, key in configure.PORT_KEY:
        try:
            out["ports"][key] = int(cfg.get("ports", {}).get(key, num))
        except (TypeError, ValueError):
            out["ports"][key] = num
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "companion-setup/0.1"

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/defaults":
            return self._json(configure.DEFAULTS)
        if parsed.path == "/api/check":
            return self._json({"checks": configure.check_setup()})
        if parsed.path == "/api/autodetect":
            return self._json(configure.autodetect())
        if parsed.path == "/api/huburl":
            try:
                cfg = json.load(open(configure.CFG_PATH, encoding="utf-8"))
                hub = int(cfg.get("ports", {}).get("hub") or 8009)
                token = cfg.get("gate_token") or ""
                return self._json({"url": "http://127.0.0.1:%d/?t=%s" % (hub, token)})
            except Exception:
                return self._json({"url": None})
        if parsed.path == "/api/identity":
            try:
                cfg = {"data_dir": configure.DEFAULTS["data_dir"]}
                try:
                    cfg = json.load(open(configure.CFG_PATH, encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    pass
                data = configure.load_identity(cfg)
                return self._json({"ok": True, "identity": data["identity"], "persona": data["persona"]})
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": str(exc)}, 400)
        rel = parsed.path.strip("/") or "index.html"
        if ".." in rel or rel.startswith("/"):
            self.send_response(404)
            return self.end_headers()
        fp = os.path.join(STATIC, rel)
        if not os.path.isfile(fp):
            self.send_response(404)
            return self.end_headers()
        body = open(fp, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(os.path.splitext(fp)[1].lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/envsetup":
            try:
                return self._json({"results": configure.env_install_missing()})
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": str(exc)}, 400)
        if parsed.path == "/api/enroll":
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                req = json.loads(raw.decode("utf-8"))
                cfg = {"data_dir": configure.DEFAULTS["data_dir"]}
                # 若已配置过，样本存进用户的 data_dir
                try:
                    cfg = json.load(open(configure.CFG_PATH, encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    pass
                return self._json(configure.save_enrollment(cfg, req.get("voice"), req.get("faces")))
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": str(exc)}, 400)
        if parsed.path == "/api/import_asset":
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                req = json.loads(raw.decode("utf-8"))
                cfg = {"data_dir": configure.DEFAULTS["data_dir"]}
                try:
                    cfg = json.load(open(configure.CFG_PATH, encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    pass
                return self._json(configure.import_assets(cfg, req.get("kind"), req.get("files")))
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": str(exc)}, 400)
        if parsed.path == "/api/autoconfig":
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                req = json.loads(raw.decode("utf-8"))
                det = configure.autodetect()
                cfg = {
                    "data_dir": configure.DEFAULTS["data_dir"],
                    "user_dir": configure.DEFAULTS["user_dir"],
                    "qq": str(req.get("user_qq") or configure.DEFAULTS["qq"]),
                    "qq2": str(req.get("user_qq2") or configure.DEFAULTS["qq2"]),
                    "fish_qq": str(req.get("fish_qq") or ""),
                    "bot_instance": det["bot_instance"] or configure.DEFAULTS["bot_instance"],
                    "bot_panel": det["bot_panel"],
                    "gate_token": __import__("secrets").token_urlsafe(18),
                    "llm": {
                        "provider": "deepseek",
                        "api_key": str(req.get("api_key") or ""),
                        "base_url": configure.DEFAULTS["llm"]["base_url"],
                        "model": "deepseek-chat",
                    },
                    "ports": dict(configure.DEFAULTS["ports"]),
                }
                files, repl = configure.apply_config(cfg)
                astr = configure.patch_astrbot_llm(cfg)
                enroll = configure.save_enrollment(cfg, req.get("voice"), req.get("faces"))
                return self._json({"ok": True, "files": files, "repl": repl,
                                   "token": cfg["gate_token"], "astrbot": astr,
                                   "detected": det, "enroll": enroll})
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": str(exc)}, 400)
        if parsed.path == "/api/configure":
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                cfg = normalize(json.loads(raw.decode("utf-8")))
                files, repl = configure.apply_config(cfg)
                astr = configure.patch_astrbot_llm(cfg)
                return self._json({"ok": True, "files": files, "repl": repl,
                                   "config_path": configure.CFG_PATH,
                                   "token": cfg["gate_token"], "astrbot": astr})
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": str(exc)}, 400)
        if parsed.path == "/api/optimize_identity":
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                req = json.loads(raw.decode("utf-8"))
                llm = {"api_key": req.get("api_key"), "base_url": req.get("base_url"), "model": req.get("model")}
                text = configure.optimize_identity(req.get("identity"), llm)
                return self._json({"ok": True, "persona": text})
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": str(exc)}, 400)
        if parsed.path == "/api/save_identity":
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                req = json.loads(raw.decode("utf-8"))
                cfg = {"data_dir": configure.DEFAULTS["data_dir"]}
                try:
                    cfg = json.load(open(configure.CFG_PATH, encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    pass
                path = configure.save_identity(cfg, req.get("identity"), req.get("persona"))
                return self._json({"ok": True, "path": path})
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": str(exc)}, 400)
        self.send_response(404)
        return self.end_headers()

    def log_message(self, fmt, *args):
        pass


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print("配置向导已启动：http://%s:%d/  （只监听本机）" % (HOST, PORT))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
