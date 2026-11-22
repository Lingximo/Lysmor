import importlib.util
import json
from pathlib import Path
import re
import subprocess
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[2]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
SERVICES = ('brain', 'console', 'gallery', 'house', 'life', 'webchat')
ENDPOINTS = {'brain': '/api/memories', 'console': '/api/overview', 'gallery': '/api/works',
             'house': '/api/house', 'life': '/api/state', 'webchat': '/api/history'}


class ServiceI18NTests(unittest.TestCase):
    def test_catalogs_cover_all_interface_keys_and_placeholders(self):
        catalogs = {locale: json.loads((ROOT / 'locales' / ('services.' + locale + '.json')).read_text())
                    for locale in ('zh-CN', 'zh-TW', 'en')}
        self.assertEqual(set(catalogs['zh-CN']), set(catalogs['zh-TW']))
        self.assertEqual(set(catalogs['zh-CN']), set(catalogs['en']))
        for key, source in catalogs['zh-CN'].items():
            for locale in ('zh-TW', 'en'):
                self.assertEqual(set(re.findall(r'\{\w+\}', source)),
                                 set(re.findall(r'\{\w+\}', catalogs[locale][key])), key)
        for service in SERVICES:
            with self.subTest(service=service):
                html = (ROOT / 'services' / service / 'static/index.html').read_text()
                script = (ROOT / 'services' / service / 'static/app.js').read_text()
                keys = re.findall(r'data-i18n(?:-\w+)?="([^"]+)"', html)
                keys += re.findall(r't\("(services\.[^"]+)"', script)
                for key in keys:
                    if key.endswith('.'):
                        continue
                    self.assertIn(key, catalogs['zh-CN'])
                self.assertIn('data-language-select', html)
                self.assertLess(html.index('src="/i18n.js"'), html.index('src="app.js"'))
                subprocess.run(['node', '--check', str(ROOT / 'services' / service / 'static/app.js')],
                               check=True, capture_output=True)

    def test_public_translations_and_localized_protected_endpoints(self):
        for service in SERVICES:
            with self.subTest(service=service):
                path = ROOT / 'services' / service / 'server.py'
                spec = importlib.util.spec_from_file_location('test_service_' + service, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.CONFIG['gate_token'] = 'fixture-only-token'
                with ThreadingHTTPServer(('127.0.0.1', 0), module.Handler) as server:
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    base = 'http://127.0.0.1:' + str(server.server_port)
                    try:
                        with OPENER.open(base + '/i18n.js') as response:
                            self.assertEqual(response.status, 200)
                            self.assertIn('application/javascript', response.headers['Content-Type'])
                            self.assertIn(b'services.webchat.send', response.read())
                        request = urllib.request.Request(base + ENDPOINTS[service],
                                                         headers={'Accept-Language': 'en-US,en;q=0.8'})
                        with self.assertRaises(urllib.error.HTTPError) as caught:
                            OPENER.open(request)
                        self.assertEqual(caught.exception.code, 403)
                        self.assertEqual(json.load(caught.exception)['error'], 'Invalid access token')
                        caught.exception.close()
                        request = urllib.request.Request(base + ENDPOINTS[service],
                                                         headers={'Accept-Language': 'zh-TW'})
                        with self.assertRaises(urllib.error.HTTPError) as caught:
                            OPENER.open(request)
                        self.assertEqual(json.load(caught.exception)['error'], '口令不正確')
                        caught.exception.close()
                    finally:
                        server.shutdown()
                        thread.join()

    def test_webchat_placeholder_response_uses_request_locale(self):
        spec = importlib.util.spec_from_file_location('test_chat_reply', ROOT / 'services/webchat/server.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.reply('Unchanged user text', locale='en'),
                         '(Placeholder reply) You said: Unchanged user text')
        self.assertEqual(module.reply('繁體輸入', locale='zh-TW'), '（預設回覆）你說的是：繁體輸入')


if __name__ == '__main__':
    unittest.main()
