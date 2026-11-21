# -*- coding: utf-8 -*-
"""淋巴系统（2026-11-09 加）

她原来有心血管、呼吸、消化、泌尿、内分泌、免疫（细胞因子/发烧）、
生殖（周期）、疼痛，缺的是"回流与免疫监视"这一层。
淋巴补上之后，几个原来接不上的地方就通了：

  · 组织液（水肿）→ 身体发沉、没精神
  · 淋巴结（颈/腋/腹股沟）→ 生病时肿、摸着疼，好了消下去
  · 淋巴细胞活性 / 免疫监视 → 和 cytokines、fever 咬合
  · 回流靠"动起来 + 喝水 + 睡好"→ 直接和 activity、thirst、睡眠挂钩

纯函数模块：不依赖 astrbot，可单独跑测试。

    from lymph import DEFAULTS, step
    state.update(DEFAULTS)
    events = step(state, hours=0.016, now=time.time())
"""
from __future__ import annotations

DEFAULTS = {
    "lymph_flow": 0.45,          # 淋巴回流效率 0~1（动起来/喝水会升）
    "lymph_capacity": 0.55,      # 清除/引流能力 0~1（睡好、补水会升；感染/水肿会降）
    "lymph_edema": 0.0,          # 组织液潴留：身体发沉、脸/手脚发胀
    "lymph_node_cervical": 0.0,  # 颈部淋巴结肿大
    "lymph_node_axillary": 0.0,  # 腋下
    "lymph_node_inguinal": 0.0,  # 腹股沟
    "lymph_tenderness": 0.0,     # 淋巴结触痛（派生，跟着肿大滞后）
    "lymphocyte": 0.30,          # 淋巴细胞活性
    "immune_surveillance": 0.50, # 免疫监视强度
    "lymph_event_at": 0.0,       # 上次"淋巴有感觉"的时间（记忆冷却）
    "lymph_mem_at": 0.0,
    "lymph_swell_peak": 0.0,
}


def _c(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def _n(state, key, default=0.0):
    try:
        v = state.get(key)
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _approach(cur, target, rate, hours):
    """指数趋近：rate 是"每小时走完的比例"。"""
    k = 1.0 - pow(2.718281828, -max(0.0, rate) * max(0.0, hours))
    return cur + (target - cur) * k


def step(state: dict, hours: float, now: float, lines=None) -> list:
    """推进淋巴系统，返回"值得记住/说出来"的事件列表。

    lines 可传入随机模板（插件那边传，便于和她的人设措辞一致）。
    """
    h = max(0.0, min(24.0, float(hours or 0)))
    if h <= 0:
        return []

    # ---- 输入：从别的系统读（这是"串联"的关键）----
    thirst = _n(state, "thirst", 0.4)
    osmo = _n(state, "osmolality", 0.35)
    hydration = _c(1.0 - max(thirst, osmo))
    asleep = bool(state.get("asleep"))
    energy = _n(state, "energy", 0.6)
    activity = str(state.get("activity") or "")
    moving = 0.25
    if any(k in activity for k in ("走", "散步", "打扫", "收", "洗", "跑", "动")):
        moving = 0.85
    elif any(k in activity for k in ("躺", "发呆", "歇", "坐")):
        moving = 0.15
    if asleep:
        moving = 0.10
    stress = _c(_n(state, "cortisol", 0.2))
    cytokines = _c(_n(state, "cytokines", 0.0))
    fever = _c(_n(state, "fever", 0.0))
    sick = 1.0 if state.get("sick_cause") else 0.0
    infection = _c(cytokines * 1.1 + fever * 0.8 + sick * 0.35)

    # ---- 回流与清除 ----
    flow_target = _c(0.18 + 0.45 * moving + 0.25 * hydration + 0.12 * (1.0 - stress))
    state["lymph_flow"] = round(_approach(_n(state, "lymph_flow", 0.45), flow_target, 0.9, h), 4)

    # 2026-11-11 修：水肿→清除力下降→水肿更重，这个正反馈会把水肿推到 1.0。
    # 把系数从 0.18 降到 0.10，并给"躺下/睡着"单独的引流。
    cap_target = _c(0.30 + 0.30 * hydration + 0.22 * (1.0 if asleep else 0.55)
                    - 0.35 * infection - 0.10 * _n(state, "lymph_edema", 0.0))
    state["lymph_capacity"] = round(
        _approach(_n(state, "lymph_capacity", 0.55), cap_target, 0.5, h), 4)

    flow = _n(state, "lymph_flow")
    cap = _n(state, "lymph_capacity")

    # 组织液：回流差、感染、久坐都会积；动起来/睡够会退
    edema = _n(state, "lymph_edema")
    _lying = ("躺" in str(state.get("activity") or "")) or asleep
    _growth = (1.0 - cap) * 0.055
    if infection < 0.05:
        _growth *= 0.50          # 没感染时，别让久坐把水肿堆满
    _drain = flow * 0.045 + (0.030 if _lying else 0.004)
    edema += (_growth + infection * 0.06 - _drain) * h
    state["lymph_edema"] = round(_c(edema), 4)

    # 淋巴结：感染时肿，跟着感染走，回落慢一点
    for key, bias in (("lymph_node_cervical", 1.0), ("lymph_node_axillary", 0.8),
                      ("lymph_node_inguinal", 0.7)):
        target = _c(infection * 0.85 * bias + _n(state, "lymph_edema") * 0.25)
        cur = _n(state, key)
        rate = 0.55 if target > cur else 0.28      # 肿得快、消得慢
        state[key] = round(_approach(cur, target, rate, h), 4)

    peak_node = max(_n(state, "lymph_node_cervical"), _n(state, "lymph_node_axillary"),
                    _n(state, "lymph_node_inguinal"))
    # 触痛滞后于肿大：刚肿起来就疼，消的时候还疼一会儿
    state["lymph_tenderness"] = round(
        _approach(_n(state, "lymph_tenderness"), _c(peak_node * 0.9), 0.9, h), 4)

    # 淋巴细胞 / 免疫监视
    state["lymphocyte"] = round(_approach(
        _n(state, "lymphocyte", 0.3), _c(0.22 + 0.55 * infection + 0.12 * (1.0 - stress)),
        0.6, h), 4)
    surv = _c(0.35 + 0.40 * _n(state, "lymphocyte") + 0.20 * cap - 0.22 * stress)
    state["immune_surveillance"] = round(surv, 4)

    events = []
    prev_peak = _n(state, "lymph_swell_peak")
    if peak_node >= 0.45 > prev_peak:
        events.append("swell")
        state["lymph_event_at"] = now
    if prev_peak >= 0.50 and peak_node <= 0.28:
        events.append("settle")
        state["lymph_event_at"] = now
    state["lymph_swell_peak"] = round(peak_node, 4)

    # 记忆冷却：两小时内同一种事件只记一次
    last_mem = _n(state, "lymph_mem_at")
    if events and now - last_mem < 2 * 3600:
        events = []
    elif events:
        state["lymph_mem_at"] = now
    return events


def summary_text(state: dict, event: str, lines: dict | None = None) -> str:
    """给记忆/气泡用的一句话（模板可被插件覆盖）。"""
    default = {
        "swell": "今天淋巴那边有点胀，摸着脖子有点小疙瘩，一按就疼。",
        "settle": "前几天肿起来的那点淋巴消下去了，摸着平了，也不疼了。",
    }
    table = dict(default)
    if isinstance(lines, dict):
        table.update(lines)
    return table.get(event, "")
