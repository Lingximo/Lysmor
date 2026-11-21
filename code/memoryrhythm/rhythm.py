"""TA记忆的拟人化遗忘（艾宾浩斯曲线）

为什么要重做：原来的衰减是"每天固定 1%"的乘法，所有记忆一个速度，
被想起也只是把速度减半。人不是这样忘东西的：

  刚经历 → 头几个小时几乎不丢
  第 1~3 天 → 掉得最快（第一次遗忘潮）
  被反复想起 → 记忆变"牢"，掉得越来越慢（间隔效应）
  情绪浓的、重要的 → 几乎不掉
  很久没碰的 → 缓慢淡出，而不是某天突然归零

所以这里给每条记忆算一条自己的曲线：

  rate = 基准 0.008/天
         × 新鲜度（越新掉越快，2 天半衰）
         × 重要性（importance 越高越慢）
         × 回忆加固（access_count 越多、最近想起过，越慢）
         × 情绪（带 positive/negative 的，慢 15%）
  新重要性 = 旧值 × (1 - rate)，每天最多掉 0.03

几条硬规矩：
  - importance >= 0.7 完全不碰（她刻在心里的东西）
  - 6 小时内刚形成的记忆不衰减
  - 每次被回忆（access_count 增加）给 +0.02 加固，封顶 0.68
  - 绝对值不低于 0.05
  - 写入前先做一次完整备份并校验

用法:
  python rhythm.py              只算不写（默认，看今天会怎么变）
  python rhythm.py --apply      真写，会先备份
  python rhythm.py --explain ID 打印某条记忆的推导过程
"""
import json
import math
import os
import sqlite3
import sys
import time
from datetime import datetime

DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
BACKUP_DIR = r"D:\你的数据目录\livingmemory\backups"
HOME = r"D:\你的数据目录\memoryrhythm"
STATE = os.path.join(HOME, "state.json")
AUDIT = os.path.join(HOME, "decay_audit.jsonl")
SAFETY_BACKUP = os.path.join(BACKUP_DIR, "before_rhythm_decay.db")

BASE_RATE = 0.008          # 每天的基准衰减率（旧模型是 0.01）
MAX_DAILY_DROP = 0.03      # 拟人化：一天不会忘太多
FLOOR = 0.05               # 再淡也有个底
PROTECTED = 0.70           # 到这个重要性就不衰减了
FRESH_HOURS = 6.0          # 新鲜期
REINFORCE = 0.02           # 每被想起一次加多少
REINFORCE_CAP = 0.68       # 加固不会自己跨进保护区


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"access": {}, "last_apply": ""}


def save_state(state):
    os.makedirs(HOME, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)


def parse_time(value):
    if not value:
        return time.time()
    try:
        return datetime.fromisoformat(str(value)[:19]).timestamp()
    except ValueError:
        return time.time()


def freshness(age_days):
    """越新的记忆，掉得越快 —— 艾宾浩斯曲线最陡的那一段。"""
    if age_days < FRESH_HOURS / 24.0:
        return 0.0
    return min(2.5, 1.0 + 1.5 * math.exp(-age_days / 2.0))


def salience(importance):
    """重要的事，忘得慢。"""
    ratio = min(1.0, max(0.0, importance / PROTECTED))
    return max(0.55, min(1.45, 0.55 + 0.9 * (1.0 - ratio)))


def review_factor(access_count, last_access_ts):
    """被想起过的记忆更牢（间隔效应）。"""
    base = 1.0 / (1.0 + 0.5 * math.log(1.0 + max(0.0, access_count)))
    if last_access_ts and (time.time() - last_access_ts) < 3 * 86400:
        base *= 0.75
    return base


def emotion_factor(sentiment):
    """带情绪的记得更久。"""
    return 0.85 if sentiment in ("positive", "negative") else 1.0


def explain(importance, age_days, accesses, last_access, sentiment):
    f = freshness(age_days)
    s = salience(importance)
    r = review_factor(accesses, last_access)
    e = emotion_factor(sentiment)
    rate = min(0.08, BASE_RATE * f * s * r * e)
    drop = min(importance * rate, MAX_DAILY_DROP)
    return {
        "freshness": f, "salience": s, "review": r, "emotion": e,
        "rate": rate, "drop": drop,
    }


def phase_of(new_importance, age_days):
    if new_importance >= PROTECTED:
        return "刻在心里"
    if age_days < 1:
        return "还新鲜"
    if new_importance >= 0.55:
        return "记得清楚"
    if new_importance >= 0.45:
        return "有点模糊"
    if new_importance >= 0.3:
        return "快忘了"
    return "几乎想不起"


def backup():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    dst = sqlite3.connect(SAFETY_BACKUP)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    check = sqlite3.connect(f"file:{SAFETY_BACKUP}?mode=ro", uri=True)
    ok = check.execute("PRAGMA integrity_check").fetchone()[0]
    check.close()
    if ok != "ok":
        raise RuntimeError("衰减前备份校验失败: %s" % ok)
    return SAFETY_BACKUP


def collect():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, created_at, metadata FROM documents"
    ).fetchall()
    con.close()
    out = []
    for row in rows:
        try:
            meta = json.loads(row["metadata"] or "{}")
        except Exception:
            meta = {}
        imp = meta.get("importance")
        if imp is None:
            continue
        out.append({
            "id": int(row["id"]),
            "age": (time.time() - parse_time(row["created_at"])) / 86400.0,
            "importance": float(imp),
            "accesses": float(meta.get("access_count") or 0),
            "last_access": float(meta.get("last_access_time") or 0),
            "sentiment": meta.get("sentiment"),
            "summary": (meta.get("canonical_summary") or "")[:40],
        })
    return out


def plan(state):
    """算出每条记忆今天该变成多少。"""
    docs = collect()
    prev_access = state.get("access") or {}
    changes = []
    for d in docs:
        d["phase"] = phase_of(d["importance"], d["age"])
        if d["importance"] >= PROTECTED:
            continue
        if d["age"] < FRESH_HOURS / 24.0:
            continue
        new = d["importance"]

        # 先结算"被想起"：回忆本身就是加固
        before = prev_access.get(str(d["id"]))
        if before is not None and d["accesses"] > before:
            gained = min(REINFORCE * (d["accesses"] - before), 0.06)
            new = min(REINFORCE_CAP, new + gained)
            d["reinforced"] = round(new - d["importance"], 4)

        detail = explain(d["importance"], d["age"], d["accesses"],
                         d["last_access"], d["sentiment"])
        new = max(FLOOR, new * (1.0 - detail["rate"]))
        new = max(d["importance"] - MAX_DAILY_DROP, new)
        new = round(new, 4)
        d.update(detail)
        d["new"] = new
        d["phase"] = phase_of(new, d["age"])
        if abs(new - d["importance"]) > 0.0005:
            changes.append(d)
    return docs, changes


def report(docs, changes):
    protected = sum(1 for d in docs if d["importance"] >= PROTECTED)
    fresh = sum(1 for d in docs if d["age"] < FRESH_HOURS / 24.0)
    print("== 记忆体温 %s" % time.strftime("%Y-%m-%d %H:%M"))
    print(f"  共 {len(docs)} 条：刻在心里 {protected}，还新鲜 {fresh}，"
          f"今天会变 {len(changes)}")
    if not changes:
        print("  今天没有需要变化的记忆")
        return
    print("\n  %-5s %-6s %-6s %-6s %-7s %s" % ("id", "现在", "之后", "年龄", "每天掉", "状态"))
    for d in sorted(changes, key=lambda x: -x["drop"])[:20]:
        mark = "+" if d.get("reinforced") else " "
        print("  %-5d %-6.3f %-6.3f %-6.1f %-7.4f %s%s" % (
            d["id"], d["importance"], d["new"], d["age"], d["drop"],
            d["phase"], mark))
    total_before = sum(d["importance"] for d in docs)
    total_after = total_before - sum(d["importance"] - d["new"] for d in changes)
    print(f"\n  全库重要性总和 {total_before:.2f} -> {total_after:.2f}"
          f"（{(total_after-total_before)/total_before*100:+.2f}%）")
    old_drop = sum(d["importance"] * 0.01 for d in docs
                   if d["importance"] < PROTECTED)
    new_drop = total_before - total_after
    print(f"  旧模型（固定 1%/天）今天会掉 {old_drop:.3f}，"
          f"拟人化曲线今天掉 {new_drop:.3f}")


def apply(changes, state):
    if not changes:
        return 0
    path = backup()
    print("  已备份:", path)
    con = sqlite3.connect(DB, timeout=30)
    try:
        with con:
            for d in changes:
                con.execute(
                    "UPDATE documents SET metadata = json_set(metadata, '$.importance', ?) "
                    "WHERE id = ?", (d["new"], d["id"]))
        # 审计日志
        os.makedirs(HOME, exist_ok=True)
        with open(AUDIT, "a", encoding="utf-8") as f:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            for d in changes:
                f.write(json.dumps({
                    "at": stamp, "id": d["id"],
                    "from": d["importance"], "to": d["new"],
                    "age_days": round(d["age"], 2),
                    "rate": round(d["rate"], 5),
                    "reinforced": d.get("reinforced", 0),
                    "phase": d["phase"],
                    "summary": d["summary"],
                }, ensure_ascii=False) + "\n")
    finally:
        con.close()
    return len(changes)


def curve():
    """把新旧两条曲线摆出来看：同一批记忆，1/3/7/30/90/365 天后还剩多少。"""
    samples = [
        ("普通小事 0.45，从没想起过", 0.45, 0, 0),
        ("普通小事 0.45，想起过 5 次", 0.45, 5, time.time()),
        ("有点分量 0.60，想起过 2 次", 0.60, 2, time.time() - 5 * 86400),
        ("重要 0.69，常被想起", 0.69, 10, time.time()),
    ]
    days_list = [1, 3, 7, 30, 90, 365]
    print("== 拟人化曲线 vs 旧的「每天固定 1%」\n")
    for label, imp, acc, last in samples:
        old = new = imp
        rec_old, rec_new = {}, {}
        for day in range(1, 366):
            rate = explain(new, day + 0.5, acc, last, None)["rate"]
            new = max(FLOOR, new * (1.0 - rate))
            old = old * 0.99
            if day in days_list:
                rec_old[day] = old
                rec_new[day] = new
        print("  " + label)
        print("      " + "  ".join(f"{d:>5}天" for d in days_list))
        print("    旧 " + "  ".join(f"{rec_old[d]:.3f}" for d in days_list))
        print("    新 " + "  ".join(f"{rec_new[d]:.3f}" for d in days_list))
        print()


def main():
    os.makedirs(HOME, exist_ok=True)
    if "--curve" in sys.argv:
        curve()
        return 0
    state = load_state()
    docs, changes = plan(state)

    if "--explain" in sys.argv:
        target = int(sys.argv[sys.argv.index("--explain") + 1])
        for d in docs:
            if d["id"] == target:
                detail = explain(d["importance"], d["age"], d["accesses"],
                                 d["last_access"], d["sentiment"])
                print(json.dumps({**d, **detail}, ensure_ascii=False, indent=2,
                                 default=str))
                return 0
        print("没有这条记忆")
        return 1

    report(docs, changes)

    if "--apply" in sys.argv:
        n = apply(changes, state)
        state["access"] = {str(d["id"]): d["accesses"] for d in docs}
        state["last_apply"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_state(state)
        print(f"  已写入 {n} 条")
        # 2026-11-03：衰减完顺手刷新场景卡（只读库、只写 memoryscene/）。
        # 失败只提示，绝不影响已经写进去的衰减结果。
        try:
            import subprocess
            subprocess.run(
                [sys.executable, r"D:\你的数据目录\memoryscene\make_scenes.py"],
                check=False, timeout=180,
            )
            print("  场景卡已刷新")
        except Exception as exc:  # noqa: BLE001
            print(f"  场景卡刷新失败（不影响衰减）：{exc}")
    else:
        print("  （只演算，没写入。要生效加 --apply）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
