"""记忆纠错：她说错了、记错了，把那条改掉——但改动必须留痕。

为什么不是"删了重写"：
  - 走插件自己的 ``/memories/update``，它会重建 FTS / 向量 / 图记忆三套索引，
    不会把索引搞歪；
  - 旧正文整段抄进 ``livingmemory/corrections.jsonl``，账本里登记一条
    ``retired``（谁改的、为什么、由谁接替），想查"当初她记的是什么"随时能查；
  - 改完自动 --sync 进账本，第二天的体检不会把这次改动当成"正文被改"报警。

用法：
  py.cmd memory_correct.py --find "黄焖鸡"          # 找候选
  py.cmd memory_correct.py --show 53               # 看某条全文
  py.cmd memory_correct.py --apply --id 53 --text "中午吃的是牛肉面" --why "你纠正"
  py.cmd memory_correct.py --apply --id 53 --text "..." --dry-run   # 只看不动手
  py.cmd memory_correct.py --log                   # 最近的纠错记录

退出码：0 成功；1 失败
"""
import argparse
import datetime
import json
import os
import sys
import time

import jwt
import requests

TOOLS = os.path.dirname(os.path.abspath(__file__))
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import memory_ledger as ledger  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

CFG_PATH = (
    r"C:\你的用户\.astrbot_launcher\instances"
    r"\<BOT_INSTANCE>\core\data\cmd_config.json"
)
BASE = "http://127.0.0.1:8012"
PAGE = BASE + "/api/plug/astrbot_plugin_livingmemory/page"
AUDIT = r"D:\你的数据目录\livingmemory\corrections.jsonl"
# 被纠正过的记忆，重要性至少抬到这里：是你亲口更正的，别再被遗忘曲线吃掉
MIN_IMPORTANCE = 0.85


def _headers():
    with open(CFG_PATH, encoding="utf-8-sig") as f:
        cfg = json.load(f)
    dash = cfg.get("dashboard", {})
    token = jwt.encode(
        {
            "username": dash.get("username", "astrbot"),
            "exp": datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(minutes=10),
        },
        dash["jwt_secret"],
        algorithm="HS256",
    )
    return {"Authorization": "Bearer " + token}


def _get(path, params=None):
    r = requests.get(PAGE + path, params=params or {}, headers=_headers(), timeout=20)
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "ok":
        raise RuntimeError(body.get("message") or str(body)[:200])
    return body.get("data")


def _post(path, payload):
    r = requests.post(PAGE + path, json=payload, headers=_headers(), timeout=60)
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "ok":
        raise RuntimeError(body.get("message") or str(body)[:200])
    return body.get("data")


def _snippet(text, n=60):
    text = (text or "").replace("\n", " ").strip()
    return text[:n] + ("…" if len(text) > n else "")


def _when(v):
    """列表里 created_at 是字符串，详情里也可能是时间戳，两种都认。"""
    if isinstance(v, str) and len(v) >= 16:
        return v[5:16]          # 2026-10-30 22:34:37… -> 10-30 22:34
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(float(v)))
    except (TypeError, ValueError):
        return "?"


def _imp(item):
    md = item.get("metadata") or {}
    for raw in (md.get("importance"), item.get("importance")):
        try:
            if raw is not None:
                return float(raw)
        except (TypeError, ValueError):
            continue
    return 0.0


def cmd_find(keyword, limit=10, as_json=False):
    data = _get(
        "/memories",
        {"keyword": keyword, "status": "active", "page_size": limit,
         "sort": "created_desc"},
    )
    items = data.get("items") or []
    if as_json:
        print(json.dumps({"ok": True, "items": [
            {"id": it.get("id"), "when": _when(it.get("created_at")),
             "imp": round(_imp(it), 2), "text": _snippet(it.get("text"), 80)}
            for it in items]}, ensure_ascii=False))
        return 0 if items else 1
    if not items:
        print(f"没找到含「{keyword}」的记忆")
        return 1
    print(f"含「{keyword}」的记忆（{len(items)} 条）：")
    for it in items:
        print("  id=%-4s %s  imp=%.2f  %s"
              % (it.get("id"), _when(it.get("created_at")),
                 _imp(it), _snippet(it.get("text"), 50)))
    print("\n挑好之后：--show <id> 看全文，--apply --id <id> --text \"正确的内容\"")
    return 0


def cmd_show(memory_id):
    d = _get("/memories/detail", {"memory_id": memory_id})
    print(f"id       : {d.get('memory_id')}")
    print(f"时间     : {_when(d.get('created_at'))}")
    print(f"重要性   : {d.get('importance')}")
    print(f"状态     : {d.get('status')}")
    print(f"主题     : {d.get('topics')}")
    print(f"修改历史 : {len(d.get('update_history') or [])} 次")
    print("-" * 60)
    print(d.get("text") or "")
    return 0


def _append_audit(record):
    os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
    with open(AUDIT, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def cmd_apply(memory_id, new_text, why, dry=False, source="cli", as_json=False):
    new_text = (new_text or "").strip()
    if not new_text:
        print(json.dumps({"ok": False, "error": "新内容是空的"}, ensure_ascii=False)
              if as_json else "新内容是空的，什么都没改")
        return 1

    detail = _get("/memories/detail", {"memory_id": memory_id})
    old_text = detail.get("text") or ""
    old_imp = float(detail.get("importance") or 0.5)
    new_imp = max(old_imp, MIN_IMPORTANCE)

    if not as_json:
        print("— 要改的那条 —")
        print(f"id={memory_id}  imp={old_imp:.2f}  {_when(detail.get('created_at'))}")
        print("旧：" + _snippet(old_text, 160))
        print("新：" + _snippet(new_text, 160))
        print(f"新重要性：{new_imp:.2f}（至少 {MIN_IMPORTANCE}，改过的别再被遗忘）")
    if dry:
        if as_json:
            print(json.dumps({"ok": True, "dry_run": True, "old_id": memory_id,
                              "old_text": old_text, "new_text": new_text},
                             ensure_ascii=False))
        else:
            print("\n[dry-run] 没有写库。去掉 --dry-run 才会真的改。")
        return 0

    payload = {
        "memory_id": memory_id,
        "field": "structured",
        "value": {"content": new_text, "importance": new_imp},
        "reason": why or "你纠正",
        "value_scale": "0-1",
    }
    try:
        data = _post("/memories/update", payload)
    except Exception as exc:  # noqa: BLE001
        if as_json:
            print(json.dumps({"ok": False, "error": str(exc)[:200]}, ensure_ascii=False))
        else:
            print("改失败了：" + str(exc)[:200])
        return 1

    new_id = data.get("new_memory_id")
    if not as_json:
        print("\n库已更新：" + str(data.get("message") or ""))

    record = {
        "at": time.time(),
        "at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
        "old_id": memory_id,
        "new_id": new_id,
        "old_importance": old_imp,
        "new_importance": new_imp,
        "old_text": old_text,
        "new_text": new_text,
        "reason": why or "你纠正",
        "source": source,
    }
    _append_audit(record)

    if as_json:
        # 账本登记：作废旧的、补上新的，保持"没丢过"的证明
        ledger.cmd_retire(memory_id, why or "你纠正", new_id, "user")
        ledger.cmd_sync()
        print(json.dumps({
            "ok": True, "old_id": memory_id, "new_id": new_id,
            "old_text": old_text, "new_text": new_text,
            "message": data.get("message") or "已更正",
        }, ensure_ascii=False))
        return 0

    print(f"旧正文已存档：{AUDIT}")
    ledger.cmd_retire(memory_id, why or "你纠正", new_id, "user")
    ledger.cmd_sync()
    code = ledger.cmd_verify()
    print("账本校验：" + ("通过" if code == 0 else "有问题，看上面"))
    return 0 if code == 0 else 1


def cmd_log(limit=10):
    if not os.path.exists(AUDIT):
        print("还没有纠错记录")
        return 0
    rows = []
    with open(AUDIT, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if not rows:
        print("还没有纠错记录")
        return 0
    for r in rows[-limit:]:
        print("%s  id %s → %s  %s"
              % (r.get("at_text"), r.get("old_id"), r.get("new_id"),
                 r.get("reason", "")))
        print("   旧：" + _snippet(r.get("old_text"), 60))
        print("   新：" + _snippet(r.get("new_text"), 60))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--find", metavar="关键词")
    ap.add_argument("--show", type=int, metavar="ID")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--id", type=int)
    ap.add_argument("--text", default="")
    ap.add_argument("--why", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true", help="给程序调用时输出 JSON")
    ap.add_argument("--log", action="store_true")
    args = ap.parse_args()

    if args.find is not None:
        return cmd_find(args.find, as_json=args.json)
    if args.show is not None:
        return cmd_show(args.show)
    if args.apply:
        if not args.id:
            print("--apply 需要 --id")
            return 1
        return cmd_apply(args.id, args.text, args.why, args.dry_run, as_json=args.json)
    if args.log:
        return cmd_log()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
