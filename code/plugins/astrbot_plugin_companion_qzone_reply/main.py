import asyncio
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
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

OWNER = "<你的QQ号>"
BOT = "<你的QQ号2>"
PENDING = r"D:\你的数据目录\video\pending_memories.json"
TASK = None
MAX_REPLY_PER_ROUND = 3


class CompanionQzoneReply(Star):
    """你在空间评论/回复她之后，TA再回一条。

    触发条件（两条都算）：
      1. TA自己的说说下，你留了评论（不管是顶楼还是回复她）；
      2. 你的说说下，你回复了TA之前的评论。
    只处理插件启动之后的新评论，靠 seen 去重，重启也不会重复回。
    """

    def __init__(self, context: Context):
        super().__init__(context)
        self.dir = os.path.join(
            get_astrbot_plugin_data_path(), "astrbot_plugin_companion_qzone_reply"
        )
        os.makedirs(self.dir, exist_ok=True)
        self.state_path = os.path.join(self.dir, "state.json")
        self.started = time.time()
        self.meta = {}
        self.seen = self._load()

    # ------------------------------------------------------------ 状态
    def _load(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            self.meta = {k: v for k, v in data.items() if k != "seen"}
            return set(data.get("seen") or [])
        except Exception:
            self.meta = {}
            return set()

    def _save(self):
        try:
            payload = dict(self.meta)
            payload["seen"] = sorted(self.seen)[-500:]
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except Exception:
            pass

    def _qzone(self):
        for star in self.context.get_all_stars():
            obj = getattr(star, "star_cls", None)
            service = getattr(obj, "service", None) if obj else None
            if service is not None and hasattr(service, "reply_comment"):
                return service
        return None

    def _queue_memory(self, summary, importance=0.7):
        if pending_store is not None:
            try:
                pending_store.append({
                    "summary": summary,
                    "importance": importance,
                    "source": "qzone_reply",
                })
                return
            except Exception as exc:
                logger.warning(f"[空间回评] 写记忆队列失败：{exc}")
                return
        try:
            try:
                with open(PENDING, encoding="utf-8") as f:
                    items = json.load(f)
            except Exception:
                items = []
            if not isinstance(items, list):
                items = []
            items.append({
                "summary": summary,
                "importance": importance,
                "source": "qzone_reply",
                "time": time.time(),
            })
            with open(PENDING, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning(f"[空间回评] 写记忆队列失败：{exc}")

    # ------------------------------------------------------------ 取说说
    async def _gather_posts(self, service):
        uin = await service.session.get_uin()
        posts = []
        # 她自己的空间（主要来源）
        try:
            posts.extend(
                await service.query_feeds(target_id=str(uin), num=8, with_detail=True)
            )
        except Exception as exc:
            logger.debug(f"[空间回评] 自己的空间读取失败：{exc}")
        # 好友动态（你的说说可能在这里）
        try:
            posts.extend(await service.query_feeds(num=10, with_detail=True))
        except Exception as exc:
            logger.debug(f"[空间回评] 好友动态读取失败：{exc}")
        # 按 tid 去重
        unique, tids = [], set()
        for p in posts:
            tid = getattr(p, "tid", None)
            if not tid or tid in tids:
                continue
            tids.add(tid)
            unique.append(p)
        return unique

    # ------------------------------------------------------------ 判定
    def _should_reply(self, post, comment, bot_tids):
        """要不要回这条评论。

        以前只认"你"：别人在她说说下面留言，她一声不吭，看起来像不会回评论。
        现在改成：她自己的说说下，任何人（除了她自己）的新评论都回；
        别人的说说下，只有你回复了她才回。
        """
        if int(comment.uin) == BOT:
            return False
        if comment.create_time < self.started - 24 * 3600:
            return False
        parent = int(comment.parent_tid or 0)
        replied_to_bot = bool(parent and parent in bot_tids)
        on_her_post = int(post.uin) == BOT
        dad_replied_me = int(comment.uin) == OWNER and replied_to_bot
        return bool(on_her_post or dad_replied_me)

    async def _check(self):
        # 身体是前提：睡着了、累趴下的时候，她不该半夜还在空间里回评论。
        # 拿不到状态就放行（vitals 内部 fail-open），别把功能整个封死。
        try:
            sys.path.insert(0, r"D:\你的数据目录\tools")
            import vitals
            ok, why = vitals.decide("qzone_reply")
            if not ok:
                logger.info(f"[空间回评] 这轮不动：{why}")
                return
        except Exception as exc:
            logger.debug(f"[空间回评] 生理闸门不可用，照常跑：{exc}")

        service = self._qzone()
        if service is None:
            logger.warning("[空间回评] 找不到 QQ 空间服务，跳过本轮")
            return

        posts = await self._gather_posts(service)
        if not posts:
            logger.debug("[空间回评] 本轮没读到说说")
            return

        if not getattr(self, "_logged_read", False):
            self._logged_read = True
            logger.info(f"[空间回评] 已读到 {len(posts)} 条说说，正在等你的新评论")

        replied = 0
        for post in posts:
            if replied >= MAX_REPLY_PER_ROUND:
                break
            try:
                comments = list(post.comments or [])
                if not comments:
                    continue
                bot_tids = {
                    int(c.tid) for c in comments if int(c.uin) == BOT and c.tid
                }
                others = [c for c in comments if int(c.uin) != BOT]
                for c in comments:
                    if replied >= MAX_REPLY_PER_ROUND:
                        break
                    if not self._should_reply(post, c, bot_tids):
                        continue
                    key = f"{post.tid}:{c.tid}"
                    if key in self.seen:
                        continue
                    try:
                        idx = others.index(c)
                    except ValueError:
                        continue

                    await service.reply_comment(post, idx)
                    self.seen.add(key)
                    self._save()
                    replied += 1

                    said = (getattr(c, "plain_content", "") or "")[:80]
                    summary = (
                        f"你在QQ空间回复了TA的评论：「{said}」，"
                        f"TA又回了他一条。"
                    )
                    self._queue_memory(summary)
                    logger.info(f"[空间回评] 已回复 {key}：{said}")
            except Exception as exc:
                logger.warning(f"[空间回评] 处理说说 {getattr(post, 'tid', '?')} 失败：{exc}")

        if replied:
            logger.info(f"[空间回评] 本轮回复了 {replied} 条")

        # 回完评论，再去看你有没有发新的说说（她主动去评论一句）
        try:
            await self._comment_dad_posts(service, posts)
        except Exception as exc:
            logger.warning(f"[空间回评] 看你的说说失败：{exc}")

    # ------------------------------------------------------------ 去你的说说下评论
    async def _comment_dad_posts(self, service, posts):
        """你发了新的说说 → 她主动去评论一句（并点个赞）。

        以前完全没有这条路：她只会在"你先评论她"之后再回，
        所以看起来像"不会在你的帖子里说话"。
        限制：只认你、只认 24 小时内的、每条只评论一次、两次之间至少 25 分钟。
        """
        if time.time() - float(self.meta.get("last_comment") or 0) < 25 * 60:
            return 0
        done = 0
        for post in posts:
            if done >= 1:
                break
            try:
                if int(post.uin) != OWNER:
                    continue
                age = time.time() - float(post.create_time or 0)
                if age > 24 * 3600 or age < 0:
                    continue
                if any(int(c.uin) == BOT for c in (post.comments or [])):
                    continue          # 已经评论过了
                key = "c:{}".format(post.tid)
                if key in self.seen:
                    continue

                await service.comment_posts(post)
                done += 1
                self.seen.add(key)
                self.meta["last_comment"] = time.time()
                self._save()

                said = ""
                if post.comments:
                    said = (getattr(post.comments[-1], "content", "") or "")[:60]
                text = (post.text or "")[:40]
                self._queue_memory(
                    "你在空间发了说说「{}」，TA去他下面评论了一句：{}".format(text, said),
                    importance=0.65,
                )
                logger.info("[空间回评] 已去你的说说下评论：{}".format(said))
                try:
                    await service.like_posts(post)
                except Exception:
                    pass
            except Exception as exc:
                logger.warning("[空间回评] 评论你的说说失败：{}".format(exc))
        return done

    # ------------------------------------------------------------ 生命周期
    async def initialize(self):
        global TASK
        logger.info("[空间回评] 已启用：你在空间评论/回复后，TA再回一条")
        if not TASK or TASK.done():
            TASK = asyncio.create_task(self._loop())

    async def terminate(self):
        global TASK
        if TASK and not TASK.done():
            TASK.cancel()
        TASK = None

    async def _loop(self):
        await asyncio.sleep(45)
        while True:
            try:
                await self._check()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning(f"[空间回评] 轮询失败：{exc}")
            await asyncio.sleep(600)
