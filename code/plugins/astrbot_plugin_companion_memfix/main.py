"""记忆纠错：你说「纠正 <关键词> => <正确内容>」时，把那条记忆改掉。

设计要点（和 tools/memory_correct.py 共用一套引擎）：
  - 走插件自己的记忆更新接口，FTS / 向量 / 图记忆三套索引一起重建，不会歪；
  - 旧正文整段进 corrections.jsonl，账本登记作废，改动全程留痕；
  - 只处理明确指令（正则匹配），不碰普通聊天，也不会让模型自己乱改记忆。
"""

import asyncio
import json
import re

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

PY = (r"C:\你的用户\.astrbot_launcher\instances"
      r"\<BOT_INSTANCE>\venv\Scripts\python.exe")
TOOL = r"D:\你的数据目录\tools\memory_correct.py"

# 纠正 关键词 => 正确内容   /   纠正 #34 => 正确内容
CMD_RE = re.compile(r"^[/／]?(?:纠正|改记忆|更正记忆)\s*(.+)$", re.S)

USAGE = (
    "用法：纠正 <关键词> => <正确的内容>\n"
    "例：纠正 牛肉面 => 中午吃的是黄焖鸡\n"
    "不知道是哪条就先发「纠正 牛肉面」，我列出来给你挑（带 id）。"
)


class CompanionMemFix(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.conf = config or {}

    async def initialize(self):
        logger.info("[记忆纠错] 已启用：纠正 <关键词> => <正确内容>")

    async def _run_tool(self, *args):
        """调 tools/memory_correct.py，拿它吐的 JSON。"""
        proc = await asyncio.create_subprocess_exec(
            PY, "-X", "utf8", TOOL, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        text = out.decode("utf-8", "ignore").strip()
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line), text
                except json.JSONDecodeError:
                    continue
        return None, text

    async def _reply(self, event: AstrMessageEvent, text: str):
        await self.context.send_message(
            event.unified_msg_origin, MessageChain([Plain(text=text)])
        )

    @filter.regex(CMD_RE)
    async def correct(self, event: AstrMessageEvent):
        raw = event.get_message_str().strip()
        m = CMD_RE.match(raw)
        if not m:
            return
        body = (m.group(1) or "").strip()
        if not body:
            event.stop_event()
            await self._reply(event, USAGE)
            return

        # 统一分隔符：=> / ＝> / →
        body = body.replace("＝>", "=>").replace("→", "=>")
        if "=>" in body:
            left, right = (p.strip() for p in body.split("=>", 1))
        else:
            left, right = body, ""

        if not left:
            event.stop_event()
            await self._reply(event, USAGE)
            return

        # 1) 只有关键词：列候选
        if not right:
            data, raw_out = await self._run_tool("--find", left, "--json")
            if not data or not data.get("items"):
                event.stop_event()
                await self._reply(event, f"没找到含「{left}」的记忆。\n{USAGE}")
                return
            items = data["items"]
            lines = [f"含「{left}」的记忆有 {len(items)} 条："]
            for it in items[:8]:
                lines.append(f"  #{it['id']}  {it['when']}  {it['text'][:40]}")
            lines.append("确定是哪条就发：纠正 #编号 => 正确的内容")
            event.stop_event()
            await self._reply(event, "\n".join(lines))
            return

        # 2) 指定 id：直接改
        if left.startswith("#") and left[1:].isdigit():
            memory_id = int(left[1:])
            why = "你在 QQ 上纠正"
            data, raw_out = await self._run_tool(
                "--apply", "--id", str(memory_id), "--text", right,
                "--why", why, "--json",
            )
            event.stop_event()
            if not data or not data.get("ok"):
                err = (data or {}).get("error") or raw_out[-200:]
                await self._reply(event, f"改失败了：{err}")
                return
            await self._reply(
                event,
                f"改好了 #{data.get('old_id')} → #{data.get('new_id')}：{right}\n"
                "旧的那段我留着，想查随时能查。",
            )
            return

        # 3) 关键词 + 新内容：先找，唯一命中才动手
        data, raw_out = await self._run_tool("--find", left, "--json")
        items = (data or {}).get("items") or []
        if not items:
            event.stop_event()
            await self._reply(event, f"没找到含「{left}」的记忆。")
            return
        if len(items) > 1:
            lines = [f"「{left}」能对上 {len(items)} 条，我不瞎猜："]
            for it in items[:8]:
                lines.append(f"  #{it['id']}  {it['when']}  {it['text'][:40]}")
            lines.append("看准了发：纠正 #编号 => 正确的内容")
            event.stop_event()
            await self._reply(event, "\n".join(lines))
            return

        memory_id = items[0]["id"]
        data, raw_out = await self._run_tool(
            "--apply", "--id", str(memory_id), "--text", right,
            "--why", f"你在 QQ 上纠正（关键词：{left}）", "--json",
        )
        event.stop_event()
        if not data or not data.get("ok"):
            err = (data or {}).get("error") or raw_out[-200:]
            await self._reply(event, f"改失败了：{err}")
            return
        await self._reply(
            event,
            f"改好了 #{data.get('old_id')} → #{data.get('new_id')}：{right}\n"
            "旧的那段我留着，想查随时能查。",
        )
