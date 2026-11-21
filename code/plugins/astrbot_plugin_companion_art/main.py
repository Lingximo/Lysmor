import asyncio
import json
import os
import random
import subprocess
import sys
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image, Plain, Video
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

ART_SCRIPT = r"D:\你的数据目录\art\make_art.py"
MOOD_STATE = (
    r"C:\你的用户\.astrbot_launcher\instances"
    r"\<BOT_INSTANCE>\core\data\plugin_data"
    r"\astrbot_plugin_companion_mood\state.json"
)
REWARD_WORDS = (
    "奶茶", "零食", "好吃的", "蛋糕", "带你出去", "带你玩", "买给",
    "加token", "加 token", "加额度", "陪你", "奖励", "好处", "请你",
)
AUTO_IDEAS = (
    ("sitting by the window at night, city lights outside, holding a warm cup, quiet smile", "窗边的夜"),
    ("hugging a round blue whale plush, cozy room, warm lamp, soft smile", "抱鲸鱼"),
    ("standing in a small quiet gallery, framed watercolor paintings, holding a brush", "小画廊"),
    ("curled up on the sofa with a blanket, rainy window, sleepy eyes", "雨天窝着"),
    ("standing on the balcony at dusk, wind in her hair, looking at the city", "傍晚的风"),
)

# 2026-11-07：默认会话（自主画没有 last_origin 时用这个，否则永远不触发）
DEFAULT_ORIGIN = "TA:FriendMessage:<你的QQ号>"
MEMORY_DB = r"D:\你的数据目录\livingmemory\livingmemory.db"

# 记忆关键词 → 画面（画"发生过的事"，不画她自己）
MEMORY_SCENES = (
    ("姜茶", "scene: a cup of ginger tea with brown sugar on a wooden desk, steam rising, warm morning light", "一杯姜茶"),
    ("红糖", "scene: a cup of ginger tea with brown sugar on a wooden desk, steam rising, warm morning light", "红糖姜茶"),
    ("水煮肉片", "scene: a bowl of spicy boiled pork slices with chili oil and vegetables, steaming, on a table", "水煮肉片"),
    ("奶茶", "scene: a cup of milk tea with pearls on a table, afternoon light, condensation", "奶茶"),
    ("面", "scene: a steaming bowl of noodles with chopsticks resting on the rim, warm kitchen light", "一碗面"),
    ("粥", "scene: a bowl of plain congee on a wooden tray, soft morning light", "白粥"),
    ("药", "scene: medicine packets and a glass of warm water on a bedside table, quiet dim light", "药和水"),
    ("西瓜", "scene: sliced watermelon on a plate, summer afternoon light, water droplets", "西瓜"),
    ("雨", "scene: rain running down a window at night, blurred city lights outside", "窗上的雨"),
    ("月亮", "scene: a full moon over a quiet city skyline, cold blue night, few clouds", "月亮"),
    ("医院", "scene: a quiet hospital corridor at night, pale lights, empty chairs", "走廊"),
)


def _recent_memory():
    """从记忆库读最近一条（只读），读不到就返回空串。"""
    try:
        import sqlite3
        con = sqlite3.connect("file:%s?mode=ro" % MEMORY_DB.replace("\\", "/"), uri=True)
        row = con.execute("select text from documents order by id desc limit 1").fetchone()
        con.close()
        return (row[0] if row else "") or ""
    except Exception:
        return ""




class CompanionArt(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.conf = config or {}
        self.busy = False
        self.tasks = set()
        self._auto_task = None
        self.state_dir = os.path.join(
            get_astrbot_plugin_data_path(), "astrbot_plugin_companion_art"
        )
        os.makedirs(self.state_dir, exist_ok=True)
        self.state_path = os.path.join(self.state_dir, "state.json")

    async def initialize(self):
        self._auto_task = asyncio.create_task(self._auto_loop())
        logger.info("[画画] 插件已加载，自主画检查已启动")

    async def terminate(self):
        if self._auto_task:
            self._auto_task.cancel()

    def _load_state(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_state(self, state):
        try:
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.state_path)
        except Exception as exc:
            logger.warning("[画画] 保存状态失败：%r" % (exc,))

    def _mood(self):
        try:
            with open(MOOD_STATE, encoding="utf-8") as f:
                s = json.load(f)
        except Exception:
            return "calm", {}
        v = float(s.get("valence", 0) or 0)
        sad = float(s.get("sadness", 0) or 0)
        anger = float(s.get("anger", 0) or 0)
        fear = float(s.get("fear", 0) or 0)
        if v >= 0.15 and sad < 0.45 and anger < 0.35 and fear < 0.45:
            mood = "good"
        elif v <= -0.12 or sad >= 0.50 or anger >= 0.40 or fear >= 0.50:
            mood = "bad"
        else:
            mood = "calm"
        return mood, s

    def _consent(self, text: str) -> tuple[bool, str]:
        # 生理优先：睡着/没力气/太昏沉时，心情再好也画不动。
        try:
            import sys

            if r"D:\你的数据目录\tools" not in sys.path:
                sys.path.insert(0, r"D:\你的数据目录\tools")
            import vitals

            ok, why = vitals.decide("art")
            if not ok:
                return False, "现在没力气画画……等我缓一缓好不好？"
        except Exception:
            pass
        mood, _ = self._mood()
        reward = any(w in text for w in REWARD_WORDS)
        if mood == "good":
            return True, ""
        if mood == "calm":
            if random.random() < 0.50:
                return False, "现在有点懒得动笔……你要是真想要，哄哄我或者许个好处？"
            return True, ""
        if reward:
            return True, ""
        return False, "现在心情不太好，不想画。你要真想看，得先许诺点好处。"

    async def _send(self, origin: str, chain: MessageChain):
        await self.context.send_message(origin, chain)

    def _qzone(self):
        try:
            for star in self.context.get_all_stars():
                obj = getattr(star, "star_cls", None)
                service = getattr(obj, "service", None) if obj else None
                if service is not None and hasattr(service, "publish_post"):
                    return obj
        except Exception:
            pass
        return None

    async def _post_qzone(self, title: str, image_path: str):
        qzone = self._qzone()
        if qzone is None:
            logger.warning("[画画] 找不到 QQ 空间服务，跳过")
            return
        try:
            with open(image_path, "rb") as f:
                data = f.read()
            text = "今天画了《%s》。" % (title or "一张画")
            await asyncio.wait_for(
                qzone.service.publish_post(text=text, images=[data]),
                timeout=30,
            )
            logger.info("[画画] 已发 QQ 空间：《%s》" % title)
        except Exception as exc:
            logger.warning("[画画] 发 QQ 空间失败：%r" % (exc,))

    async def _draw(self, origin: str, idea: str, title: str, source: str = "qq"):
        if self.busy:
            await self._send(origin, MessageChain([Plain("上一张还在画，等我画完这张。")]))
            return
        self.busy = True
        try:
            if source != "auto":
                await self._send(origin, MessageChain([Plain("好，我去画。先别催，画好了给你看过程。")]))
            proc = await asyncio.to_thread(
                subprocess.run,
                [
                    sys.executable, ART_SCRIPT,
                    "--idea", idea,
                    "--title", title or idea[:24],
                    "--source", source,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
                # 2026-11-10：子进程 stdout 用系统编码（GBK）写，父进程按 UTF-8 读，
                # 标题就变成《????》写进记忆。强制子进程 UTF-8。
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            )
            if proc.returncode != 0:
                logger.error("[画画] 生成失败：%s" % (proc.stderr or proc.stdout)[-800:])
                await self._send(origin, MessageChain([Plain("画到一半卡住了……这次没画成，等下再试。")]))
                return
            lines = [x.strip() for x in (proc.stdout or "").splitlines() if x.strip()]
            item = None
            for line in reversed(lines):
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict) and obj.get("image") and obj.get("process"):
                    item = obj
                    break
            if not item:
                raise RuntimeError("没有解析到画作结果")
            image = item["image"]
            process = item["process"]
            title = item.get("title") or title
            # 2026-11-07：视频发送失败会把整条链路带崩（retcode 1200 EventChecker），
            # 改成：先发成品图，再单独试视频；视频失败只记日志，不影响成品。
            await self._send(origin, MessageChain([Image.fromFileSystem(image),
                                                   Plain("《%s》画好了。" % title)]))
            if os.path.isfile(process):
                try:
                    await self._send(origin, MessageChain([Plain("这是按成品重绘的笔画过程——")]))
                    await self._send(origin, MessageChain([Video.fromFileSystem(process)]))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[画画] 过程视频发送失败，跳过视频：%r" % (exc,))
            await self._post_qzone(title, image)
            try:
                sys.path.insert(0, r"D:\你的数据目录\video")
                import bridge
                bridge.append_pending(
                    "我今天画了一张《%s》：%s" % (title, idea[:200]),
                    0.55,
                    "art",
                )
            except Exception as exc:
                logger.warning("[画画] 写记忆队列失败：%r" % (exc,))
            logger.info("[画画] 完成 %s《%s》" % (item.get("id"), title))
        except asyncio.TimeoutError:
            await self._send(origin, MessageChain([Plain("画太久了，这次先停笔……下次画小一点。")]))
        except Exception as exc:
            logger.error("[画画] 异常：%r" % (exc,))
            try:
                await self._send(origin, MessageChain([Plain("画着画着出错了……这次没画成。")]))
            except Exception:  # noqa: BLE001
                pass
        finally:
            self.busy = False

    def _start(self, origin: str, idea: str, title: str, source: str = "qq"):
        task = asyncio.create_task(self._draw(origin, idea, title, source))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def _remember_origin(self, event: AstrMessageEvent):
        origin = str(getattr(event, "unified_msg_origin", "") or "")
        if not origin:
            return
        state = self._load_state()
        state["last_origin"] = origin
        self._save_state(state)

    def _compose_auto(self, st):
        """按生理 + 记忆选题：画什么由她此刻的状态决定，不再只画自己。"""
        def v(k, d=0.0):
            try:
                return float(st.get(k, d) or d)
            except Exception:
                return d

        hour = time.localtime().tm_hour

        # ① 饥饿 / 口渴 / 疼：身体最先说话
        if v("hunger") > 0.65:
            return ("scene: a steaming bowl of noodles on a wooden desk, chopsticks, warm lamp light, cozy", "想吃东西")
        if v("thirst") > 0.65:
            return ("scene: a glass of water with condensation on a nightstand, soft lamp light", "渴了")
        if v("pain") > 0.55 or v("cramps") > 0.55:
            return ("scene: a hot water bag on a rumpled blanket, warm red-brown palette, dim room", "难受的时候")
        if str(st.get("cycle_phase", "")) in ("menstrual", "period") or v("cramps") > 0.3:
            return ("scene: ginger tea and a hot water bag on a bed, warm tones, soft window light", "那几天")

        # ② 梦里去过的地方
        if str(st.get("dream") or "").strip() and v("dream_residue") > 0.3:
            return ("scene: a strange quiet dreamscape, floating lights, impossible architecture, muted colors", "梦里")

        # ③ 记忆里的一件事（只读最近一条）
        mem = _recent_memory()
        for kw, idea, title in MEMORY_SCENES:
            if kw and kw in mem:
                return (idea, title)

        # ④ 时间与光
        if hour >= 21 or hour < 6:
            return ("scene: city lights through a window at night, quiet street below, cool blue tones", "窗外的夜")
        if 6 <= hour < 9:
            return ("scene: morning sunlight through thin curtains, dust in the air, a desk and a cup", "早上的光")
        if 17 <= hour < 19:
            return ("scene: dusk over a small balcony, potted plants, warm orange sky", "傍晚")

        # ⑤ 兜底：偶尔还是画她自己
        if random.random() < 0.35:
            return random.choice(AUTO_IDEAS)
        return ("scene: a quiet corner of a room, a chair, a book and a cup, afternoon light", "房间一角")

    async def _auto_loop(self):
        """一天两个窗口（10 点、16 点）各检查一次；按心情给概率，不再要求必须 mood=good。"""
        await asyncio.sleep(30)
        while True:
            try:
                now = time.localtime()
                today = time.strftime("%Y-%m-%d", now)
                slot = "am" if 10 <= now.tm_hour < 12 else ("pm" if 16 <= now.tm_hour < 18 else "")
                st = self._load_state()
                done = st.get("auto_slots") or {}
                if slot and done.get(today) != slot and not self.busy:
                    done[today] = slot
                    st["auto_slots"] = done
                    self._save_state(st)
                    mood, full = self._mood()
                    if isinstance(full, dict):
                        st.update(full)
                    p = {"good": 0.60, "calm": 0.40, "bad": 0.25}.get(mood, 0.4)
                    if random.random() < p:
                        idea, title = self._compose_auto(st)
                        origin = st.get("last_origin") or DEFAULT_ORIGIN
                        logger.info("[画画] 自主想画：《%s》 idea=%s" % (title, idea[:60]))
                        self._start(origin, idea, title, "auto")
                    else:
                        logger.info("[画画] 这次窗口不画（mood=%s p=%.2f）" % (mood, p))
            except Exception as exc:
                logger.warning("[画画] 自主检查失败：%r" % (exc,))
            await asyncio.sleep(300)

    @filter.llm_tool(name="draw_picture")
    async def draw_picture(self, event: AstrMessageEvent, idea: str, title: str = ""):
        """对方让你画画（画一张、画个、给我画）时调用。你可以自己决定画什么，但要把画面写成英文 booru 标签，方便模型画准。会按当前心情决定答不答应：心情好会同意，平静可能拒绝，心情差要对方许诺具体好处才画。画完后成品和笔画过程会自动发到当前私聊；你只要先回一两句很短的话，不要描述完整画面，也不要说“我画好了”直到图片真的发出去。

        Args:
            idea(string): 画面描述，尽量用英文 booru 标签，例如 "1girl, sitting by a window, city night, holding a cup"；不要写“画一张”这种指令。
            title(string): 中文短标题，例如“窗边夜灯”，不要超过 12 个字。
        """
        if not event.is_private_chat():
            return "只给你画，群里不画。"
        if not idea.strip():
            return "没说要画什么呀。"
        self._remember_origin(event)
        ok, refusal = self._consent(event.message_str or "")
        if not ok:
            return refusal
        self._start(event.unified_msg_origin, idea.strip(), title.strip(), "qq")
        return "好，我去画，画好了把过程发你。"

    @filter.command("画")
    async def draw_command(self, event: AstrMessageEvent):
        if not event.is_private_chat():
            await self._send(event.unified_msg_origin, MessageChain([Plain("只给你画，群里不画。")]))
            return
        self._remember_origin(event)
        text = (event.message_str or "").strip()
        for prefix in ("/画", "画"):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                break
        if not text:
            await self._send(event.unified_msg_origin, MessageChain([Plain("要画什么呀？说具体一点。")]))
            return
        ok, refusal = self._consent(text)
        if not ok:
            await self._send(event.unified_msg_origin, MessageChain([Plain(refusal)]))
            return
        self._start(event.unified_msg_origin, text, "一张画", "qq")
