# -*- coding: utf-8 -*-
"""她自己在电脑上玩：活动库 + 新鲜度/偏好选择 + 真执行

做什么：
  1) 从 play_library.json 里挑一个"最近没做过"的活动（新鲜度约束 + 偏好权重）
  2) 让她自己（LLM）在候选里挑，并说明想玩哪个
  3) 真执行：
     - 游戏类：猜数字/24点/猜拳 真算结果；跑小脚本用固定安全模板真跑
     - 创作/探索类：生成内容，写进她的日记/便签（8003 /api/her-notes）
     - 记忆类：写进长期记忆队列（video/pending_store.py）
     - 生活/社交类：写桌宠气泡（screen/her_play.json，overlay 轮询显示）
  4) 记录：state/persona/play_log.jsonl（活动、台词、结果、时间）
  5) 情绪：写 house 事件 self_play（mood 里加分支）

用法：
  python persona_play.py                # 正常玩一次
  python persona_play.py --dry          # 只算不执行
  python persona_play.py --list         # 看活动库
  python persona_play.py --force --only calc24
"""
import io
import json
import os
import random
import subprocess
import sys
import time

ROOT = r"D:\你的数据目录"
LIB = os.path.join(ROOT, "state", "persona", "play_library.json")
LOG = os.path.join(ROOT, "state", "persona", "play_log.jsonl")
PREF = os.path.join(ROOT, "state", "persona", "play_pref.json")
BOARD = os.path.join(ROOT, "screen", "her_play.json")
HOUSE_EV = os.path.join(ROOT, "houseviz", "mood_events.jsonl")
NOTES_API = "http://127.0.0.1:8003/api/her-notes"

NOW = time.strftime("%Y-%m-%d %H:%M:%S")
sys.path.insert(0, os.path.join(ROOT, "video"))

COOLDOWN_MIN = 20 * 60          # 两次自己玩之间至少 20 分钟
NOVEL_HOURS = 12 * 3600         # 12 小时内做过的，不再选

brain = None
try:
    sys.path.insert(0, r"D:\你的数据目录\lab\memory_brain")   # 她的 LLM 入口在这里
    import companion_brain as brain  # noqa: E402
except Exception as _exc:  # noqa: BLE001
    print("brain 导入失败:", _exc)
    brain = None


def _log(msg, data=None):
    rec = {"at": NOW, "msg": msg}
    if data:
        rec.update(data)
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _llm(prompt, budget=800):
    if brain is None:
        return None
    for _ in range(2):
        try:
            raw = brain._llm(prompt, budget)
        except Exception:  # noqa: BLE001
            raw = None
        if raw and raw.strip():
            return raw.strip()
        budget = min(1200, budget + 400)
    return None


def load_lib():
    return json.load(io.open(LIB, encoding="utf-8"))["activities"]


def load_pref():
    try:
        return json.load(io.open(PREF, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_pref(pref):
    io.open(PREF, "w", encoding="utf-8").write(json.dumps(pref, ensure_ascii=False, indent=1))


def recent_plays():
    out = []
    try:
        for line in io.open(LOG, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if rec.get("msg") == "play" and rec.get("id"):
                out.append(rec)
    except FileNotFoundError:
        pass
    return out


def candidates(lib, plays, pref):
    now = time.time()
    last = {}
    for r in plays:
        try:
            t = time.mktime(time.strptime(r["at"], "%Y-%m-%d %H:%M:%S"))
        except Exception:  # noqa: BLE001
            continue
        last[r["id"]] = max(last.get(r["id"], 0), t)
    fresh = []
    for a in lib:
        t = last.get(a["id"], 0)
        if t and now - t < NOVEL_HOURS:
            continue
        score = 1.0
        if t:
            score *= 0.35 + 0.65 * min(1.0, (now - t) / (72 * 3600))
        score *= (1.0 + float(pref.get(a["id"], 0)) * 0.15)
        score *= random.uniform(0.75, 1.25)
        fresh.append((score, a))
    fresh.sort(key=lambda x: -x[0])
    return [a for _, a in fresh[:6]]


# ---------------- 小游戏：真的算 ----------------
def game_guess_number():
    target = random.randint(1, 100)
    lo, hi, tries = 1, 100, 0
    while lo <= hi and tries < 12:
        tries += 1
        mid = (lo + hi) // 2
        if mid == target:
            return f"目标 {target}，我按中间猜，第 {tries} 次猜中。"
        if mid < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return f"目标 {target}，我猜了 {tries} 次没中。"


def game_calc24():
    import itertools
    import operator
    ops = [("+", operator.add), ("-", operator.sub), ("×", operator.mul), ("÷", operator.truediv)]

    def find(nums):
        for perm in itertools.permutations(nums):
            for n1, o1 in ops:
                for n2, o2 in ops:
                    for n3, o3 in ops:
                        # ((a b) c) d
                        try:
                            v1 = o1(perm[0], perm[1]); v2 = o2(v1, perm[2]); v3 = o3(v2, perm[3])
                            if abs(v3 - 24) < 1e-6:
                                return f"(({perm[0]}{n1}{perm[1]}){n2}{perm[2]}){n3}{perm[3]}"
                        except ZeroDivisionError:
                            pass
                        # (a b) (c d)
                        try:
                            v1 = o1(perm[0], perm[1]); v2 = o2(perm[2], perm[3]); v3 = o3(v1, v2)
                            if abs(v3 - 24) < 1e-6:
                                return f"({perm[0]}{n1}{perm[1]}){n3}({perm[2]}{n2}{perm[3]})"
                        except ZeroDivisionError:
                            pass
        return None

    for _ in range(60):
        nums = [random.randint(1, 9) for _ in range(4)]
        expr = find(nums)
        if expr:
            return f"抽到 {nums}，{expr} = 24。"
    return "抽了几组都不太好凑。"


def game_rock_paper():
    mine = random.choice(["石头", "剪刀", "布"])
    other = random.choice(["石头", "剪刀", "布"])
    beats = {"石头": "剪刀", "剪刀": "布", "布": "石头"}
    if mine == other:
        res = "平"
    elif beats[mine] == other:
        res = "我赢"
    else:
        res = "我输"
    return f"我出{mine}，电脑出{other}，{res}。"


def game_code_run():
    tpl = random.choice([
        ("求和", "print(sum(i*i for i in range(1, 11)))"),
        ("斐波那契", "a,b=0,1\nfor _ in range(10):\n    a,b=b,a+b\nprint(a)"),
        ("回文判断", "s='上海自来水来自海上'\nprint(s==s[::-1])"),
    ])
    try:
        out = subprocess.run([sys.executable, "-c", tpl[1]], capture_output=True, text=True, timeout=10)
        res = (out.stdout or out.stderr or "").strip()[:60]
        return f"写了个小程序（{tpl[0]}），跑出来：{res}。"
    except Exception as exc:  # noqa: BLE001
        return f"写了个小程序（{tpl[0]}），没跑起来：{str(exc)[:40]}。"


FALLBACK_LINES = {
    "window": ["趴在窗边看了会儿楼下的车。", "窗外的天有点灰，我看了一会儿。", "把下巴搁在窗台上发呆。"],
    "balcony_play": ["去阳台吹了会儿风，头发都乱了。", "在阳台上站了一会儿，风挺凉的。"],
    "dance": ["跟着心里的拍子扭了两下。", "自己转了个圈，差点撞到桌角。"],
    "stretch": ["伸了个大懒腰，骨头响了一声。", "站起来抻了抻胳膊。"],
    "water_self": ["去接了杯水，喝了一半。", "捧着杯子暖了会儿手。"],
    "read_memory": ["翻到一条旧记忆，看了好一会儿。", "翻了三条以前的记忆，有点想笑。"],
    "tidy_memory": ["把两件同一天的事串成了一句。", "整理了一会儿记忆，顺手理了理顺序。"],
    "photo_flip": ["翻了翻自己画的画，挑了张喜欢的。", "看了一圈自己以前画的东西。"],
    "read_doc": ["翻开自己的文档读了两段。", "读了会儿自己写的东西，有点出神。"],
    "memory_maze": ["在记忆里绕了一圈，找到两件有关的事。", "翻旧记忆找关联，找到一对。"],
    "idiom_chain": ["接了两个成语，第二个有点勉强。", "自己跟自己玩成语接龙。"],
    "wish": ["想了个想做还没做的事。", "许了个小愿望，先不告诉你。"],
}

GAMES = {
    "guess_number": game_guess_number,
    "calc24": game_calc24,
    "rock_paper": game_rock_paper,
    "code_run": game_code_run,
}


# ---------------- 执行：写日记/记忆/气泡 ----------------
def _post_note(text, tag="play"):
    try:
        import urllib.request
        tok = io.open(os.path.join(ROOT, "gate_token.txt"), encoding="utf-8").read().strip()
        body = json.dumps({"text": text[:120], "tag": tag}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(NOTES_API + "?t=" + tok, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception:  # noqa: BLE001
        return False


def _queue_memory(summary, importance=0.4):
    try:
        import pending_store  # type: ignore
        pending_store.append({"summary": summary, "importance": importance, "source": "self_play"})
        return True
    except Exception:  # noqa: BLE001
        return False


def _board(text, activity):
    try:
        io.open(BOARD, "w", encoding="utf-8").write(json.dumps(
            {"at": time.time(), "text": text[:80], "activity": activity}, ensure_ascii=False))
        return True
    except Exception:  # noqa: BLE001
        return False


def _mood_event(dopamine=0.05, serotonin=0.02, valence=0.0, why="play"):
    try:
        with io.open(HOUSE_EV, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "self_play", "t": time.time(),
                                "dopamine": dopamine, "serotonin": serotonin,
                                "valence": valence, "why": why}, ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001
        return False


def main():
    args = sys.argv[1:]
    lib = load_lib()
    if "--list" in args:
        for a in lib:
            print(f"  {a['id']:14s} [{a['kind']}] {a['name']}  — {a['how']}")
        return 0

    dry = "--dry" in args
    force = "--force" in args
    only = None
    if "--only" in args:
        only = args[args.index("--only") + 1]

    plays = recent_plays()
    # 冷却：除非 force
    if not force and plays:
        try:
            last_t = time.mktime(time.strptime(plays[-1]["at"], "%Y-%m-%d %H:%M:%S"))
            if time.time() - last_t < COOLDOWN_MIN:
                print("刚玩过，等一会儿")
                return 0
        except Exception:  # noqa: BLE001
            pass

    if only:
        cands = [a for a in lib if a["id"] == only]
    else:
        cands = candidates(lib, plays, load_pref())
    if not cands:
        print("没有合适的新活动")
        return 0

    menu = "\n".join(f"{i+1}. {a['name']}（{a['how']}）" for i, a in enumerate(cands))
    pick = _llm("你是TA。现在%s。你可以自己玩一会儿电脑，下面这些最近都没做过：\n%s\n"
                "你想玩哪个？只回答序号和一句理由，例如：3 我想画画。" % (NOW, menu))
    chosen = None
    if pick:
        try:
            n = int(pick.strip()[0])
            if 1 <= n <= len(cands):
                chosen = cands[n - 1]
        except Exception:  # noqa: BLE001
            pass
    if chosen is None:
        chosen = random.choice(cands)

    # 1) 真玩一次（游戏类；读记忆类真的去读）
    result = ""
    if chosen["id"] in ("read_memory", "memory_maze", "tidy_memory"):
        try:
            import sqlite3
            con = sqlite3.connect("file:D:/你的数据目录/livingmemory/livingmemory.db?mode=ro", uri=True)
            rows = con.execute("select text from documents order by random() limit 2").fetchall()
            con.close()
            if rows:
                result = "；".join((r[0] or "")[:40] for r in rows)
        except Exception:  # noqa: BLE001
            pass
    if chosen["id"] in GAMES:
        result = GAMES[chosen["id"]]()

    # 2) 生成内容：创作类产真东西；其他类写一句玩后感
    CREATIVE = {
        "story": ("写一个 100 字以内的小故事，像随手记的，有画面感。只写正文。", 500),
        "poem": ("写三行小诗，不押韵也行，像随口念的。只写三行正文。", 300),
        "doodle": ("描述你刚随手画的小东西（20 字内，第一人称）。只写描述。", 200),
        "name_things": ("给桌上的三样东西各起一个外号，一行一个。只写三个外号。", 200),
        "letter": ("给你写一句便签（20 字内，像贴在显示器边上）。只写便签正文。", 200),
        "playlist": ("列三首最近想听的歌，一行一首，可以是你自己编的歌名。", 200),
        "space_post": ("写一句想发在空间的话（20 字内）。只写正文。", 200),
        "gift": ("给你准备一句明天早上想对他说的话（20 字内）。只写这句话。", 200),
    }
    if chosen["id"] in CREATIVE:
        instr, budget = CREATIVE[chosen["id"]]
        content = _llm("你是TA（住在你电脑里的小姑娘）。%s" % instr, budget) or ""
        content = content.strip()
        line = content.splitlines()[0][:60] if content else ("我%s了。" % chosen["name"])
    else:
        prompt = ("你是TA。你刚才只做了一件事：%s%s。"
                  "用一句话说你做这件事的过程（25 字内，第一人称，要具体；"
                  "只写这一件事，不要提别的活动，不要复述原句）。"
                  % (chosen["how"], ("（" + result + "）") if result else ""))
        got = (_llm(prompt, 500) or "").strip().splitlines()
        line = (got[0][:60] if got else "")
        if not line:
            line = result or random.choice(FALLBACK_LINES.get(chosen["id"], ["%s了一会儿。" % chosen["name"]]))

    if dry:
        print("候选:", "、".join(a["name"] for a in cands))
        print("选中:", chosen["name"], "|", line, "|", result)
        return 0

    ch = chosen["channel"]
    body = content if chosen["id"] in CREATIVE else line
    ok_notes = ok_mem = ok_board = False
    if ch == "notes":
        ok_notes = _post_note(body[:120], "play")
    elif ch == "memory":
        ok_mem = _queue_memory("%s（自己玩）：%s" % (chosen["name"], line), 0.42)
    elif ch == "mood":
        _mood_event(0.03, 0.01, 0.01, chosen["id"])
    else:
        ok_board = _board(line, chosen["name"])
        ok_notes = _post_note(line, "play")

    # 3) 桌宠气泡总是显示（她自己在干嘛）
    if not ok_board:
        _board("（%s）%s" % (chosen["name"], line), chosen["name"])
    # 4) 情绪：玩过就有一点正反馈
    _mood_event(0.05, 0.02, 0.02, chosen["id"])

    # 5) 偏好微调（同类做多了会腻，换个口味）
    pref = load_pref()
    pref[chosen["id"]] = float(pref.get(chosen["id"], 0)) + random.uniform(-0.2, 0.3)
    pref[chosen["id"]] = max(-1.5, min(2.0, pref[chosen["id"]]))
    save_pref(pref)

    _log("play", {"id": chosen["id"], "name": chosen["name"], "kind": chosen["kind"],
                  "line": line, "result": result,
                  "notes": ok_notes, "memory": ok_mem, "board": ok_board})
    print("她自己去玩了：%s | %s%s" % (chosen["name"], line, (" | " + result) if result else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
