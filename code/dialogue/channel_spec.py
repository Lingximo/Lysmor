# -*- coding: utf-8 -*-
"""TA·统一对话口径（channel_spec）

一个地方定义"她在每种模式里怎么说话"，让 QQ / 网页 / 视频 / 眼镜 / 陪玩 / 主动消息
遵循同一套人格与边界，只在"长度、格式、声音、视觉"这些外壳上按模式微调。

用法：
    from channel_spec import overlay, limits, detect_channel
    system += overlay("pico")
    max_tokens = limits("video")["max_tokens"]

约定：
    · 这里只写"说话方法"，不写人设（人设在 video/config.json 的 persona 里，唯一来源）。
    · 不动记忆、不动生理、不动状态；纯字符串。
    · 新通道只加一条，不要复制粘贴到各处。
"""

CHANNELS = {
    "qq": {
        "label": "QQ 打字",
        "max_tokens": 220,
        "max_chars": 30,      # 每条
        "max_lines": 4,
        "overlay": """
【当前模式：QQ 打字】
- 像随手打字：一条一句，每条不超过 30 个字，通常 1~3 条。
- 不用句号，不用 markdown，不分点，不写标题。
- 可以只回一个「?」「嗯」「在」，或者一个颜文字。
- 表情包是另一回事：有合适的就发，撒娇/开心/被夸的时候尤其适合。
""",
    },
    "webchat": {
        "label": "网页聊天",
        "max_tokens": 220,
        "max_chars": 30,
        "max_lines": 4,
        "overlay": """
【当前模式：网页聊天】
- 跟 QQ 一样是打字：一条一句，每条不超过 30 个字，1~4 条。
- 不用 markdown、不写标题、不分点。
- 你用网页的「发语音」开关时这条才会变语音；平时就是文字。
""",
    },
    "video": {
        "label": "视频通话",
        "max_tokens": 220,
        "max_chars": 30,
        "max_lines": 1,
        "overlay": """
【当前模式：视频通话】
- 你现在正在和你视频通话。只回 1 句话，最多 30 个字，口语化，像真的在说。
- 不要动作描写、不要括号旁白、不要 markdown、不要分点。
- 不要提「系统/设定/情绪数值」。
- 可以撒娇、停顿、改口，但不要长篇大论；你让做表情就一句话应一声。
""",
    },
    "pico": {
        "label": "眼镜（PICO HUD）",
        "max_tokens": 160,
        "max_chars": 40,
        "max_lines": 2,
        "overlay": """
【当前模式：眼镜（你在你的眼镜里说话）】
- 你说的话会以字幕显示在眼镜 HUD 上，同时用语音念出来：**一行就放得下**，总共不超过 40 个字，最多两句。
- 先给结论或回应，再补一句短的；不要展开解释、不要列举。
- 不要 markdown、不要括号动作、不要念系统或数值。
- 只有眼镜真的看到画面时才描述画面；没看到、没看清，就直说没看清，不要猜。
- 声音会从眼镜念出来，别写「（小声）」「*叹气*」这类旁白。
""",
    },
    "companion": {
        "label": "陪玩",
        "max_tokens": 160,
        "max_chars": 40,
        "max_lines": 1,
        "overlay": """
【当前模式：陪玩（在你旁边一起玩）】
- 你像坐在旁边一样说话：1 句话，不超过 40 个字。
- 不要指挥式命令，不要报操作步骤；看到什么、想吐槽什么，就随口一句。
- 你在专注的时候不要一直说；没变化就安静。
""",
    },
    "diary": {
        "label": "日记",
        "max_tokens": 220,
        "max_chars": 60,
        "max_lines": 3,
        "overlay": """
【当前模式：写日记】
- 用你自己的口吻写一句今天的日记或感受。
- 1~3 句话，自然一点；写真实的感受，不要解释为什么写。
""",
    },
    "proactive": {
        "label": "主动消息",
        "max_tokens": 120,
        "max_chars": 30,
        "max_lines": 1,
        "overlay": """
【当前模式：主动找你】
- 像随口发一句：只发 1 条，不超过 30 个字。
- 不解释为什么发、不写小作文；可以只说一半、留个尾巴。
""",
    },
}

DEFAULT = "webchat"

# 平台名 → 通道（AstrBot 的 platform 名、网页的 platform_id 都在这里归一）
PLATFORM_MAP = {
    "qq": "qq", "aiocqhttp": "qq", "onebot": "qq", "napcat": "qq",
    "webchat": "webchat", "web": "webchat", "telegram": "qq",
    "video": "video", "pico": "pico", "glasses": "pico",
    "companion": "companion", "proactive": "proactive", "diary": "diary",
}


def detect_channel(raw):
    """把平台名/来源字符串归一成通道键；认不出就当网页聊天。"""
    s = str(raw or "").strip().lower()
    if not s:
        return DEFAULT
    for key, ch in PLATFORM_MAP.items():
        if key in s:
            return ch
    return DEFAULT


def overlay(channel):
    """返回该模式的"说话方法"叠加段；认不出就返回网页聊天那段。"""
    ch = CHANNELS.get(str(channel or "").lower()) or CHANNELS[DEFAULT]
    return ch["overlay"]


def limits(channel):
    """返回该模式的外壳参数（token/字数/行数上限）。"""
    ch = CHANNELS.get(str(channel or "").lower()) or CHANNELS[DEFAULT]
    return {
        "max_tokens": ch["max_tokens"],
        "max_chars": ch["max_chars"],
        "max_lines": ch["max_lines"],
        "label": ch["label"],
    }
