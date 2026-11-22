# -*- coding: utf-8 -*-
"""一键配置

两条路，效果一样：
  · 可视化向导（推荐）：双击 一键配置.cmd，浏览器里填表点按钮
  · 命令行：python configure.py            # 交互式
            python configure.py --non-interactive

apply_config() 是公共入口：向导服务器和命令行都调它。
"""

import json
import ntpath
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
from i18n import t

ROOT = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.join(ROOT, "code")
CFG_PATH = os.path.join(ROOT, "config.json")

DEFAULTS = {
    "language": "zh-CN",
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


def autodetect():
    """自动探测这台机器上的 AstrBot 实例与面板端口。"""
    out = {"bot_instance": "", "bot_panel": 8012, "cmd_config": ""}
    base = os.path.join(os.path.expanduser("~"), ".astrbot_launcher", "instances")
    candidates = []
    if os.path.isdir(base):
        for name in os.listdir(base):
            p = os.path.join(base, name)
            cfgp = os.path.join(p, "core", "data", "cmd_config.json")
            if os.path.isdir(p) and os.path.exists(cfgp):
                try:
                    candidates.append((os.path.getmtime(p), name, cfgp))
                except OSError:
                    candidates.append((0, name, cfgp))
    if candidates:
        candidates.sort(reverse=True)
        _, inst, cfgp = candidates[0]
        out["bot_instance"] = inst
        out["cmd_config"] = cfgp
        try:
            dash = json.load(open(cfgp, encoding="utf-8")).get("dashboard") or {}
            if isinstance(dash.get("port"), int):
                out["bot_panel"] = dash["port"]
        except Exception:  # noqa: BLE001
            pass
    return out


def env_install_missing():
    """尽力自动安装缺失的环境（除账号外的软件），返回 [{name, ok, detail}]。
    winget 有的就 winget 静默装；装完 Ollama 后在后台拉两个模型。"""
    results = []

    def winget(pkg, name):
        if not shutil.which("winget"):
            results.append({"name": name, "ok": False,
                            "detail": t('setup.winget_missing')})
            return
        try:
            r = subprocess.run(["winget", "install", "-e", "--id", pkg,
                                "--accept-source-agreements", "--accept-package-agreements",
                                "--silent"], capture_output=True, text=True, timeout=900)
            results.append({"name": name, "ok": r.returncode == 0,
                            "detail": ((r.stdout or "") + (r.stderr or ""))[-160:]})
        except Exception as exc:  # noqa: BLE001
            results.append({"name": name, "ok": False, "detail": str(exc)[:120]})

    # Python 3.12
    if sys.version_info[:2] == (3, 12):
        results.append({"name": "Python 3.12", "ok": True, "detail": t('setup.version_installed') % sys.version_info[:3]})
    else:
        winget("Python.Python.3.12", "Python 3.12")

    # Ollama
    ollama_ok = bool(shutil.which("ollama"))
    if ollama_ok:
        results.append({"name": "Ollama", "ok": True, "detail": shutil.which("ollama")})
    else:
        winget("Ollama.Ollama", "Ollama")

    # ffmpeg
    ff = shutil.which("ffmpeg")
    if ff:
        results.append({"name": "ffmpeg", "ok": True, "detail": ff})
    else:
        winget("Gyan.FFmpeg", "ffmpeg")

    # AstrBot（没有 winget 包，给指引）
    det = autodetect()
    if det["bot_instance"]:
        results.append({"name": "AstrBot", "ok": True, "detail": t('setup.instance_detected') + det["bot_instance"]})
    else:
        results.append({"name": "AstrBot", "ok": False,
                        "detail": t('setup.astrbot.install_hint')})

    # 模型：Ollama 可用就后台拉
    started = _pull_models_background()
    results.append({"name": t('setup.label.model_downloads'), "ok": len(started) == 2,
                    "detail": t('setup.downloads_started') + "、".join(started) if started else
                    t('setup.models.start_failed')})
    return results


def _pull_models_background():
    started = []
    for m in ("qwen3-vl:4b", "bge-m3"):
        try:
            subprocess.Popen(["ollama", "pull", m],
                             creationflags=(0x00000008 | 0x08000000) if os.name == "nt" else 0,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            started.append(m)
        except Exception:  # noqa: BLE001
            pass
    return started


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
        return {"ok": False, "error": t('setup.assets.unknown_kind') % kind}
    base = os.path.realpath(os.path.join(cfg.get("data_dir") or "", *parts))
    saved = []
    for f in files or []:
        name = str(f.get("name") or "").replace("\\", "/")
        segments = name.split("/")
        if not name or ntpath.splitdrive(name)[0] or any(s in ("", ".", "..") or ":" in s for s in segments):
            continue
        dst = os.path.realpath(os.path.join(base, *segments))
        try:
            if os.path.commonpath((base, dst)) != base:
                continue
            data = _b64.b64decode(str(f.get("data") or "").split(",", 1)[-1], validate=True)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(data)
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
        if slot not in {"v1", "v2", "v3", "v4", "v5"}:
            continue
        try:
            sample = _b64.b64decode(data.split(",", 1)[-1], validate=True)
            d = os.path.join(base, "voice")
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "voice_%s.wav" % slot)
            with open(p, "wb") as f:
                f.write(sample)
            saved.append(os.path.relpath(p, cfg.get("data_dir") or ""))
        except Exception:  # noqa: BLE001
            pass
    for slot, data in (faces or {}).items():
        if slot not in {"up", "down", "left", "right", "front"}:
            continue
        try:
            sample = _b64.b64decode(data.split(",", 1)[-1], validate=True)
            d = os.path.join(base, "faces")
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "face_%s.jpg" % slot)
            with open(p, "wb") as f:
                f.write(sample)
            saved.append(os.path.relpath(p, cfg.get("data_dir") or ""))
        except Exception:  # noqa: BLE001
            pass
    note = (t('setup.enrollment_saved') % len(saved))
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
        return t('setup.astrbot.no_key')
    path = astrbot_config_path(cfg)
    if not os.path.exists(path):
        return t('setup.astrbot.config_missing') % path
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        sources = data.get("provider_sources")
        if not isinstance(sources, list):
            return t('setup.astrbot.sources_missing')
        target = None
        for item in sources:
            if isinstance(item, dict) and item.get("provider") == "deepseek":
                target = item
                break
        if target is None:
            return t('setup.astrbot.provider_missing')
        bak = path + ".bak-before-llm-" + time.strftime("%Y%m%d_%H%M%S")
        with open(bak, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        target["key"] = key
        base = ((cfg.get("llm") or {}).get("base_url") or "").strip()
        if base and not target.get("api_base"):
            target["api_base"] = base
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return t('setup.astrbot.updated') % os.path.basename(bak)
    except Exception as exc:  # noqa: BLE001
        return t('setup.astrbot.write_failed') % str(exc)[:80]


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
        raise ValueError(t('setup.identity.required'))
    api_key = str((llm or {}).get("api_key") or "").strip()
    if not api_key:
        raise ValueError(t('setup.identity.key_required'))
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
        raise RuntimeError(t('setup.identity.empty_response'))
    return text


def apply_config(cfg):
    """重写 code/ 占位符，写 config.json 与口令文件。返回 (文件数, 替换处数)。"""
    if not os.path.isdir(CODE):
        raise RuntimeError(t('setup.code_missing'))
    ports = [int(cfg["ports"][key]) for _, key in PORT_KEY]
    if any(port < 1 or port > 65535 for port in ports) or len(set(ports)) != len(ports):
        raise ValueError(t("setup.error.ports"))
    previous = {}
    if os.path.exists(CFG_PATH):
        with open(CFG_PATH, encoding="utf-8-sig") as f:
            previous = json.load(f)
        if not isinstance(previous, dict):
            raise ValueError(t("setup.error.config_object"))

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
    for key in ("data_dir", "user_dir", "qq2", "qq", "bot_instance", "gate_token"):
        old = previous.get(key)
        if not isinstance(old, str) or not old:
            continue
        new = str(cfg[key])
        repl.append((old, new))
        if key in ("data_dir", "user_dir"):
            repl.extend(((old.replace("\\", "\\\\"), new.replace("\\", "\\\\")),
                         (old.replace("\\", "/"), new.replace("\\", "/"))))
    replacements = {}
    for old, new in repl:
        if replacements.setdefault(old, new) != new:
            raise ValueError(t('setup.error.ambiguous_reconfiguration'))
    previous_ports = previous.get("ports") or {}
    port_replacements = {}
    for num, key in PORT_KEY:
        old, new = str(previous_ports.get(key, num)), str(cfg['ports'][key])
        if old in replacements and replacements[old] != new:
            raise ValueError(t('setup.error.ambiguous_reconfiguration'))
        if old != new:
            port_replacements[old] = new
    alternatives = [re.escape(old) for old in sorted(replacements, key=len, reverse=True)]
    if port_replacements:
        alternatives.append(r"(?<!\d)(?:" + "|".join(port_replacements) + r")(?!\d)")
    replacement_pattern = re.compile("|".join(alternatives))
    replacements.update(port_replacements)
    n_files = n_repl = 0
    for dp, dn, fns in os.walk(CODE):
        if "__pycache__" in dp:
            continue
        for fn in fns:
            if not fn.lower().endswith(TEXT_EXT):
                continue
            p = os.path.join(dp, fn)
            try:
                with open(p, encoding="utf-8") as source:
                    raw = source.read()
            except Exception:
                continue
            text = raw
            text, replacements_count = replacement_pattern.subn(lambda match: replacements[match.group()], text)
            if text != raw:
                with open(p, "w", encoding="utf-8", newline="") as target:
                    target.write(text)
                n_files += 1
                n_repl += replacements_count

    os.makedirs(cfg["data_dir"], exist_ok=True)
    for name in ("i18n.py", "i18n.js", "locales"):
        source = os.path.join(ROOT, name)
        target = os.path.join(cfg["data_dir"], name)
        if os.path.realpath(source) == os.path.realpath(target):
            continue
        if os.path.isdir(source):
            shutil.copytree(source, target, dirs_exist_ok=True)
        elif os.path.isfile(source):
            shutil.copy2(source, target)
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    gp = os.path.join(cfg["data_dir"], "gate_token.txt")
    try:
        with open(gp, "w", encoding="utf-8") as f:
            f.write(cfg["gate_token"])
    except OSError as exc:
        print(t('setup.token_write_failed') % exc)

    # 大平层户型：没有 plan.json 就从示例复制一份，用户再按自己家改
    plan = os.path.join(cfg["data_dir"], "houseviz", "plan.json")
    plan_example = os.path.join(CODE, "houseviz", "plan.json.example")
    if os.path.exists(plan_example) and not os.path.exists(plan):
        try:
            import shutil as _sh
            os.makedirs(os.path.dirname(plan), exist_ok=True)
            _sh.copy2(plan_example, plan)
            print(t('setup.plan_copied'))
        except Exception as exc:  # noqa: BLE001
            print(t('setup.plan_copy_failed') % exc)

    # 视频服务配置：没有 config.json 就从示例复制一份（人设/模型由使用者自己填）
    vcfg = os.path.join(cfg["data_dir"], "video", "config.json")
    vcfg_example = os.path.join(CODE, "video", "config.example.json")
    if os.path.exists(vcfg_example) and not os.path.exists(vcfg):
        try:
            import shutil as _sh
            os.makedirs(os.path.dirname(vcfg), exist_ok=True)
            _sh.copy2(vcfg_example, vcfg)
            print(t('setup.video_config_copied'))
        except Exception as exc:  # noqa: BLE001
            print(t('setup.video_copy_failed') % exc)
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
        with open(CFG_PATH, encoding="utf-8") as source:
            cfg = json.load(source)
        add("ok", "config.json", t('setup.generated'), "")
    except Exception:
        cfg = None
        add("fail", "config.json", t('setup.missing'), t('setup.run_setup_first'))

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
        add("fail", t('setup.label.placeholders'), t('setup.placeholders_remaining') % len(left), t('setup.rerun_setup'))
    else:
        add("ok", t('setup.label.placeholders'), t('setup.complete'), "")

    # 3) 数据目录
    dd = (cfg or {}).get("data_dir") or ""
    dd_ok = bool(dd and os.path.isdir(dd))
    add("ok" if dd_ok else "warn", t('setup.label.data_dir'), dd or t('setup.not_configured'),
        "" if dd_ok else t('setup.data_dir_hint'))

    # 4) Python 版本
    v = sys.version_info
    add("ok" if v[:2] == (3, 12) else "warn", t('setup.label.python_version'), "%d.%d.%d" % v[:3],
        "" if v[:2] == (3, 12) else t('setup.python_hint'))

    # 5) Ollama 与模型
    models = []
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as r:
            models = [str(m.get("name") or "") for m in json.loads(r.read().decode("utf-8")).get("models") or []]
        missing = [m for m in ("qwen3-vl:4b", "bge-m3")
                   if not any(x == m or x.startswith(m + ":") for x in models)]
        if missing:
            add("warn", t('setup.label.ollama_models'), t('setup.models_missing') % "、".join(missing), "ollama pull " + "；ollama pull ".join(missing))
        else:
            add("ok", t('setup.label.ollama_models'), t('setup.models.available'), "")
    except Exception:
        add("warn", t('setup.label.ollama_service'), t('setup.ollama_unreachable'), t('setup.ollama_hint'))

    # 6) ffmpeg
    ff = shutil.which("ffmpeg")
    add("ok" if ff else "warn", "ffmpeg", ff or t('setup.not_in_path'),
        "" if ff else t('setup.ffmpeg_hint'))

    # 7) 端口（重复 / 被占用）
    ports = (cfg or {}).get("ports") or {}
    used = {}
    for k, pv in ports.items():
        try:
            pv = int(pv)
        except (TypeError, ValueError):
            add("fail", t('setup.label.port') % k, t('setup.not_numeric'), t('setup.edit_config'))
            continue
        if pv in used:
            add("fail", t('setup.label.port') % k, t('setup.port_conflict') % (used[pv], pv), t('setup.different_ports_hint'))
        elif _listening(pv):
            # 在跑 = 大概率是本项目自己的服务（有 HTTP 响应），不算问题
            if _http_ok(pv):
                add("ok", t('setup.label.port') % k, t('setup.http_running') % pv, "")
            else:
                add("warn", t('setup.label.port') % k, t('setup.port_busy') % pv, t('setup.port_busy_hint'))
        else:
            add("ok", t('setup.label.port') % k, str(pv), "")
        used[pv] = k

    # 8) 关键服务文件
    for name, rel in (("Hub", "hub/server.py"), (t('setup.label.webchat'), "webchat/server.py"),
                      (t('setup.label.life'), "lifeviz/server.py"), (t('setup.label.brain'), "brainviz/server.py"),
                      (t('setup.label.house'), "houseviz/server.py")):
        p = os.path.join(CODE, rel)
        exists = os.path.exists(p)
        add("ok" if exists else "fail", name, rel, "" if exists else t('setup.file_missing'))

    # 9) 大平层户型
    plan = os.path.join(CODE, "houseviz", "plan.json")
    if os.path.exists(plan):
        add("ok", t('setup.label.house_layout'), t('setup.plan_exists'), "")
    else:
        add("warn", t('setup.label.house_layout'), t('setup.plan_missing'), t('setup.plan_hint'))

    # 10) 口令
    tok = (cfg or {}).get("gate_token") or ""
    tok_ok = bool(tok)
    add("ok" if tok_ok else "fail", t('setup.label.gate_token'), t('setup.configured') if tok_ok else t('setup.empty'),
        "" if tok_ok else t('setup.token_hint'))

    # 11) 大脑 API（本地 config.json 或 AstrBot 模型配置里任一有 key 即算过）
    key = ((cfg or {}).get("llm") or {}).get("api_key") or ""
    where = ""
    if not key and cfg:
        ap = astrbot_config_path(cfg)
        if os.path.exists(ap):
            try:
                data = json.load(open(ap, encoding="utf-8"))
                for item in data.get("provider_sources") or []:
                    if isinstance(item, dict) and item.get("provider") == "deepseek" and item.get("key"):
                        where = t('setup.astrbot_key_location')
                        break
            except Exception:  # noqa: BLE001
                pass
    if key or where:
        add("ok", "DeepSeek API Key", t('setup.entered') + where, "")
    else:
        add("warn", "DeepSeek API Key", t('setup.not_entered'), t('setup.llm_hint'))
    return checks


def ask(label, default):
    if "--non-interactive" in sys.argv:
        return default
    ans = input(t('setup.cli.prompt') % (label, default)).strip()
    return ans or default


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if "--check" in sys.argv:
        print(t('setup.cli.check_title'))
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
        print(t('setup.cli.result') % (fails, warns))
        return 1 if fails else 0

    print(t('setup.cli.title'))
    print(t('setup.cli.hint'))
    cfg = {
        "language": DEFAULTS["language"],
        "data_dir": ask(t('setup.label.data_dir'), DEFAULTS["data_dir"]),
        "user_dir": ask(t('setup.label.user_dir'), DEFAULTS["user_dir"]),
        "qq": ask(t('setup.cli.qq'), DEFAULTS["qq"]),
        "qq2": ask(t('setup.cli.qq2'), DEFAULTS["qq2"]),
        "bot_instance": ask(t('setup.cli.instance'), DEFAULTS["bot_instance"]),
        "gate_token": ask(t('setup.cli.gate_token'), ""),
        "llm": {
            "provider": "deepseek",
            "api_key": ask(t('setup.cli.api_key'), ""),
            "base_url": ask(t('setup.label.api_url'), DEFAULTS["llm"]["base_url"]),
            "model": ask(t('setup.label.model'), DEFAULTS["llm"]["model"]),
        },
        "bot_panel": int(ask(t('setup.label.bot_panel'), DEFAULTS["bot_panel"])),
        "ports": {},
    }
    if not cfg["gate_token"]:
        cfg["gate_token"] = secrets.token_urlsafe(18)
        print(t('setup.token_generated'))
    print(t('setup.cli.ports'))
    for num, key in PORT_KEY:
        cfg["ports"][key] = int(ask("  %s" % key, num))

    n_files, n_repl = apply_config(cfg)
    msg = patch_astrbot_llm(cfg)
    print(t('setup.cli.completed') % (n_files, n_repl))
    print("AstrBot：%s" % msg)
    print(t('setup.cli.next'))
    return 0


if __name__ == "__main__":
    sys.exit(main())
