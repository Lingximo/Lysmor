"""待写入长期记忆的跨进程安全队列。

生产者：mood / taste / qzone_reply / video server
消费者：astrbot_plugin_companion_video_bridge（每 20 秒最多 3 条）

保证：
1. 读-改-写全程持有文件锁，多个进程同时 append 不会互相覆盖；
2. 写入先写 .tmp 再 os.replace，进程被杀不会留下半个 JSON；
3. 主文件损坏时自动从 .bak 恢复；
4. 消费者只按 id 删除自己处理成功的条目，不会覆盖消费期间新追加的内容。
"""

import json
import os
import shutil
import time
import uuid

try:
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None
try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(ROOT, "pending_memories.json")
KEEP = 200


def _lock_file(f):
    if msvcrt is not None:
        f.seek(0)
        if os.fstat(f.fileno()).st_size == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
    elif fcntl is not None:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)


def _unlock_file(f):
    if msvcrt is not None:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    elif fcntl is not None:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


class _Lock:
    def __init__(self, path):
        self.path = path + ".lock"
        self.f = None

    def __enter__(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self.f = open(self.path, "a+b")
        _lock_file(self.f)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.f is not None:
            try:
                _unlock_file(self.f)
            finally:
                self.f.close()
                self.f = None
        return False


def _read_unlocked(path):
    candidates = [path, path + ".bak"]
    for candidate in candidates:
        try:
            with open(candidate, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            continue
    return []


def _write_unlocked(path, items):
    items = list(items)[-KEEP:]
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    try:
        if os.path.exists(path):
            shutil.copy2(path, path + ".bak")
    except Exception:
        pass
    os.replace(tmp, path)


def load(path=DEFAULT_PATH):
    with _Lock(path):
        return _read_unlocked(path)


def save(items, path=DEFAULT_PATH):
    with _Lock(path):
        _write_unlocked(path, items)


def append(item, path=DEFAULT_PATH):
    item = dict(item)
    if not str(item.get("summary") or "").strip() and not item.get("messages"):
        raise ValueError("empty memory item")
    item.setdefault("id", uuid.uuid4().hex)
    item.setdefault("time", time.time())
    with _Lock(path):
        items = _read_unlocked(path)
        items.append(item)
        _write_unlocked(path, items)
    return item["id"]


def item_id(item):
    if not isinstance(item, dict):
        return str(item)
    if item.get("id"):
        return str(item["id"])
    return "%s|%s" % (
        item.get("time"),
        item.get("summary") or item.get("messages") or "",
    )


def remove_ids(ids, path=DEFAULT_PATH):
    ids = set(str(x) for x in ids)
    if not ids:
        return 0
    with _Lock(path):
        items = _read_unlocked(path)
        keep = [item for item in items if item_id(item) not in ids]
        removed = len(items) - len(keep)
        if removed:
            _write_unlocked(path, keep)
        return removed
