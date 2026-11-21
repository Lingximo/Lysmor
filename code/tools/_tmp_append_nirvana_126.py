import io
import datetime

path = r"D:\你的数据目录\灾后复活.md"
stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
text = f"""

---

## 126. 2026-11-15 下午：PICO 启动、隐私与手势收口

> 本轮只修运行生命周期和手势，不改人设、不改记忆正文。

### 126.1 相机生命周期（防“下次启动又不行”）

```text
应用启动：CameraVision idle，不初始化相机、不采集
握拳/捏合开窗：InitCamera + warmup
首次 Acquire 失败：0.5 秒重试
初始化失败：每 2 秒重试
连续 5 次取帧失败：自动重建相机会话
关窗：DestroyCameraCaptureSession + DestroyCameraDevice
切后台/睡眠：释放相机
回前台且窗口还开着：自动重建
```

这样既满足“没握拳不捕捉画面”，也不会再因为启动首帧竞态一直 NO SIGNAL。

### 126.2 手势与球

```text
球：x=0.28, y=-0.24, z=0.48（相机局部坐标）
半径：4.5cm
握拳阈值：0.090（张开约 0.111，握拳约 0.046~0.081）
捏合：可抓球、可开窗
球坐标不再凭感觉调，只按相机局部坐标计算
```

### 126.3 脚本与面板

```text
panel_watch.ps1 之前被拼接损坏（重复 4 份 + 半句残留），已重建
PicoPanel 任务保持禁用，避免重复开面板
AlphaPanel 改为 wscript + spawn_hidden.vbs 隐藏启动
Edge 面板只在屏幕外重建
所有 tools/*.ps1 解析通过
```

### 126.4 当前验证

```text
CameraVision idle
mic started
voice ws connected
```

开窗后日志会出现：

```text
Magnifier on
CameraVision warmup requested
CameraVision session ready=True
CameraVision crop
```

生成时间：{stamp}
"""
with io.open(path, "a", encoding="utf-8", newline="\n") as f:
    f.write(text)
print("appended", len(text))
