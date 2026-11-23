# -*- coding: utf-8 -*-
"""她的核心文件指纹：只告警，不阻止。

为什么要有它
------------
AstrBot / 插件升级、别人动过手、补丁被覆盖，这些都不会报错——她照样跑，
只是某一块悄悄变回了原版（画画插件、qzone 注入、meme 发图这三处最容易中招，见灾后复活.md §15/§36.5/§26）。
这份指纹只做一件事：把"上次确认好的样子"记下来，变了就喊一声。

用法
----
    python tools\\core_fingerprint.py --baseline   # 确认当前状态是好的，然后记下来
    python tools\\core_fingerprint.py --check      # 比对；0=一致 1=有变化 2=没有基线
    python tools\\core_fingerprint.py --list       # 看都在盯哪些文件
    python tools\\core_fingerprint.py --quiet      # 只在有问题时说话（给别的脚本调用）

红线
----
只读文件、只写 tools\\core_fingerprint.json；不碰记忆、不碰 state.json、不改任何代码。
"""
import glob
import hashlib
import io
import json
import os
import sys
import time

MEM = r"D:\你的数据目录"
INST = (r"C:\你的用户\.astrbot_launcher\instances"
        r"\<BOT_INSTANCE>")
STARTUP = r"C:\你的用户\CompanionStartup"
BASELINE = os.path.join(MEM, "tools", "core_fingerprint.json")

# 记忆内核（改这几处会影响她怎么想起事情）
LIVING = os.path.join(INST, "core", "data", "plugins", "astrbot_plugin_livingmemory")


def _p(*parts):
    return os.path.join(*parts)


def targets():
    """返回 [(分组, 绝对路径), ...]，顺序稳定。"""
    out = []
    for p in sorted(glob.glob(_p(INST, "core", "data", "plugins",
                                 "astrbot_plugin_companion_*", "main.py"))):
        out.append(("她的插件", p))

    out += [
        ("打过补丁的第三方", _p(INST, "core", "data", "plugins",
                          "astrbot_plugin_qzone", "core", "llm_action.py")),
        ("打过补丁的第三方", _p(INST, "core", "data", "plugins",
                          "meme_manager", "mixins", "event_handlers.py")),
        ("记忆内核", _p(LIVING, "core", "retrieval", "hybrid_retriever.py")),
        ("记忆内核", _p(LIVING, "core", "retrieval", "affect.py")),
        ("记忆内核", _p(LIVING, "core", "retrieval", "graph_retriever.py")),
        ("记忆内核", _p(LIVING, "core", "processors", "claim.py")),
        ("记忆内核", _p(LIVING, "core", "processors", "memory_processor_build.py")),
        ("记忆内核", _p(LIVING, "core", "base", "config_validator.py")),
        ("服务", _p(MEM, "video", "server.py")),
        ("服务", _p(MEM, "houseviz", "server.py")),
        ("服务", _p(MEM, "lifeviz", "server.py")),
        ("服务", _p(MEM, "memoryrhythm", "rhythm.py")),
        ("工具", _p(MEM, "tools", "vitals.py")),
        ("工具", _p(MEM, "tools", "recall.py")),
        ("工具", _p(MEM, "tools", "restart_bot.ps1")),
        ("灾后复活", _p(MEM, "nirvana", "build.py")),
        ("灾后复活", _p(MEM, "nirvana", "upload.py")),
        ("灾后复活", _p(MEM, "nirvana", "restore.py")),
        ("灾后复活", _p(MEM, "nirvana", "check.py")),
        ("灾后复活", _p(MEM, "nirvana", "kit.py")),
        ("启动", _p(STARTUP, "start-astrbot.ps1")),
        ("启动", _p(STARTUP, "start-napcat.ps1")),
    ]
    return out


def digest(path):
    h = hashlib.sha256()
    with io.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot():
    files = {}
    for group, path in targets():
        if not os.path.exists(path):
            continue
        files[path] = {
            "group": group,
            "sha256": digest(path),
            "size": os.path.getsize(path),
        }
    return files


def save_baseline(files):
    data = {
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "确认当前状态是好的才写；以后变了会告警。回滚=删掉这个文件。",
        "count": len(files),
        "files": files,
    }
    tmp = BASELINE + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, BASELINE)
    return data


def load_baseline():
    if not os.path.exists(BASELINE):
        return None
    # utf-8-sig：容忍有人用记事本另存后带上的 BOM（否则 json 直接崩）
    with io.open(BASELINE, encoding="utf-8-sig") as f:
        return json.load(f)


def diff(base, cur):
    """返回 (变化列表, 新增列表, 消失列表)。"""
    changed, added, missing = [], [], []
    for path, meta in sorted(cur.items()):
        old = base.get(path)
        if old is None:
            added.append(path)
        elif old.get("sha256") != meta["sha256"]:
            changed.append((path, old.get("size"), meta["size"]))
    for path in sorted(base):
        if path not in cur:
            missing.append(path)
    return changed, added, missing


def check():
    """返回 (状态, 文字列表)。状态: ok / changed / nobaseline"""
    base = load_baseline()
    if base is None:
        return "nobaseline", []
    cur = snapshot()
    changed, added, missing = diff(base["files"], cur)
    lines = []
    for path, old_size, new_size in changed:
        lines.append("~ %s  (%s -> %s 字节)" % (path, old_size, new_size))
    for path in added:
        lines.append("+ %s  (新增)" % path)
    for path in missing:
        lines.append("- %s  (不见了)" % path)
    if not lines:
        return "ok", []
    return "changed", lines


def summary():
    """给 check_nirvana_sync.py 用：返回一行结论 + 明细。"""
    state, lines = check()
    if state == "nobaseline":
        return ["  [SKIP] 核心文件指纹：还没有基线（python tools\\core_fingerprint.py --baseline）"]
    base = load_baseline()
    if state == "ok":
        return ["  [OK]   核心文件指纹一致（%d 个文件，基线 %s）"
                % (base["count"], base["created"])]
    out = ["  [WARN] 核心文件指纹有 %d 处变化（基线 %s）：" % (len(lines), base["created"])]
    out += ["         " + x for x in lines]
    out.append("         确认是你自己改的，再跑 --baseline 更新；不是就查是谁覆盖了补丁。")
    return out


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    quiet = "--quiet" in argv
    if "--baseline" in argv:
        files = snapshot()
        data = save_baseline(files)
        print("== 核心文件指纹 ==")
        print("  已记录 %d 个文件 -> %s" % (data["count"], BASELINE))
        if len(files) < data["count"]:  # pragma: no cover
            print("  注意：有 %d 个文件没找到，已跳过" % (data["count"] - len(files)))
        return 0

    if "--list" in argv:
        base = load_baseline()
        print("== 核心文件指纹：在看哪些文件 ==")
        groups = {}
        for group, path in targets():
            groups.setdefault(group, []).append(path)
        for group in groups:
            print("  [%s]" % group)
            for path in groups[group]:
                mark = ""
                if base and path in base["files"]:
                    mark = "  已记录"
                print("    %s%s" % (path, mark))
        print("  共 %d 个文件；基线文件：%s" % (len(targets()), BASELINE))
        return 0

    state, lines = check()
    if state == "nobaseline":
        print("== 核心文件指纹 ==")
        print("  还没有基线。确认现在她的状态是好的，再跑：")
        print("    python tools\\core_fingerprint.py --baseline")
        return 2

    base = load_baseline()
    if state == "ok":
        if not quiet:
            print("== 核心文件指纹 ==")
            print("  基线：%s，共 %d 个文件" % (base["created"], base["count"]))
            print("  ✅ 全部一致")
        return 0

    print("== 核心文件指纹 ==")
    print("  基线：%s，共 %d 个文件" % (base["created"], base["count"]))
    print("  ⚠ %d 处变化：" % len(lines))
    for line in lines:
        print("    " + line)
    print("")
    print("  这说明她的某块被别人动过（升级覆盖、补丁丢失、或你自己改的）。")
    print("  确认改动是你要的，再跑 --baseline 更新基线。")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
