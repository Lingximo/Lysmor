# -*- coding: utf-8 -*-
"""全链路自检：服务 / 记忆 / 生命模拟 / 手 / 视线 / 文档包一致性

只读检查为主；唯一会写的是 hands 的急停/解除（立刻恢复）和一次真实召回。
"""
from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import sys
import time

import requests

OK = "PASS"
BAD = "FAIL"
WARN = "WARN"
rows = []


def add(name, status, detail=""):
    rows.append((name, status, detail))
    print("%-4s %-26s %s" % (status, name, detail))


def http_get(url, timeout=10):
    r = requests.get(url, timeout=timeout)
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:200])


def http_post(url, payload=None, timeout=30):
    r = requests.post(url, json=payload or {}, timeout=timeout)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text[:200]


def main():
    # ---------- 1. 服务端口 ----------
    ports = {
        8012: "AstrBot 面板", 8011: "OneBot", 8003: "视频", 8004: "视频(HTTPS)",
        8782: "屏幕观察", 8001: "网页聊天", 8002: "简笔画画廊", 8797: "手机中继",
        8009: "统一入口",
        8801: "眼睛服务", 8010: "她的手",
    }
    for port, name in ports.items():
        import socket
        s = socket.socket()
        s.settimeout(2)
        try:
            s.connect(("127.0.0.1", port))
            add("端口 %d %s" % (port, name), OK)
        except Exception:
            # 8782 屏幕观察：改为按需启动（陪玩采样时才起），不作为常驻必需端口
            if port == 8782:
                add("端口 %d %s" % (port, name), WARN, "未启动（按需）")
            else:
                add("端口 %d %s" % (port, name), BAD, "连不上")
        finally:
            s.close()

    # ---------- 2. 她的状态心跳 ----------
    state = (r"C:\你的用户\.astrbot_launcher\instances"
             r"\<BOT_INSTANCE>\core\data\plugin_data"
             r"\astrbot_plugin_companion_mood\state.json")
    age = time.time() - os.path.getmtime(state)
    add("生理状态心跳", OK if age < 600 else BAD, "%.0f 秒前更新" % age)
    try:
        data = json.load(io.open(state, encoding="utf-8"))
        mood = data.get("emotion_level") or "?"
        add("情绪/生理字段", OK if data.get("valence") is not None else WARN,
            "情绪=%s 饥饿=%.2f 精力=%.2f" % (mood, data.get("hunger", 0), data.get("energy", 0)))
    except Exception as exc:
        add("情绪/生理字段", BAD, str(exc)[:60])

    # ---------- 3. 记忆库 ----------
    db = (r"C:\你的用户\.astrbot_launcher\instances"
          r"\<BOT_INSTANCE>\core\data\plugin_data"
          r"\astrbot_plugin_livingmemory\livingmemory.db")
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    cur = con.cursor()
    total = cur.execute("select count(*) from documents").fetchone()[0]
    groups = cur.execute("select count(*) from (select text from documents group by text having count(*)>1)").fetchone()[0]
    integrity = cur.execute("pragma quick_check").fetchone()[0]
    con.close()
    wal = os.path.getsize(db + "-wal") / 1e6 if os.path.exists(db + "-wal") else 0.0
    add("记忆库完整性", OK if integrity == "ok" else BAD, integrity)
    add("记忆条数", OK, "%d 条（重复 %d 组，待清理）" % (total, groups))
    add("记忆库 WAL", OK if wal < 100 else WARN, "%.1f MB" % wal)

    # 去重记录文件（B 方案）
    recent = (r"C:\你的用户\.astrbot_launcher\instances"
              r"\<BOT_INSTANCE>\core\data\plugin_data"
              r"\astrbot_plugin_companion_mood\mem_recent.json")
    if os.path.exists(recent):
        try:
            n = len(json.load(io.open(recent, encoding="utf-8")))
            add("去重记录持久化", OK, "mem_recent.json %d 条" % n)
        except Exception as exc:
            add("去重记录持久化", BAD, "文件读不了：%s" % exc)
    else:
        add("去重记录持久化", WARN, "还没产生（等下一次生活事件写入）")

    # ---------- 4. 她的手 ----------
    try:
        code, j = http_get("http://127.0.0.1:8010/health")
        add("手的健康", OK if j.get("ok") else BAD, json.dumps(j, ensure_ascii=False))
        code, j = http_post("http://127.0.0.1:8010/do", {"action": "run_shell", "cmd": "x"})
        add("白名单拦截", OK if code == 400 else BAD, "HTTP %d %s" % (code, str(j)[:40]))
        http_post("http://127.0.0.1:8010/stop")
        code, j = http_post("http://127.0.0.1:8010/do", {"action": "volume", "delta": 1})
        add("急停生效", OK if code == 403 else BAD, "HTTP %d" % code)
        http_post("http://127.0.0.1:8010/resume")
        code, j = http_post("http://127.0.0.1:8010/do", {"action": "volume", "delta": 0})
        add("急停可解除", OK if code == 200 else BAD, str(j.get("result")))
    except Exception as exc:
        add("手的健康", BAD, str(exc)[:80])

    # ---------- 5. 陪玩 / 在场 ----------
    try:
        code, j = http_get("http://127.0.0.1:8003/api/companion/status")
        add("陪玩状态接口", OK if code == 200 else BAD, json.dumps(j, ensure_ascii=False))
        code, j = http_get("http://127.0.0.1:8003/api/proactive")
        add("气泡推送接口", OK if code == 200 else BAD, str(j)[:60])
    except Exception as exc:
        add("陪玩状态接口", BAD, str(exc)[:80])

    # ---------- 6. 视线（静态资源版本） ----------
    try:
        html = requests.get("http://127.0.0.1:8003/", timeout=10).text
        m = re.search(r"v\.\d{4}-\d{4}", html)
        gz = "/static/facegaze.js?v=" in html
        ai = "autoInteract: false" in requests.get(
            "http://127.0.0.1:8003/static/live2d/live2d.js?v=22", timeout=10).text
        add("页面版本号", OK if m else WARN, m.group(0) if m else "找不到")
        add("视线脚本版本", OK if gz else WARN, "facegaze 引用在" if gz else "缺引用")
        add("autoInteract 关闭", OK if ai else BAD, "live2d.js 已关" if ai else "还开着")
    except Exception as exc:
        add("视线检查", BAD, str(exc)[:80])

    # ---------- 7. 真实召回 ----------
    try:
        key = io.open(r"D:\你的数据目录\webchat\key.txt", encoding="utf-8").read().strip()
        t0 = time.time()
        r = requests.post("http://127.0.0.1:8001/api/send?t=" + key,
                          json={"text": "还记得我们认识那天吗"}, timeout=180, stream=True)
        out = ""
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            ev = json.loads(line)
            if ev.get("t"):
                out += ev["t"]
            if ev.get("done") and ev.get("text"):
                out = ev["text"]
        dt = time.time() - t0
        add("真实召回+回复", OK if out and dt < 60 else WARN,
            "%.1fs：%s" % (dt, out.replace("\n", " ")[:60]))
    except Exception as exc:
        add("真实召回+回复", BAD, str(exc)[:80])

    # ---------- 8. 文档 / 包 ----------
    doc = r"D:\你的数据目录\灾后复活.md"
    try:
        text = io.open(doc, encoding="utf-8").read()
        sections = re.findall(r"^## (\d+)\.", text, re.M)
        add("灾后复活章节", OK, "共 %d 节，最新 §%s" % (len(sections), max(sections, key=int)))
        need = ["## 81.", "## 82.", "## 83."]
        add("本次新增章节", OK if all(n in text for n in need) else WARN,
            ",".join(n for n in need if n in text))
    except Exception as exc:
        add("灾后复活章节", BAD, str(exc)[:60])

if __name__ == "__main__":
    main()
    bad = [r for r in rows if r[1] == BAD]
    warn = [r for r in rows if r[1] == WARN]
    print("\n合计 %d 项：PASS %d / WARN %d / FAIL %d" % (
        len(rows), len(rows) - len(bad) - len(warn), len(warn), len(bad)))
    sys.exit(1 if bad else 0)
