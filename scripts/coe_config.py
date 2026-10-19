"""Transactional, comment-preserving Coe configuration. No network/audio code."""

from __future__ import annotations
import contextlib
import copy
import fcntl
import io
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
import uuid
from urllib.parse import urlsplit
from ruamel.yaml import YAML
import coe_languages as languages

HOME = Path.home()
ROOT = Path(os.environ.get("COE_ENHANCE_CONFIG", HOME / ".config/omarchy-coe-enhance"))
CONFIG = Path(os.environ.get("COE_CONFIG", HOME / ".config/coe/config.yaml"))
ENV = CONFIG.parent / "env"
STORE = ROOT / "profiles.json"
PRESETS = {
    "openai": dict(
        name="OpenAI",
        provider="openai",
        protocol="openai-multipart",
        endpoint="https://api.openai.com/v1/audio/transcriptions",
        model="gpt-4o-mini-transcribe",
        language="",
        prompt="",
    ),
    "compatible": dict(
        name="OpenAI-Compatible",
        provider="openai",
        protocol="openai-multipart",
        endpoint="https://api.openai.com/v1/audio/transcriptions",
        model="whisper-1",
        language="",
        prompt="",
    ),
    "doubao": dict(
        name="豆包 Flash",
        provider="doubao",
        protocol="doubao-native",
        endpoint="https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash",
        model="bigmodel",
        language="",
        prompt="",
    ),
    "sensevoice": dict(
        name="SenseVoice HTTP",
        provider="sensevoice",
        protocol="sensevoice-multipart",
        endpoint="http://127.0.0.1:50000/api/v1/asr",
        model="",
        language="auto",
        prompt="",
    ),
    "aliyun": dict(
        name="阿里云 Qwen Audio ASR",
        provider="aliyun-asr",
        protocol="dashscope-native",
        endpoint="https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        model="qwen-audio-3.0-asr-flash",
        language="",
        prompt="",
    ),
    "qwen": dict(
        name="Qwen3-ASR vLLM",
        provider="qwen3-asr-vllm",
        protocol="chat-audio",
        endpoint="http://127.0.0.1:8000/v1/chat/completions",
        model="Qwen/Qwen3-ASR-1.7B",
        language="",
        prompt="",
    ),
}
PROTOCOLS = {
    "openai": "openai-multipart",
    "doubao": "doubao-native",
    "sensevoice": "sensevoice-multipart",
    "qwen3-asr-vllm": "chat-audio",
    "aliyun-asr": "dashscope-native",
}
DEFAULT_PROMPT = "修正明显错别字，添加自然标点，去除不必要的语气词。保留专业术语、代码符号和原句含义。仅输出修正后的文字。\n{{.Dictionary}}"


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise ValueError("配置目录不安全")
    os.chmod(path, 0o700)


def atomic(path, data, mode=None):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    old = path.lstat() if path.exists() or path.is_symlink() else None
    if old and (not stat.S_ISREG(old.st_mode) or old.st_uid != os.getuid()):
        raise ValueError("拒绝写入非本用户普通文件")
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        os.fchmod(
            fd,
            mode if mode is not None else (stat.S_IMODE(old.st_mode) if old else 0o600),
        )
        if old:
            os.fchown(fd, old.st_uid, old.st_gid)
        with os.fdopen(fd, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode())
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        d = os.open(path.parent, os.O_DIRECTORY)
        os.fsync(d)
        os.close(d)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextlib.contextmanager
def locked():
    private_dir(ROOT)
    fd = os.open(ROOT / "config.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def yaml_load():
    y = YAML()
    y.preserve_quotes = True
    doc = y.load(CONFIG.read_text()) if CONFIG.exists() else {}
    if doc is None:
        doc = {}
    if not isinstance(doc, dict):
        raise ValueError("Coe YAML 顶层必须是映射")
    return y, doc


def env_values():
    out = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
            if m:
                val = m[2]
                try:
                    val = json.loads(val) if val.startswith('"') else val.strip("'")
                except ValueError:
                    continue
                out[m[1]] = val
    return out


def set_env(raw, name, key):
    if not re.fullmatch("[A-Z][A-Z0-9_]*", name):
        raise ValueError("无效密钥引用")
    if not isinstance(key, str) or any(c in key for c in "\r\n\x00") or len(key) > 8192:
        raise ValueError("API Key 格式错误")
    # Strict printable token: works identically in systemd EnvironmentFile and Coe env parser.
    if any(c.isspace() or c in "\\\"'" for c in key):
        raise ValueError("API Key 不可包含空白或引号")
    lines = [l for l in raw.splitlines() if not l.startswith(name + "=")]
    lines.append(name + "=" + key)
    return "\n".join(lines) + "\n"


def valid_endpoint(value, suffix=None):
    if (
        not isinstance(value, str)
        or len(value) > 4096
        or any(ord(c) < 33 for c in value)
    ):
        raise ValueError("Endpoint 格式错误")
    try:
        u = urlsplit(value)
        _ = u.port  # Access validates the port range.
    except ValueError:
        raise ValueError("Endpoint 格式错误") from None
    if (
        u.scheme not in ("http", "https")
        or not u.hostname
        or u.username
        or u.password
        or u.query
        or u.fragment
    ):
        raise ValueError("Endpoint 需为无凭据、查询参数的 HTTP(S) URL")
    # Remote HTTP is supported for self-hosted deployments; UI warns about transport privacy.
    if suffix and u.path.rstrip("/") in ("", "/v1", "/openai/v1"):
        return value.rstrip("/") + suffix
    return value.rstrip("/")


def text(value, label, limit=4096):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError(label + " 格式错误")
    return value


def timeout(value):
    if type(value) != int or not 1 <= value <= 600:
        raise ValueError("超时需为 1–600 秒整数")
    return value


def validate_profile(p, previous=None):
    p = copy.deepcopy(p)
    p["name"] = text(p.get("name"), "名称", 80).strip()
    if not p["name"]:
        raise ValueError("Profile 名称不能为空")
    provider = p.get("provider")
    protocol = p.get("protocol")
    if PROTOCOLS.get(provider) != protocol:
        raise ValueError("该协议需要独立 Adapter，当前不支持")
    p["endpoint"] = valid_endpoint(
        p.get("endpoint"),
        "/audio/transcriptions"
        if provider == "openai"
        else "/chat/completions"
        if provider == "qwen3-asr-vllm"
        else None,
    )
    p["model"] = text(p.get("model", ""), "模型", 256).strip()
    if provider in ("openai", "qwen3-asr-vllm", "aliyun-asr") and not p["model"]:
        raise ValueError("模型不能为空")
    p["language"] = text(p.get("language", ""), "语言", 32).strip()
    if provider != "sensevoice" and p["language"] == "auto":
        p["language"] = ""
    p["prompt"] = text(p.get("prompt", ""), "Prompt", 16000)
    p["timeout"] = timeout(p.get("timeout", 60))
    if provider == "doubao" and (
        p["model"] != "bigmodel" or p["language"] or p["prompt"]
    ):
        raise ValueError("豆包 Adapter 固定 bigmodel，不支持语言和 Prompt")
    if provider == "sensevoice" and (p["model"] or p["prompt"]):
        raise ValueError("SenseVoice Adapter 不支持模型和 Prompt")
    if provider == "qwen3-asr-vllm" and p["language"]:
        raise ValueError("Qwen Adapter 使用 Prompt 提示语言，无独立 Language 字段")
    if provider == "aliyun-asr" and len(p["prompt"]) > 400:
        raise ValueError("阿里云 ASR 上下文最多 400 字符")
    # Preserve imported language values during unrelated edits. Apply capability
    # validation when a language/model/protocol/endpoint actually changes.
    language_unchanged = previous is not None and all(
        p.get(k) == previous.get(k)
        for k in ("provider", "protocol", "endpoint", "model", "language")
    )
    if not language_unchanged:
        languages.validate(p)
    allowed = (
        "id",
        "name",
        "provider",
        "protocol",
        "endpoint",
        "model",
        "language",
        "prompt",
        "timeout",
        "key_ref",
        "prompt_file",
    )
    return {k: p[k] for k in allowed if k in p}


def read_store():
    if STORE.exists():
        return json.loads(STORE.read_text())
    return {
        "version": 1,
        "profiles": [],
        "active": "",
        "default": "",
        "output": "smart",
        "hotkey": "Alt_R",
        "hotkey_mode": "hold",
        "llm": dict(
            enabled=False,
            endpoint="https://api.openai.com/v1",
            model="gpt-4o-mini",
            endpoint_type="chat",
            prompt=DEFAULT_PROMPT,
            timeout=45,
            key_ref="COE_ENHANCE_LLM_KEY",
        ),
    }


def write_store(s):
    atomic(STORE, json.dumps(s, ensure_ascii=False, indent=2) + "\n")


def initialize():
    with locked():
        if STORE.exists():
            return
        s = read_store()
        _, c = yaml_load()
        a = c.get("asr", {})
        p = dict(PRESETS["openai"])
        p.update(id=uuid.uuid4().hex, timeout=60)
        if c:
            if a.get("provider") not in PROTOCOLS:
                raise ValueError("原 Coe 使用未管理的 Provider，请先备份并手动导入")
            for k in (
                "provider",
                "endpoint",
                "model",
                "language",
                "prompt",
                "prompt_file",
            ):
                p[k] = a.get(k, p.get(k, ""))
            p["name"] = "导入的 Coe"
            p["protocol"] = PROTOCOLS[p["provider"]]
            p["timeout"] = a.get("timeout_seconds", 60)
            p["key_ref"] = a.get("api_key_env") or "COE_ENHANCE_ASR_" + p["id"].upper()
            l = c.get("llm", {})
            s["llm"].update(
                enabled=l.get("provider", "stub") != "stub",
                **{
                    k: l[k]
                    for k in (
                        "endpoint",
                        "model",
                        "endpoint_type",
                        "prompt",
                        "prompt_file",
                    )
                    if k in l
                },
            )
            s["llm"]["timeout"] = l.get("timeout_seconds", 45)
            s["llm"]["key_ref"] = l.get("api_key_env", "")
        # Import metadata only; never rewrite an existing Coe config or plaintext key here.
        p.setdefault("key_ref", "COE_ENHANCE_ASR_" + p["id"].upper())
        s.update(profiles=[p], active=p["id"] if c else "", default=p["id"])
        write_store(s)


def public_store():
    s = read_store()
    keys = env_values()
    _, c = yaml_load()
    for p in s["profiles"]:
        p["key_present"] = bool(
            keys.get(p.get("key_ref"), os.getenv(p.get("key_ref", "")))
            or (p["id"] == s["active"] and c.get("asr", {}).get("api_key"))
        )
    s["llm"]["key_present"] = bool(
        keys.get(s["llm"].get("key_ref"), os.getenv(s["llm"].get("key_ref", "")))
        or c.get("llm", {}).get("api_key")
    )
    s["presets"] = PRESETS
    s["language_catalog"] = languages.catalog()
    return s


# Snapshot events cannot change configuration. Invalidate on atomic replacement,
# edit, permissions/owner change or path change; return a fresh public copy.
def cached_public_store():
    fingerprint = tuple(
        (
            str(p),
            p.stat().st_ino,
            p.stat().st_mtime_ns,
            p.stat().st_size,
            p.stat().st_ctime_ns,
        )
        if p.exists()
        else (str(p), None)
        for p in (CONFIG, ENV, STORE)
    )
    return copy.deepcopy(_cached_public_store(fingerprint))


from functools import lru_cache


@lru_cache(maxsize=1)
def _cached_public_store(fingerprint):
    return public_store()


class Transaction:
    def __init__(self, paths):
        self.paths = paths
        self.before = {
            p: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) if p.exists() else None
            for p in paths
        }
        self.backup = None

    def backup_files(self):
        self.backup = (
            ROOT
            / "backups"
            / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        )
        private_dir(self.backup)
        for i, p in enumerate(self.paths):
            if self.before[p]:
                atomic(self.backup / str(i), self.before[p][0], 0o600)
        atomic(
            self.backup / "manifest.json",
            json.dumps({str(i): str(p) for i, p in enumerate(self.paths)}),
        )

    def rollback(self):
        for p, b in self.before.items():
            if b:
                atomic(p, b[0], b[1])
            elif p.exists():
                p.unlink()


# Caller holds config lock and has checked D-Bus idle. Recheck in restart callback.
def save_profile(req, restart):
    with locked():
        s = read_store()
        ident = req.get("id", "")
        original = next((p for p in s["profiles"] if p["id"] == ident), None)
        p = validate_profile(req["profile"], original)
        p["id"] = ident if original else uuid.uuid4().hex
        p["key_ref"] = (
            original.get("key_ref")
            if original
            else "COE_ENHANCE_ASR_" + p["id"].upper()
        )
        # Existing credential references stay untouched; new keys get profile-specific refs.
        if req.get("api_key") is not None and req["api_key"] != "":
            p["key_ref"] = "COE_ENHANCE_ASR_" + p["id"].upper()
        env = ENV.read_text() if ENV.exists() else ""
        if req.get("api_key"):
            env = set_env(env, p["key_ref"], req["api_key"])
        llm = copy.deepcopy(req.get("llm", s["llm"]))
        if type(llm.get("enabled")) != bool:
            raise ValueError("LLM 开关格式错误")
        llm["endpoint"] = valid_endpoint(
            llm.get("endpoint", "https://api.openai.com/v1")
        )
        llm["model"] = text(llm.get("model", ""), "LLM 模型", 256)
        llm["prompt"] = text(llm.get("prompt", ""), "LLM Prompt", 16000)
        llm["timeout"] = timeout(llm.get("timeout", 45))
        if llm.get("endpoint_type", "chat") not in ("chat", "responses"):
            raise ValueError("LLM 协议不支持")
        llm["key_ref"] = s["llm"].get("key_ref") or "COE_ENHANCE_LLM_KEY"
        if req.get("llm_key"):
            llm["key_ref"] = "COE_ENHANCE_LLM_KEY"
            env = set_env(env, llm["key_ref"], req["llm_key"])
        llm = {
            k: v
            for k, v in llm.items()
            if k
            in (
                "enabled",
                "endpoint",
                "model",
                "prompt",
                "prompt_file",
                "timeout",
                "key_ref",
                "endpoint_type",
            )
        }
        output = req.get("output", s["output"])
        if output not in ("smart", "clipboard"):
            raise ValueError("输出方式不支持")
        y, c = yaml_load()
        # Migrate pre-existing direct keys before switching, without exposing them in Profiles.
        for section, entry in [
            ("asr", next((x for x in s["profiles"] if x["id"] == s["active"]), None)),
            ("llm", s["llm"]),
        ]:
            direct = c.get(section, {}).get("api_key")
            if direct and entry:
                ref = (
                    ("COE_ENHANCE_ASR_" + entry["id"].upper())
                    if section == "asr"
                    else "COE_ENHANCE_LLM_KEY"
                )
                env = set_env(env, ref, direct)
                entry["key_ref"] = ref
                if (
                    section == "asr"
                    and p["id"] == entry["id"]
                    and not req.get("api_key")
                ):
                    p["key_ref"] = ref
                if section == "llm" and not req.get("llm_key"):
                    llm["key_ref"] = ref
        # Deletion is explicit and scoped to this entry. Shared/imported env
        # references remain available to other Profiles and applications.
        for flag, entry, prefix in [
            ("delete_api_key", p, "COE_ENHANCE_ASR_" + p["id"].upper()),
            ("delete_llm_key", llm, "COE_ENHANCE_LLM_KEY"),
        ]:
            if req.get(flag) is True:
                ref = prefix
                if any(
                    x["id"] != p["id"] and x.get("key_ref") == ref
                    for x in s["profiles"]
                ):
                    ref += "_" + uuid.uuid4().hex[:8].upper()
                entry["key_ref"] = ref
                env = set_env(env, ref, "")
                if flag == "delete_llm_key":
                    llm["enabled"] = False
        for section in ("runtime", "hotkey", "asr", "llm", "output", "notifications"):
            if section not in c:
                c[section] = {}
            if not isinstance(c[section], dict):
                raise ValueError(section + " 必须是映射")
        # No changes to audio, dictionary, scene data or unknown keys.
        c["runtime"].update(mode="desktop", target_desktop="hyprland", log_level="warn")
        c["hotkey"]["trigger_mode"] = "toggle"
        for k in ("provider", "endpoint", "model", "language", "prompt"):
            c["asr"][k] = p[k]
        # Preserve file prompts unless the user explicitly edits inline prompt.
        c["asr"]["prompt_file"] = (
            p.get("prompt_file", "")
            if original and p["prompt"] == original.get("prompt", "")
            else ""
        )
        c["asr"].update(api_key_env=p["key_ref"], timeout_seconds=p["timeout"])
        c["asr"]["api_key"] = ""
        c["llm"].update(
            provider="openai" if llm["enabled"] else "stub",
            endpoint=llm["endpoint"],
            model=llm["model"],
            endpoint_type=llm.get("endpoint_type", "chat"),
            prompt=llm["prompt"],
            api_key_env=llm["key_ref"],
            timeout_seconds=llm["timeout"],
        )
        if llm["prompt"] != s["llm"].get("prompt"):
            c["llm"]["prompt_file"] = ""
        c["llm"]["api_key"] = ""
        c["output"].update(enable_auto_paste=False, use_gnome_focus_helper=False)
        c["notifications"].update(enable_system=False, notify_on_complete=False)
        if original:
            # Keep existing metadata and JSON field order on a no-op edit.
            p = {**original, **p}
        s["profiles"] = [p if old["id"] == p["id"] else old for old in s["profiles"]]
        if not original:
            s["profiles"].append(p)
        s.update(active=p["id"], llm=llm, output=output)
        if req.get("make_default") or not s["default"]:
            s["default"] = p["id"]
        buffer = io.StringIO()
        y.dump(c, buffer)
        runtime_changed = (
            not CONFIG.exists()
            or CONFIG.read_bytes() != buffer.getvalue().encode()
            or not ENV.exists()
            or ENV.read_bytes() != env.encode()
        )
        tx = Transaction([CONFIG, ENV, STORE])
        tx.backup_files()
        try:
            atomic(ENV, env, 0o600)
            atomic(CONFIG, buffer.getvalue())
            if runtime_changed:
                restart()
            write_store(s)
            atomic(ROOT / "last-good.yaml", CONFIG.read_bytes(), 0o600)
        except Exception:
            tx.rollback()
            try:
                if runtime_changed:
                    restart()
            except Exception:
                pass
            raise RuntimeError(
                "应用失败，已恢复原配置。请检查服务状态或模板语法。"
            ) from None
        return str(tx.backup)


def active_profile(s=None):
    s = s or read_store()
    p = next((x for x in s["profiles"] if x["id"] == s["active"]), None)
    if not p:
        raise ValueError("请先保存并应用一个语音识别服务")
    return copy.deepcopy(p)


def update_preferences(req, restart):
    s = read_store()
    p = active_profile(s)
    llm = copy.deepcopy(s["llm"])
    if "language" in req:
        if req.get("language_profile_id", p["id"]) != p["id"]:
            raise ValueError("当前模型已切换，请重新选择识别语言")
        cap = languages.capabilities(p)
        if cap["mode"] == "none":
            raise ValueError("当前服务不支持独立的识别语言参数")
        p["language"] = text(req["language"], "语言", 32)
        # The common language page accepts only advertised single selections;
        # multi-language hints belong to the Profile's advanced editor.
        if p["language"] not in ("", "auto", *cap["codes"]):
            raise ValueError("请选择当前模型支持的语言；高级语言提示请在模型设置中修改")
    if "llm_enabled" in req:
        if type(req["llm_enabled"]) is not bool:
            raise ValueError("纠错开关格式错误")
        if req["llm_enabled"] and not public_store()["llm"]["key_present"]:
            raise ValueError("请先在 AI 文本纠错设置中配置密钥")
        llm["enabled"] = req["llm_enabled"]
    if set(req).issubset({"action", "request_id", "output"}) and "output" in req:
        if req["output"] not in ("smart", "clipboard"):
            raise ValueError("输出方式不支持")
        with locked():
            s = read_store()
            tx = Transaction([STORE])
            tx.backup_files()
            s["output"] = req["output"]
            write_store(s)
            return str(tx.backup)
    return save_profile(
        {
            "id": p["id"],
            "profile": p,
            "llm": llm,
            "output": req.get("output", s["output"]),
        },
        restart,
    )


def profile_action(action, ident):
    with locked():
        s = read_store()
        p = next((x for x in s["profiles"] if x["id"] == ident), None)
        if not p:
            raise ValueError("Profile 不存在")
        if action == "duplicate":
            p = copy.deepcopy(p)
            p["id"] = uuid.uuid4().hex
            p["name"] += " 副本"
            old_ref = p.get("key_ref")
            p["key_ref"] = "COE_ENHANCE_ASR_" + p["id"].upper()
            keys = env_values()
            if keys.get(old_ref):
                atomic(
                    ENV, set_env(ENV.read_text(), p["key_ref"], keys[old_ref]), 0o600
                )
            s["profiles"].append(p)
        elif action == "delete":
            if ident == s["active"]:
                raise ValueError("请先切换到其他 Profile 再删除当前项")
            s["profiles"] = [x for x in s["profiles"] if x["id"] != ident]
            if s["default"] == ident:
                s["default"] = s["active"]
        elif action == "default":
            s["default"] = ident
        else:
            raise ValueError("未知 Profile 操作")
        write_store(s)


def restore_good():
    with locked():
        path = ROOT / "last-good.yaml"
        if not path.exists():
            raise RuntimeError("没有可恢复的配置")
        tx = Transaction([CONFIG])
        tx.backup_files()
        atomic(CONFIG, path.read_bytes())
        return str(tx.backup)
