# -*- coding: utf-8 -*-
"""一键配置

两条路，效果一样：
  · 可视化向导（推荐）：双击 一键配置.cmd，浏览器里填表点按钮
  · 命令行：python configure.py            # 交互式
            python configure.py --non-interactive

apply_config() 是公共入口：向导服务器和命令行都调它。
"""

import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import uuid
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.join(ROOT, "code")
CFG_PATH = os.path.join(ROOT, "config.json")

DEFAULTS = {
    "data_dir": os.path.join(ROOT, "code"),
    "user_dir": os.path.expanduser("~"),
    "gate_token": "",
    "qq": "1000000000",
    "qq2": "1000000001",
    "bot_instance": str(uuid.uuid4()),
    "llm": {
        "provider": "deepseek",
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "bot_panel": 8012,
    "fish_qq": "",
    "ports": {
        "chat": 8001, "gallery": 8002, "video": 8003, "video_https": 8004,
        "life": 8005, "brain": 8006, "house": 8007, "qr": 8008,
        "hub": 8009, "hands": 8010, "bot": 8011, "panel": 8012, "napcat": 8013,
    },
}

PORT_KEY = [
    (8001, "chat"), (8002, "gallery"), (8003, "video"), (8004, "video_https"),
    (8005, "life"), (8006, "brain"), (8007, "house"), (8008, "qr"),
    (8009, "hub"), (8010, "hands"), (8011, "bot"), (8012, "panel"), (8013, "napcat"),
]

TEXT_EXT = (".py", ".js", ".html", ".css", ".md", ".txt", ".ps1", ".cmd", ".xml", ".cs")


def _launcher_dirs(user_dir=""):
    """AstrBot 启动器可能所在的目录。

    以前只查 ~/.astrbot_launcher，装到别处（或换了用户名/盘符）就永远“找不到实例”。
    这里把常见的家目录、LOCALAPPDATA/APPDATA、ProgramData 和环境变量都算上。
    """
    cands = []
    env = os.environ.get("ASTRBOT_LAUNCHER_DIR") or os.environ.get("ASTRBOT_HOME") or ""
    if env:
        env = os.path.expandvars(env)
        cands.append(env)
        if not os.path.basename(env).lower().endswith(".astrbot_launcher"):
            cands.append(os.path.join(env, ".astrbot_launcher"))
    for base in (user_dir, os.path.expanduser("~"), os.environ.get("USERPROFILE"),
                 os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA"),
                 os.environ.get("ProgramData")):
        if base:
            cands.append(os.path.join(base, ".astrbot_launcher"))
            cands.append(os.path.join(base, "astrbot_launcher"))
    out, seen = [], set()
    for p in cands:
        try:
            p = os.path.abspath(p)
        except Exception:  # noqa: BLE001
            continue
        key = os.path.normcase(p)
        if key in seen or not os.path.isdir(p):
            continue
        seen.add(key)
        out.append(p)
    return out


def autodetect(user_dir=""):
    """自动探测这台机器上的 AstrBot 实例与面板端口。"""
    out = {"bot_instance": "", "bot_panel": 8012, "cmd_config": "", "instance_dir": ""}
    candidates = []
    for launcher in _launcher_dirs(user_dir):
        base = os.path.join(launcher, "instances")
        if not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            p = os.path.join(base, name)
            cfgp = os.path.join(p, "core", "data", "cmd_config.json")
            if os.path.isdir(p) and os.path.exists(cfgp):
                try:
                    mt = os.path.getmtime(p)
                except OSError:
                    mt = 0
                candidates.append((mt, name, cfgp, p))
    if candidates:
        candidates.sort(reverse=True)
        _, inst, cfgp, inst_dir = candidates[0]
        out["bot_instance"] = inst
        out["cmd_config"] = cfgp
        out["instance_dir"] = inst_dir
        try:
            dash = json.load(open(cfgp, encoding="utf-8-sig")).get("dashboard") or {}
            if isinstance(dash.get("port"), int):
                out["bot_panel"] = dash["port"]
        except Exception:  # noqa: BLE001
            pass
    return out


def env_install_missing():
    """尽力自动安装缺失的环境（除账号外的软件），返回 [{name, ok, detail, hint}]。
    winget 有的就 winget 静默装；装完 Ollama 后在后台拉两个模型。"""
    results = []

    def _friendly_error(out: str) -> str:
        low = (out or "").lower()
        if "0x80072efd" in low or "internetopenurl" in low or "无法连接" in low or "cannot connect" in low:
            return ("下载失败：这台电脑连不上 GitHub/Ollama 的下载源。"
                    "请检查网络或代理，或手动安装后重跑本页（Ollama: ollama.com/download/windows）")
        if "0x80072ee7" in low or "name resolution" in low or "解析" in out:
            return "下载失败：域名解析失败，请检查 DNS/网络后重试，或手动安装。"
        return "安装失败：" + ((out or "未知错误").strip().splitlines() or ["未知错误"])[-1][:180]

    def winget(pkg, name, manual=""):
        if not shutil.which("winget"):
            results.append({"name": name, "ok": False,
                            "detail": "没找到 winget，请手动安装（见 docs/model-requirements.md）" + (("；" + manual) if manual else "")})
            return False
        try:
            r = subprocess.run(["winget", "install", "-e", "--id", pkg,
                                "--accept-source-agreements", "--accept-package-agreements",
                                "--silent"], capture_output=True, text=True, timeout=900)
            out = (r.stdout or "") + (r.stderr or "")
            ok = r.returncode == 0
            results.append({"name": name, "ok": ok,
                            "detail": (out.strip()[-160:] if ok else _friendly_error(out))})
            return ok
        except Exception as exc:  # noqa: BLE001
            results.append({"name": name, "ok": False,
                            "detail": "安装失败：" + str(exc)[:120] + (("；" + manual) if manual else "")})
            return False

    # Python 3.12
    if sys.version_info[:2] == (3, 12):
        results.append({"name": "Python 3.12", "ok": True, "detail": "%d.%d.%d 已装" % sys.version_info[:3]})
    else:
        winget("Python.Python.3.12", "Python 3.12", "python.org/downloads，安装时勾 Add to PATH")

    # Ollama
    ollama_ok = bool(shutil.which("ollama"))
    if ollama_ok:
        results.append({"name": "Ollama", "ok": True, "detail": shutil.which("ollama")})
    else:
        if winget("Ollama.Ollama", "Ollama", "ollama.com/download/windows"):
            ollama_ok = True
        else:
            # winget 装完有时 PATH 还没刷新，直接再查一遍常见安装位置
            for cand in (
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
                r"C:\Program Files\Ollama\ollama.exe",
            ):
                if cand and os.path.isfile(cand):
                    ollama_ok = True
                    results.append({"name": "Ollama", "ok": True, "detail": cand + "（重开终端后 PATH 才会更新）"})
                    break
            if not ollama_ok:
                results.append({"name": "Ollama", "ok": False,
                                "detail": "Ollama 没装上：其它功能还能用，但视觉/向量检索（qwen3-vl、bge-m3）需要它。"
                                          "手动装：https://ollama.com/download/windows ，装完重跑本页。"})

    # ffmpeg
    ff = shutil.which("ffmpeg")
    if ff:
        results.append({"name": "ffmpeg", "ok": True, "detail": ff})
    else:
        winget("Gyan.FFmpeg", "ffmpeg", "winget install Gyan.FFmpeg")

    # AstrBot（没有 winget 包，给指引）
    det = autodetect()
    if det["bot_instance"]:
        results.append({"name": "AstrBot", "ok": True, "detail": "已找到实例 " + det["bot_instance"]})
    else:
        results.append({"name": "AstrBot", "ok": False,
                        "detail": "没自动找到启动器实例（查了家目录 / LOCALAPPDATA / APPDATA 下的 "
                                  ".astrbot_launcher）。如果已经装了：设环境变量 ASTRBOT_LAUNCHER_DIR "
                                  "指向启动器目录，或在向导里手填实例 UUID；只用网页可以先继续"})

    # 模型：只有 Ollama 真能用才拉，否则如实说没拉
    if ollama_ok:
        _pull_models_background()
        results.append({"name": "模型下载", "ok": True, "detail": "已后台开始拉 qwen3-vl:4b 与 bge-m3（可能要几分钟，稍后体检可见）"})
    else:
        results.append({"name": "模型下载", "ok": False, "detail": "跳过：Ollama 没装上，先装 Ollama 再重跑本页"})
    return results



def _pull_models_background():
    for m in ("qwen3-vl:4b", "bge-m3"):
        try:
            subprocess.Popen(["ollama", "pull", m],
                             creationflags=0x00000008 | 0x08000000,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001
            pass


def enrollment_dir(cfg):
    return os.path.join(cfg.get("data_dir") or "", "state", "enrollment")


# 素材导入目标目录（相对 data_dir，即 code/ 目录）
ASSET_DIRS = {
    "live2d": ("video", "static", "live2d"),
    "stickers": ("assets", "stickers"),
    "background": ("video", "static", "backgrounds"),
    "pet": ("app", "petweb", "whale"),
}


def import_assets(cfg, kind, files):
    """把用户选的素材文件（base64 列表）写入对应目录。返回 {ok, count, saved, dir}"""
    import base64 as _b64
    parts = ASSET_DIRS.get(kind)
    if not parts:
        return {"ok": False, "error": "未知素材类型: %s" % kind}
    base = os.path.join(cfg.get("data_dir") or "", *parts)
    saved = []
    for f in files or []:
        name = str(f.get("name") or "").replace("\\", "/")
        segments = [s for s in name.split("/") if s not in ("", ".", "..")]
        if not segments:
            continue
        dst = os.path.join(base, *segments)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(_b64.b64decode(str(f.get("data") or "").split(",", 1)[-1]))
            saved.append("/".join(segments))
        except Exception:  # noqa: BLE001
            pass
    return {"ok": bool(saved), "count": len(saved), "saved": saved[:300], "dir": base}


def save_enrollment(cfg, voice, faces):
    """声纹（5 段 base64 wav）与人脸（上/下/左/右/正 5 张 base64 jpg）落盘。返回 {ok, saved, note}"""
    base = enrollment_dir(cfg)
    saved = []
    import base64 as _b64
    for slot, data in (voice or {}).items():
        try:
            d = os.path.join(base, "voice")
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "voice_%s.wav" % slot)
            with open(p, "wb") as f:
                f.write(_b64.b64decode(data.split(",", 1)[-1]))
            saved.append(os.path.relpath(p, cfg.get("data_dir") or ""))
        except Exception:  # noqa: BLE001
            pass
    for slot, data in (faces or {}).items():
        try:
            d = os.path.join(base, "faces")
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "face_%s.jpg" % slot)
            with open(p, "wb") as f:
                f.write(_b64.b64decode(data.split(",", 1)[-1]))
            saved.append(os.path.relpath(p, cfg.get("data_dir") or ""))
        except Exception:  # noqa: BLE001
            pass
    note = ("已保存 %d 个样本。注意：声纹/人脸匹配的识别代码在你的机器人系统里；"
            "开源包负责采集与登记，样本只存本地 data_dir，不进仓库。" % len(saved))
    return {"ok": len(saved) > 0, "saved": saved, "note": note}


def astrbot_config_path(cfg):
    """AstrBot 主配置路径（按真实系统的目录布局推导）。"""
    return os.path.join(cfg.get("user_dir") or "", ".astrbot_launcher", "instances",
                        cfg.get("bot_instance") or "", "core", "data", "cmd_config.json")


def patch_astrbot_llm(cfg):
    """把 DeepSeek API Key 写进 AstrBot 的模型服务商配置（provider_sources 里 provider=deepseek 的 key 字段）。
    写前自动备份；找不到就返回说明文字，绝不报错打断配置流程。"""
    key = ((cfg.get("llm") or {}).get("api_key") or "").strip()
    if not key:
        return "没填 Key，跳过 AstrBot 写入"
    path = astrbot_config_path(cfg)
    if not os.path.exists(path):
        return "没找到 AstrBot 配置（%s）——装好 AstrBot 后重跑配置即可自动写入" % path
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        sources = data.get("provider_sources")
        if not isinstance(sources, list):
            return "AstrBot 配置里没有 provider_sources —— 请先在管理面板添加 DeepSeek 服务商，再重跑配置"
        target = None
        for item in sources:
            if isinstance(item, dict) and item.get("provider") == "deepseek":
                target = item
                break
        if target is None:
            return "AstrBot 里还没有 DeepSeek 服务商条目 —— 先在管理面板添加，再重跑配置"
        bak = path + ".bak-before-llm-" + time.strftime("%Y%m%d_%H%M%S")
        with open(bak, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        target["key"] = key
        base = ((cfg.get("llm") or {}).get("base_url") or "").strip()
        if base and not target.get("api_base"):
            target["api_base"] = base
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return "已写入 AstrBot 模型配置（原文件已备份 %s）" % os.path.basename(bak)
    except Exception as exc:  # noqa: BLE001
        return "写入 AstrBot 配置失败（%s）——请手动在管理面板填" % str(exc)[:80]


# ---------------- 身份词 → 人格提示词（可选，用使用者自己的 API） ----------------
# 身份词：只用来确认身份（她叫什么、怎么称呼、什么关系、底线），不是人格提示词。
# 优化：用使用者自己的 API 把身份词扩写成一份完整的人格提示词（system prompt），
#      写到 data_dir/video/config.json 的 persona 字段（视频服务唯一人设来源）。
IDENTITY_META_PROMPT = (
    "你是一个 AI 伴侣系统的「人设生成器」。使用者会给你一段【身份词】，"
    "它只用于确认身份（她叫什么、你们是什么关系、怎么称呼），不是人格提示词。\n"
    "请你依据这段身份词，写出一份完整、稳定、可长期使用的人格提示词（system prompt）。要求：\n"
    "1. 只写「她是谁、和你的关系与称呼、说话风格与语气、情绪表达方式、行为边界与红线、2~3 句语气示例」；\n"
    "2. 不编造具体经历、不写记忆内容、不写技术细节、不提任何系统/模型/插件；\n"
    "3. 用第二人称「你」来写，语气自然；长度 800~2000 字；\n"
    "4. 只输出人格提示词正文，不要标题、不要解释、不要代码块。"
)


def identity_path(cfg):
    """人设文件：data_dir/video/config.json（视频服务 persona 的唯一来源）。"""
    return os.path.join(str(cfg.get("data_dir") or DEFAULTS["data_dir"]), "video", "config.json")


def load_identity(cfg):
    """读回身份词与人格提示词（没有就返回空串）。"""
    p = identity_path(cfg)
    try:
        with open(p, encoding="utf-8-sig") as f:
            d = json.load(f)
        return {"identity": str(d.get("identity_raw") or ""), "persona": str(d.get("persona") or "")}
    except Exception:  # noqa: BLE001
        return {"identity": "", "persona": ""}


def save_identity(cfg, identity_raw, persona):
    """把身份词（仅确认身份）和优化后的人格提示词写进 video/config.json。"""
    p = identity_path(cfg)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        with open(p, encoding="utf-8-sig") as f:
            d = json.load(f)
    except Exception:  # noqa: BLE001
        d = {}
        try:
            with open(os.path.join(CODE, "video", "config.example.json"), encoding="utf-8-sig") as f:
                d = json.load(f)
        except Exception:  # noqa: BLE001
            d = {}
    d["identity_raw"] = str(identity_raw or "")
    d["persona"] = str(persona or "")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    # 根 config.json 也留一份，方便向导回显（真值以 video/config.json 为准）
    try:
        root = {}
        if os.path.exists(CFG_PATH):
            with open(CFG_PATH, encoding="utf-8-sig") as f:
                root = json.load(f)
        root["identity"] = str(identity_raw or "")
        root["persona"] = str(persona or "")
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(root, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass
    return p


def optimize_identity(identity_raw, llm):
    """用使用者自己的 API 把身份词扩写成完整人格提示词。返回提示词正文。"""
    import urllib.request
    identity_raw = str(identity_raw or "").strip()
    if not identity_raw:
        raise ValueError("身份词是空的，先写一段")
    api_key = str((llm or {}).get("api_key") or "").strip()
    if not api_key:
        raise ValueError("还没有填 DeepSeek API Key（在「账号清单」里填，然后重试）")
    base = str((llm or {}).get("base_url") or DEFAULTS["llm"]["base_url"]).rstrip("/")
    model = str((llm or {}).get("model") or "deepseek-chat")
    payload = {
        "model": model,
        "temperature": 0.7,
        "messages": [
            {"role": "system", "content": IDENTITY_META_PROMPT},
            {"role": "user", "content": "身份词：\n" + identity_raw[:2000]},
        ],
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    text = text.strip()
    if not text:
        raise RuntimeError("API 返回了空内容，换个模型或重试")
    return text


def apply_config(cfg):
    """重写 code/ 占位符，写 config.json 与口令文件。返回 (文件数, 替换处数)。"""
    if not os.path.isdir(CODE):
        raise RuntimeError("没找到 code/ 目录，请在项目根目录运行")

    try:
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        raise RuntimeError("写不了 config.json（%s）——请把整个项目放到可写目录（桌面/文档），"
                           "不要放在 Program Files 或只读盘" % exc) from exc

    repl = [
        ("D:\\你的数据目录", cfg["data_dir"]),                                  # 单反斜杠
        ("D:\\\\你的数据目录", cfg["data_dir"].replace("\\", "\\\\")),          # 双反斜杠（注释/文档里）
        ("D:/你的数据目录", cfg["data_dir"].replace("\\", "/")),                # 正斜杠（SQLite URI 里）
        ("C:\\你的用户", cfg["user_dir"]),
        ("C:/你的用户", cfg["user_dir"].replace("\\", "/")),
        ("<你的QQ号2>", cfg["qq2"]),
        ("<你的QQ号>", cfg["qq"]),
        ("<BOT_INSTANCE>", cfg["bot_instance"]),
        ("<GATE_TOKEN>", cfg["gate_token"]),
    ]
    port_pats = [(re.compile(r"(?<!\d)%d(?!\d)" % num), str(cfg["ports"][key]))
                 for num, key in PORT_KEY if int(cfg["ports"].get(key, num)) != num]
    n_files = n_repl = 0
    for dp, dn, fns in os.walk(CODE):
        if "__pycache__" in dp:
            continue
        for fn in fns:
            if not fn.lower().endswith(TEXT_EXT):
                continue
            p = os.path.join(dp, fn)
            try:
                raw = open(p, encoding="utf-8").read()
            except Exception:
                continue
            text = raw
            for old, new in repl:
                text = text.replace(old, new)
            for pat, new in port_pats:
                text, c = pat.subn(new, text)
                n_repl += c
            if text != raw:
                try:
                    with open(p, "w", encoding="utf-8", newline="") as f:
                        f.write(text)
                except OSError as exc:
                    # 单个文件被占用/只读（杀软、同步盘）不该让整次配置失败
                    print("  ! 跳过写不了的 %s：%s" % (p, str(exc)[:80]))
                    continue
                n_files += 1
                for old, _ in repl:
                    n_repl += raw.count(old)

    gp = os.path.join(cfg["data_dir"], "gate_token.txt")
    try:
        with open(gp, "w", encoding="utf-8") as f:
            f.write(cfg["gate_token"])
    except OSError as exc:
        print("  ! 口令文件没写进数据目录：%s" % exc)

    # 大平层户型：没有 plan.json 就从示例复制一份，用户再按自己家改
    plan = os.path.join(cfg["data_dir"], "houseviz", "plan.json")
    plan_example = os.path.join(CODE, "houseviz", "plan.json.example")
    if os.path.exists(plan_example) and not os.path.exists(plan):
        try:
            import shutil as _sh
            _sh.copy2(plan_example, plan)
            print("  大平层户型：已从示例复制 plan.json")
        except Exception as exc:  # noqa: BLE001
            print("  ! 户型复制失败：%s" % exc)

    # 视频服务配置：没有 config.json 就从示例复制一份（人设/模型由使用者自己填）
    vcfg = os.path.join(cfg["data_dir"], "video", "config.json")
    vcfg_example = os.path.join(CODE, "video", "config.example.json")
    if os.path.exists(vcfg_example) and not os.path.exists(vcfg):
        try:
            import shutil as _sh
            _sh.copy2(vcfg_example, vcfg)
            print("  视频服务：已从示例复制 config.json")
        except Exception as exc:  # noqa: BLE001
            print("  ! 视频配置复制失败：%s" % exc)
    return n_files, n_repl


def _listening(port):
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except Exception:
        return False


def _http_ok(port):
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=0.8)
        return True
    except Exception:
        return False


def check_setup():
    """配置体检：返回 [{level: ok|warn|fail, name, detail, hint}, ...]"""
    checks = []

    def add(level, name, detail, hint=""):
        checks.append({"level": level, "name": name, "detail": detail, "hint": hint})

    # 1) config.json
    try:
        cfg = json.load(open(CFG_PATH, encoding="utf-8-sig"))
        add("ok", "config.json", "已生成", "")
    except Exception:
        cfg = None
        add("fail", "config.json", "还没有", "先跑一键配置（可视化：双击 一键配置.cmd）")

    # 2) 占位符替换干净没有
    markers = ("你的数据目录", "<你的QQ号>", "<BOT_INSTANCE>", "<GATE_TOKEN>")
    left = []
    for dp, dn, fns in os.walk(CODE):
        if "__pycache__" in dp:
            continue
        for fn in fns:
            if not fn.lower().endswith(TEXT_EXT):
                continue
            try:
                raw = open(os.path.join(dp, fn), encoding="utf-8").read()
            except Exception:
                continue
            for m in markers:
                if m in raw:
                    left.append(fn)
                    break
    if left:
        add("fail", "占位符替换", "还有 %d 个文件没替换" % len(left), "重跑一键配置")
    else:
        add("ok", "占位符替换", "全部完成", "")

    # 3) 数据目录
    dd = (cfg or {}).get("data_dir") or ""
    dd_ok = bool(dd and os.path.isdir(dd))
    add("ok" if dd_ok else "warn", "数据目录", dd or "未设置",
        "" if dd_ok else "目录不存在会自动建；或改 config.json 后重跑配置")

    # 4) Python 版本
    v = sys.version_info
    add("ok" if v[:2] == (3, 12) else "warn", "Python 版本", "%d.%d.%d" % v[:3],
        "" if v[:2] == (3, 12) else "建议 3.12（python.org，勾 Add to PATH）")

    # 5) Ollama 与模型
    models = []
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as r:
            models = [str(m.get("name") or "") for m in json.loads(r.read().decode("utf-8")).get("models") or []]
        missing = [m for m in ("qwen3-vl:4b", "bge-m3")
                   if not any(x == m or x.startswith(m + ":") for x in models)]
        if missing:
            add("warn", "Ollama 模型", "缺 %s" % "、".join(missing), "ollama pull " + "；ollama pull ".join(missing))
        else:
            add("ok", "Ollama 模型", "qwen3-vl:4b + bge-m3 都在", "")
    except Exception:
        add("warn", "Ollama 服务", "11434 连不上", "安装 Ollama 并启动 ollama serve")

    # 6) ffmpeg
    ff = shutil.which("ffmpeg")
    add("ok" if ff else "warn", "ffmpeg", ff or "不在 PATH",
        "" if ff else "装 essentials 构建并把 bin 加进 PATH")

    # 7) 端口（重复 / 被占用）
    ports = (cfg or {}).get("ports") or {}
    used = {}
    for k, pv in ports.items():
        try:
            pv = int(pv)
        except (TypeError, ValueError):
            add("fail", "端口·%s" % k, "不是数字", "改 config.json")
            continue
        if pv in used:
            add("fail", "端口·%s" % k, "和 %s 撞了（都用了 %d）" % (used[pv], pv), "改成不同的端口")
        elif _listening(pv):
            # 在跑 = 大概率是本项目自己的服务（有 HTTP 响应），不算问题
            if _http_ok(pv):
                add("ok", "端口·%s" % k, "%d（本项目的服务在跑）" % pv, "")
            else:
                add("warn", "端口·%s" % k, "%d 被其它软件占用" % pv, "换一个端口，或先停掉占用者")
        else:
            add("ok", "端口·%s" % k, str(pv), "")

    # 8) 关键服务文件
    for name, rel in (("Hub", "hub/server.py"), ("网页聊天", "webchat/server.py"),
                      ("生命面板", "lifeviz/server.py"), ("记忆星图", "brainviz/server.py"),
                      ("大平层", "houseviz/server.py")):
        p = os.path.join(CODE, rel)
        exists = os.path.exists(p)
        add("ok" if exists else "fail", name, rel, "" if exists else "文件缺失，检查包是否完整")

    # 9) 大平层户型
    plan = os.path.join(CODE, "houseviz", "plan.json")
    if os.path.exists(plan):
        add("ok", "大平层户型", "plan.json 在", "")
    else:
        add("warn", "大平层户型", "还没有 plan.json", "把 plan.json.example 复制成 plan.json 再改")

    # 10) 口令
    tok = (cfg or {}).get("gate_token") or ""
    tok_ok = bool(tok)
    add("ok" if tok_ok else "fail", "口令", "已设置" if tok_ok else "为空",
        "" if tok_ok else "重跑一键配置（留空会自动生成）")

    # 11) 大脑 API（本地 config.json 或 AstrBot 模型配置里任一有 key 即算过）
    key = ((cfg or {}).get("llm") or {}).get("api_key") or ""
    where = ""
    if not key and cfg:
        ap = astrbot_config_path(cfg)
        if os.path.exists(ap):
            try:
                data = json.load(open(ap, encoding="utf-8-sig"))
                for item in data.get("provider_sources") or []:
                    if isinstance(item, dict) and item.get("provider") == "deepseek" and item.get("key"):
                        where = "（在 AstrBot 模型配置里）"
                        break
            except Exception:  # noqa: BLE001
                pass
    if key or where:
        add("ok", "DeepSeek API Key", "已填写" + where, "")
    else:
        add("warn", "DeepSeek API Key", "还没有填", "向导「③ 大脑」里填；会同时写进本地 config.json 和 AstrBot 模型配置")

    # 12) AstrBot 实例（QQ 通道需要；只用网页可以跳过）
    det = autodetect((cfg or {}).get("user_dir") or "")
    if det["bot_instance"]:
        add("ok", "AstrBot 实例", det["bot_instance"], "")
    else:
        add("warn", "AstrBot 实例", "没自动找到（QQ 通道需要）",
            "已装的话：在 config.json 填 bot_instance，或设环境变量 ASTRBOT_LAUNCHER_DIR 指向启动器目录；"
            "只用网页聊天可以先跳过")
    return checks


def ask(label, default):
    if "--non-interactive" in sys.argv:
        return default
    ans = input("%s [默认 %s]：" % (label, default)).strip()
    return ans or default


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if "--check" in sys.argv:
        print("== 配置体检 ==")
        fails = warns = 0
        for c in check_setup():
            mark = {"ok": "[OK]  ", "warn": "[WARN]", "fail": "[FAIL]", "info": "[INFO]"}[c["level"]]
            print("%s %-12s %s" % (mark, c["name"], c["detail"]))
            if c["hint"]:
                print("      -> %s" % c["hint"])
            if c["level"] == "fail":
                fails += 1
            elif c["level"] == "warn":
                warns += 1
        print("结果：FAIL=%d WARN=%d" % (fails, warns))
        return 1 if fails else 0

    print("== 一键配置（命令行版） ==")
    print("提示：想要可视化界面，双击 一键配置.cmd 即可。")
    cfg = {
        "data_dir": ask("数据目录", DEFAULTS["data_dir"]),
        "user_dir": ask("用户目录", DEFAULTS["user_dir"]),
        "qq": ask("QQ 号（可留默认占位）", DEFAULTS["qq"]),
        "qq2": ask("第二个 QQ 号", DEFAULTS["qq2"]),
        "bot_instance": ask("机器人框架实例 UUID", DEFAULTS["bot_instance"]),
        "gate_token": ask("页面口令（留空自动生成）", ""),
        "llm": {
            "provider": "deepseek",
            "api_key": ask("DeepSeek API Key（sk-…，可先留空）", ""),
            "base_url": ask("API 地址", DEFAULTS["llm"]["base_url"]),
            "model": ask("模型", DEFAULTS["llm"]["model"]),
        },
        "bot_panel": int(ask("机器人框架面板端口", DEFAULTS["bot_panel"])),
        "ports": {},
    }
    if not cfg["gate_token"]:
        cfg["gate_token"] = secrets.token_urlsafe(18)
        print("  口令已自动生成。")
    print("-- 各服务端口（回车用默认）--")
    for num, key in PORT_KEY:
        cfg["ports"][key] = int(ask("  %s" % key, num))

    n_files, n_repl = apply_config(cfg)
    msg = patch_astrbot_llm(cfg)
    print("完成：重写 %d 个文件 / %d 处；config.json 与口令已生成。" % (n_files, n_repl))
    print("AstrBot：%s" % msg)
    print("下一步：docs/setup-checklist.md 第 4 步（启动）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

