# -*- coding: utf-8 -*-
"""灾后复活 · 上传（分片版）

整包切 16MB 分片、逐片校验上传、传完核对远端大小、保留最近 KEEP 套。

**网盘接口说明（部署时必看）：**
本文件的 分片/清单/校验/清理 逻辑都是通用且可本地测试的；
只有 upload_one() / list_remote() / delete_remote() 三个函数需要你
接进自己网盘的 API（夸克 / 阿里云盘 / 自建等，去对应官方开放平台申请）。
没接接口时，脚本会打印明确提示并停止，不会误传。

用法：
    python upload.py                  # 先 build.py 打包，再分片上传
    python upload.py --upload-only    # 只传 out/latest.json 指向的包
"""

import hashlib
import json
import os
import sys
import time

# ================= 部署时按需修改 =================
ROOT        = r"D:\你的数据目录"          # 数据根目录
CLOUD_FOLDER = "companion-backup"         # 云端文件夹名
KEEP        = 7                           # 云端保留套数（≈ 14 天）
# ==================================================

OUT      = os.path.join(ROOT, "backup", "out")
TMP      = os.path.join(ROOT, "backup", "tmp")
STATE_FILE = os.path.join(ROOT, "backup", "upload_state.json")
LOG_FILE = os.path.join(ROOT, "backup", "backup.log")
PART_SIZE = 16 * 1024 * 1024


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ============ 网盘接口（部署时实现这三个函数） ============
# 示例（伪代码，别直接用）：
#   def upload_one(path, name):
#       import 你的网盘SDK
#       sdk.upload(path, folder=CLOUD_FOLDER, name=name)
#   def list_remote():
#       return {文件名: 大小, ...}
#   def delete_remote(names):
#       for n in names: sdk.delete(n)

def upload_one(path, name):
    raise NotImplementedError("还没接网盘接口：请按本文件顶部说明实现 upload_one()")


def list_remote():
    raise NotImplementedError("还没接网盘接口：请按本文件顶部说明实现 list_remote()")


def delete_remote(names):
    raise NotImplementedError("还没接网盘接口：请按本文件顶部说明实现 delete_remote()")
# ==========================================================


def split(src, stamp):
    os.makedirs(TMP, exist_ok=True)
    parts = []
    with open(src, "rb") as f:
        idx = 1
        while True:
            block = f.read(PART_SIZE)
            if not block:
                break
            name = "backup_%s.p%02d" % (stamp, idx)
            path = os.path.join(TMP, name)
            with open(path, "wb") as out:
                out.write(block)
            parts.append({"name": name, "path": path, "size": len(block),
                          "sha256": hashlib.sha256(block).hexdigest()})
            idx += 1
    return parts


def clean_stale_tmp():
    """清掉 tmp 里历史中断留下的分片/清单，避免无限累积占盘。
    只碰 backup_*.p* 和 backup_*.json；split() 之前调用，不会误删本轮产物。"""
    if not os.path.isdir(TMP):
        return
    for dirpath, _dirnames, filenames in os.walk(TMP):
        for fn in filenames:
            if fn.startswith("backup_") and (".p" in fn or fn.endswith(".json")):
                try:
                    os.remove(os.path.join(dirpath, fn))
                except OSError:
                    pass


def wait_visible(expected, retries=15, delay=3.0):
    """轮询远端列表直到每一项大小匹配（网盘列表常有延迟）。"""
    remote = {}
    for _ in range(retries):
        try:
            remote = list_remote() or {}
        except NotImplementedError:
            raise
        if isinstance(remote, dict) and all(remote.get(n) == s for n, s in expected.items()):
            return remote
        time.sleep(delay)
    return remote


def prune(keep_stamp):
    """远端保留最新 KEEP 套（含本轮），更旧的连清单一起删。"""
    try:
        remote = list_remote() or {}
    except NotImplementedError:
        return
    stamps = set()
    for n in remote:
        if n.startswith("backup_") and "." in n:
            stamps.add(n.split(".")[0].replace("backup_", ""))
    old = sorted([s for s in stamps if s != keep_stamp], reverse=True)
    drop = old[KEEP - 1:]
    if drop:
        names = [n for n in remote if any(n.startswith("backup_" + s) for s in drop)]
        try:
            delete_remote(names)
            log("已清理旧套 %s（%d 个文件）" % (",".join(drop), len(names)))
        except Exception as exc:  # noqa: BLE001
            log("清理旧套失败（不影响新套）：%s" % exc)
    else:
        log("网盘上共 %d 套，无需清理" % len(stamps))


def main():
    if sys.stdout is not None:  # pythonw 下是 None
        sys.stdout.reconfigure(encoding="utf-8")
    if "--upload-only" not in sys.argv:
        log("开始打包…")
        import build
        build.main()

    with open(os.path.join(OUT, "latest.json"), encoding="utf-8") as f:
        latest = json.load(f)
    src = latest["path"]
    stamp = latest["created"]
    if not os.path.exists(src):
        log("找不到包：%s" % src)
        return 1

    log("检查网盘接口是否已接入…")
    try:
        list_remote()
    except NotImplementedError as exc:
        log("未接入网盘接口，本轮只做本地分片演示：%s" % exc)
        log("本地分片与清单仍会生成，供你验证分片逻辑；接入接口后即可真正上传。")
        dry = True
    except Exception as exc:  # noqa: BLE001
        log("网盘接口调用失败：%s" % exc)
        return 1
    else:
        dry = False

    clean_stale_tmp()
    log("切分 %s（%.1f MB，每片 16MB）" % (os.path.basename(src), os.path.getsize(src) / 1e6))
    parts = split(src, stamp)
    log("共 %d 片" % len(parts))

    t0 = time.time()
    if not dry:
        for i, p in enumerate(parts, 1):
            t = time.time()
            last_err = None
            for attempt in (1, 2):          # 每片重试一次，失败留痕
                try:
                    upload_one(p["path"], p["name"])
                    last_err = None
                    break
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
                    log("  [%d/%d] 第 %d 次失败：%s" % (i, len(parts), attempt, exc))
                    time.sleep(3)
            if last_err is not None:
                log("[FAIL] 分片 %s 两次都失败，本轮中止（旧套没动）" % p["name"])
                for q in parts:
                    try:
                        os.remove(q["path"])
                    except OSError:
                        pass
                return 1
            log("  [%d/%d] %s  %.1f MB  %.0f 秒" % (i, len(parts), p["name"],
                                                   p["size"] / 1e6, time.time() - t))
    else:
        log("（dry 模式：跳过实际上传，仅本地生成分片与清单）")

    manifest = {
        "stamp": stamp,
        "full_name": os.path.basename(src),
        "full_sha256": latest["sha256"],
        "full_size": latest["size"],
        "memory": latest.get("memory"),
        "created_at": stamp,
        "parts": [{"name": p["name"], "size": p["size"], "sha256": p["sha256"]} for p in parts],
    }
    mpath = os.path.join(TMP, "backup_%s.json" % stamp)
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    log("清单已生成：%s" % os.path.basename(mpath))

    if not dry:
        try:
            upload_one(mpath, os.path.basename(mpath))
            expected = {p["name"]: p["size"] for p in parts}
            expected[os.path.basename(mpath)] = os.path.getsize(mpath)
            remote = wait_visible(expected)
            bad = [n for n, s in expected.items() if remote.get(n) != s]
            if bad:
                log("[FAIL] 远端大小对不上：%s（本轮不清理旧套）" % ", ".join(bad))
                for p in parts:
                    try:
                        os.remove(p["path"])
                    except OSError:
                        pass
                return 1
            log("远端大小核对通过（%d 片 + 清单）" % len(parts))
            prune(stamp)
        except Exception as exc:  # noqa: BLE001
            log("[FAIL] 上传流程出错：%s" % exc)
            return 1

    state = {"uploaded_at": time.time(), "stamp": stamp, "parts": len(parts),
             "size": latest["size"], "sha256": latest["sha256"],
             "memory": latest.get("memory"), "verified": not dry}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    for p in parts:
        try:
            os.remove(p["path"])
        except OSError:
            pass
    try:
        import kit
        kit.main()
        log("应急包已刷新")
    except Exception as exc:  # noqa: BLE001
        log("应急包刷新失败（不影响云端包）：%s" % exc)
    log("完成：%d 片，用时 %.1f 分钟" % (len(parts), (time.time() - t0) / 60))
    return 0


if __name__ == "__main__":
    sys.exit(main())
