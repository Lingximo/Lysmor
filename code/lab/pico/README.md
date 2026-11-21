# TA · Pico 4 Ultra 接入（2026-11-10 起）

机器还没到（已下单，标准版 ¥4299）。这两天先把**不依赖头显**的部分做完。

## 目录

```text
lab\pico\eye_server_8804.py    电脑端：收透视相机帧 → 视觉描述（已跑通）
lab\pico\app\                  Pico 2D 客户端（Kotlin，正在编译）
D:\dev\                         工具链（JDK17 + Android SDK + Gradle，不占 C 盘）
```

## 两条线

### 线 1：2D 客户端（不需要 Unity）

```text
协议：TCP 8797，5 字节头（1=音频 / 2=JSON）+ 大端长度
上行：麦克风 16k 单声道 PCM，20ms 一块
下行：subtitle / heard / voice_pcm(base64, sr)
流程：说话 → 8797 → 她的回复 → 字幕 + 语音
```

### 线 2：相机（要 Unity，机器到货后做）

```text
Pico 4 Ultra 消费版 + PICO Unity Integration SDK 3.4.0
  PXR_CameraImage：双路 RGB，30fps，RGBA_8888
  权限：CAMERA + com.picovr.permission.SPATIAL_DATA
Unity 应用把帧压成 JPEG（640×480，10~15fps）→ POST http://<PC>:8804/frame
电脑端 8804 调 qwen3-vl 描述 → 她的"看见"
```

## 到货后的顺序

```text
1. 开开发者模式（设置→通用→关于→连点版本号）
2. adb devices 确认连上
3. 装 D:\dev\companion-pico.apk，戴上说一句话，确认字幕/声音
4. 装相机探针（Unity 编），确认能拿到双路帧
5. 接进 video server，让她的话能引用"看到的"
```
