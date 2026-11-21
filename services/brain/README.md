# 记忆星图（services/brain）

把记忆按主题聚类画成星图：**点 = 记忆，连线 = 同主题关联**。

## 启动

```
python server.py --port 8006 --token 你自己的口令
```

- 浏览器打开 `http://127.0.0.1:8006/?t=你的口令`；
- 交互：滚轮缩放、拖拽平移、悬停看摘要。

## 数据

- 服务器读 `data/memories.json`；
- 不存在时退回 `data/memories.example.json`（**演示数据，全是示例记忆**）；
- 接你自己的记忆系统：把记忆导出成同样结构即可——

```json
{
  "nodes": [
    {"id": 1, "summary": "记忆摘要文本", "topic": "主题", "importance": 0.8, "t": "2026-01-01"}
  ]
}
```

`links` 不用自己算：服务端按"同主题"自动生成连线。

## 文件

| 文件 | 作用 |
|---|---|
| `server.py` | 数据读取 + 连线生成 + 服务端（纯标准库） |
| `data/memories.example.json` | 演示数据（可删，换成你自己的导出） |
| `static/index.html` / `style.css` / `app.js` | 星图页（Canvas，无第三方库） |

## 安全提醒

- 记忆摘要可能包含隐私：页面挂口令门禁，敏感内容别放进公网部署；
- `memories.json`（真实数据）已被 `.gitignore` 屏蔽，示例文件不受影响。
