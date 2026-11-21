"""看上下文有没有逼近上限（只看不写）。

每次调用带的 token 存在 provider_stats 表里，这里直接统计最近 N 次：
  - 最大 / 平均输入 token
  - 占配置上限（默认 32768）的百分比
  - 超过 80% 就警告

用法: python check_context_usage.py [最近次数]
"""
import json
import os
import sqlite3
import sys

# Windows 控制台默认 GBK，打印 ✅/⚠ 会 UnicodeEncodeError 把输出打断
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

DB = r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\core\data\data_v4.db"
CFG = r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\core\data\cmd_config.json"


def context_limit():
    try:
        with open(CFG, encoding="utf-8-sig") as f:
            cfg = json.load(f)
        for prov in cfg.get("provider", []) or cfg.get("providers", []) or []:
            if isinstance(prov, dict) and "deepseek" in str(prov.get("id", "")).lower():
                return int(prov.get("max_context_tokens") or 32768)
    except Exception:  # noqa: BLE001
        pass
    return 32768


def main():
    limit = context_limit()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    if not os.path.exists(DB):
        print("找不到数据库:", DB)
        return

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = list(con.execute(
        "SELECT created_at, token_input_other, token_input_cached, token_output "
        "FROM provider_stats ORDER BY id DESC LIMIT ?", (n,)))
    con.close()
    if not rows:
        print("还没有调用记录")
        return

    ins = [int(r[1] or 0) + int(r[2] or 0) for r in rows]
    outs = [int(r[3] or 0) for r in rows]
    peak = max(ins)
    avg = sum(ins) / len(ins)
    print(f"最近 {len(rows)} 次调用 | 上限 {limit} token")
    print(f"  输入最大 {peak} ({100*peak/limit:.0f}% of 上限)")
    print(f"  输入平均 {avg:.0f} ({100*avg/limit:.0f}%)")
    print(f"  输出平均 {sum(outs)/len(outs):.0f}")
    print(f"  最挤的那次: {rows[ins.index(peak)][0]}")

    ratio = peak / limit
    if ratio >= 0.8:
        print("⚠ 已经到 80% 以上，该收一收历史或记忆注入了")
    elif ratio >= 0.6:
        print("⚠ 到 60% 了，还安全但别再加东西")
    else:
        print("✅ 余量充足")


if __name__ == "__main__":
    main()
