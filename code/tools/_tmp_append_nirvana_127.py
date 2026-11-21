import io
import datetime

path = r"D:\你的数据目录\灾后复活.md"
stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
text = f"""

---

## 127. 2026-11-15 下午：视觉入口分流、精细识图与时间戳防护

> 本轮不改人设、不改记忆正文；把 PICO 与电脑摄像头彻底分开，并修复一次“未来时间戳卡死识图”。

### 127.1 带TA出门（视觉入口总开关）

Hub 首页新增独立卡片：

```text
带TA出门
状态文件：D:\\你的数据目录\\state\\camera_source.json
```

```text
开 = pico：她的眼睛是 PICO 眼镜，电脑摄像头让位
关 = pc：她的眼睛是电脑摄像头，PICO 识图让位
```

统一控制：

```text
/api/look          只在 pc 模式工作（电脑摄像头）
/api/pico_look     只在 pico 模式工作（眼镜）
vision_context     pc 模式才注入
pico_vision_context pico 模式才注入
screen_context     pc 模式才注入
屏幕陪玩           pico 模式跳过
网页摄像头按钮      pico 模式自动关闭
```

Hub API：

```text
GET  /api/camera_source
POST /api/camera_source  {{"on": true/false}}
```

### 127.2 快速 / 精细识图

```text
平时：快速识图，640 缩略图，约 1~2 秒
用户说“看看 / 看一下 / 瞧瞧 / 帮我看看…”：
  960 缩略图
  360 token
  temperature 0.1
  更细的画面提示词
  约 5 秒
```

精细识图只在本次回复期间生效；`VISION_ACCURATE_LOCK` 防止 PICO 每 3 秒的快速帧覆盖精细结果。  
`handle_text` 的 finally 释放锁，下一帧自动回快速模式。

实测：

```text
快速：0.92~2.24 秒
精细：4.85~5.03 秒
回复后下一帧：1.83 秒
```

### 127.3 未来时间戳卡死（重要教训）

测试时 PowerShell 的 `Get-Date -UFormat %s` 返回的 epoch 比真实 Unix 快约 8 小时。  
这个未来时间被写进 `PICO_VISION.frame_ts` 后，PICO 真机的正常帧全部被判定为旧帧，返回 `stale:true`，模型根本没有被调用。

已加防护：

```text
PICO frame_ts 超过当前时间 120 秒 → 按当前时间修正
PICO_VISION 记录超过当前时间 120 秒 → 清空重置
```

以后测试时间戳必须用 Python：

```python
import time; int(time.time())
```

不要再用 PowerShell 的 `%s` 做 epoch。

### 127.4 识图字幕清理

模型偶尔复述提示词，例如：

```text
只列画面内容，一句中文
```

已加 `clean_vision_caption()`，过滤提示词/思考残留，只保留画面内容。

### 127.5 全息球

```text
中心：淡蓝实体球（不透明，遮住盘中心）
外圈：复杂全息盘（橙红/红白分段环、青蓝弧、红色辐条）
动态：双层反向旋转、呼吸、脉冲、抓取加速
坐标：x=0.28, y=-0.24, z=0.48
```

曾遇到中心球与环不重合：环在 z=-0.012，球在 z=0，透视投影中心错开。  
现在球、外壳、内环、外环全部在 z=-0.012，三维中心重合。

### 127.6 本轮验证

```text
Hub 7 个服务全通
PICO 快速识图正常
未来时间戳防护正常
精细识图 5 秒内
回复后回快速
电脑摄像头识图正常
```

生成时间：{stamp}
"""
with io.open(path, "a", encoding="utf-8", newline="\n") as f:
    f.write(text)
print("appended", len(text))
