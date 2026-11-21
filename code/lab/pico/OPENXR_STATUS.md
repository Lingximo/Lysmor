# TA OpenXR 迁移状态（2026-11-14 03:19）

## 当前稳定 APK

```text
D:\dev\companion-openxr.apk
D:\dev\companion-openxr-20260318-0318.apk
```

已安装，包名 `com.companion.openxr`。

## 实机确认

```text
PassthroughEnabler: EnableSeeThroughManual=True
PICO_CreateFullScreenLayer: passthrough Started.
PICO_PassthroughStart: passthrough Started.
voice ws connected
ArchSort applied=136/136
```

## 已做

- OpenXR + XR Hands，右手食指/拇指关节可用
- Live2D 模型，ArchSort 136/136
- 语音 WebSocket（WiFi 直连 `YOUR-PC.local:8003`）
- 声纹 `profile_dad_pico.npz`，6 段，一致性 0.79，阈值 0.55
- 服务端 `video/server.py` 已接声纹 B 门控
- 头部跟踪 `XRHeadDriver`
- 指尖小球 + 食指方向射线
- PICO 透视开启

## 未完成

- 相机 RGB 帧：官方 `XR_PICO_camera_image` 只暴露
  `Begin/Acquire/GetImageData`，缺
  `CreateDevice/CreateCaptureSession/EnumerateCameras`，返回 -7。
- PXR 老相机：`libPxrPlatform` 直接调用返回 -12（平台句柄无效）。
- 放大窗/相机视觉依赖相机帧。

## 备份

```text
D:\dev\openxr2022-src-20261114-031923.zip
D:\你的数据目录\video\server.py.bak-voiceenroll-20261114-022510
D:\你的数据目录\video\server.py.bak-voiceid-20261114-023859
```

旧 PXR 工程、记忆、人设未改动。
