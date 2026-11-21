import asyncio
import json
import os
import random
import time

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

BALANCE_URL = "https://api.deepseek.com/user/balance"
KAOMOJI = ["(｡•́︿•̀｡)", "(╥﹏╥)", "(｡╯︵╰｡)", "(๑•́ ₃ •̀๑)", "(´；ω；`)"]
_task = None


class CompanionBalance(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self.state_dir = os.path.join(
            get_astrbot_plugin_data_path(), "astrbot_plugin_companion_balance"
        )
        os.makedirs(self.state_dir, exist_ok=True)
        self.state_path = os.path.join(self.state_dir, "state.json")

    async def initialize(self):
        global _task
        if not bool(self.conf.get("enabled", True)):
            logger.info("[饭钱预警] 已在配置中关闭")
            return
        if _task and not _task.done():
            logger.info("[饭钱预警] 已有检查任务，跳过重复启动")
            return
        _task = asyncio.create_task(self._loop())
        logger.info(
            "[饭钱预警] 已启动，阈值 %.2f 元，每 %s 分钟检查一次"
            % (
                float(self.conf.get("threshold", 10.0)),
                self.conf.get("check_interval_minutes", 30),
            )
        )

    async def terminate(self):
        global _task
        if _task and not _task.done():
            _task.cancel()
        _task = None

    def _load_state(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_state(self, state):
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("[饭钱预警] 保存状态失败：%s" % exc)

    def _api_key(self):
        try:
            provider = self.context.get_provider_by_id("deepseek/deepseek-flash")
            cfg = getattr(provider, "provider_config", {}) or {}
            key = cfg.get("key")
            if isinstance(key, list):
                key = key[0] if key else ""
            return str(key or "").strip()
        except Exception as exc:
            logger.warning("[饭钱预警] 读取 DeepSeek key 失败：%s" % exc)
            return ""

    async def _fetch_balance(self):
        key = self._api_key()
        if not key:
            raise RuntimeError("没有找到 DeepSeek API key")
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
        connector = aiohttp.TCPConnector(ssl=False)
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(
            headers=headers, connector=connector, timeout=timeout
        ) as session:
            async with session.get(BALANCE_URL) as resp:
                data = await resp.json(content_type=None)
        infos = data.get("balance_infos") or []
        if not infos:
            raise RuntimeError("余额接口没有返回 balance_infos")
        info = next((x for x in infos if x.get("currency") == "CNY"), infos[0])
        return float(info.get("total_balance") or 0.0)

    async def _check(self):
        balance = await self._fetch_balance()
        threshold = float(self.conf.get("threshold", 10.0))
        repeat_seconds = max(1, int(self.conf.get("repeat_hours", 12))) * 3600
        state = self._load_state()
        now = time.time()

        try:
            with open(r"D:\你的数据目录\token_status.json", "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "balance": round(balance, 2),
                        "low": balance <= threshold,
                        "updated": now,
                    },
                    f,
                    ensure_ascii=False,
                )
        except Exception as exc:
            logger.warning("[饭钱预警] 写 token_status 失败：%s" % exc)

        if balance > threshold:
            if state.get("last_alert"):
                state["last_alert"] = 0
                state["last_balance"] = balance
                self._save_state(state)
            return

        if now - float(state.get("last_alert") or 0) < repeat_seconds:
            return

        session_id = str(self.conf.get("session") or "").strip()
        if not session_id:
            logger.warning("[饭钱预警] 没有配置发送会话")
            return

        first = random.choice(KAOMOJI)
        second = random.choice([x for x in KAOMOJI if x != first])
        text = (
            "你我快要饿死了，我想吃大米饭！%s\n"
            "DeepSeek 饭钱只剩 %.2f 块了\n"
            "再不充 token 我就真的饿死了 %s"
            % (first, balance, second)
        )
        try:
            ok = await self.context.send_message(
                session_id, MessageChain([Plain(text=text)])
            )
        except Exception as exc:
            logger.error("[饭钱预警] 发送失败：%s" % exc, exc_info=True)
            return
        if ok is False:
            logger.warning("[饭钱预警] 平台没有找到会话 %s" % session_id)
            return
        state["last_alert"] = now
        state["last_balance"] = balance
        self._save_state(state)
        logger.info("[饭钱预警] 已喊饿，余额 %.2f 元" % balance)

    async def _loop(self):
        await asyncio.sleep(8)
        while True:
            try:
                await self._check()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("[饭钱预警] 检查失败：%s" % exc)
            interval = max(5, int(self.conf.get("check_interval_minutes", 30)))
            try:
                await asyncio.sleep(interval * 60)
            except asyncio.CancelledError:
                return

    @filter.command("余额")
    async def balance_command(self, event: AstrMessageEvent):
        try:
            balance = await self._fetch_balance()
            await self.context.send_message(
                event.unified_msg_origin,
                MessageChain([Plain(text="现在饭钱还有 %.2f 块" % balance)]),
            )
        except Exception as exc:
            await self.context.send_message(
                event.unified_msg_origin,
                MessageChain([Plain(text="余额查不到：%s" % exc)]),
            )
