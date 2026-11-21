# TA Pico 自检（实机回来跑一遍）

```powershell
powershell -ExecutionPolicy Bypass -File D:\你的数据目录\tools\pico_check.ps1
```

它会检查：

1. adb 是否连上头显
2. `com.companion.window` 是否安装
3. 8014 面板流是否在跑、能不能取到一帧
4. 头显里有没有 CameraVision / voice 日志
5. 当前前台应用

把输出发我，我按结果修。
