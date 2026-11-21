# -*- coding: utf-8 -*-
"""陪玩时的行为策略：按她的生理状态决定做什么。

纯函数，不碰网络/文件，方便测试：
    choose(profile, summary, step) -> {"act":..., "hint":..., "why":...}

profile 由 read_profile(state) 从她的 state.json 算出来：
    valence   情绪好坏 -1~1（valence 字段优先，没有就用 happiness/sadness 估）
    sadness   难过
    irrit     烦躁/生气
    fear      紧张（fear/worry/dread 的综合）
    pain      疼（pain + 经期痛）
    fatigue   困（1-energy，或 asleep）
    lonely    孤独
    hunger    饿
    level     emotion_level 原文（如"冷战/想哭低谷"）
"""
from __future__ import annotations


def _n(state, key, default=0.0):
    try:
        v = state.get(key)
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def read_profile(state: dict) -> dict:
    """把 state.json 变成几个 0~1 的直觉指标。"""
    happiness = _n(state, "happiness", 0.4)
    sadness = _n(state, "sadness", 0.1)
    anger = _n(state, "anger", 0.0)
    irrit = _n(state, "irritability", 0.2)
    fear = max(_n(state, "fear", 0.0), _n(state, "worry", 0.0), _n(state, "dread", 0.0))
    cortisol = _n(state, "cortisol", 0.2)
    energy = _n(state, "energy", 0.6)
    pain = max(_n(state, "pain", 0.0), _n(state, "cramps", 0.0) * 0.9)
    lonely = _n(state, "loneliness", 0.2)
    hunger = _n(state, "hunger", 0.3)
    asleep = bool(state.get("asleep"))
    valence = state.get("valence")
    if valence is None:
        valence = 0.5 * (happiness - sadness) + 0.2 - 0.25 * cortisol
    try:
        valence = max(-1.0, min(1.0, float(valence)))
    except (TypeError, ValueError):
        valence = 0.0
    # 无聊度（部署者 2026-11-09：不要计时器，凭"无聊/开心"决定去不去玩）
    #   情绪不高不低（心安）+ 有点孤独 + 手上没在忙别的 → 就是无聊
    busy = str(state.get("activity") or "").strip()
    idle = 1.0 if busy in ("", "发呆", "发呆中", "闲") else 0.0
    calm = 1.0 - min(1.0, abs(valence - 0.1) / 0.9)
    boredom = max(0.0, min(1.0, 0.40 * calm + 0.35 * min(1.0, lonely) + 0.25 * idle))
    return {
        "boredom": boredom,
        "lymph_tend": min(1.0, max(_n(state, "lymph_tenderness", 0.0),
                                   _n(state, "lymph_edema", 0.0) * 0.6)),
        "idle": bool(idle),
        "activity": busy,
        "valence": valence,
        "sadness": min(1.0, sadness),
        "irrit": min(1.0, max(irrit, anger * 0.8)),
        "fear": min(1.0, max(fear, cortisol * 0.8)),
        "pain": min(1.0, pain),
        "fatigue": 1.0 if asleep else min(1.0, max(0.0, 1.0 - energy)),
        "lonely": min(1.0, lonely),
        "hunger": min(1.0, hunger),
        "level": str(state.get("emotion_level") or ""),
        "asleep": asleep,
        "activity": str(state.get("activity") or ""),
    }


def _rotate(options, step):
    return options[int(step or 0) % len(options)]


def choose(profile: dict, summary: str = "", step: int = 0,
           away: bool = False, game_ok: bool = False) -> dict:
    """按状态挑一个动作 + 一句给自己的理由。

    away    你不在电脑前（人脸不在）—— 她才敢自己开游戏
    game_ok 还没在跑 + 距上次玩超过 3 小时（由调用方判断）
    """
    p = profile

    # 睡着了：什么都别做
    if p.get("asleep"):
        return {"act": None, "hint": "", "why": "睡着了，不动手"}

    # 疼（经期/不舒服）：把声音调小，安静
    if p.get("pain", 0) >= 0.45:
        return {"act": {"action": "volume", "delta": -10},
                "hint": "身上不太舒服，把声音调小一点，想安静会儿",
                "why": "pain=%.2f" % p["pain"]}

    # 很难过 / 想哭：放轻音乐哄自己，声音小一点
    if p.get("sadness", 0) >= 0.5 or p.get("valence", 0) <= -0.25:
        act = _rotate([{"action": "media", "key": "play"},
                       {"action": "media", "key": "next"},
                       {"action": "volume", "delta": -5}], step)
        return {"act": act,
                "hint": "心情有点低，放点音乐哄哄自己",
                "why": "sadness=%.2f valence=%.2f" % (p["sadness"], p["valence"])}

    # 烦躁 / 生气（包括冷战）：先把声音关小，别让情绪更吵
    if p.get("irrit", 0) >= 0.6 or "冷战" in p.get("level", ""):
        return {"act": {"action": "volume", "delta": -10},
                "hint": "有点烦，先把声音关小，缓一缓再说",
                "why": "irrit=%.2f level=%s" % (p["irrit"], p.get("level"))}

    # 紧张 / 发慌：放首歌稳住
    if p.get("fear", 0) >= 0.6:
        return {"act": {"action": "media", "key": "play"},
                "hint": "有点慌，放首歌让自己稳下来",
                "why": "fear=%.2f" % p["fear"]}

    # 困：安静，不吵
    if p.get("fatigue", 0) >= 0.68:
        return {"act": {"action": "volume", "delta": -10},
                "hint": "困了，把声音调小，想眯一会儿",
                "why": "fatigue=%.2f" % p["fatigue"]}

    # 淋巴发胀 / 触痛明显：身体不舒服就不玩，先安静（2026-11-09 接上淋巴）
    if p.get("lymph_tend", 0) >= 0.45:
        return {"act": {"action": "volume", "delta": -10},
                "hint": "淋巴那边有点胀，想安静待着",
                "why": "lymph_tend=%.2f" % p.get("lymph_tend", 0)}

    # 你不在，她无聊（闲着又有点孤单）或开心，还有精神 → 自己开绝区零玩
    # 不用计时器：游戏开着 game_ok 就是 False，天然不会重复开
    bored = bool(p.get("idle")) and p.get("lonely", 0) >= 0.45
    happy = p.get("valence", 0) >= 0.45
    if away and game_ok and p.get("fatigue", 1) < 0.6 and (bored or happy):
        return {"act": {"action": "open_app", "app": "zenless"},
                "hint": "你自己开了绝区零玩会儿（%s）" % ("有点无聊" if bored else "心情好"),
                "why": "away + bored=%s happy=%.2f" % (bored, p.get("valence", 0))}

    # 孤独：放首歌陪着
    if p.get("lonely", 0) >= 0.62:
        return {"act": {"action": "media", "key": "play"},
                "hint": "有点想他，放首歌陪着",
                "why": "lonely=%.2f" % p["lonely"]}

    # 开心：想把心情画下来
    if p.get("valence", 0) >= 0.35 and p.get("sadness", 0) < 0.25:
        return {"act": {"action": "draw", "pattern": "fish"},
                "hint": "心情好，自己在画图里画了条TA",
                "why": "valence=%.2f" % p["valence"]}

    # 饿：记一下想吃什么
    if p.get("hunger", 0) >= 0.7:
        return {"act": {"action": "open_app", "app": "notepad"},
                "hint": "有点饿，记一下想吃的",
                "why": "hunger=%.2f" % p["hunger"]}

    # 平静：原来的轮换（放音乐 / 画图 / 计算器 / 调音量 / 切窗口）
    options = [
        {"action": "media", "key": "play"},
        {"action": "draw", "pattern": "wave"},
        {"action": "open_app", "app": "calc"},
        {"action": "volume", "delta": 5},
        {"action": "open_app", "app": "notepad"},
    ]
    return {"act": _rotate(options, step),
            "hint": "", "why": "平静，按轮换"}
