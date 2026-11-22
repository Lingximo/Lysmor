import ast
import asyncio
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tmp/http-review-deps"))


def selected_module(relative, names, namespace):
    source = ast.parse((ROOT / relative).read_text(encoding="utf-8-sig"))
    nodes = [node for node in source.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), relative, "exec"), namespace)
    return namespace


def handler_instance(cls, path, body=b"", headers=None):
    handler = object.__new__(cls)
    handler.path = path
    handler.headers = headers or {}
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.client_address = ("192.0.2.2", 12345)
    handler._access = lambda: None
    response = {}
    handler.send_response = lambda status: response.update(status=status)
    handler.send_header = lambda key, value: response.setdefault("headers", {}).update({key: value})
    handler.end_headers = lambda: None
    return handler, response


class HttpReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("review_webchat", ROOT / "code/webchat/server.py")
        cls.webchat = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.webchat)

    def test_webchat_gate_protects_private_reads_and_push_writes(self):
        for path, method in [("/api/push", "GET"), ("/api/doodles", "GET"),
                             ("/p/8005/api/state", "GET"), ("/img/private.png", "GET"),
                             ("/api/push", "POST")]:
            with self.subTest(path=path, method=method), patch.object(self.webchat, "gate_token", return_value="test-pass"):
                handler, response = handler_instance(self.webchat.Handler, path)
                getattr(handler, "do_" + method)()
                self.assertEqual(response["status"], 403)

    def test_webchat_gate_keeps_shell_public_and_accepts_authorized_push(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp/test") as directory:
            root = Path(directory)
            (root / "index.html").write_text("shell")
            with patch.object(self.webchat, "gate_token", return_value="test-pass"), patch.object(self.webchat, "STATIC", directory):
                handler, response = handler_instance(self.webchat.Handler, "/")
                handler.do_GET()
                self.assertEqual(response["status"], 200)
                self.assertEqual(handler.wfile.getvalue(), b"shell")
                handler, response = handler_instance(self.webchat.Handler, "/api/push?t=test-pass&since=0")
                handler._push_read = lambda since: []
                handler.do_GET()
                self.assertEqual(response["status"], 200)

    def test_webchat_rejects_invalid_json_objects_lengths_and_cursor(self):
        with patch.object(self.webchat, "gate_token", return_value=""):
            for path, raw, headers in [
                ("/api/push", b"[]", {"Content-Length": "2"}),
                ("/api/send", b"null", {"Content-Length": "4"}),
                ("/api/send", b"", {"Content-Length": "-1"}),
                ("/api/send", b"", {"Content-Length": "not-a-number"}),
            ]:
                with self.subTest(path=path, raw=raw, headers=headers):
                    handler, response = handler_instance(self.webchat.Handler, path, raw, headers)
                    handler.do_POST()
                    self.assertEqual(response["status"], 400)
            handler, response = handler_instance(self.webchat.Handler, "/api/push?since=invalid")
            handler.do_GET()
            self.assertEqual(response["status"], 400)

    def test_webchat_static_cannot_escape_into_prefix_sibling_or_symlink(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp/test") as directory:
            root = Path(directory)
            static = root / "static"
            static.mkdir()
            sibling = root / "static-private"
            sibling.mkdir()
            (sibling / "data.txt").write_text("private")
            (static / "leak.txt").symlink_to(sibling / "data.txt")
            with patch.object(self.webchat, "STATIC", str(static)):
                for name in ("../static-private/data.txt", "leak.txt"):
                    handler, response = handler_instance(self.webchat.Handler, "/")
                    handler._static(name)
                    self.assertEqual(response["status"], 404)

    def test_lifeviz_query_route_and_static_containment(self):
        from http.server import BaseHTTPRequestHandler
        from urllib.parse import urlparse
        env = selected_module("code/lifeviz/server.py", {"Handler"}, {
            "BaseHTTPRequestHandler": BaseHTTPRequestHandler, "urlparse": urlparse,
            "gate": SimpleNamespace(guard=lambda handler: False), "json": json, "os": os,
            "state": lambda: {"ok": True}, "browser_asset": lambda path: None})
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp/test") as directory:
            root = Path(directory)
            static = root / "static"
            static.mkdir()
            (root / "private.txt").write_text("private")
            env.update(STATIC=str(static), LIVE2D=str(static))
            handler, response = handler_instance(env["Handler"], "/api/state?t=test-pass")
            handler.do_GET()
            self.assertEqual(response["status"], 200)
            for path in ("/../private.txt", "/live2d/../private.txt"):
                handler, response = handler_instance(env["Handler"], path)
                handler.do_GET()
                self.assertEqual(response["status"], 404)

    def test_hub_remote_host_spoof_is_not_local_and_manifest_has_no_secret(self):
        from aiohttp import web
        import secrets
        from i18n import language_from_header, t
        env = selected_module("code/hub/server.py", {"_local", "allowed", "gate_middleware", "manifest_dynamic"}, {
            "web": web, "secrets": secrets, "KEY": "hub-test-pass", "COOKIE": "companion_hub",
            "t": t, "language_from_header": language_from_header})
        remote = SimpleNamespace(remote="192.0.2.2", host="localhost:8009", query={}, cookies={}, headers={}, secure=False)
        self.assertFalse(env["allowed"](remote))
        remote.remote = "::1"
        self.assertTrue(env["allowed"](remote))
        remote.remote = "192.0.2.2"
        remote.path = "/"
        remote.query = {"t": "hub-test-pass"}
        async def page(request):
            return web.Response(text="page")
        async def run():
            wrapper = await env["gate_middleware"](None, page)
            authorized = await wrapper(remote)
            self.assertEqual(authorized.cookies["companion_hub"].value, "hub-test-pass")
            remote.query = {}
            self.assertEqual((await wrapper(remote)).status, 403)
            remote.path = "/static/app.js"
            self.assertEqual((await wrapper(remote)).status, 200)
            for asset in ("/i18n.js", "/locales/zh-CN.json", "/locales/zh-TW.json", "/locales/en.json"):
                remote.path = asset
                self.assertEqual((await wrapper(remote)).status, 200)
            manifest = await env["manifest_dynamic"](remote)
            self.assertEqual(json.loads(manifest.text)["start_url"], "/")
            self.assertNotIn("hub-test-pass", manifest.text)
        asyncio.run(run())

    def test_video_static_rejects_prefix_sibling(self):
        from aiohttp import web
        env = selected_module("code/video/server.py", {"static_files"}, {"web": web, "os": os})
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp/test") as directory:
            root = Path(directory)
            static = root / "static"
            static.mkdir()
            sibling = root / "static-private"
            sibling.mkdir()
            (sibling / "data.txt").write_text("private")
            env["STATIC"] = str(static)
            request = SimpleNamespace(match_info={"tail": "../static-private/data.txt"})
            with self.assertRaises(web.HTTPNotFound):
                asyncio.run(env["static_files"](request))

    def test_gate_rejects_non_ascii_invalid_token_without_crashing(self):
        import secrets
        from urllib.parse import parse_qs, urlparse
        env = selected_module("code/tools/gate.py", {"check"}, {
            "secrets": secrets, "parse_qs": parse_qs, "urlparse": urlparse,
            "TOKEN": "valid-pass", "LOCAL_ADDRS": ("127.0.0.1", "::1"), "COOKIE_NAME": "companion_gate"})
        handler = SimpleNamespace(client_address=("192.0.2.2", 1), path="/api/state?t=测试", headers={})
        self.assertEqual(env["check"](handler), (False, False))
        handler.path = "/api/state"
        handler.headers = {"Cookie": "companion_gate=测试"}
        self.assertEqual(env["check"](handler), (False, False))

    def test_i18n_assets_are_public_across_services(self):
        from aiohttp import web
        from http.server import BaseHTTPRequestHandler
        from urllib.parse import urlparse
        from i18n import browser_asset
        js = browser_asset("/i18n.js")
        self.assertIsNotNone(js)
        with patch.object(self.webchat, "gate_token", return_value="test-pass"):
            handler, response = handler_instance(self.webchat.Handler, "/i18n.js")
            handler.do_GET()
            self.assertEqual(response["status"], 200)
            self.assertEqual(handler.wfile.getvalue(), js[0])
        for relative in ("code/lifeviz/server.py", "code/houseviz/server.py"):
            env = selected_module(relative, {"Handler"}, {
                "BaseHTTPRequestHandler": BaseHTTPRequestHandler, "urlparse": urlparse,
                "browser_asset": browser_asset, "os": os,
                "gate": SimpleNamespace(guard=lambda handler: self.fail("i18n must precede private gate"))})
            handler, response = handler_instance(env["Handler"], "/i18n.js")
            if relative.endswith("houseviz/server.py"):
                handler._send = lambda status, body, mime: response.update(status=status, body=body)
            handler.do_GET()
            self.assertEqual(response["status"], 200)
        for relative in ("code/hub/server.py", "code/video/server.py"):
            env = selected_module(relative, {"i18n_asset"}, {"web": web, "browser_asset": browser_asset})
            response = asyncio.run(env["i18n_asset"](SimpleNamespace(path="/i18n.js")))
            self.assertEqual(response.status, 200)
            self.assertEqual(response.body, js[0])
            with self.assertRaises(web.HTTPNotFound):
                asyncio.run(env["i18n_asset"](SimpleNamespace(path="/locales/../../private.json")))

    def test_gate_deny_translates_and_escapes_configured_path(self):
        from html import escape
        from i18n import language_from_header, t
        env = selected_module("code/tools/gate.py", {"deny"}, {
            "escape": escape, "language_from_header": language_from_header, "t": t,
            "TOKEN_PATH": 'data/<script>alert("path")</script>/gate_token.txt'})
        for locale, text in (("en", "Access token required"), ("zh-TW", "需要存取密碼"), ("zh-CN", "需要访问口令")):
            handler, response = handler_instance(self.webchat.Handler, "/api/state", headers={"Accept-Language": locale})
            env["deny"](handler)
            html = handler.wfile.getvalue().decode()
            self.assertEqual(response["status"], 403)
            self.assertIn(text, html)
            self.assertNotIn("<script>", html)
            self.assertIn("&lt;script&gt;", html)

    def test_video_gate_uses_request_locale(self):
        from aiohttp import web
        from html import escape
        from i18n import locale_context, language_from_header, t
        import secrets
        env = selected_module("code/video/server.py", {"gate_middleware", "_gate_request"}, {
            "web": web, "escape": escape, "locale_context": locale_context,
            "language_from_header": language_from_header, "t": t, "secrets": secrets,
            "_gate_token": lambda: "test-pass", "GATE_COOKIE": "companion_gate", "GATE_TOKEN_PATH": "data/gate_token.txt"})
        async def page(request):
            return web.Response(text="page")
        for locale, expected in (("en", "Access token required"), ("zh-TW", "需要存取密碼")):
            request = SimpleNamespace(headers={"Accept-Language": locale}, remote="192.0.2.2", path="/api/chat", query={}, cookies={})
            response = asyncio.run(env["gate_middleware"](request, page))
            self.assertEqual(response.status, 401)
            self.assertEqual(json.loads(response.text)["error"], expected)


if __name__ == "__main__":
    unittest.main()
