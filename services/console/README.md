# 控制台（services/console）

一页总览：**各服务健康度 + 生命状态摘要 + 最近动态 + 最近记忆数**。只读，卡片点击跳到对应服务页面。

## 启动

```
python server.py --port 8001 --token 你自己的口令
```

- 浏览器打开 `http://127.0.0.1:8001/?t=你的口令`；
- 每 5 秒自动刷新。

## 设计

- 服务注册表在 `data/services.json`：每个服务 = 名字 + 地址 + 健康端点 + 页面入口；
- 控制台定时 GET 各服务的健康端点判断"运行中/未启动"；
- 生命面板、记忆星图在运行时，会顺手把它们的数据摘要拉过来展示；
- 最近动态读 `data/activity.json`（接你自己的系统时往里写即可）。

## 文件

| 文件 | 作用 |
|---|---|
| `server.py` | 聚合探活 + 服务端（纯标准库） |
| `data/services.json` | 服务注册表 |
| `data/activity.json` | 最近动态示例 |
| `static/index.html` / `style.css` / `app.js` | 控制台页 |
