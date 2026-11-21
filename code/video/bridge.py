import json
import os
import time

try:
    import pending_store
except Exception:
    pending_store = None

ROOT = os.path.dirname(os.path.abspath(__file__))
VIDEO_PATH = os.path.join(ROOT, "video_recent.json")
QQ_PATH = os.path.join(ROOT, "qq_recent.json")
PENDING_PATH = os.path.join(ROOT, "pending_memories.json")


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(path, items, keep=12):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items[-keep:], f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# 待处理队列要留得久一点：消费端偶尔卡住时，不能把还没总结的对话挤掉
PENDING_KEEP = 200


def load_video(n=6):
    return _load(VIDEO_PATH)[-n:]


def load_qq(n=6):
    return _load(QQ_PATH)[-n:]


def append_video(user, bot):
    items = _load(VIDEO_PATH)
    items.append({"time": time.time(), "user": user[:200], "bot": bot[:300]})
    _save(VIDEO_PATH, items)


def append_qq(user, bot):
    items = _load(QQ_PATH)
    items.append({"time": time.time(), "user": user[:200], "bot": bot[:300]})
    _save(QQ_PATH, items)


def load_pending():
    if pending_store is not None:
        return pending_store.load(PENDING_PATH)
    return _load(PENDING_PATH)


def append_pending(summary, importance=0.6, source=None):
    items = _load(PENDING_PATH)
    item = {
        "time": time.time(),
        "summary": summary[:1500],
        "importance": max(0.0, min(1.0, float(importance))),
    }
    if source:
        item["source"] = str(source)[:40]
    if pending_store is not None:
        pending_store.append(item, PENDING_PATH)
        return
    if pending_store is not None:
        pending_store.append(item, PENDING_PATH)
        return
    items.append(item)
    _save(PENDING_PATH, items, PENDING_KEEP)


def append_pending_messages(messages, importance=0.5, source=None):
    items = _load(PENDING_PATH)
    clean = []
    for msg in messages:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            clean.append({"role": role, "content": content[:500]})
    if not clean:
        return
    item = {
        "time": time.time(),
        "messages": clean,
        "importance": max(0.0, min(1.0, float(importance))),
    }
    if source:
        item["source"] = str(source)[:40]
    items.append(item)
    _save(PENDING_PATH, items, PENDING_KEEP)


def save_pending(items):
    if pending_store is not None:
        pending_store.save(items, PENDING_PATH)
        return
    _save(PENDING_PATH, items, PENDING_KEEP)


def format_recent(items, where, n=4):
    items = items[-n:]
    if not items:
        return ""
    lines = []
    for item in items:
        u = (item.get("user") or "").strip()
        b = (item.get("bot") or "").strip()
        if u:
            lines.append(f"你：{u[:120]}")
        if b:
            lines.append(f"TA：{b[:160]}")
    if not lines:
        return ""
    return f"【你们刚在{where}里聊过，只作参考，不要提同步】\n" + "\n".join(lines)
