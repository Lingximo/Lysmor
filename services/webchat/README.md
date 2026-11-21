# 网页聊天（services/webchat）

不依赖 IM 平台的最小聊天通道骨架。

## 启动

```
python server.py --port 8001 --token 你自己的口令
```

- 不加 `--token` 时自动生成一个开发口令并打印出来；
- 默认只监听本机（127.0.0.1）。要开局域网/外网，先设好口令，并按项目根目录 `SECURITY.md` 检查防火墙；
- 浏览器打开 `http://127.0.0.1:8001/?t=你的口令`。

## 接你自己的大脑

`server.py` 里的 `reply(text)` 是插头。占位行为是 echo；接入方式：

- 本地模型（Ollama）：POST `http://127.0.0.1:11434/api/chat`；
- 云端 API：按服务商文档调用，把 `config/config.example.json` 里 `llm` 段的 key 带上；
- 或者干脆把请求转给机器人框架。

## 文件

| 文件 | 作用 |
|---|---|
| `server.py` | 服务端（Python 标准库，无第三方依赖） |
| `static/index.html` | 聊天页 |
| `static/style.css` | 样式 |
| `static/app.js` | 交互（含输入法组词保护、Enter 发送） |

## 安全提醒

- 口令门禁是"一道门"不是"保险箱"：只挂口令的 HTTP 页面在公网依然有风险，敏感场景用 HTTPS（视频通话页有示例）；
- 历史只存内存，重启即清——骨架刻意不落盘聊天记录，你要"记忆"就接到记忆系统去。
