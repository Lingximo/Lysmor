# -*- coding: utf-8 -*-
"""记忆召回评估集：把"她能不能想起来"变成一个能重复跑的数字。

为什么要它
----------
检索改着改着会悄悄变好或变坏——不报错，只是开始给错答案（§15.12「视频还开不开呀」就是）。
没有基线的时候，"感觉变好了"和"真的变好了"是同一句话。

三条硬规矩（照某个开源卡片项目，MIT）
------------------------------------
1. 跑真链路：直接用她自己的 BM25Retriever + HybridRetriever，不另写一份"模拟检索"；
2. 绝不碰真库：先用 SQLite backup 接口拷一份到临时目录，评估只在副本上跑，跑完删掉；
3. 判据不看分数：只问"期望的那几个字在不在前 N 条"，分数高只说明主题相关。

用法
----
    python tools\\eval_recall.py            # 跑默认用例，出 R@1 / R@3
    python tools\\eval_recall.py -v         # 逐条看命中在哪一名、没中时给了什么
    python tools\\eval_recall.py --json     # 只出摘要
    python tools\\eval_recall.py --cases 别的.json

说明
----
向量那条路在这里是**故意关掉**的（离线拿不到 embedding provider），
所以数字衡量的是"字面路 + 她的加权（重要性/时间/线索/元记忆）"。
换句话说：这是短问句最容易翻车的那一半。真链路（含向量）在 AstrBot 里跑。
"""
import argparse
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import types

MEM = r"D:\你的数据目录"
SRC_DB = os.path.join(MEM, "livingmemory", "livingmemory.db")
INST = (r"C:\你的用户\.astrbot_launcher\instances"
        r"\<BOT_INSTANCE>")
PLUGINS = os.path.join(INST, "core", "data", "plugins")
CFG = os.path.join(INST, "core", "data", "config",
                   "astrbot_plugin_livingmemory_config.json")
CASES = os.path.join(MEM, "tools", "eval", "cases.json")
BASELINE = os.path.join(MEM, "tools", "eval", "baseline.json")


# ---------------------------------------------------------------- 环境准备
def stub_astrbot():
    """插件头部会 import 一堆 astrbot 平台类型（离线没有这个包）。

    造一个"什么都接受"的假包：任何 astrbot.* 的模块/属性都能导入、能调用、
    能当基类。只为了让她的检索代码原样跑起来，不做任何真实动作。
    """
    import importlib.abc
    import importlib.machinery

    if getattr(sys, "_dsh_astrbot_stub", False):
        return

    class _AnyMeta(type):
        def __getattr__(cls, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any

        def __call__(cls, *a, **k):
            return object.__new__(cls)

    class _Any(metaclass=_AnyMeta):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any

        def __call__(self, *a, **k):
            return _Any()

        def __iter__(self):
            return iter(())

        def __bool__(self):
            return False

    class _Loader(importlib.abc.Loader):
        def create_module(self, spec):
            mod = types.ModuleType(spec.name)
            mod.__path__ = []
            return mod

        def exec_module(self, module):
            module.__getattr__ = lambda name: _Any

    class _Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "astrbot" or fullname.startswith("astrbot."):
                return importlib.machinery.ModuleSpec(
                    fullname, _Loader(), is_package=True)
            return None

    sys.meta_path.insert(0, _Finder())
    sys._dsh_astrbot_stub = True


def snapshot_db():
    """把真库备份成临时副本；只读源库，绝不写它。"""
    fd, tmp = tempfile.mkstemp(prefix="dsh_eval_", suffix=".db")
    os.close(fd)
    src = sqlite3.connect("file:%s?mode=ro" % SRC_DB.replace("\\", "/"), uri=True)
    dst = sqlite3.connect(tmp)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    return tmp


def load_config():
    """运行时配置 + schema 默认值（配置文件里不会写 schema 默认的那三个键）。"""
    cfg = {}
    try:
        with open(CFG, encoding="utf-8-sig") as f:
            cfg = json.load(f).get("recall_engine", {}) or {}
    except Exception as exc:  # noqa: BLE001
        print("  (读不到配置，用默认值：%s)" % exc)
    cfg.setdefault("recency_half_life_days", 30.0)
    cfg.setdefault("affect_weight", 0.0)      # 离线不读 8005，关掉情绪项，保证可复现
    cfg.setdefault("cue_weight", 0.15)
    cfg.setdefault("fallback_enabled", True)
    return cfg


class _NoVector:
    """向量路的占位：永远失败 → 走她的 _fallback_bm25_only（真代码，不是我写的）。"""

    async def search(self, *_a, **_k):
        raise RuntimeError("offline: no embedding provider")


# ---------------------------------------------------------------- 跑用例
async def run_cases(cases, top):
    from astrbot_plugin_livingmemory.core.processors.text_processor import TextProcessor
    from astrbot_plugin_livingmemory.core.retrieval.bm25_retriever import BM25Retriever
    from astrbot_plugin_livingmemory.core.retrieval.hybrid_retriever import (
        HybridRetriever,
    )
    from astrbot_plugin_livingmemory.core.retrieval.rrf_fusion import RRFFusion

    cfg = load_config()
    tmp = snapshot_db()
    try:
        tp = TextProcessor()
        init = getattr(tp, "async_init", None)   # 她自己的初始化（停用词 / 分词器）
        if init:
            await init()

        bm25 = BM25Retriever(tmp, tp, cfg)
        await bm25.initialize()
        hybrid = HybridRetriever(bm25, _NoVector(), RRFFusion(int(cfg.get("rrf_k", 60))), cfg)

        results = []
        for cs in cases:
            hits = await hybrid.search(cs["q"], k=top)
            texts = [getattr(h, "content", "") or "" for h in hits]
            want = cs.get("expect") or []
            at = None
            for i, txt in enumerate(texts):
                if any(w in txt for w in want):
                    at = i + 1
                    break
            results.append({"id": cs.get("id"), "q": cs["q"], "want": want,
                            "at": at, "got": texts})
        return results
    finally:
        try:
            os.remove(tmp)
        except Exception:  # noqa: BLE001
            pass


def metrics(rows):
    n = len(rows) or 1
    return {
        "n": len(rows),
        "R@1": round(sum(1 for r in rows if r["at"] == 1) / n, 4),
        "R@3": round(sum(1 for r in rows if r["at"] and r["at"] <= 3) / n, 4),
        "miss": [r["id"] for r in rows if r["at"] is None],
    }


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=CASES)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--save", action="store_true", help="把这轮成绩记成基线")
    a = ap.parse_args(argv)

    with open(a.cases, encoding="utf-8-sig") as f:
        raw = json.load(f)
    cases = raw.get("cases") if isinstance(raw, dict) else raw

    stub_astrbot()
    sys.path.insert(0, PLUGINS)
    try:                      # jieba 第一次会往 stderr 打"Building prefix dict..."
        import logging
        logging.getLogger("jieba").setLevel(logging.ERROR)
    except Exception:  # noqa: BLE001
        pass

    rows = asyncio.run(run_cases(cases, a.top))
    m = metrics(rows)

    if a.save:
        import time
        data = {"saved": time.strftime("%Y-%m-%d %H:%M:%S"), "top": a.top,
                "R@1": m["R@1"], "R@3": m["R@3"], "n": m["n"], "miss": m["miss"]}
        with open(BASELINE, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=1))
        print("已记基线：R@1 %.1f%% / R@3 %.1f%% -> %s"
              % (m["R@1"] * 100, m["R@3"] * 100, BASELINE))
        return 0

    if a.json:
        print(json.dumps({"metrics": m}, ensure_ascii=False, indent=1))
        return 0

    print("=" * 58)
    print("记忆召回评估 · 字面路（BM25 + 她的加权，向量已关）")
    print("=" * 58)
    print("  用例 %d 条    R@1 %5.1f%%    R@3 %5.1f%%"
          % (m["n"], m["R@1"] * 100, m["R@3"] * 100))
    if m["miss"]:
        print("  前 %d 条都没找到：%s" % (a.top, ", ".join(m["miss"])))
    if os.path.exists(BASELINE):
        try:
            with open(BASELINE, encoding="utf-8-sig") as f:
                b = json.load(f)
            d1 = (m["R@1"] - b.get("R@1", 0)) * 100
            d3 = (m["R@3"] - b.get("R@3", 0)) * 100
            flag = "⚠ 掉了" if d3 < -1 else ("✅" if d3 >= 0 else "")
            print("  对比基线（%s）：R@1 %+.1f  R@3 %+.1f  %s"
                  % (b.get("saved", "?"), d1, d3, flag))
        except Exception:  # noqa: BLE001
            pass
    if a.verbose:
        print("\n-- 明细 --")
        for r in rows:
            print("  %-4s at=%s  %s" % (r["id"], r["at"], r["q"]))
            if r["at"] is None:
                for g in r["got"][:3]:
                    print("         · " + g[:56].replace("\n", " "))
    # 只有"比基线掉了 5 个点以上"才算退步；第一次跑没有基线就只报数字
    if os.path.exists(BASELINE):
        try:
            with open(BASELINE, encoding="utf-8-sig") as f:
                b = json.load(f)
            if (b.get("R@3", 0) - m["R@3"]) * 100 > 5:
                return 1
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
