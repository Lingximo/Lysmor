# Pico 相机探针（Unity）搭建说明

机器到货后再做；这两天先把工程准备好。

## 需要装什么

```text
Unity Hub + Unity 2022.3 LTS（约 10~15GB，装到 D 盘）
  · 安装时勾选 Android Build Support（含 SDK/NDK/OpenJDK）
PICO Unity Integration SDK（3.4.0 或更新）
  · https://developer-cn.picoxr.com/ → 下载 .unitypackage
  · 导入 Unity 后会提示配置：Project Settings → XR Plug-in Management → PICO
```

Unity 许可证需要你登录一次（个人版免费），我无法代登录。

## 工程结构（建议）

```text
New 3D (URP) 工程
  Assets/
    PicoCameraStreamer.cs     ← 本目录的文件，拖进 Assets
    PICO SDK 导入的内容
  Assets/Scenes/SampleScene
    · 空的 GameObject，命名 CameraStreamer
    · 挂 PicoCameraStreamer
    · Inspector 填 PC IP（例如 192.168.1.2），端口 8804
```

## 权限（AndroidManifest）

PICO SDK 导入后一般会自动加 `CAMERA`；还需要手动确认：

```xml
<uses-permission android:name="com.picovr.permission.SPATIAL_DATA" />
```

在 `Assets/Plugins/Android/AndroidManifest.xml` 里加（没有就新建）。

## 打包装到眼镜

```text
Build Settings → Android → Switch Platform
Player Settings:
  · Minimum API Level 29+
  · Scripting Backend: IL2CPP
  · Target Architectures: ARM64
Build → 得到 apk
adb install -r xxx.apk
```

## 第一次运行看什么

```text
戴上后首启会弹两个权限：相机、空间数据 → 都允许
电脑上开 8804（lab\pico\eye_server_8804.py）
看日志：
  PicoCameraStreamer: streaming XR_CAMERA_ID_RGB_LEFT_PICO 640x480
电脑端：GET http://127.0.0.1:8804/state → frames 在涨
       POST /frame?describe=1 返回 desc → 说明她真的"看见"了
```

## 已知风险

```text
· SPATIAL_DATA 权限被拒 → 拿不到帧（重装或去设置里给权限）
· 帧率/发热：640×480@10fps 比较稳，1080p 会热
· 色彩/方向：透视画面可能需要 180° 旋转或镜像，先看 /latest.jpg 调
```
