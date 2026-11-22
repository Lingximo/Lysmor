# 模型与接口需求清单

本项目**不附带任何模型文件与密钥**。这份清单只是"指路"——一切由使用者从官方源自行获取，
并**自行核对每个模型/服务的授权**是否允许你的用途（尤其商用与否）。

## 云端接口（API）

| 接口 | 用途 | 获取方式 | 授权/计费 |
|---|---|---|---|
| **DeepSeek API** | 聊天的大脑（推荐） | `platform.deepseek.com` 注册并创建 Key | 按量计费；模型 `deepseek-chat`（日常）/ `deepseek-reasoner`（深度思考） |
| 其它 OpenAI 兼容 API | 换别家大脑 | 各服务商官网 | 各自条款 |
| edge-tts | 语音合成（在线，免 Key） | `pip install edge-tts` | 微软在线服务，留意服务条款 |

## 本地模型

| 模型 | 用途 | 获取方式 | 授权（以官方发布页为准） |
|---|---|---|---|
| qwen3-vl:4b | 视觉理解（摄像头 / 看图） | `ollama pull qwen3-vl:4b` | Apache-2.0 |
| bge-m3 | 记忆向量检索（embedding） | `ollama pull bge-m3` | MIT |
| faster-whisper small | 语音识别（约 460MB） | `pip install faster-whisper`，首次运行自动下载 | MIT（模型见 Hugging Face 发布页） |
| 画图模型（如 animagine-xl 系列） | 画画 | 在 ComfyUI 中按官方指引下载 | 各模型授权不同（多为 Open RAIL 类），请逐一看发布页 |

> "授权"一列只是常见说法，**最终以模型/服务官方发布页为准**；商用与否、能否再分发，逐项确认后再决定怎么用。

## 软件环境（非模型，一并列出）

| 软件 | 用途 | 怎么装 | 授权注意 |
|---|---|---|---|
| Python 3.12 | 运行所有脚本 | python.org，勾 Add to PATH | PSF 许可 |
| **AstrBot** | 聊天机器人框架（大脑外壳） | 官方 GitHub 仓库按文档安装启动器 | 见其官方仓库；装好后把本仓库 `code/plugins/` 里的 `companion_*` 插件拷进实例的 `data/plugins/`，并记下实例 UUID |
| Ollama | 本地模型服务 | ollama.com | MIT |
| ffmpeg | 音视频处理 | gyan.dev essentials 构建 | GPL/LGPL |
| NapCat | QQ 协议接入 | 见其官方仓库 | **QQ 本体是腾讯闭源软件，必须由使用者自行安装** |
| 蒲公英 | 外网隧道（可选） | 官网 | 闭源，自行注册安装 |
| ComfyUI | 画图工作流（可选） | 官方仓库 | 见其官方仓库 |

## 自备素材 / 可选工具（开源包里刻意没有的）

| 东西 | 说明 | 怎么准备 |
|---|---|---|
| **角色形象素材**（Live2D .moc3 + 贴图 / 立绘） | 形象属于角色本人，开源包不附带任何形象 | 使用者自备；配置向导「🎨 素材导入」一键导入到 `code/video/static/live2d/` |
| 表情包素材 | 同理 | 自备；向导「🎨 素材导入」导入到 `code/assets/stickers/` |
| 视频通话背景 | 同理 | 自备；向导「🎨 素材导入」导入到 `code/video/static/backgrounds/` |
| 桌宠形象 | 同理 | 自备；向导「🎨 素材导入」导入到 `code/app/petweb/whale/` |
| 大平层户型 | 户型属于部署者自己的家 | 把 `code/houseviz/plan.json.example` 复制成 `plan.json` 再改成自己的布局（不建会起不来） |
| Electron 运行时（可选） | 只有想把聊天页包成独立桌面 App 才需要 | electronjs.org；壳源码在 `code/app/` |
| Android 平台工具 adb（可选） | 眼镜部署用 | Android SDK Platform-Tools |

## 三个提醒

1. 本清单只是"指路"，**不搬运、不打包、不托管**任何模型、软件与密钥文件；
2. 本项目自身按 GNU AGPL-3.0 发布，但它**不改变**第三方模型/服务各自的授权；
3. **API Key 类只填本地 `config.json`**，`config.example.json` 里永远是空占位。
