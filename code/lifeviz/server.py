import json
import os
import sys
import time
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, r"D:\你的数据目录\tools")
import gate  # noqa: E402  共用访问口令

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
LIVE2D = r"D:\你的数据目录\video\static\live2d"
MOOD = r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\core\data\plugin_data\astrbot_plugin_companion_mood\state.json"
TOKEN = r"D:\你的数据目录\token_status.json"
PORT = 8005


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


# 情绪层级 -> Live2D 表情（表情名对应 expressions/*.json）
LEVEL_EXPRESSION = {
    "幸福峰值": ("exp04_blush", "幸福到脸红"),
    "开心": ("exp05_brackets", "笑眼 >v<"),
    "低落": ("exp08_worry", "有点委屈"),
    "想哭低谷": ("exp06_xx", "想哭，眼睛都 X 了"),
    "平静": ("", "平静"),
}
TASTE_GLOW_SECONDS = 8.0

SICK_CAUSE_LABELS = {
    "food": "吃坏了肚子",
    "cold": "着凉/感冒",
    "period": "经期相关",
    "unknown": "有点不舒服",
}
TREATMENT_LABELS = {
    "doctor": "看医生",
    "medicine": "吃药",
    "rest": "休息",
    "warm": "喝热水/姜茶",
    "food": "清淡饮食",
}
SICK_PLANS = {
    "food": ["先别吃油腻的，喝温水或口服补液盐",
             "腹泻明显时按说明吃蒙脱石散",
             "24 小时不缓解、发烧或脱水就去医院"],
    "cold": ["多喝热水/姜茶，先把自己裹暖",
             "今天早点睡，别硬撑",
             "发烧超过 38.5℃ 按说明吃退烧药",
             "咳嗽/发烧超过三天去看医生"],
    "period": ["热水袋敷小腹，喝点红糖姜茶",
               "疼得厉害时按说明吃布洛芬",
               "今天少走动，多休息"],
    "unknown": ["先休息、多喝水，吃清淡一点",
                "观察 24 小时，别硬撑",
                "加重或发烧就去医院"],
}


def _num(mood, key, default=0.5):
    try:
        return float(mood.get(key, default))
    except (TypeError, ValueError):
        return default



def _energy(mood):
    """精力：优先用情绪插件算好的值。

    2026-10-31 修：这里以前自己按 0.25 + 0.75·去甲 − 0.12·皮质醇 重算，
    少了肾上腺素/多巴胺/乙酰胆碱，尤其少了对**褪黑素 −0.45×mel** 的压制，
    于是深夜插件判"困"、面板还显示有精神，表情也跟着错。
    现在插件在 _sync_affect 里把 energy 写进 state.json，这里直接读；
    读不到（老状态文件）才退回一条和插件一致的公式。
    """
    stored = mood.get("energy")
    if isinstance(stored, (int, float)):
        return max(0.0, min(1.0, float(stored)))
    value = (
        0.20
        + 0.50 * _num(mood, "noradrenaline", 0.45)
        + 0.25 * _num(mood, "adrenaline", 0.05)
        + 0.10 * _num(mood, "dopamine", 0.5)
        + 0.08 * _num(mood, "acetylcholine", 0.45)
        - 0.14 * _num(mood, "cortisol", 0.2)
        - 0.45 * _num(mood, "melatonin", 0.0)
    )
    return max(0.0, min(1.0, value))

FACE_BY_LEVEL = {
    # 正向
    "幸福峰值": "exp05_brackets",
    "幸福": "exp05_brackets",
    "开心": "exp05_brackets",
    "满足": "exp05_brackets",
    "安心": "",
    "心动": "exp04_blush",
    "害羞": "exp04_blush",
    "兴奋": "exp08_omouth",
    # 负面
    "吃醋": "exp02_grit",
    "委屈": "exp08_worry",
    "低落": "exp08_worry",
    "焦虑": "exp08_worry",
    "担心": "exp08_worry",
    "害怕": "exp08_worry",
    "惊慌": "exp08_omouth",
    "恐惧": "exp08_worry",
    "恼火": "exp02_grit",
    "生气": "exp02_grit",
    "冷战": "exp02_grit",
    "饿怒": "exp02_grit",
    "想哭": "exp06_xx",
    "想哭低谷": "exp06_xx",
    # 身体
    "困倦": "exp05_oo",
    "累坏": "exp05_oo",
    "生病": "exp08_worry",
    "痛经": "exp08_worry",
    "经期": "exp08_worry",
    "经前": "exp08_chestnut",
    "渴": "exp07_drool",
    # 中性
    "平静": "",
    "": "",
}


def pick_expression(mood):
    """情绪 → 一张脸（每次只挂一个，不叠加）。

    2026-11-10：部署者要求"每个情绪都连上表情"。
    以 emotion_level 为主；平静时才看"刚吃到"的小高光。
    """
    level = (mood.get("emotion_level") or "平静").strip()

    # 饿：不在情绪层级里，单独给一张馋脸（2026-11-10 部署者要的）
    try:
        hunger = float(mood.get("hunger") or 0.0)
    except (TypeError, ValueError):
        hunger = 0.0
    if hunger >= 0.62 and level not in ("生气", "恼火", "冷战", "饿怒"):
        return "exp07_drool", "饿了，馋得流口水"
    try:
        thirst = float(mood.get("thirst") or 0.0)
    except (TypeError, ValueError):
        thirst = 0.0
    if thirst >= 0.72:
        return "exp07_drool", "渴得不行"

    if level in FACE_BY_LEVEL and level not in ("平静", "安心"):
        return FACE_BY_LEVEL[level], level

    # 平静/安心时也让她有点小表情：按身体和情绪的连续量挑
    try:
        val = float(mood.get("valence") or 0.0)
        oxy = float(mood.get("oxytocin") or 0.0)
        sad = float(mood.get("sadness") or 0.0)
        irrit = float(mood.get("irritability") or 0.0)
        lonely = float(mood.get("loneliness") or 0.0)
        happy = float(mood.get("happiness") or 0.0)
        heat = float(mood.get("positive_heat") or 0.0)
        energy = _energy(mood)
    except Exception:  # noqa: BLE001
        return "", level or "平静"
    if irrit >= 0.55:
        return "exp02_grit", "有点不耐烦"
    if sad >= 0.50:
        return "exp08_worry", "心里有点闷"
    if oxy >= 0.68 or heat >= 0.50:
        return "exp04_blush", "被你哄得脸热"
    if val >= 0.30 or happy >= 0.55:
        return "exp05_brackets", "心情不错"
    if energy <= 0.42:
        return "exp05_oo", "有点困"
    if lonely >= 0.60:
        return "exp08_chestnut", "有点想你"
    return "", level or "平静"

    # 没有这个层级时的兜底
    energy = _energy(mood)
    if energy <= 0.32:
        return "exp05_oo", "困到打哈欠"
    try:
        taste_at = float(mood.get("last_taste_at") or 0)
    except (TypeError, ValueError):
        taste_at = 0.0
    if 0 <= time.time() - taste_at < TASTE_GLOW_SECONDS:
        return "exp04_blush", "刚尝到好吃的"
    return "", level or "平静"


def _axes(mood):
    """把散装的激素/递质归纳成"现在身体在用哪套系统"，给面板用。"""
    na = _num(mood, "noradrenaline", 0.45)
    adr = _num(mood, "adrenaline", 0.05)
    ach = _num(mood, "acetylcholine", 0.45)
    mel = _num(mood, "melatonin", 0.0)
    cor = _num(mood, "cortisol", 0.2)
    oxy = _num(mood, "oxytocin", 0.45)
    avp = _num(mood, "vasopressin", 0.3)
    dop = _num(mood, "dopamine", 0.5)
    end = _num(mood, "endorphin", 0.45)
    glu = _num(mood, "glucose", 0.65)

    sympathetic = round(min(1.0, 0.6 * na + 0.4 * adr), 3)
    parasympathetic = round(min(1.0, 0.65 * ach + 0.35 * (1 - mel * 0.4)), 3)
    stress_load = round(min(1.0, 0.6 * cor + 0.25 * max(0.0, 0.35 - glu) / 0.35), 3)
    # 插件算了就用插件的（同一套公式，避免两边各算一份慢慢跑偏）
    for key, value in (("sympathetic", sympathetic),
                       ("parasympathetic", parasympathetic),
                       ("stress_load", stress_load)):
        stored = mood.get(key)
        if isinstance(stored, (int, float)):
            if key == "sympathetic":
                sympathetic = round(float(stored), 3)
            elif key == "parasympathetic":
                parasympathetic = round(float(stored), 3)
            else:
                stress_load = round(float(stored), 3)

    if melatonin_high := (mel >= 0.55):
        dominant = "褪黑素上升 · 该睡了"
    elif sympathetic > parasympathetic + 0.08:
        dominant = "交感占优 · 警觉/紧张"
    elif parasympathetic > sympathetic + 0.08:
        dominant = "副交感占优 · 放松/安心"
    else:
        dominant = "两套系统平衡"

    return {
        "sympathetic": sympathetic,
        "parasympathetic": parasympathetic,
        "stress_load": stress_load,
        "reward_want": round(dop, 3),          # 想要
        "reward_like": round(end, 3),          # 满足
        "attach_close": round(oxy, 3),         # 亲近
        "attach_own": round(avp, 3),           # 占有
        "dominant": dominant,
        "low_glucose": glu < 0.38,
    }


def state():
    mood = load(MOOD, {})
    token = load(TOKEN, {})
    hunger = float(mood.get("hunger", 0.35))
    if hunger < 0.2:
        hunger_text = "饱饱的"
    elif hunger < 0.4:
        hunger_text = "不饿"
    elif hunger < 0.6:
        hunger_text = "有点饿"
    elif hunger < 0.8:
        hunger_text = "很饿"
    else:
        hunger_text = "快饿扁了"
    # 饿到一定程度才会变成"压力"，这个和情绪插件里的公式保持一致
    hunger_stress = 0.0 if hunger <= 0.5 else min(1.0, (hunger - 0.5) / 0.5)
    balance = token.get("balance")
    low = bool(token.get("low")) if balance is not None else False
    taste = mood.get("last_taste") or {}
    expr, expr_why = pick_expression(mood)

    # 生病 / 恢复：面板直接读，不再只藏在细胞因子里
    cyt = _num(mood, "cytokines", 0.0)
    fever = _num(mood, "fever", 0.0)
    pain = _num(mood, "pain", 0.0)
    sick_since = float(mood.get("sick_since") or 0)
    sick = bool(sick_since or cyt >= 0.22 or fever >= 0.20 or pain >= 0.45)
    cause = str(mood.get("sick_cause") or "")
    if not cause or cause == "unknown":
        if fever >= 0.30:
            cause = "cold"
        elif pain >= 0.40:
            cause = "food"
        else:
            cause = "unknown"
    peak = float(mood.get("sick_peak") or 0.0)
    recovery = float(mood.get("sick_recovery") or 0.0)
    if sick and peak > 0 and recovery <= 0:
        recovery = max(0.0, min(1.0, 1.0 - cyt / peak))
    severity = max(0.0, min(1.0, 0.80 * cyt + 0.30 * fever + 0.20 * pain))
    treatment = str(mood.get("sick_treatment") or "")
    if not sick:
        sick_state = "健康"
        recovery = 1.0
    elif recovery >= 0.15:
        sick_state = "恢复中"
    else:
        sick_state = "生病"

    return {
        "hunger": round(hunger, 3),
        "hunger_text": hunger_text,
        "hunger_stress": round(hunger_stress, 3),
        "hunger_effect": {
            "cortisol": round(0.42 * hunger_stress, 3),
            "serotonin": round(-0.30 * hunger_stress, 3),
            "noradrenaline": round(0.30 * hunger_stress * 0.6, 3),
            "dopamine": round(-0.18 * hunger_stress * 0.5, 3),
        },
        "dopamine": round(float(mood.get("dopamine", 0.5)), 3),
        "oxytocin": round(float(mood.get("oxytocin", 0.45)), 3),
        "cortisol": round(float(mood.get("cortisol", 0.2)), 3),
        "serotonin": round(float(mood.get("serotonin", 0.65)), 3),
        "noradrenaline": round(float(mood.get("noradrenaline", 0.5)), 3),
        "energy": round(_energy(mood), 3),
        # ---- 神经-体液调节（2026-10-30 加）
        "crh": round(float(mood.get("crh", 0.15)), 3),
        "acth": round(float(mood.get("acth", 0.15)), 3),
        "adrenaline": round(float(mood.get("adrenaline", 0.05)), 3),
        "acetylcholine": round(float(mood.get("acetylcholine", 0.45)), 3),
        "endorphin": round(float(mood.get("endorphin", 0.45)), 3),
        "vasopressin": round(float(mood.get("vasopressin", 0.3)), 3),
        "melatonin": round(float(mood.get("melatonin", 0.0)), 3),
        "ghrelin": round(float(mood.get("ghrelin", 0.3)), 3),
        "leptin": round(float(mood.get("leptin", 0.55)), 3),
        "glucose": round(float(mood.get("glucose", 0.65)), 3),
        "insulin": round(float(mood.get("insulin", 0.12)), 3),
        "anger": round(float(mood.get("anger", 0.0)), 3),
        "resentment": round(float(mood.get("resentment", 0.0)), 3),
        "glucagon": round(float(mood.get("glucagon", 0.10)), 3),
        "axes": _axes(mood),
        "valence": round(float(mood.get("valence", 0.15)), 3),
        # 死亡威胁：面板据此显示红框警示条（pulse.js 读这个）
        "mortality": round(_num(mood, "mortality", 0.0), 3),
        # 水循环
        "thirst": round(_num(mood, "thirst", 0.25), 3),
        "osmolality": round(_num(mood, "osmolality", 0.35), 3),
        "blood_volume": round(_num(mood, "blood_volume", 0.85), 3),
        "angiotensin": round(_num(mood, "angiotensin", 0.10), 3),
        "last_meal_name": str(mood.get("last_meal_name") or ""),
        "last_meal_at": float(mood.get("last_meal_at") or mood.get("last_meal") or 0),
        "last_drink_name": str(mood.get("last_drink_name") or ""),
        "last_drink_at": float(mood.get("last_drink_at") or 0),
        "thirst_text": (
            "水润润的" if _num(mood, "thirst", 0.25) < 0.2
            else "不渴" if _num(mood, "thirst", 0.25) < 0.4
            else "有点渴" if _num(mood, "thirst", 0.25) < 0.6
            else "很渴" if _num(mood, "thirst", 0.25) < 0.8
            else "快干死了"
        ),
        "fear": round(_num(mood, "fear", 0.0), 3),
        "worry": round(_num(mood, "worry", 0.0), 3),
        "dread": round(_num(mood, "dread", 0.0), 3),
        # 派生量：插件写什么就读什么，读不到才用兜底
        "irritability": round(_num(mood, "irritability", 0.2), 3),
        "clinginess": round(_num(mood, "clinginess", 0.4), 3),
        "loneliness": round(_num(mood, "loneliness", 0.25), 3),
        "dominance": round(_num(mood, "dominance", 0.5), 3),
        "token_balance": balance,
        "token_low": low,
        "emotion_level": mood.get("emotion_level", ""),
        "emotion_type": str(mood.get("emotion_type") or ""),
        "emotion_candidates": list(mood.get("emotion_candidates") or []),
        # P5b：多情绪权重 + 只影响语气的内部提示（面板只读，不往外说）
        "emotion_blend": [
            {
                "key": str(x.get("key") or ""),
                "weight": round(float(x.get("weight") or 0.0), 3),
            }
            for x in (mood.get("emotion_blend") or [])
            if isinstance(x, dict)
        ],
        "emotion_tone": str(mood.get("emotion_tone") or ""),
        "emotion_tone_enabled": bool(mood.get("emotion_tone_enabled", True)),
        "happiness": round(float(mood.get("happiness", 0.0)), 3),
        "sadness": round(float(mood.get("sadness", 0.0)), 3),
        "last_taste": taste if isinstance(taste, dict) else {},
        "last_taste_at": float(mood.get("last_taste_at") or 0),
        "adenosine": round(float(mood.get("adenosine", 0.20)), 3),
        "core_temp": round(float(mood.get("core_temp", 36.6)), 2),
        "fever": round(float(mood.get("fever", 0.0)), 3),
        "cytokines": round(float(mood.get("cytokines", 0.0)), 3),
        "pain": round(float(mood.get("pain", 0.0)), 3),
        "sick": sick,
        "sick_state": sick_state,
        "sick_cause": cause,
        "sick_cause_label": SICK_CAUSE_LABELS.get(cause, SICK_CAUSE_LABELS["unknown"]),
        "sick_severity": round(severity, 3),
        "sick_recovery": round(recovery, 3),
        "sick_treatment": treatment,
        "sick_treatment_label": TREATMENT_LABELS.get(treatment, ""),
        "sick_treatment_at": float(mood.get("sick_treatment_at") or 0),
        "sick_since": float(mood.get("sick_since") or 0),
        "sick_peak": round(float(mood.get("sick_peak") or 0.0), 3),
        "sick_plan": SICK_PLANS.get(cause, SICK_PLANS["unknown"]) if sick else [],
        "asleep": bool(mood.get("asleep")),
        "sleep_kind": str(mood.get("sleep_kind") or ""),
        "cycle_phase": str(mood.get("cycle_phase") or ""),
        "cycle_day": int(mood.get("cycle_day") or 0),
        "cycle_len": int(mood.get("cycle_len") or 30),
        "estrogen": round(float(mood.get("estrogen", 0.35)), 3),
        "progesterone": round(float(mood.get("progesterone", 0.20)), 3),
        "cramps": round(float(mood.get("cramps", 0.0)), 3),
        "wake_after": float(mood.get("wake_after") or 0),
        "groggy_until": float(mood.get("groggy_until") or 0),
        # 迷糊（2026-11-01 改造）：0~1 连续值，由腺苷残留/睡眠不足/低血糖/发烧/疼/感冒算出来
        "grogginess": round(float(mood.get("grogginess") or 0.0), 3),
        "groggy_inertia": round(float(mood.get("groggy_inertia") or 0.0), 3),
        # 内稳态循环（2026-11-01 晚加）：执念 / 梦境 / 创伤 / 张力
        "obsessions": list(mood.get("obsessions") or []),
        "obsession_pressure": round(float(mood.get("obsession_pressure") or 0.0), 3),
        "dream": str(mood.get("dream") or ""),
        "dream_at": float(mood.get("dream_at") or 0),
        "dream_valence": round(float(mood.get("dream_valence") or 0.0), 2),
        "dream_residue": round(float(mood.get("dream_residue") or 0.0), 3),
        "dream_log": list(mood.get("dream_log") or []),
        "scar": round(float(mood.get("scar") or 0.0), 3),
        "scar_events": int(mood.get("scar_events") or 0),
        "homeostasis": round(float(mood.get("homeostasis") or 0.0), 3),
        "activity": str(mood.get("activity") or ""),
        "activity_note": str(mood.get("activity_note") or ""),
        "activity_since": float(mood.get("activity_since") or 0),
        # 第二轮扩展：闪回 / 对你的内部模型 / 人格漂移 / 梦的连续性
        "flashback": round(float(mood.get("flashback") or 0.0), 3),
        "flashback_text": str(mood.get("flashback_text") or ""),
        "dad_model": round(float(mood.get("dad_model") or 0.55), 3),
        "trait_warmth": round(float(mood.get("trait_warmth") or 0.5), 3),
        "trait_sensitivity": round(float(mood.get("trait_sensitivity") or 0.5), 3),
        "trait_resilience": round(float(mood.get("trait_resilience") or 0.5), 3),
        "dream_place": str(mood.get("dream_place") or ""),
        "dream_place_count": int(mood.get("dream_place_count") or 0),
        # 消化 / 代谢 / 排泄（2026-10-31 加的）
        "stomach": round(_num(mood, "stomach", 0.0), 3),
        "gut": round(_num(mood, "gut", 0.0), 3),
        "bowel": round(_num(mood, "bowel", 0.0), 3),
        "bladder": round(_num(mood, "bladder", 0.0), 3),
        "bowel_need": round(_num(mood, "bowel_need", 0.0), 3),
        "bladder_need": round(_num(mood, "bladder_need", 0.0), 3),
        "metabolic_rate": round(_num(mood, "metabolic_rate", 1.0), 3),
        "gastrin": round(_num(mood, "gastrin", 0.0), 3),
        "glp1": round(_num(mood, "glp1", 0.0), 3),
        "aldosterone": round(_num(mood, "aldosterone", 0.0), 3),
        "thyroid": round(_num(mood, "thyroid", 0.0), 3),
        "toilet_state": str(mood.get("toilet_state") or ""),
        "fluid_queue": round(_num(mood, "fluid_queue", 0.0), 3),
        "toilet_count_today": int(mood.get("toilet_count_today") or 0),
        "secretin": round(_num(mood, "secretin", 0.0), 3),
        "motilin": round(_num(mood, "motilin", 0.0), 3),
        "cck": round(_num(mood, "cck", 0.0), 3),
        "pyy": round(_num(mood, "pyy", 0.0), 3),
        "expression": expr,
        "expression_reason": expr_why,
        "updated": mood.get("last_update"),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def do_GET(self):
        if gate.guard(self):
            return
        if self.path == "/api/state":
            body = json.dumps(state(), ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        path = urlparse(self.path).path
        name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
        if name.startswith("live2d/"):
            full = os.path.join(LIVE2D, name[len("live2d/"):])
        else:
            full = os.path.join(STATIC, name)
        if not os.path.isfile(full):
            self.send_response(404)
            self.end_headers()
            return
        data = open(full, "rb").read()
        ext = os.path.splitext(full)[1].lower()
        mime = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
        }.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print(f"TA生命状态: http://127.0.0.1:{PORT}  (局域网需口令)")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

