# -*- coding: utf-8 -*-
"""AstrBot 侧（QQ/网页）人设事件化同步：
1) 备份 data_v4.db 的 personas 表
2) 从「伴侣」system_prompt 中撤掉【你是什么样的】性格声明段（保留身份/你/说话/底线/语气）
3) 底线措辞同步（"可以任性、粘人" → "可以有情绪、可以要小东西"）
4) 校验：写回后读一次，确认无"粘人/嘴馋/傲娇/爱摸鱼/很粘人"
"""
import io, json, os, shutil, sqlite3, time

DB = r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\core\data\data_v4.db"
BAK_DIR = r"D:\你的数据目录\state\persona\snapshots"
os.makedirs(BAK_DIR, exist_ok=True)
stamp = time.strftime("%Y%m%d-%H%M%S")
bak = os.path.join(BAK_DIR, "data_v4.bak-%s.db" % stamp)
shutil.copy2(DB, bak)
print("已备份 data_v4.db ->", bak)

con = sqlite3.connect(DB)
cur = con.cursor()
row = cur.execute("SELECT system_prompt FROM personas WHERE persona_id='伴侣'").fetchone()
if not row:
    raise SystemExit("没找到伴侣人格")
text = row[0]
io.open(os.path.join(BAK_DIR, "qq.persona.before-%s.txt" % stamp), "w", encoding="utf-8").write(text)

# 撤掉【你是什么样的】整段（到【你的你】之前）
start = text.find("【你是什么样的】")
end = text.find("【你的你】")
if start >= 0 and end > start:
    slim = text[:start] + text[end:]
else:
    raise SystemExit("找不到【你是什么样的】段，先人工确认结构")

slim = slim.replace("可以任性、粘人，但不能", "可以有情绪、可以要小东西，但不能")
slim = slim.replace("很粘人。", "")
cur.execute("UPDATE personas SET system_prompt=?, updated_at=? WHERE persona_id='伴侣'",
            (slim, time.strftime("%Y-%m-%d %H:%M:%S")))
con.commit()

# 校验
row2 = cur.execute("SELECT system_prompt FROM personas WHERE persona_id='伴侣'").fetchone()[0]
bad = [w for w in ("粘人", "嘴馋", "傲娇", "爱摸鱼") if w in row2]
print("原 %d 字 -> 现 %d 字" % (len(text), len(row2)))
print("残留性格词:", bad or "无")
io.open(os.path.join(BAK_DIR, "qq.persona.after-%s.txt" % stamp), "w", encoding="utf-8").write(row2)
con.close()
print("AstrBot 侧人格已瘦身（重启 AstrBot 生效）")
