import asyncio
import base64
import io
import json
import re
import sys
import time

sys.path.insert(0, r"D:\你的数据目录\video")
try:
    import pending_store
except Exception:
    pending_store = None

import aiohttp
from PIL import Image as PILImage

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.message.components import Image, Plain

OLLAMA = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3-vl:4b"
TARGET = "TA:FriendMessage:<你的QQ号>"

PROMPT = """你是食物品尝器。看这张图片，只输出 JSON，不要解释：
{"is_food":true/false,"name":"食物名称","taste":["味道词"],"temperature":"冰/热/常温","texture":"口感",
"sweet":0到1,"sour":0到1,"bitter":0到1,"salty":0到1,"umami":0到1,"spicy":0到1}
如果图片不是食物，is_food 为 false，其他字段留空。"""

LIKE_WORDS = ("奶茶", "蛋糕", "冰淇淋", "冰淇淋", "巧克力", "草莓", "甜品", "布丁", "糖果", "饼干", "牛奶")
DISLIKE_WORDS = ("苦瓜", "香菜", "辣椒", "火锅", "麻辣", "苦", "酸", "芥末", "洋葱")

FOOD_HINTS = {
    "珍珠奶茶": {"name": "珍珠奶茶", "taste": ["甜", "奶香", "茶香"], "temperature": "冰", "texture": "珍珠Q弹", "sweet": 0.8, "umami": 0.2},
    "奶茶": {"name": "奶茶", "taste": ["甜", "奶香"], "temperature": "冰", "texture": "顺滑", "sweet": 0.75},
    "蛋糕": {"name": "蛋糕", "taste": ["甜", "奶香"], "temperature": "常温", "texture": "松软", "sweet": 0.8},
    "冰淇淋": {"name": "冰淇淋", "taste": ["甜", "奶香"], "temperature": "冰", "texture": "冰凉绵密", "sweet": 0.85},
    "火锅": {"name": "火锅", "taste": ["辣", "咸", "鲜"], "temperature": "热", "texture": "滚烫", "spicy": 0.85, "salty": 0.6, "umami": 0.6},
    "烧烤": {"name": "烧烤", "taste": ["咸", "香", "辣"], "temperature": "热", "texture": "焦香", "spicy": 0.45, "salty": 0.65, "umami": 0.7},
    "炸鸡": {"name": "炸鸡", "taste": ["咸", "香"], "temperature": "热", "texture": "酥脆", "salty": 0.6, "umami": 0.7},
    "泡面": {"name": "泡面", "taste": ["咸", "鲜"], "temperature": "热", "texture": "软滑", "salty": 0.7, "umami": 0.6},
    "草莓": {"name": "草莓", "taste": ["甜", "酸"], "temperature": "常温", "texture": "多汁", "sweet": 0.6, "sour": 0.35},
    "水果": {"name": "水果", "taste": ["甜", "清爽"], "temperature": "常温", "texture": "多汁", "sweet": 0.55, "sour": 0.2},
}


def _hint_from_text(text):
    text = text or ""
    hits = [k for k in FOOD_HINTS if k in text]
    return max(hits, key=len) if hits else ""


def _fallback_profile(name):
    data = dict(FOOD_HINTS.get(name) or {})
    data["is_food"] = True
    data.setdefault("name", name or "这样食物")
    data.setdefault("taste", [])
    data.setdefault("sweet", 0.25)
    return data


def _queue_memory(effect):
    summary = (
        f"你给TA尝了{effect.get('name')}：{effect.get('desc')}。"
        f"TA的感受：{effect.get('feel')}。"
    )
    if pending_store is not None:
        try:
            pending_store.append({"summary": summary, "importance": 0.55, "source": "taste"})
            return
        except Exception as exc:
            logger.warning(f"[品尝] 写记忆队列失败：{exc}")
            return
    path = r"D:\你的数据目录\video\pending_memories.json"
    try:
        try:
            with open(path, encoding="utf-8") as f:
                items = json.load(f)
        except Exception:
            items = []
        if not isinstance(items, list):
            items = []
        items.append({
            "summary": summary,
            "importance": 0.55,
            "source": "taste",
            "time": time.time(),
        })
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning(f"[品尝] 写记忆队列失败：{exc}")


def _json_from_text(text):
    text = (text or "").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _num(value):
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def _shrink_b64(b64):
    try:
        raw = base64.b64decode(b64)
        image = PILImage.open(io.BytesIO(raw)).convert("RGB")
        image.thumbnail((1280, 1280), PILImage.LANCZOS)
        out = io.BytesIO()
        image.save(out, "JPEG", quality=88, optimize=True)
        return base64.b64encode(out.getvalue()).decode()
    except Exception:
        return b64


class CompanionTaste(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)

    async def _look(self, image: Image, hint: str = ""):
        try:
            b64 = await image.convert_to_base64()
        except Exception as exc:
            logger.warning(f"[品尝] 读取图片失败：{exc}")
            return None
        if b64.startswith("data:"):
            b64 = b64.split(",", 1)[-1]
        b64 = _shrink_b64(b64)
        logger.info(f"[品尝] 图片已压缩，base64 {len(b64) // 1024} KB")
        prompt = PROMPT
        if hint:
            prompt += (
                f"\n你说这是：{hint}。以你说的名称为准，"
                "图片只用来判断甜度、温度、口感和辣度。"
            )
        payload = {
            "model": MODEL,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "format": "json",
            "keep_alive": "24h",   # 2026-11-07：30 分钟就卸载 → 每条图要冷加载 50 秒，改成常驻
            "options": {
                "temperature": 0.1,
                "num_predict": 600,
                "repeat_penalty": 1.1,
                "repeat_last_n": 64,
            },
        }
        for attempt in range(1, 3):
            try:
                timeout = aiohttp.ClientTimeout(total=120)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(OLLAMA, json=payload) as resp:
                        data = await resp.json(content_type=None)
                raw = data.get("response") or ""
                result = _json_from_text(raw)
                if result:
                    return result
                logger.warning(
                    f"[品尝] 第 {attempt} 次模型返回为空/非 JSON："
                    f"resp={raw[:200]!r} err={str(data.get('error'))[:200]!r}"
                )
            except Exception as exc:
                logger.warning(f"[品尝] 第 {attempt} 次视觉模型失败：{exc}")
            await asyncio.sleep(2)
        return None

    def _effect(self, data):
        name = str(data.get("name") or "这样食物").strip()
        sweet = _num(data.get("sweet"))
        sour = _num(data.get("sour"))
        bitter = _num(data.get("bitter"))
        salty = _num(data.get("salty"))
        umami = _num(data.get("umami"))
        spicy = _num(data.get("spicy"))
        taste = data.get("taste") or []
        if isinstance(taste, str):
            taste = [taste]
        taste = [str(x) for x in taste if str(x).strip()][:4]
        temperature = str(data.get("temperature") or "").strip()
        texture = str(data.get("texture") or "").strip()

        preference = 0.0
        if sweet > 0.45:
            preference += 0.26
        if umami > 0.55:
            preference += 0.12
        if bitter > 0.4:
            preference -= 0.3
        if spicy > 0.55:
            preference -= 0.24
        if sour > 0.7:
            preference -= 0.10
        if any(w in name for w in LIKE_WORDS):
            preference += 0.28
        if any(w in name for w in DISLIKE_WORDS):
            preference -= 0.28
        preference = max(-1.0, min(1.0, preference))

        deltas = {
            "dopamine": 0.08 + max(0.0, preference) * 0.12 - max(0.0, -preference) * 0.04,
            "oxytocin": 0.05 if sweet > 0.4 or umami > 0.5 else 0.0,
            "serotonin": 0.08 if preference > 0.1 else (-0.07 if preference < -0.1 else 0.0),
            "cortisol": 0.12 if preference < -0.1 else (0.08 if spicy > 0.55 else 0.0),
            "noradrenaline": 0.10 if spicy > 0.5 else 0.0,
        }
        desc = []
        if taste:
            desc.append("、".join(taste))
        if temperature:
            desc.append(temperature)
        if texture:
            desc.append(texture)
        if spicy > 0.55:
            desc.append("有点辣")
        if bitter > 0.45:
            desc.append("有点苦")
        if sweet > 0.5:
            desc.append("甜甜的")
        if preference > 0.15:
            feel = "很合胃口，吃得很开心"
            emotion_label = "开心！"
        elif preference < -0.15:
            feel = "不太合胃口，有点委屈/抗拒"
            emotion_label = "有点委屈…"
        elif spicy > 0.55:
            feel = "被辣到了，嘴里热热的"
            emotion_label = "辣得吸气！"
        else:
            feel = "味道还行，没什么特别"
            emotion_label = "嗯…还行"

        if any(w in name for w in ("奶茶", "咖啡", "果汁", "饮料")):
            hunger_reduction = 0.16
        elif any(w in name for w in ("蛋糕", "冰淇淋", "甜品", "巧克力")):
            hunger_reduction = 0.24
        elif any(w in name for w in ("饭", "面", "粉", "火锅", "烧烤", "炸鸡", "汉堡")):
            hunger_reduction = 0.44
        else:
            hunger_reduction = 0.30

        return {
            "name": name,
            "desc": "，".join(desc) or "尝到了味道",
            "feel": feel,
            "emotion_label": emotion_label,
            "hunger_reduction": hunger_reduction,
            "preference": round(preference, 2),
            "deltas": {k: round(v, 3) for k, v in deltas.items()},
        }

    @filter.on_llm_request(priority=200000)
    async def taste_food(self, event: AstrMessageEvent, req):
        if event.unified_msg_origin != TARGET:
            return
        if event.get_extra("_taste_done"):
            return
        text = event.message_str or ""
        hint = _hint_from_text(text)
        try:
            images = [c for c in event.message_obj.message if isinstance(c, Image)]
        except Exception:
            images = []
        if not images:
            if hint and any(k in text for k in ("尝", "吃", "喝", "给你", "试试", "喂")):
                event.set_extra("_taste_done", True)
                data = _fallback_profile(hint)
                logger.info(f"[品尝] 没有图片，按文字里的「{hint}」兜底")
            else:
                return
        else:
            event.set_extra("_taste_done", True)
            data = None
            for image in images[:2]:
                try:
                    data = await asyncio.wait_for(self._look(image, hint), timeout=12)
                except asyncio.TimeoutError:
                    logger.warning("[品尝] 识别超过 12 秒，跳过不等了（避免拖慢回复）")
                    data = None
                if data and str(data.get("is_food")).lower() in ("true", "yes", "1"):
                    break
            if not data or not (
                data.get("is_food") is True
                or str(data.get("is_food")).lower() in ("true", "yes", "1")
            ):
                if hint:
                    data = _fallback_profile(hint)
                    logger.info(f"[品尝] 图片没认准，按你说的「{hint}」兜底")
                else:
                    logger.info("[品尝] 这张不是可辨认的食物，跳过")
                    return
        effect = self._effect(data)
        event.set_extra("_companion_taste", effect)
        event.set_extra("_taste_emotion_label", effect.get("emotion_label"))
        block = (
            "【你刚尝了你发的食物】\n"
            f"食物：{effect['name']}\n"
            f"味道：{effect['desc']}\n"
            f"你的感觉：{effect['feel']}。\n"
            "用一两句真实的反应回答你，不要提图片识别、模型、系统；"
            "喜欢就表现开心，不喜欢可以皱眉头、撒娇或直说。"
            "这次一定要回应这次品尝，至少说一句，不要沉默。"
        )
        base = getattr(req, "system_prompt", "") or ""
        if "【你刚尝了你发的食物】" not in base:
            req.system_prompt = (base + "\n\n" + block).strip()
        logger.info(f"[品尝] {effect['name']} / {effect['desc']} / {effect['feel']}")
        _queue_memory(effect)

    @filter.on_decorating_result(priority=80000)
    async def append_emotion(self, event: AstrMessageEvent):
        label = event.get_extra("_taste_emotion_label")
        if not label:
            return
        result = event.get_result()
        if result is None or not getattr(result, "chain", None):
            return
        plains = [c for c in result.chain if isinstance(c, Plain) and c.text.strip()]
        if not plains:
            return
        target = plains[-1]
        if label not in target.text:
            target.text = target.text.rstrip("。！？!?~～，, ") + "，" + str(label)
        event.set_extra("_taste_emotion_label", None)

