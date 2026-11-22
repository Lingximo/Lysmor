import base64
import copy
import importlib.util
import json
import tempfile
import unittest
from http.server import ThreadingHTTPServer
import threading
import urllib.request
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("lys_configure", ROOT / "configure.py")
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)
setup_spec = importlib.util.spec_from_file_location("lys_setup", ROOT / "setup/server.py")
setup_server = importlib.util.module_from_spec(setup_spec)
setup_spec.loader.exec_module(setup_server)


class ConfigureRegressionTests(unittest.TestCase):
    def test_ports_are_remapped_once_and_reconfiguration_uses_previous_values(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp/test") as directory:
            base = Path(directory)
            code = base / "code"
            code.mkdir()
            source = code / "service.py"
            source.write_text('path = r"D:\\你的数据目录"\na = 8001\nb = 8002\ntoken = "<GATE_TOKEN>"\n', encoding="utf-8")
            cfg = copy.deepcopy(configure.DEFAULTS)
            cfg.update(data_dir=str(base / "8001/data"), gate_token="first-test-token-8002")
            cfg["ports"]["chat"], cfg["ports"]["gallery"] = 8002, 8001
            with patch.multiple(configure, CODE=str(code), CFG_PATH=str(base / "config.json")):
                configure.apply_config(cfg)
                self.assertIn("a = 8002\nb = 8001", source.read_text())
                self.assertIn(str(base / "8001/data"), source.read_text())
                self.assertIn("first-test-token-8002", source.read_text())
                cfg.update(data_dir=str(base / "new-data"), gate_token="second-test-token")
                cfg["ports"]["chat"], cfg["ports"]["gallery"] = 9001, 9002
                configure.apply_config(cfg)
                content = source.read_text()
                self.assertIn("a = 9001\nb = 9002", content)
                self.assertIn("second-test-token", content)
                self.assertNotIn("first-test-token", content)
                self.assertIn(str(base / "new-data"), content)
                self.assertEqual((base / "new-data/gate_token.txt").read_text(), "second-test-token")

    def test_windows_escaped_paths_remain_escaped(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp/test") as directory:
            base = Path(directory)
            code = base / "code"
            code.mkdir()
            source = code / "source.py"
            source.write_text('path = "D:\\\\你的数据目录"\n', encoding="utf-8")
            cfg = copy.deepcopy(configure.DEFAULTS)
            cfg.update(data_dir=r"E:\data\new", gate_token="fixture")
            with patch.multiple(configure, CODE=str(code), CFG_PATH=str(base / "config.json")), \
                    patch.object(configure.os, "makedirs"), patch.object(configure.shutil, "copy2"), \
                    patch.object(configure.shutil, "copytree"), patch("builtins.print"):
                configure.apply_config(cfg)
            self.assertEqual(source.read_text(), 'path = "E:\\\\data\\\\new"\n')

    def test_invalid_ports_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp/test") as directory:
            base = Path(directory)
            cfg = copy.deepcopy(configure.DEFAULTS)
            cfg["ports"]["chat"] = cfg["ports"]["gallery"]
            path = base / "config.json"
            with patch.multiple(configure, CODE=str(base), CFG_PATH=str(path)):
                with self.assertRaises(ValueError):
                    configure.apply_config(cfg)
            self.assertFalse(path.exists())

    def test_ambiguous_previous_values_stop_before_any_write(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp/test') as directory:
            base = Path(directory)
            code = base / 'code'
            code.mkdir()
            source = code / 'service.py'
            source.write_text('primary="<你的QQ号>"; secondary="<你的QQ号2>"', encoding='utf-8')
            cfg = copy.deepcopy(configure.DEFAULTS)
            cfg.update(data_dir=str(base / 'data'), qq='123456789', qq2='123456789', gate_token='fixture')
            config_path = base / 'config.json'
            with patch.multiple(configure, CODE=str(code), CFG_PATH=str(config_path)):
                configure.apply_config(cfg)
                original = source.read_bytes(), config_path.read_bytes()
                cfg['qq2'] = '987654321'
                with self.assertRaises(ValueError) as error:
                    configure.apply_config(cfg)
                self.assertNotIn('123456789', str(error.exception))
                self.assertEqual((source.read_bytes(), config_path.read_bytes()), original)

    def test_check_setup_reports_duplicate_ports(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp/test") as directory:
            base = Path(directory)
            path = base / "config.json"
            path.write_text(json.dumps({"ports": {"chat": 8101, "gallery": 8101}}))
            with patch.multiple(configure, CODE=str(base), CFG_PATH=str(path)), \
                    patch.object(configure, "_listening", return_value=False), \
                    patch.object(configure.urllib.request, "urlopen", side_effect=OSError):
                checks = configure.check_setup()
            self.assertTrue(any(item["level"] == "fail" and "撞了" in item["detail"] for item in checks))

    def test_asset_import_rejects_drive_and_traversal_without_truncating_files(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp/test") as directory:
            root = Path(directory)
            cfg = {"data_dir": directory}
            payload = base64.b64encode(b"image").decode()
            result = configure.import_assets(cfg, "live2d", [
                {"name": "model/textures/texture.png", "data": payload},
                {"name": "../escape.png", "data": payload},
                {"name": "C:/escape.png", "data": payload},
                {"name": "C:\\escape.png", "data": payload},
                {"name": "bad.png", "data": "invalid!"},
            ])
            self.assertEqual(result["saved"], ["model/textures/texture.png"])
            self.assertFalse((root / "video/static/live2d/bad.png").exists())
            self.assertFalse((root / "video/static/escape.png").exists())

    def test_enrollment_only_accepts_declared_slots(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp/test") as directory:
            payload = base64.b64encode(b"fixture").decode()
            result = configure.save_enrollment({"data_dir": directory},
                {"v1": payload, "../../../escape": payload},
                {"front": payload, "../../../escape": payload})
            self.assertEqual(len(result["saved"]), 2)

    def test_model_launch_failures_are_not_reported_as_started(self):
        with patch.object(configure.subprocess, "Popen", side_effect=FileNotFoundError):
            self.assertEqual(configure._pull_models_background(), [])

    def test_wizard_language_normalization_preserves_api_fields(self):
        for locale in ("zh-TW", "en"):
            normalized = setup_server.normalize({"language": locale, "llm": {"model": "deepseek-chat"}})
            self.assertEqual(normalized["language"], locale)
            self.assertEqual(normalized["llm"]["model"], "deepseek-chat")

    def test_wizard_assets_and_language_context_are_per_request(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), setup_server.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with patch.object(setup_server.configure, "check_setup", side_effect=lambda: [{"detail": configure.t("setup.generated")} ]):
                for locale, expected in (("en", "Generated"), ("zh-TW", "已產生"), ("zh-CN", "已生成")):
                    request = urllib.request.Request("http://127.0.0.1:%d/api/check" % server.server_port,
                                                     headers={"Accept-Language": locale})
                    with opener.open(request, timeout=3) as response:
                        self.assertEqual(json.load(response)["checks"][0]["detail"], expected)
            with opener.open("http://127.0.0.1:%d/i18n.js" % server.server_port, timeout=3) as response:
                self.assertIn(b"setup.text.1", response.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
