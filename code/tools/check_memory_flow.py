"""记忆链路体检：五个通道写进来的东西，有没有卡在中间。

只看不写。用法: python check_memory_flow.py
"""
import json
import os
import sqlite3
import sys
import time

# Windows 控制台默认 GBK，打印 ⚠ 会 UnicodeEncodeError 把输出打断
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
PENDING = r"D:\你的数据目录\video\pending_memories.json"
VIDEO_RECENT = r"D:\你的数据目录\video\video_recent.json"
QQ_RECENT = r"D:\你的数据目录\video\qq_recent.json"
STALE_MINUTES = 5


def load_list(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def fmt_age(seconds):
    if seconds < 60:
        return "%d 秒" % seconds
    if seconds < 3600:
        return "%d 分钟" % (seconds // 60)
    return "%.1f 小时" % (seconds / 3600)




def health_line(append=False):
    """一行健康日志：每天跑一次，退化一眼可见。

    格式：
      [memory] 2026-10-30 00:20 total=51 pinned=17 cold=2 inject_cap=1200
               ledger=OK pending=0 miss=-  warn=
    """
    import sys as _sys

    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import memory_ledger as led

    docs = led.load_docs()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    pinned = cold = 0
    for (meta,) in con.execute("SELECT metadata FROM documents"):
        try:
            imp = float(json.loads(meta or "{}").get("importance") or 0)
        except Exception:
            imp = 0.0
        if imp >= 0.7:
            pinned += 1
        elif imp < 0.2:
            cold += 1
    con.close()

    # 账本状态
    status = "NO-LEDGER"
    ledger = led.load_ledger()
    if ledger is not None:
        entries = ledger.get("entries", {})
        supp = led.load_supplement()
        supp_retired = led.supplement_retired(supp)
        supp_rehashed = led.supplement_rehashed(supp)
        missing = [k for k in entries if k not in supp_retired and int(k) not in docs]
        changed = [k for k in entries
                   if k not in supp_retired and int(k) in docs
                   and led.sha(docs[int(k)]) != (supp_rehashed.get(k) or entries[k]).get("sha256")]
        status = "OK" if not missing and not changed else f"FAIL(miss={len(missing)},chg={len(changed)})"

    pending = len(load_list(PENDING))
    warns = []
    if status.startswith("FAIL") or status == "NO-LEDGER":
        warns.append("ledger")
    if pending > 50:
        warns.append("pending积压")
    if pinned > 30:
        warns.append("pinned过多")

    line = ("[memory] {ts} total={tot} pinned={pin} cold={cold} inject_cap=1200 "
            "ledger={st} pending={pend}{warn}").format(
        ts=time.strftime("%Y-%m-%d %H:%M"), tot=len(docs), pin=pinned, cold=cold,
        st=status, pend=pending, warn=(" warn=" + ",".join(warns)) if warns else "")
    print(line)
    if append:
        log = r"D:\你的数据目录\logs\memory-health.log"
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return 1 if warns else 0


def main():
    now = time.time()
    print("== 记忆库")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        docs = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        fts = con.execute("SELECT COUNT(*) FROM documents_fts").fetchone()[0]
        print(f"  integrity={integrity} | 文档 {docs} | FTS {fts}"
              f"{'  ⚠ 不一致' if docs != fts else ''}")

        sources = {}
        for (meta,) in con.execute("SELECT metadata FROM documents"):
            try:
                meta = json.loads(meta or "{}")
            except Exception:
                meta = {}
            key = meta.get("source") or "(QQ 反思)"
            sources[key] = sources.get(key, 0) + 1
        print("  来源分布: " + " · ".join(f"{k} {v}" for k, v in
                                        sorted(sources.items(), key=lambda x: -x[1])))
    finally:
        con.close()

    print("\n== 待处理队列（视频/陪玩/味觉/空间都走这里）")
    pending = load_list(PENDING)
    print(f"  条数: {len(pending)}")
    if pending:
        oldest = min(float(item.get("time") or now) for item in pending)
        age = now - oldest
        srcs = {}
        for item in pending:
            key = item.get("source") or "未标注"
            srcs[key] = srcs.get(key, 0) + 1
        print(f"  最老一条: {fmt_age(age)} 前 | 来源: {srcs}")
        if age > STALE_MINUTES * 60:
            print(f"  ⚠ 超过 {STALE_MINUTES} 分钟没被消化，检查 video_bridge 插件")
        if len(pending) > 50:
            print("  ⚠ 积压偏多，确认 AstrBot 的记忆引擎是否正常")
    else:
        print("  空（都已总结入库）")

    print("\n== 最近上下文缓存（只用于对话衔接，不算长期记忆）")
    for name, path in (("视频", VIDEO_RECENT), ("QQ", QQ_RECENT)):
        items = load_list(path)
        if not items:
            print(f"  {name}: 空")
            continue
        last = max(float(item.get("time") or 0) for item in items)
        print(f"  {name}: {len(items)} 条，最后一条 {fmt_age(now - last)} 前")

    print("\n== 最近 5 条记忆是谁写的")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        for doc_id, created, meta in con.execute(
            "SELECT id, created_at, metadata FROM documents ORDER BY id DESC LIMIT 5"
        ):
            try:
                meta = json.loads(meta or "{}")
            except Exception:
                meta = {}
            print(f"  id={doc_id} {str(created)[5:16]} "
                  f"source={meta.get('source') or '(QQ 反思)'} "
                  f"importance={meta.get('importance')}")
    finally:
        con.close()

    print("\n判定：pending 空 + integrity ok = 链路通畅；"
          "\n      若 pending 长期积压或某来源长期为 0，再往下查。")


if __name__ == "__main__":
    import sys as _s
    if "--line" in _s.argv:
        _s.exit(health_line(append="--append" in _s.argv))
    main()
