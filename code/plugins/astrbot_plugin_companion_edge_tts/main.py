from astrbot import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain, Record
from astrbot.api.star import Context, Star
from astrbot.core.star.session_llm_manager import SessionServiceManager


class EdgeVoicePlugin(Star):
    """用 AstrBot 自带的 edge_tts 服务商，整条回复合成一条语音。

    只负责“什么时候发语音”，不再注册 edge_tts 适配器，避免和内置适配器冲突。
    """

    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self._warned_double = False

    def _provider(self):
        for p in self.context.get_all_tts_providers():
            cfg = getattr(p, "provider_config", {}) or {}
            if cfg.get("type") == "edge_tts" or cfg.get("provider") == "edge":
                return p
        return None

    @filter.on_decorating_result(priority=-1000)
    async def whole_reply_voice(self, event: AstrMessageEvent):
        result = event.get_result()
        if result is None or not result.chain or not result.is_llm_result():
            return
        prov = self._provider()
        if prov is None:
            return
        try:
            tts_on = bool(
                self.context.get_config(umo=event.unified_msg_origin)[
                    "provider_tts_settings"
                ]["enable"]
            )
        except Exception:
            tts_on = False
        if tts_on and not self._warned_double:
            self._warned_double = True
            logger.warning(
                "[EdgeVoice] 整条语音已由本插件处理，请把 AstrBot 的语音总开关关掉"
            )
        if not await SessionServiceManager.should_process_tts_request(event):
            return

        asked = any(
            k in (event.message_str or "")
            for k in (
                "语音",
                "开嗓",
                "开好嗓",
                "念",
                "说一遍",
                "说一句",
                "发语音",
                "语音说",
                "语音回",
                "发条语音",
                "念给我听",
                "说给我听",
                "用声音",
            )
        )
        if not asked:
            return

        texts = [
            c.text.strip()
            for c in result.chain
            if isinstance(c, Plain) and c.text.strip()
        ]
        if not texts:
            return
        full = ""
        for t in (x.strip() for x in "\n".join(texts).splitlines()):
            if not t:
                continue
            if full and full[-1] not in "，。！？、；：～…,.!?;:~":
                full += "，"
            full += t
        if len(full) < 2:
            return
        try:
            path = await prov.get_audio(full)
        except Exception as e:
            logger.warning(f"[EdgeVoice] 整条语音没成，照常发文字：{e}")
            return
        new_chain, placed = [], False
        for c in result.chain:
            if isinstance(c, Plain):
                if not placed:
                    new_chain.append(Record(file=path, url=path, text=full))
                    placed = True
                continue
            new_chain.append(c)
        result.chain = new_chain
