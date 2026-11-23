import asyncio
import importlib
import json
import os
import sys
import time

sys.path.insert(0, r"D:\你的数据目录\video")
try:
    import pending_store
except Exception:
    pending_store = None

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

VIDEO_RECENT = r"D:\你的数据目录\video\video_recent.json"
QQ_RECENT = r"D:\你的数据目录\video\qq_recent.json"
PENDING = r"D:\你的数据目录\video\pending_memories.json"
STATUS = r"D:\你的数据目录\video\memory_sync_status.json"
TARGET = "TA:FriendMessage:<你的QQ号>"
MARKER = "【你们刚在视频通话里聊过"
_task = None


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


PENDING_KEEP = 200   # 待总结的对话要留得住


def _save(path, items, keep=12):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items[-keep:], f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _write_status(data):
    try:
        tmp = STATUS + "." + str(os.getpid()) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATUS)
    except Exception:
        pass


NAILS_MARK = "[钉子]"


def _ingest_nails(text, req):
    """把用户说的话喂进钉子账本，并把钉子常驻注入这次请求。失败静默。"""
    try:
        tools = r"D:\你的数据目录\tools"
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import nails as _nails
        _nails.ingest(text, who="user")
        block = _nails.nails_block()
        if block and NAILS_MARK not in (getattr(req, "system_prompt", "") or ""):
            base = getattr(req, "system_prompt", "") or ""
            req.system_prompt = (base + "\n\n" + NAILS_MARK + " " + block).strip()
    except Exception:
        pass


class VideoBridge(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)

    async def initialize(self):
        global _task
        if _task and not _task.done():
            return
        _task = asyncio.create_task(self._loop())
        logger.info("[视频桥] 已启动：最近上下文 + 视频结束写长期记忆")

    async def terminate(self):
        global _task
        if _task and not _task.done():
            _task.cancel()
        _task = None

    def _memory_engine(self):
        for star in self.context.get_all_stars():
            star_obj = getattr(star, "star_cls", None)
            init = getattr(star_obj, "initializer", None)
            engine = getattr(init, "memory_engine", None) if init else None
            if engine is not None and getattr(engine, "index_writer", None):
                return engine
        return None

    def _memory_processor(self):
        for star in self.context.get_all_stars():
            star_obj = getattr(star, "star_cls", None)
            init = getattr(star_obj, "initializer", None)
            processor = getattr(init, "memory_processor", None) if init else None
            if processor is not None:
                return processor
        return None

    def _make_messages(self, turns):
        mod = importlib.import_module(
            "data.plugins.astrbot_plugin_livingmemory.core.models.conversation_models"
        )
        Message = mod.Message
        out = []
        for idx, turn in enumerate(turns, 1):
            role = turn.get("role")
            content = (turn.get("content") or "").strip()
            if role not in ("user", "assistant") or not content:
                continue
            is_user = role == "user"
            out.append(
                Message(
                    id=idx,
                    session_id=TARGET,
                    role=role,
                    content=content,
                    sender_id="<你的QQ号>" if is_user else "<你的QQ号2>",
                    sender_name="你" if is_user else "TA",
                    platform="aiocqhttp",
                    timestamp=time.time(),
                )
            )
        return out

    MOOD_STATE = ("C:/你的用户/.astrbot_launcher/instances/"
                  "<BOT_INSTANCE>/core/data/plugin_data/"
                  "astrbot_plugin_companion_mood/state.json")

    def _mood_snapshot(self, importance=0.5):
        try:
            with open(self.MOOD_STATE, encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            return None
        snap = {
            "emotion": str(st.get("emotion_type") or ""),
            "valence": round(float(st.get("valence") or 0), 3),
            "energy": round(float(st.get("energy") or 0), 3),
            "hunger": round(float(st.get("hunger") or 0), 3),
            "thirst": round(float(st.get("thirst") or 0), 3),
            "irritability": round(float(st.get("irritability") or 0), 3),
            "clinginess": round(float(st.get("clinginess") or 0), 3),
            "loneliness": round(float(st.get("loneliness") or 0), 3),
            "scar": round(float(st.get("scar") or 0), 3),
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        # --- 情绪真实化 Phase A：情绪混色 + 命运 + 深度（只记不改）---
        try:
            blend = st.get("emotion_blend") or []
            if isinstance(blend, list):
                snap["emotion_blend"] = [
                    {"key": str(b.get("key") or ""), "weight": round(float(b.get("weight") or 0), 3)}
                    for b in blend if isinstance(b, dict)
                ]
        except Exception:  # noqa: BLE001
            pass
        try:
            imp = float(importance)
            val = float(st.get("valence") or 0)
            scar = float(st.get("scar") or 0)
            sadness = float(st.get("sadness") or 0)
            snap["depth"] = round(min(1.0, max(0.0, 0.6 * imp + 0.3 * abs(val) + 0.1 * scar)), 3)
            if val <= -0.25 and (imp >= 0.6 or scar >= 0.3 or sadness >= 0.4):
                snap["fate"] = "敏化"
            elif val >= 0.25 and imp >= 0.5:
                snap["fate"] = "回味"
            else:
                snap["fate"] = "习惯化"
        except Exception:  # noqa: BLE001
            pass
        return snap

    async def _flush_pending(self):
        items = pending_store.load(PENDING) if pending_store is not None else _load(PENDING)
        if not items:
            return
        if len(items) >= 50:
            logger.warning(f"[视频桥] 待处理队列积压 {len(items)} 条，正在消化")
        engine = self._memory_engine()
        status = {
            "at": time.time(),
            "queue": len(items),
            "engine": engine is not None,
            "processed": 0,
            "failed": 0,
            "dropped": 0,
            "last": None,
            "last_error": "",
        }
        if engine is None:
            status["last_error"] = "memory_engine_not_ready"
            _write_status(status)
            return
        processor = self._memory_processor()
        processed = []
        failed = []
        for item in items[:3]:
            key = pending_store.item_id(item) if pending_store is not None else str(item.get("time"))
            try:
                importance = float(item.get("importance", 0.6))
            except Exception:
                importance = 0.6
            summary = (item.get("summary") or "").strip()
            try:
                if item.get("messages"):
                    if processor is None:
                        raise RuntimeError("记忆处理器还没准备好")
                    messages = self._make_messages(item["messages"])
                    if not messages:
                        status["dropped"] += 1
                        status["last"] = {"type": "messages", "dropped": "empty_messages"}
                        processed.append(key)
                        logger.warning("[视频桥] 跳过一条空对话记忆")
                        continue
                    content, metadata, auto_importance = await processor.process_conversation(
                        messages, persona_id="伴侣"
                    )
                    metadata = dict(metadata or {})
                    metadata.update({
                        "source": item.get("source") or "video_call",
                        "create_time": item.get("time") or time.time(),
                    })
                    if not metadata.get("mood_snapshot"):
                        snap = item.get("mood_snapshot") or self._mood_snapshot(auto_importance)
                        if snap:
                            metadata["mood_snapshot"] = snap
                    doc_id = await engine.add_memory(
                        content,
                        session_id=TARGET,
                        persona_id="伴侣",
                        importance=max(0.0, min(1.0, float(auto_importance))),
                        metadata=metadata,
                    )
                    preview = (content or "")[:180]
                else:
                    if not summary:
                        status["dropped"] += 1
                        status["last"] = {"type": "summary", "dropped": "empty_summary"}
                        processed.append(key)
                        logger.warning("[视频桥] 跳过一条空记忆条目")
                        continue
                    doc_id = await engine.add_memory(
                        summary,
                        session_id=TARGET,
                        persona_id="伴侣",
                        importance=importance,
                        metadata={
                            "source": item.get("source") or "video_call",
                            "memory_type": "episode",
                            "create_time": item.get("time") or time.time(),
                            "mood_snapshot": item.get("mood_snapshot") or self._mood_snapshot(importance),
                        },
                    )
                    preview = summary[:180]
                logger.info(f"[视频桥] 记忆已写入：{doc_id}")
                status["processed"] += 1
                status["last"] = {
                    "type": "messages" if item.get("messages") else "summary",
                    "summary": preview,
                    "source": item.get("source") or "video_call",
                    "doc_id": str(doc_id),
                    "at": time.time(),
                }
                processed.append(key)
            except Exception as exc:
                logger.warning(f"[视频桥] 写入长期记忆失败，保留重试：{exc}")
                status["failed"] += 1
                status["last_error"] = str(exc)[:300]
                failed.append(item)
        if pending_store is not None:
            if processed:
                pending_store.remove_ids(processed, PENDING)
            status["queue_after"] = len(pending_store.load(PENDING))
        else:
            remaining = failed + items[3:]
            _save(PENDING, remaining, PENDING_KEEP)
            status["queue_after"] = len(remaining)
        status["at"] = time.time()
        _write_status(status)

    async def _loop(self):
        await asyncio.sleep(12)
        while True:
            try:
                await self._flush_pending()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning(f"[视频桥] 轮询失败：{exc}")
            await asyncio.sleep(20)

    @filter.on_llm_request(priority=50000)
    async def inject_video_context(self, event: AstrMessageEvent, req):
        if event.unified_msg_origin != TARGET:
            return
        text = (event.message_str or "").strip()
        if not text:
            return
        event.set_extra("_video_bridge_user", text[:200])
        _ingest_nails(text, req)
        items = _load(VIDEO_RECENT)[-4:]
        if not items:
            return
        lines = []
        for item in items:
            u = (item.get("user") or "").strip()
            b = (item.get("bot") or "").strip()
            if u:
                lines.append(f"你：{u[:120]}")
            if b:
                lines.append(f"TA：{b[:160]}")
        if not lines:
            return
        block = (
            MARKER
            + "，只作参考，不要提“同步/桥接”】\n"
            + "\n".join(lines)
        )
        base = getattr(req, "system_prompt", "") or ""
        if MARKER not in base:
            req.system_prompt = (base + "\n\n" + block).strip()
            logger.debug("[视频桥] 已注入最近视频上下文")

    @filter.on_llm_response(priority=50000)
    async def save_qq_context(self, event: AstrMessageEvent, resp):
        if event.unified_msg_origin != TARGET:
            return
        user = event.get_extra("_video_bridge_user")
        text = getattr(resp, "completion_text", None)
        if not user or not isinstance(text, str) or not text.strip():
            return
        event.set_extra("_video_bridge_user", None)
        items = _load(QQ_RECENT)
        items.append(
            {"time": time.time(), "user": str(user)[:200], "bot": text.strip()[:300]}
        )
        _save(QQ_RECENT, items)
        logger.debug("[视频桥] 已记录最近 QQ 上下文")
