"""记忆文本账本：证明"一年后没丢过、没被改过"。

原理很简单：
  - 每条记忆写入后，记下它正文的 SHA256 和长度
  - 以后每次校验，逐条比对：还在不在、正文有没有变
  - 账本只增不减：新记忆允许补进去，老记录的哈希永远不许改
  - **纠错也算一种"合法的消失"**：被改掉的那条进 `retired`，带上原因和
    替换它的新 ID，校验时不再算"丢了"，但记录一直留着（见 --retire）

用法：
  python memory_ledger.py --init     首次生成账本
  python memory_ledger.py --verify   校验（备份前、每天跑）
  python memory_ledger.py --sync     把新增的记忆补进账本（不改老记录）
  python memory_ledger.py --report   看一眼账本覆盖了多少条
  python memory_ledger.py --retire 53 --replaced-by 61 --reason "你纠正"
                                     把某条标记作废（不删记录，挪进 retired）

退出码：0 = 一切正常；1 = 发现问题（丢条或正文被改）
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from contextlib import contextmanager

if os.name == 'nt':
    import msvcrt
else:
    import fcntl

# Windows 控制台默认 GBK，直接 print ✅/❌ 会抛 UnicodeEncodeError，
# 把「校验通过」变成退出码 1（踩过：--verify 明明全过却报错）
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

DB = os.environ.get("MEM_DB", r"D:\你的数据目录\livingmemory\livingmemory.db")
LEDGER = os.environ.get("MEM_LEDGER", r"D:\你的数据目录\livingmemory\memory-text-ledger.json")
# 补登记文件：去重/乱码修复这类"合法删改"的历史登记，主账本保持只增不改。
SUPPLEMENT = os.environ.get(
    "MEM_LEDGER_SUPPLEMENT",
    os.path.join(os.path.dirname(LEDGER), "memory-text-ledger.supplement.json"),
)


def sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def load_docs():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT id, text FROM documents").fetchall()
    finally:
        con.close()
    return {int(i): (t or "") for i, t in rows}


def load_ledger():
    if not os.path.exists(LEDGER):
        return None
    with open(LEDGER, encoding="utf-8") as f:
        return json.load(f)


@contextmanager
def _ledger_write_lock():
    """锁定不会被 replace 的旁文件；关闭句柄（含进程退出）即释放锁。"""
    with open(LEDGER + '.lock', 'a+b') as lock_file:
        if os.name == 'nt':
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        yield


@_ledger_write_lock()
def save_ledger(data):
    _save_ledger_locked(data)


def _save_ledger_locked(data):
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LEDGER)


def load_supplement():
    """读补登记文件；不存在/损坏时返回空 dict（绝不阻断校验）。"""
    if not os.path.exists(SUPPLEMENT):
        return {}
    try:
        with open(SUPPLEMENT, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def supplement_retired(supp):
    """把补登记里的 retired_ids 展开成与 retired 同构的 dict。"""
    ids = supp.get("retired_ids") or []
    meta = {
        "reason": supp.get("retired_reason", ""),
        "by": supp.get("retired_by", "supplement"),
        "at_text": supp.get("retired_at_text", ""),
        "replaced_by": None,
    }
    out = {}
    for i in ids:
        try:
            out[str(int(i))] = dict(meta)
        except (TypeError, ValueError):
            continue
    return out


def supplement_rehashed(supp):
    """补登记里的重算哈希：{id(str): {sha256, len, reason}}。"""
    return supp.get("rehashed") or {}


@_ledger_write_lock()
def cmd_init(force=False):
    return _init_locked(force)


def _init_locked(force=False):
    if os.path.exists(LEDGER) and not force:
        print("账本已存在。要重建请加 --force（会先备份旧的）")
        return 1
    docs = load_docs()
    data = {
        "created": time.time(),
        "updated": time.time(),
        "entries": {str(i): {"sha256": sha(t), "len": len(t)} for i, t in docs.items()},
    }
    if force and os.path.exists(LEDGER):
        shutil.copy2(LEDGER, LEDGER + f".old-{time.time_ns()}")
    _save_ledger_locked(data)
    print(f"账本已建立：{len(docs)} 条")
    return 0


def cmd_verify():
    ledger = load_ledger()
    if ledger is None:
        print("账本不存在，先跑 --init")
        return 1
    docs = load_docs()
    entries = ledger.get("entries", {})
    retired = ledger.get("retired", {})
    supp = load_supplement()
    supp_retired = supplement_retired(supp)
    rehashed = supplement_rehashed(supp)
    retired = dict(retired)
    retired.update(supp_retired)

    missing, changed = [], []
    for key, rec in entries.items():
        if key in retired:
            continue          # 已登记作废的，不再当"丢了"
        doc_id = int(key)
        if doc_id not in docs:
            missing.append(doc_id)
            continue
        now = sha(docs[doc_id])
        expected = rehashed.get(key) or rec
        if now != expected.get("sha256"):
            changed.append(doc_id)

    new_ids = [i for i in docs if str(i) not in entries]

    print(f"账本 {len(entries)} 条 | 库内 {len(docs)} 条 | 新增未记账 {len(new_ids)} 条")
    if retired:
        print(f"ℹ 已登记作废 {len(retired)} 条（纠错/改写，记录仍在账本里）")
    if supp_retired:
        print(f"ℹ 其中补登记 {len(supp_retired)} 条（去重/乱码修复，见 supplement 文件）")
    if missing:
        print(f"❌ 丢了 {len(missing)} 条：{missing[:10]}{' …' if len(missing) > 10 else ''}")
    if changed:
        print(f"❌ 正文被改 {len(changed)} 条：{changed[:10]}{' …' if len(changed) > 10 else ''}")
    if not missing and not changed:
        print("✅ 校验通过：账本里的每一条都还在，正文一字未变")
    if new_ids:
        print(f"ℹ 有 {len(new_ids)} 条新记忆还没进账本，跑 --sync 补上（不影响本次校验）")
    return 1 if (missing or changed) else 0


@_ledger_write_lock()
def cmd_retire(doc_id, reason="", replaced_by=None, by="user"):
    """把一条记忆登记为「被合法改写」，连同原因一起留档。

    记录不会删：从 entries 挪到 retired，保留原文哈希和长度，
    以后想查"这条当初是什么、为什么改"都还在。
    """
    ledger = load_ledger()
    if ledger is None:
        print("账本不存在，先跑 --init")
        return 1
    key = str(int(doc_id))
    entries = ledger.setdefault("entries", {})
    retired = ledger.setdefault("retired", {})
    rec = entries.get(key)
    docs = load_docs()
    if rec is None:
        # 还没进账本（比如今天刚写、要等 00:20 才 sync）——本来就没有记录，
        # 不需要登记作废；纠错明细在 corrections.jsonl 里
        print(f"ℹ id={doc_id} 还没进账本，跳过作废登记（详情见 corrections.jsonl）")
        return 0
    if key in retired:
        print(f"id={doc_id} 已经登记过作废了（{retired[key].get('at_text', '')}）")
        return 0
    retired[key] = {
        "sha256": rec.get("sha256"),
        "len": rec.get("len"),
        "at": time.time(),
        "at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reason": reason,
        "replaced_by": int(replaced_by) if replaced_by else None,
        "by": by,
    }
    entries.pop(key, None)
    ledger["updated"] = time.time()
    _save_ledger_locked(ledger)
    print(f"已登记作废 id={doc_id}" + (f" → 由 {replaced_by} 接替" if replaced_by else ""))
    if reason:
        print(f"原因：{reason}")
    return 0


@_ledger_write_lock()
def retire_many(doc_ids, reason="", by="dedupe"):
    """批量把已删除的记忆登记为「合法去重/改写」，一次读写账本。

    供 dedupe_memories.py / memory_maintenance.py 去重后调用：
    删了正文之后，把被删的 id 挪进 retired，memory_ledger --verify 就不会再报"丢了"。
    """
    ledger = load_ledger()
    if ledger is None:
        return 0
    entries = ledger.setdefault("entries", {})
    retired = ledger.setdefault("retired", {})
    now = time.time()
    moved = 0
    for doc_id in doc_ids:
        try:
            key = str(int(doc_id))
        except (TypeError, ValueError):
            continue
        rec = entries.get(key)
        if rec is None or key in retired:
            continue
        retired[key] = {
            "sha256": rec.get("sha256"),
            "len": rec.get("len"),
            "at": now,
            "at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason,
            "replaced_by": None,
            "by": by,
        }
        entries.pop(key, None)
        moved += 1
    ledger["updated"] = now
    _save_ledger_locked(ledger)
    return moved


def cmd_log(limit=10):
    ledger = load_ledger()
    if ledger is None:
        print("账本不存在")
        return 1
    retired = ledger.get("retired", {})
    if not retired:
        print("还没有作废/改写记录")
        return 0
    rows = sorted(retired.items(), key=lambda kv: kv[1].get("at", 0))[-limit:]
    for key, rec in rows:
        print(
            "id=%s  %s  由 %s 接替  %s"
            % (key, rec.get("at_text", ""), rec.get("replaced_by"),
               rec.get("reason", ""))
        )
    return 0


@_ledger_write_lock()
def cmd_sync():
    ledger = load_ledger()
    if ledger is None:
        return _init_locked()
    docs = load_docs()
    entries = ledger.setdefault("entries", {})
    retired = ledger.setdefault("retired", {})
    # 补登记先并进正式 retired，--sync 一次就永久落账（主账本只增不改）。
    retired.update(supplement_retired(load_supplement()))
    added = 0
    for doc_id, text in docs.items():
        key = str(doc_id)
        if key in entries or key in retired:
            # 老记录绝不覆盖；已登记作废的也不再补回来
            continue
        entries[key] = {"sha256": sha(text), "len": len(text)}
        added += 1
    ledger["updated"] = time.time()
    _save_ledger_locked(ledger)
    print(f"已补 {added} 条新记忆进账本，共 {len(entries)} 条")
    return 0


def cmd_report():
    ledger = load_ledger()
    docs = load_docs()
    if ledger is None:
        print("暂无账本")
        return 1
    entries = ledger["entries"]
    retired = ledger.get("retired", {})
    retired = dict(retired)
    retired.update(supplement_retired(load_supplement()))
    covered = sum(1 for k in entries if int(k) in docs)
    total_chars = sum(v.get("len", 0) for v in entries.values())
    print(f"账本条数      : {len(entries)}")
    print(f"库内条数      : {len(docs)}")
    print(f"覆盖率        : {covered}/{len(docs)}")
    print(f"记账正文总字数 : {total_chars}")
    print(f"已登记作废    : {len(retired)} 条（改写过，记录仍在）")
    print(f"建立时间      : {time.strftime('%Y-%m-%d %H:%M', time.localtime(ledger.get('created', 0)))}")
    print(f"最后更新      : {time.strftime('%Y-%m-%d %H:%M', time.localtime(ledger.get('updated', 0)))}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--retire", type=int, metavar="ID", help="把某条登记作废（纠错/改写）")
    ap.add_argument("--replaced-by", type=int, metavar="NEW_ID")
    ap.add_argument("--reason", default="")
    ap.add_argument("--by", default="user")
    ap.add_argument("--log", action="store_true", help="看作废/改写记录")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.init:
        return cmd_init(args.force)
    if args.verify:
        return cmd_verify()
    if args.sync:
        return cmd_sync()
    if args.report:
        return cmd_report()
    if args.retire is not None:
        return cmd_retire(args.retire, args.reason, args.replaced_by, args.by)
    if args.log:
        return cmd_log()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
