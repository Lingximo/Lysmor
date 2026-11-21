# -*- coding: utf-8 -*-
"""收工检查：文档、压缩包、kit 三者是不是同一份。

用法：
    python tools\\check_nirvana_sync.py

检查四件事：
  1. 最新包是什么（out\\latest.json）
  2. 包里的 docs-root/灾后复活.md 和磁盘上的 灾后复活.md 是否逐字节一致
  3. 包的实际 sha256 是否等于 latest.json 里记的（防止拷坏/半截）
  4. out\\kit 里那份是不是同一个包（U 盘要用的就是它）

退出码：0 全部一致；1 有不一致（按打印的最后一行处理）。
"""
import glob
import hashlib
import io
import json
import os
import sys
import tarfile

NIRVANA = r"D:\你的数据目录\nirvana"
DOC = r"D:\你的数据目录\灾后复活.md"
LATEST = os.path.join(NIRVANA, "out", "latest.json")
KIT = os.path.join(NIRVANA, "out", "kit")

FAILS = []


def check(name, ok, detail=""):
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
    if not ok:
        FAILS.append(name)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    print("== 灾后复活同步检查 ==")
    if not os.path.exists(LATEST):
        print("  [FAIL] 找不到 out\\latest.json，先跑一次打包")
        return 1

    latest = json.load(io.open(LATEST, encoding="utf-8"))
    tar_path = latest["path"]
    print("  最新包：%s" % os.path.basename(tar_path))

    check("包文件存在", os.path.exists(tar_path), tar_path)
    if not os.path.exists(tar_path):
        return 1

    size = os.path.getsize(tar_path)
    check("包大小与记录一致", size == latest["size"],
          "%d / %d 字节" % (size, latest["size"]))

    digest = sha256_of(tar_path)
    check("包 sha256 与记录一致", digest == latest["sha256"], digest[:16] + "…")

    with tarfile.open(tar_path, "r:gz") as t:
        member = None
        for m in t.getmembers():
            if m.name == "docs-root/灾后复活.md":
                member = m
                break
        check("包里有 docs-root/灾后复活.md", member is not None)
        if member is not None:
            in_tar = t.extractfile(member).read()
            on_disk = io.open(DOC, "rb").read()
            check("文档与包内一致", in_tar == on_disk,
                  "包内 %d 字节 / 磁盘 %d 字节" % (len(in_tar), len(on_disk)))

    kit_tar = glob.glob(os.path.join(KIT, "nirvana_*.tar.gz"))
    check("kit 里有包", len(kit_tar) == 1, "%d 个" % len(kit_tar))
    if len(kit_tar) == 1:
        check("kit 里就是最新包", os.path.basename(kit_tar[0]) == os.path.basename(tar_path),
              os.path.basename(kit_tar[0]))
        check("kit 大小一致", os.path.getsize(kit_tar[0]) == size)

    # 附带的体检：核心文件指纹（只告警，不改退出码——不影响"能不能拷 U 盘"）
    print("")
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import core_fingerprint
        for line in core_fingerprint.summary():
            print(line)
    except Exception as exc:  # noqa: BLE001
        print("  [SKIP] 核心文件指纹检查跳过了：%s" % exc)

    print("")
    if FAILS:
        print("结论：有 %d 项不一致 → 重跑打包（schtasks /run /tn \"Companion-Nirvana\"）" % len(FAILS))
        return 1
    print("结论：文档、包、kit 三者一致，可以直接拷 U 盘。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
