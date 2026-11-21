import datetime
import io

path = r"D:\你的数据目录\灾后复活.md"
stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
text = f"""

---

## 125. 2026-11-15 凌晨：PICO / 语音最终收口与灾后复活整合

> 本轮不改人设、不改记忆正文、不重置任何东西；只把今晚验证过的运行状态、模型约束和修复记录进灾后复活。

### 125.1 最终运行配置

```text
PICO：旧 PXR 应用 com.companion.window，不是 OpenXR
视觉模型：qwen3-vl:4b（本地 GPU）
视觉预算：220 token + 直接回答提示词
视觉热机：约 2 秒；冷启动第一次会慢一些
显存：8GB，qwen3-vl 约 3.6GB；bge-m3 放 CPU
Ollama：OLLAMA_MAX_LOADED_MODELS=2
语音 TTS：edge zh-CN-XiaoyiNeural 优先，本地 piper 兜底
声纹门：PICO 阈值 0.55，只认你
记忆检索：bge-m3 + faiss；双模型常驻后约 0.06 秒
```

`qwen2.5vl:3b` 曾下载测试过：热机约 0.27 秒，但把窗帘/衣物识别成“黑色外套的狗”，已删除，不进入正式链路。

### 125.2 今晚已验证

```text
声纹门：其他人说话 0.003~0.479 全部拒绝；你 0.554 / 0.660 通过
语音延迟：首字 1.21~2.95 秒，整段 2.57~4.49 秒
识图：PICO 最新帧时间戳 + 30 秒过期；旧请求返回 stale，不覆盖新描述
视觉来源：问“眼镜/前面/看到我”只用 PICO；问“屏幕/电脑/桌面”才抓 PC
大平层补水：渴/饿优先于视频/聊天；睡着且渴≥0.92 会醒来接水
补水平衡：thirst 1.0 → 0.403，last_water_dispenser_at 已写入
字幕：下移到 y=-0.32
```

### 125.3 不随包、换电脑要补的

```text
Ollama 模型文件（qwen3-vl:4b、bge-m3）不进灾后复活包，需 ollama pull
Ollama 环境：OLLAMA_MAX_LOADED_MODELS=2
模型在 GPU/CPU 的分配：qwen3-vl 用 GPU，bge-m3 用 CPU
PICO APK 不进包；源码在 code/pico/companion-window
```

### 125.4 本轮收尾

```text
更新本文件 → build.py → kit.py → upload.py --upload-only
→ check_nirvana_sync.py → 触发 Companion-Nirvana → core_fingerprint --baseline
```

生成时间：{stamp}
"""
with io.open(path, "a", encoding="utf-8", newline="\n") as f:
    f.write(text)
print("appended", path, "len", len(text))
