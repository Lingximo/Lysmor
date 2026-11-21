# -*- coding: utf-8 -*-
"""生理闸门：任何行为动手之前，先看她此刻的身体。

数据源：8005/api/state（生命状态服务）。
**取不到就放行**（fail-open）——状态服务挂了不能把她的嘴、手、嗓子全封住。

用法（在插件里懒加载，别在模块顶部 import，免得拖累插件加载）：

    sys.path.insert(0, r"D:\\你的数据目录\\tools")
    import vitals
    ok, why = vitals.decide("qzone_reply")
    if not ok:
        ...跳过，并把 why 写日志
"""

import json
import time
import urllib.request

URL = "http://127.0.0.1:8005/api/state"
TTL = 20.0                     # 20 秒缓存：一次行为里别反复打服务

_cache = {"at": 0.0, "v": None}


def fetch(force=False):
    now = time.time()
    if not force and _cache["v"] is not None and now - _cache["at"] < TTL:
        return _cache["v"]
    try:
        with urllib.request.urlopen(URL, timeout=1.5) as resp:
            v = json.loads(resp.read().decode("utf-8"))
        if not isinstance(v, dict):
            v = {}
    except Exception:
        v = {}
    _cache["v"] = v
    _cache["at"] = now
    return v


def num(v, key, default=0.0):
    try:
        return float(v.get(key, default))
    except Exception:
        return default


def brief(v=None):
    """一句话概括她此刻的身体，用来塞进提示词。"""
    v = fetch() if v is None else v
    if not v:
        return ""
    bits = []
    act = str(v.get("activity") or "").strip()
    if act:
        bits.append("在" + act)
    if v.get("asleep"):
        bits.append("睡着了")
    energy = num(v, "energy", 1.0)
    if energy < 0.2:
        bits.append("快没力气")
    elif energy < 0.4:
        bits.append("有点累")
    if num(v, "hunger") > 0.7:
        bits.append("饿")
    if num(v, "thirst") > 0.7:
        bits.append("渴")
    if num(v, "pain") > 0.5:
        bits.append("身上不舒服")
    if num(v, "cramps") > 0.5:
        bits.append("肚子疼")
    if num(v, "grogginess") > 0.6:
        bits.append("昏昏沉沉")
    return ("她此刻：" + "、".join(bits)) if bits else ""


# 每个行为自己的门槛：宁可严格一点，也不要在她睡着时替她回空间
POLICY = {
    "qzone_reply": {"asleep_ok": False, "min_energy": 0.08, "max_groggy": 0.85},
    "sing": {"asleep_ok": False, "min_energy": 0.12, "max_groggy": 0.90},
    "signature": {"asleep_ok": False, "min_energy": 0.10, "max_groggy": 0.85},
    "art": {"asleep_ok": False, "min_energy": 0.10, "max_groggy": 0.85},
}


def decide(behavior, v=None):
    """返回 (能不能做, 不能做的原因)。"""
    v = fetch() if v is None else v
    if not v:
        return True, ""                     # 拿不到状态：放行
    p = POLICY.get(behavior) or {}
    if v.get("asleep") and not p.get("asleep_ok", True):
        return False, "她睡着了"
    energy = num(v, "energy", 1.0)
    if energy < float(p.get("min_energy", 0.0)):
        return False, "力气不够（energy=%.2f）" % energy
    groggy = num(v, "grogginess", 0.0)
    if groggy > float(p.get("max_groggy", 1.0)):
        return False, "昏沉得厉害（grogginess=%.2f）" % groggy
    return True, ""
