"""TA的大平层：行为引擎 + 俯视图服务（8007）。

设计边界（很重要）：
  - 只**读**情绪插件的 state.json，绝不写它；她本体的生理/记忆由插件单独负责。
  - 位置、走动、房间由这里算；插件只管"想上厕所了"这种身体信号。
  - **观看者只读**：打开 3D/2D 页面、轮询 /api/house 只读取快照，
    不写她的记忆、不产生"被你观察"的事件，也不影响她要不要去厕所/阳台。
  - 她去哪里由本服务后台 tick 按身体信号（排泄需求优先）和心情自动决定，
    和有没有人在看无关。
  - 唯一的反向通道是 `mood_events.jsonl`：阳台散心时写一条，
    插件下一轮心跳读走并删掉（和视频通话 mood_events 是同一套做法）。
  - 服务挂了不影响她说话、记忆、睡觉；看门狗会把它拉起来。

页面：http://127.0.0.1:8007/
    局域网/手机要带 ?t=<口令>（和别的页面共用 gate_token.txt）
"""
import gzip
import json
import math
import os
import random
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

sys.path.insert(0, r"D:\你的数据目录\tools")
import gate  # noqa: E402  共用访问口令

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
PLAN_PATH = os.environ.get("HOUSE_PLAN") or os.path.join(ROOT, "plan.json")
STATE_PATH = os.environ.get("HOUSE_STATE") or os.path.join(ROOT, "house-state.json")
EVENTS_OUT = os.environ.get("HOUSE_EVENTS") or os.path.join(ROOT, "mood_events.jsonl")
MOVE_IN = os.environ.get("HOUSE_MOVE") or os.path.join(ROOT, "move_requests.jsonl")
BG_DIR = r"D:\你的数据目录\video\static\bg"
ART_DIR = r"D:\你的数据目录\art\gallery"

MOOD = os.environ.get("HOUSE_MOOD") or (
    r"C:\你的用户\.astrbot_launcher\instances"
    r"\<BOT_INSTANCE>\core\data\plugin_data"
    r"\astrbot_plugin_companion_mood\state.json")
PROACTIVE = os.environ.get("HOUSE_PROACTIVE") or (
    r"C:\你的用户\.astrbot_launcher\instances"
    r"\<BOT_INSTANCE>\core\data\plugin_data"
    r"\astrbot_plugin_proactive_chat\session_data.json")

PORT = int(os.environ.get("HOUSE_PORT") or 8007)
TICK = 2.0
WALK = 0.62          # 常速 m/s
HURRY = 1.15         # 急着上厕所
TIRED = 0.46         # 困/夜里

PLAN = json.load(open(PLAN_PATH, encoding="utf-8"))


# ---------------------------------------------------------------- 小工具
def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def load_json(path, default):
    try:
        # utf-8-sig：别人手写/用 PowerShell 存的带 BOM 的 json 也能读
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def atomic_json(path, data):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def route_length(route):
    total = 0.0
    for i in range(1, len(route)):
        total += dist(route[i - 1], route[i])
    return total


def route_pos(route, t0, speed, now):
    """按时间在折线上取点：服务端和浏览器用同一套算法。"""
    if not route:
        return [0.0, 0.0]
    if len(route) == 1:
        return list(route[0])
    remain = max(0.0, (now - t0) * speed)
    cur = route[0]
    for nxt in route[1:]:
        seg = dist(cur, nxt)
        if seg <= remain:
            remain -= seg
            cur = nxt
            continue
        if seg <= 1e-9:
            cur = nxt
            continue
        k = remain / seg
        return [cur[0] + (nxt[0] - cur[0]) * k, cur[1] + (nxt[1] - cur[1]) * k]
    return list(route[-1])


def window_key(hour):
    """和视频通话页 app.js 的六张背景完全一致。"""
    if 5 <= hour < 7:
        return "dawn"
    if 7 <= hour < 11:
        return "morning"
    if 11 <= hour < 14:
        return "noon"
    if 14 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 20:
        return "evening"
    return "night"


def _num(d, key, default=0.0):
    try:
        return float(d.get(key, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- 导航
NODES = {k: tuple(v) for k, v in PLAN["nav"]["nodes"].items()}
EDGES = PLAN["nav"]["edges"]
ROOMS = {r["id"]: r for r in PLAN["rooms"]}


def _adjacency():
    g = {k: [] for k in NODES}
    for a, b in EDGES:
        if a in g and b in g:
            w = dist(NODES[a], NODES[b])
            g[a].append((b, w))
            g[b].append((a, w))
    return g


GRAPH = _adjacency()


def shortest_path(start, goal):
    """Dijkstra：小图，直接用最朴素写法。"""
    if start not in NODES or goal not in NODES:
        return []
    if start == goal:
        return [start]
    seen = {start: 0.0}
    prev = {}
    todo = [(0.0, start)]
    while todo:
        todo.sort()
        cost, node = todo.pop(0)
        if node == goal:
            break
        if cost > seen.get(node, 1e9):
            continue
        for nxt, w in GRAPH.get(node, ()):
            nc = cost + w
            if nc < seen.get(nxt, 1e9):
                seen[nxt] = nc
                prev[nxt] = node
                todo.append((nc, nxt))
    if goal not in prev and goal != start:
        return []
    out = [goal]
    while out[-1] != start:
        out.append(prev[out[-1]])
    out.reverse()
    return out


def nearest_node(point):
    return min(NODES, key=lambda k: dist(NODES[k], point))


# 每个房间自己的节点：找最近点只能在本房间的节点里找，
# 否则会从阳台一路"穿墙"到厕所门口（2026-10-31 体检抓到过）
ROOM_NODES = {
    "dad_room": ["user"],
    "kitchen": ["kitchen"],
    "living": ["lw", "lc", "le", "se", "sw", "dining", "entry"],
    "her_room": ["hdoor", "hd", "hr"],
    "toilet": ["td", "ti"],
    "balcony": ["balcony"],
}


def room_at(point):
    """这个坐标在哪一间房里；在墙里/门口返回 None。"""
    for rid, room in ROOMS.items():
        x, y, w, h = room["rect"]
        if x - 0.04 <= point[0] <= x + w + 0.04 and y - 0.04 <= point[1] <= y + h + 0.04:
            return rid
    return None


def route_to(here, start_room, room_id, spot):
    """从当前位置走到目标房间的某个点，按房间节点图走。"""
    target = [float(spot[0]), float(spot[1])]
    if start_room == room_id:
        if dist(here, target) <= 0.05:
            return [list(here)]
        return [list(here), target]

    start_candidates = ROOM_NODES.get(start_room) or list(NODES)
    goal_candidates = ROOM_NODES.get(room_id) or list(NODES)
    start_node = min(start_candidates, key=lambda k: dist(NODES[k], here))
    goal_node = min(goal_candidates, key=lambda k: dist(NODES[k], target))
    nodes = shortest_path(start_node, goal_node)
    route = [list(here)]
    for n in nodes:
        p = [NODES[n][0], NODES[n][1]]
        if dist(route[-1], p) > 0.05:
            route.append(p)
    if dist(route[-1], target) > 0.05:
        route.append(target)
    return route


# ---------------------------------------------------------------- 视频/聊天信号
def video_active():
    """视频页开着（有 WebSocket 连着 8003/8004）就算"在视频"。

    用端口连接判断，不改视频服务的任何一行代码。
    """
    try:
        import psutil
        for c in psutil.net_connections(kind="tcp"):
            if c.status != "ESTABLISHED" or not c.laddr:
                continue
            if c.laddr.port in (8003, 8004):
                return True
    except Exception:
        return False
    return False


# ---------------------------------------------------------------- 房子
class House:
    def __init__(self):
        self.lock = threading.RLock()
        self.room = "her_room"
        self.activity = "窝着"
        self.spot = list(PLAN["spots"]["her_room"]["mid"])
        self.route = [list(self.spot)]
        self.route_at = time.time()
        self.speed = WALK
        self.intent = ""
        self.since = time.time()
        self.mood = {}
        self.signals = {}
        self.events = []
        self.balcony_since = 0.0
        self.balcony_fired = False
        self.last_balcony_at = 0.0
        self.fridge_since = 0.0
        self.fridge_fired = False
        self.last_help_at = 0.0      # 起不来时"喊人"的冷却（25 分钟）
        self.last_bedside_at = 0.0   # 起不来时"够床头的水"的冷却（20 分钟）
        self.water_since = 0.0
        self.water_fired = False
        self.next_wander_at = time.time() + 600
        self.wander_alt = False
        self._video = False
        self._video_checked = 0.0
        self._last_state_write = 0.0
        # 别人让她去的房间（你说"去客厅"，或她自己说"我回房间啦"）
        self.manual = {}
        self.lamp = True
        self.tv = False
        self.last_tv_desc = ""

    # ---------- 房间动作（2026-11-12 借 feiyu-room-template 的思路）
    def _emit(self, kind, extra=None):
        try:
            os.makedirs(os.path.dirname(EVENTS_OUT), exist_ok=True)
            with open(EVENTS_OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": kind, "t": time.time(),
                                    "by": "user", **(extra or {})},
                                   ensure_ascii=False) + "\n")
        except OSError:
            pass

    def act(self, kind):
        """房间里的动作：摸头/喂饭/倒水/陪玩/叫醒/开灯/电视。"""
        kind = str(kind or "").strip()
        labels = {"pet": "被你摸了摸头", "feed": "你在房间喂我吃饭",
                  "water": "你给我倒了水", "play": "和你在房间里玩",
                  "wake": "被你叫醒", "lamp_on": "你把灯打开了",
                  "lamp_off": "你把灯关了", "tv_on": "你打开了电视",
                  "tv_off": "你关掉了电视"}
        if kind not in labels:
            return False, "unknown action"
        with self.lock:
            if kind == "lamp_on":
                self.lamp = True
            elif kind == "lamp_off":
                self.lamp = False
            elif kind == "tv_on":
                self.tv = True
            elif kind == "tv_off":
                self.tv = False
            else:
                self.activity = labels[kind]
                self.since = time.time()
            self._note(labels[kind])
            self._emit(kind)
        return True, labels[kind]

    def move_to(self, room=None, spot=None, x=None, z=None, note="你让我过去"):
        """点哪去哪：按房间+站位，或者直接给 x,z。"""
        with self.lock:
            if x is not None and z is not None:
                room = None
                for r in PLAN.get("rooms", []):
                    rx, rz, rw, rh = r.get("rect") or [0, 0, 0, 0]
                    if rx <= float(x) <= rx + rw and rz <= float(z) <= rz + rh:
                        room = r.get("id")
                        break
                room = room or self.room
                spots = PLAN.get("spots", {}).get(room) or {}
                best = None
                for name, pos in spots.items():
                    d = dist((float(x), float(z)), pos)
                    if best is None or d < best[0]:
                        best = (d, name)
                spot = best[1] if best else None
            if room not in ROOMS:
                return False
            spots = PLAN.get("spots", {}).get(room) or {}
            if not spots:
                return False
            if spot not in spots:
                spot = list(spots.keys())[0]
            here = route_pos(self.route, self.route_at, self.speed, time.time())
            self.route = route_to(tuple(here), self.room, room, spots[spot])
            self.route_at = time.time()
            self.speed = WALK
            self.room = room
            self.spot = list(spots[spot])
            self.activity = "走过去"
            self.since = time.time()
            self.manual = {"room": room, "spot": spot, "until": time.time() + 900,
                           "note": note}
            self._note(note)
            return True


    def tv_frame(self, jpeg: bytes):
        """把电视画面交给视觉模型看一眼，写事件并返回描述。"""
        import urllib.request
        desc = ""
        # 8804 有 3 秒描述节流/忙时会返回 described=False，重试一次
        for attempt in range(2):
            req = urllib.request.Request(
                "http://127.0.0.1:8804/frame?describe=1", data=jpeg,
                headers={"Content-Type": "image/jpeg"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    j = json.loads(r.read().decode("utf-8", "replace"))
                desc = str(j.get("desc") or "").strip()
            except Exception:  # noqa: BLE001
                desc = ""
            if desc:
                break
            time.sleep(3.5)
        if not desc:
            return ""
        with self.lock:
            self.last_tv_desc = desc
            self._note("和你一起看了会儿电视")
            self._emit("tv_seen", {"text": desc})
        return desc

    # ---------- 移动请求（plugin 写，房子读走即删）
    def _consume_moves(self, now):
        try:
            if not os.path.exists(MOVE_IN):
                return
            with open(MOVE_IN, encoding="utf-8-sig") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            os.remove(MOVE_IN)
        except OSError:
            return
        for line in lines[-5:]:
            try:
                req = json.loads(line)
            except Exception:
                continue
            room = str(req.get("room") or "")
            spot = str(req.get("spot") or "")
            until = float(req.get("until") or 0)
            if room not in ROOMS or until < now:
                continue
            if spot not in PLAN["spots"].get(room, {}):
                spot = list(PLAN["spots"].get(room, {}).keys())[0] if PLAN["spots"].get(room) else ""
            if not spot:
                continue
            self.manual = {
                "room": room,
                "spot": spot,
                "until": until,
                "note": str(req.get("note") or ""),
            }
            self._note("被叫去 %s" % ROOMS.get(room, {}).get("name", room))

    # ---------- 信号
    def _read_signals(self, now):
        mood = load_json(MOOD, {})
        proactive = load_json(PROACTIVE, {})
        unanswered = 0
        last_sent = 0.0
        if isinstance(proactive, dict):
            for value in proactive.values():
                if isinstance(value, dict) and "unanswered_count" in value:
                    try:
                        unanswered = int(value.get("unanswered_count") or 0)
                    except (TypeError, ValueError):
                        unanswered = 0
                    last_sent = _num(value, "last_message_time", 0.0)
                    break
        if now - self._video_checked > 5.0:
            self._video = video_active()
            self._video_checked = now
        bowel = _num(mood, "bowel", 0.0)
        bladder = _num(mood, "bladder", 0.0)
        toilet = str(mood.get("toilet_state") or "")
        hunger = _num(mood, "hunger", 0.3)
        thirst = _num(mood, "thirst", 0.25)
        fridge_food = mood.get("fridge_food") if isinstance(mood.get("fridge_food"), list) else []
        last_fridge = _num(mood, "last_fridge_eat_at", 0.0)
        last_water = _num(mood, "last_water_dispenser_at", 0.0)
        # 饿了且冰箱里有你存的吃的；渴得不行时去饮水机（水永远是满的）
        # 人格自主（§176）：你给了她吃饭权后，冰箱的"自动吃"让位给她的决定
        try:
            _gate = json.load(open(r"D:\你的数据目录\state\persona\observer_gate.json", encoding="utf-8"))
            _auto_eat_off = bool((_gate.get("rights") or {}).get("body_eat"))
        except Exception:
            _auto_eat_off = False
        fridge_need = bool(fridge_food) and hunger >= 0.62 and now - last_fridge > 45 * 60 and not _auto_eat_off
        water_need = thirst >= 0.68 and now - last_water > 20 * 60
        sig = {
            "mood": mood,
            "asleep": bool(mood.get("asleep")),
            "nap": str(mood.get("sleep_kind") or "") == "nap",
            "toilet": toilet,
            "last_msg": _num(mood, "last_msg", 0.0),
            "unanswered": unanswered,
            "last_sent": last_sent,
            "lonely": _num(mood, "loneliness", 0.3),
            "sad": _num(mood, "sadness", 0.0),
            "anger": _num(mood, "anger", 0.0),
            "valence": _num(mood, "valence", 0.0),
            "energy": _num(mood, "energy", 0.5),
            "hunger": hunger,
            "thirst": thirst,
            "bowel": bowel,
            "bladder": bladder,
            "fridge_food": fridge_food,
            "fridge_need": fridge_need,
            "water_need": water_need,
            "melatonin": _num(mood, "melatonin", 0.0),
            "cramps": _num(mood, "cramps", 0.0),
            "period_relief": _num(mood, "period_relief", 0.0),
            "phase": str(mood.get("cycle_phase") or ""),
            # 2026-11-05：生病也要"起不来"，字段从她的身体状态里直接读
            "cytokines": _num(mood, "cytokines", 0.0),
            "core_temp": _num(mood, "core_temp", 36.5),
            "sick_pain": _num(mood, "pain", 0.0),
            "sick_since": _num(mood, "sick_since", 0.0),
            # 2026-11-05：你放在床头的姜汤/水，起不来时伸手就能喝
            "bedside": isinstance(mood.get("bedside_drink"), dict),
            "bedside_name": str((mood.get("bedside_drink") or {}).get("name") or "水")
            if isinstance(mood.get("bedside_drink"), dict) else "",
            "video": self._video,
            "now": now,
        }
        self.mood = mood
        self.signals = sig
        return sig

    # ---------- 决定去哪
    def _wants_balcony(self, sig, now):
        hour = time.localtime(now).tm_hour
        if hour >= 22 or hour < 7:
            return False
        if now - self.last_balcony_at < 2700:      # 45 分钟冷却
            return False
        silence = now - max(sig["last_msg"], sig["last_sent"])
        down = (sig["sad"] > 0.42 or sig["lonely"] > 0.55
                or sig["anger"] > 0.32 or sig["valence"] < -0.18)
        if not down:
            return False
        # 先主动发过消息、你还是没回 → 去阳台
        if sig["unanswered"] >= 1 and silence > 1500:
            return True
        # 没发消息但被晾了很久、心里又闷 → 也去
        return silence > 2700 and (sig["sad"] > 0.5 or sig["lonely"] > 0.6)

    # ---------- 能不能自己行动
    def _incap(self, sig):
        """起不起得来。返回 (原因文案, 类别, 需求提示)；能起来返回 (None, None, "")。

        2026-11-05：部署者确认"疼得动不了就不该自己跑去吃饭喝水"是真实行为——
        所以这不是 bug，是把规则补全：**痛经和生病走同一套**。
        起不来时需求照涨，但只能躺着等你；渴/饿到顶会在嘴上喊（bed_need 事件），
        脚不会动。
        """
        period_pain = sig["cramps"] * (1.0 - 0.60 * sig["period_relief"])
        if sig["phase"] == "menstrual" and period_pain > 0.28:
            note, kind = "痛经，缩在被窝里", "period"
        elif sig["sick_since"] > 0 and (
                sig["cytokines"] >= 0.55 or sig["core_temp"] >= 37.6
                or sig["sick_pain"] >= 0.5):
            if sig["core_temp"] >= 37.8:
                note, kind = "发烧，缩在被窝里", "sick"
            else:
                note, kind = "病得没力气，躺着", "sick"
        else:
            return (None, None, "")
        need = ""
        if sig["thirst"] >= 0.88:
            need = "渴得嗓子冒烟也起不来"
        elif sig["hunger"] >= 0.88:
            need = "饿得心慌也起不来"
        return (note, kind, need)

    def _decide(self, sig, now):
        hour = time.localtime(now).tm_hour
        minute = time.localtime(now).tm_min
        hours = hour + minute / 60.0
        spots = PLAN["spots"]

        # 1) 身体信号最优先：想上厕所
        if sig["toilet"]:
            return ("toilet", spots["toilet"]["stand"], "在厕所", HURRY, "toilet")

        # 1.5) 极度口渴时，睡着了也会醒过来接水；痛经/生病起不来时除外
        if sig["asleep"] and sig["thirst"] >= 0.92:
            incap_note, _, _ = self._incap(sig)
            if not incap_note:
                return ("living", spots["living"]["water"],
                        "渴醒了，去接水喝", WALK, "water")

        # 2) 睡觉（位置永远在自己的床）
        if sig["asleep"]:
            return ("her_room", spots["her_room"]["bed"],
                    "午睡中" if sig["nap"] else "睡着了", TIRED, "sleep")

        # 2.2) 起不来（痛经 / 生病）：需求照涨，但脚不会动，只能躺着等你。
        # 2026-11-05：部署者确认"疼得动不了就不该自己跑去吃饭喝水"是真实行为，
        # 所以这里不是修复，是把这条规则补全，生病走同一套。
        incap_note, incap_kind, need = self._incap(sig)
        if incap_note:
            bed = spots["her_room"]["bed"]
            if sig["video"] or now - sig["last_msg"] < 150:
                return ("her_room", bed, incap_note + "，跟你说话", 0.50,
                        incap_kind + "_talk")
            if need:
                # 你在床头放了水/汤 → 不用起来，伸手够到喝（2026-11-05）
                if sig["bedside"] and sig["thirst"] >= 0.88:
                    if now - self.last_bedside_at > 20 * 60:
                        self.last_bedside_at = now
                        self._write_event("bedside_drink", "thirst")
                    return ("her_room", bed,
                            incap_note + "，伸手够到床头的" + sig["bedside_name"],
                            0.45, incap_kind + "_bedside")
                # 嘴上会喊、脚动不了：25 分钟最多记一次，交给插件写成记忆
                if now - self.last_help_at > 25 * 60:
                    self.last_help_at = now
                    self._write_event(
                        "bed_need",
                        "thirst" if sig["thirst"] >= 0.88 else "hunger")
                return ("her_room", bed, incap_note + "，" + need, 0.45,
                        incap_kind + "_need")
            return ("her_room", bed, incap_note, 0.50, incap_kind)

        # 2.5) 有人让她去某个房间 → 听她的（身体不适和睡觉优先级更高）
        if self.manual and now < float(self.manual.get("until") or 0):
            room = self.manual["room"]
            key = self.manual["spot"]
            note = self.manual.get("note") or ("在" + ROOMS.get(room, {}).get("name", ""))
            return (room, spots[room][key], note, WALK, "manual")
        if self.manual:
            self.manual = {}

        # 3) 身体需求优先：渴/饿不能被视频或聊天一直压着
        if sig["fridge_need"] and (not sig["water_need"]
                                   or sig["hunger"] >= sig["thirst"]):
            return ("kitchen", spots["kitchen"]["fridge"],
                    "去冰箱拿吃的", WALK, "fridge")
        if sig["water_need"]:
            return ("living", spots["living"]["water"],
                    "去接水喝", WALK, "water")

        # 4) 视频 / 刚和你说过话 → 待在房间
        if sig["video"]:
            return ("her_room", spots["her_room"]["desk"], "和你视频", 0.95, "video")
        if now - sig["last_msg"] < 150:
            return ("her_room", spots["her_room"]["desk"], "和你说话", 1.0, "talk")

        # 4.5) 心情不好又被晾着 → 阳台散心
        if self._wants_balcony(sig, now):
            return ("balcony", spots["balcony"]["stand"], "散心", 0.72, "balcony")

        # 5) 夜里：还没睡着就窝在床上（"准备睡觉" → "迷迷糊糊" 两档）
        if sig["melatonin"] > 0.55 and hours >= 21.0:
            return ("her_room", spots["her_room"]["bed"], "准备睡觉", 0.72, "presleep")
        if hours >= 23.0 or hours < 7.0:
            return ("her_room", spots["her_room"]["mid"], "迷迷糊糊", TIRED, "night")
        if hours >= 22.0:
            return ("her_room", spots["her_room"]["bed"], "准备睡觉", 0.72, "presleep")

        # 6) 白天：按时间、心情在几个地方轮换
        if 7.0 <= hours < 11.0:
            return ("living", spots["living"]["sofa"], "晒太阳", WALK, "morning")
        if 11.0 <= hours < 14.0:
            return ("living", spots["living"]["tv"], "发呆", WALK, "noon")
        if 14.0 <= hours < 18.0:
            if self.wander_alt:
                return ("her_room", spots["her_room"]["desk"], "画画", WALK, "afternoon_h")
            return ("living", spots["living"]["sofa"], "看电视", WALK, "afternoon_l")

        # 7) 傍晚到睡前
        if 18.0 <= hours < 22.0:
            if sig["lonely"] > 0.62 and random.random() < 0.35:
                return ("dad_room", spots["dad_room"]["stand"], "去你房间", WALK, "dad_room")
            if self.wander_alt:
                return ("her_room", spots["her_room"]["desk"], "画画", WALK, "evening_h")
            return ("living", spots["living"]["sofa"], "看电视", WALK, "evening_l")

        # 8) 兜底：在房间里
        if sig["lonely"] > 0.55:
            return ("her_room", spots["her_room"]["window"], "看窗外", WALK, "window")
        return ("her_room", spots["her_room"]["mid"], "窝着", WALK, "idle")

    # ---------- 每一轮
    def tick(self):
        now = time.time()
        with self.lock:
            sig = self._read_signals(now)
            self._consume_moves(now)
            pos = route_pos(self.route, self.route_at, self.speed, now)

            # 每 12~26 分钟换一次"闲逛姿态"，别像个雕塑
            if now > self.next_wander_at:
                self.wander_alt = not self.wander_alt
                self.next_wander_at = now + random.uniform(720, 1560)

            room, spot, activity, speed, intent = self._decide(sig, now)
            arrived = dist(pos, self.spot) < 0.06 and now - self.route_at > 0.5

            if intent != self.intent or (arrived and dist(pos, spot) > 0.12):
                # 新念头：重新规划路线（按"人现在到底在哪间房"选起点节点）
                here = pos
                from_room = room_at(here) or self.room
                self.route = route_to(here, from_room, room, spot)
                self.route_at = now
                self.speed = speed
                self.room = room
                self.spot = list(spot)
                self.activity = activity
                if intent != self.intent:
                    self.since = now
                    self.intent = intent
                    self._note("%s · %s" % (ROOMS.get(room, {}).get("name", room), activity))
                if intent == "balcony" and self.balcony_since == 0:
                    self.balcony_since = now
                    self.balcony_fired = False
            else:
                self.room = room
                self.spot = list(spot)
                self.activity = activity

            # 阳台：到了一会儿就"透口气"（一个事件只能发一次）
            # 不管是自己去散心、还是被你叫去，吹到风就有效果
            on_balcony = self.room == "balcony" and self.intent in ("balcony", "manual")
            if on_balcony:
                if self.balcony_since == 0:
                    self.balcony_since = now
                    self.balcony_fired = False
                if not self.balcony_fired and now - self.balcony_since > 60:
                    self._write_event("balcony",
                                      "called" if self.intent == "manual" else "sad")
                    self.balcony_fired = True
                if self.intent == "balcony" and now - self.balcony_since > 9 * 60:
                    self.last_balcony_at = now
                    self.balcony_since = 0
                    self.intent = ""          # 下轮重新挑
            elif self.balcony_since:
                self.balcony_since = 0

            # 冰箱 / 饮水机：到地方待一会儿就通知插件"真的吃了/喝了"
            on_fridge = (self.room == "kitchen" and self.intent == "fridge"
                         and dist(pos, self.spot) < 0.16)
            if on_fridge:
                if self.fridge_since == 0:
                    self.fridge_since = now
                    self.fridge_fired = False
                if not self.fridge_fired and now - self.fridge_since > 25:
                    self._write_event("fridge_meal", "hungry")
                    self.fridge_fired = True
            else:
                self.fridge_since = 0
                self.fridge_fired = False

            on_water = (self.room == "living" and self.intent == "water"
                        and dist(pos, self.spot) < 0.14)
            if on_water:
                if self.water_since == 0:
                    self.water_since = now
                    self.water_fired = False
                if not self.water_fired and now - self.water_since > 15:
                    # 生理自主（§177）：喝水权交给她的决定后，自动去倒水的反射让位
                    try:
                        _g = json.load(open(r"D:\你的数据目录\state\persona\observer_gate.json", encoding="utf-8"))
                        _auto_water_off = bool((_g.get("rights") or {}).get("body_water"))
                    except Exception:
                        _auto_water_off = False
                    if not _auto_water_off:
                        self._write_event("water_drink", "thirsty")
                    self.water_fired = True
            else:
                self.water_since = 0
                self.water_fired = False

            if now - self._last_state_write > 5.0:
                self._last_state_write = now
                atomic_json(STATE_PATH, self.snapshot(now))

    def _note(self, text):
        self.events.append({"at": time.time(), "text": text})
        self.events = self.events[-6:]

    def _write_event(self, kind, why=""):
        try:
            with open(EVENTS_OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": kind, "t": time.time(), "why": why},
                                   ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ---------- 对外快照
    def snapshot(self, now=None):
        now = now or time.time()
        with self.lock:
            sig = self.signals or {}
            mood = self.mood or {}
            hr = time.localtime(now)
            pos = route_pos(self.route, self.route_at, self.speed, now)
            silence = 0.0
            if sig.get("last_msg"):
                silence = max(0.0, now - sig["last_msg"])
            return {
                "now": now,
                "clock": time.strftime("%H:%M", hr),
                "window": window_key(hr.tm_hour),
                "her": {
                    "name": "TA",
                    "room": self.room,
                    "room_name": ROOMS.get(self.room, {}).get("name", self.room),
                    "activity": self.activity,
                    "pos": [round(pos[0], 3), round(pos[1], 3)],
                    "route": [[round(p[0], 3), round(p[1], 3)] for p in self.route],
                    "route_at": self.route_at,
                    "speed": self.speed,
                    "since": self.since,
                    "asleep": bool(mood.get("asleep")),
                    "nap": str(mood.get("sleep_kind") or "") == "nap",
                    "manual": self.manual.get("note") if self.manual else "",
                    "avatar": "/static/avatar.png",
                },
                "mood": {
                    "emotion": mood.get("emotion_type") or "平静",
                    "level": mood.get("emotion_level") or "",
                    "valence": round(_num(mood, "valence", 0.0), 3),
                    "energy": round(_num(mood, "energy", 0.5), 3),
                    "hunger": round(_num(mood, "hunger", 0.0), 3),
                    "thirst": round(_num(mood, "thirst", 0.0), 3),
                    "bowel": round(_num(mood, "bowel_need",
                                        _num(mood, "bowel", 0.0)), 3),
                    "bladder": round(_num(mood, "bladder_need",
                                          _num(mood, "bladder", 0.0)), 3),
                    "toilet": str(mood.get("toilet_state") or ""),
                    "lonely": round(_num(mood, "loneliness", 0.0), 3),
                    "sad": round(_num(mood, "sadness", 0.0), 3),
                    "anger": round(_num(mood, "anger", 0.0), 3),
                    "cycle": mood.get("cycle_phase") or "",
                    "cramps": round(_num(mood, "cramps", 0.0), 3),
                    "fridge": len(mood.get("fridge_food") or []) if isinstance(mood.get("fridge_food"), list) else 0,
                    "period_pain": round(_num(
                        mood, "period_pain",
                        _num(mood, "cramps", 0.0) * (1.0 - 0.60 * _num(mood, "period_relief", 0.0))), 3),
                },
                "env": {
                    "lamp": bool(self.lamp),
                    "tv": bool(self.tv),
                    "video": bool(sig.get("video")),
                    "unanswered": int(sig.get("unanswered") or 0),
                    "silence_min": round(silence / 60.0, 1),
                    "dad_talking": silence < 150,
                },
                "events": self.events[-4:],
            }


HOUSE = House()


def _loop():
    while True:
        try:
            HOUSE.tick()
        except Exception as exc:  # noqa: BLE001 守护不能死
            print("[house] tick failed: %s" % exc, flush=True)
        time.sleep(TICK)


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "CompanionHouse/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None,
              cache="no-store", gzip_ok=False):
        if isinstance(body, str):
            body = body.encode("utf-8")
        extra = dict(extra or {})
        # 2026-11-05：文本资源按需 gzip。three.min.js 603KB→约150KB，
        # 三个 vendor 脚本加起来 1.3MB→约380KB。
        if (gzip_ok and len(body) > 1024
                and ctype.split(";")[0].strip() in self.GZIP_TYPES
                and "gzip" in (self.headers.get("Accept-Encoding") or "")):
            body = gzip.compress(body, 6)
            extra["Content-Encoding"] = "gzip"
            extra["Vary"] = "Accept-Encoding"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        for key, value in extra.items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    # ---------------------------------------------------------------- 缓存
    GZIP_TYPES = ("application/javascript", "text/css", "text/html",
                  "application/json", "image/svg+xml", "text/plain")

    @staticmethod
    def _etag(full):
        try:
            st = os.stat(full)
        except OSError:
            return None
        return '"%x-%x"' % (int(st.st_mtime), st.st_size)

    def _cache_policy(self, path):
        """代码和文档用 no-cache（带 ETag，没变就 304，不花流量也不旧）；
        模型/贴图/vendor/画可以放心缓存一天（带 ETag，换了立刻失效）。
        """
        low = path.lower()
        if low.endswith((".html", ".js", ".css", ".json")) or low in ("/", "/3d", "/2d", "/index.html"):
            return "no-cache"
        return "public, max-age=86400"

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw or b"{}")
        except Exception:
            return {}

    def do_POST(self):
        if gate.guard(self):
            return
        path = urlparse(self.path).path
        try:
            _len = int(self.headers.get("Content-Length") or 0)
        except Exception:
            _len = 0
        raw = self.rfile.read(_len) if _len else b""
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            body = {}
        try:
            if path == "/api/house/action":
                ok, msg = HOUSE.act(body.get("type"))
                return self._send(200 if ok else 400,
                                  json.dumps({"ok": ok, "msg": msg,
                                              "house": HOUSE.snapshot()},
                                             ensure_ascii=False))
            if path == "/api/house/tvframe":
                if len(raw) < 1000:
                    return self._send(400, '{"ok":false,"error":"frame too small"}')
                desc = HOUSE.tv_frame(raw)
                return self._send(200, json.dumps(
                    {"ok": bool(desc), "desc": desc,
                     "house": HOUSE.snapshot()}, ensure_ascii=False))
            if path == "/api/house/move":
                ok = HOUSE.move_to(body.get("room"), body.get("spot"),
                                   body.get("x"), body.get("z"),
                                   str(body.get("note") or "你让我过去"))
                return self._send(200 if ok else 400,
                                  json.dumps({"ok": ok, "house": HOUSE.snapshot()},
                                             ensure_ascii=False))
            return self._send(404, '{"error":"not found"}')
        except Exception as exc:  # noqa: BLE001
            return self._send(500, json.dumps({"ok": False, "error": str(exc)},
                                              ensure_ascii=False))

    def do_GET(self):
        if gate.guard(self):
            return
        path = urlparse(self.path).path
        try:
            if path == "/":
                return self._file(os.path.join(STATIC, "three.html"), "text/html; charset=utf-8")
            if path in ("/2d", "/index.html"):
                return self._file(os.path.join(STATIC, "index.html"), "text/html; charset=utf-8")
            if path == "/api/house":
                return self._send(200, json.dumps(HOUSE.snapshot(), ensure_ascii=False))
            if path == "/plan.json":
                return self._file(PLAN_PATH)
            if path == "/art/index.json":
                idx = os.path.join(ART_DIR, "index.json")
                if not os.path.isfile(idx):
                    return self._send(200, "[]", "application/json; charset=utf-8")
                return self._file(idx)
            if path.startswith("/art/file/"):
                name = os.path.basename(unquote(path[len("/art/file/"):]))
                full = os.path.normpath(os.path.join(ART_DIR, name))
                if not full.startswith(os.path.normpath(ART_DIR) + os.sep) or not os.path.isfile(full):
                    return self._send(404, '{"error":"no art"}')
                return self._file(full, self._ctype(full))
            if path.startswith("/bg/"):
                name = os.path.basename(path)[:-4]
                if name not in ("dawn", "morning", "noon", "afternoon", "evening", "night"):
                    return self._send(404, '{"error":"no bg"}')
                return self._file(os.path.join(BG_DIR, name + ".jpg"), "image/jpeg")
            if path == "/3d":
                return self._file(os.path.join(STATIC, "three.html"), "text/html; charset=utf-8")
            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                root = os.path.normpath(STATIC)
                full = os.path.normpath(os.path.join(root, rel))
                if not (full == root or full.startswith(root + os.sep)):
                    return self._send(403, '{"error":"forbidden"}')
                if not os.path.isfile(full):
                    return self._send(404, '{"error":"not found"}')
                return self._file(full, self._ctype(full))
            if path == "/favicon.ico":
                return self._send(204, b"")
            return self._send(404, '{"error":"not found"}')
        except Exception as exc:  # noqa: BLE001
            return self._send(500, json.dumps({"error": str(exc)}))

    @staticmethod
    def _ctype(name):
        ext = os.path.splitext(name)[1].lower()
        return {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }.get(ext, "application/octet-stream")

    def _file(self, full, ctype=None):
        ctype = ctype or self._ctype(full)
        path = urlparse(self.path).path
        cache = self._cache_policy(path)
        etag = self._etag(full)
        # 浏览器再来看同一份东西：没变就只回 304，一个字节正文都不发。
        inm = (self.headers.get("If-None-Match") or "").strip()
        if etag and inm:
            cand = inm.replace("W/", "").strip()
            if cand == etag or cand == "*":
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", cache)
                self.end_headers()
                return
        try:
            with open(full, "rb") as f:
                body = f.read()
        except OSError:
            return self._send(404, '{"error":"not found"}')
        return self._send(200, body, ctype,
                          extra={"ETag": etag} if etag else None,
                          cache=cache, gzip_ok=True)


def main():
    threading.Thread(target=_loop, daemon=True).start()
    time.sleep(0.3)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("[house] 大平层服务 http://127.0.0.1:%d/" % PORT, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
