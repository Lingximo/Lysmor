import ast
import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[2]


class MemfixAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    def handler(self, conf):
        source = ROOT / 'code/plugins/astrbot_plugin_companion_memfix/main.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == 'correct')
        method.decorator_list = []
        namespace = {'CMD_RE': re.compile(r'^[/／]?(?:纠正|改记忆|更正记忆)\s*(.+)$', re.S),
                     'AstrMessageEvent': object, 't': __import__('i18n').t}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(source), 'exec'), namespace)
        plugin = type('Plugin', (), {})()
        plugin.conf = conf
        plugin._run_tool = AsyncMock(return_value=({'ok': True, 'items': []}, ''))
        plugin._reply = AsyncMock()
        namespace['USAGE'] = 'usage'
        return plugin, namespace['correct']

    async def test_untrusted_sender_cannot_search_or_modify(self):
        for message in ['纠正 memory', '纠正 #1 => replacement']:
            event = self.event(message, 'other', False)
            plugin, handler = self.handler({'owner_session': 'owner'})
            await handler(plugin, event)
            plugin._run_tool.assert_not_awaited()
            plugin._reply.assert_not_awaited()
            self.assertTrue(event.stopped)

    async def test_admin_and_configured_owner_can_search(self):
        for origin, is_admin in [('owner', False), ('other', True)]:
            event = self.event('纠正 memory', origin, is_admin)
            plugin, handler = self.handler({'owner_session': 'owner'})
            await handler(plugin, event)
            plugin._run_tool.assert_awaited_once_with('--find', 'memory', '--json')

    def event(self, message, origin, admin):
        class Event:
            unified_msg_origin = origin
            stopped = False

            def get_message_str(self):
                return message

            def is_admin(self):
                return admin

            def stop_event(self):
                self.stopped = True

        return Event()


if __name__ == '__main__':
    unittest.main()
