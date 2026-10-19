"""Language capabilities of the installed adapters, shared with the QML UI.

Unknown compatible servers keep their saved settings; a protocol alone does not
prove which languages a remote model supports. No probing or config migration.
Sources and wire-field mappings are documented in docs/language-settings.md.
"""

import copy
import re

LABELS = dict(
    zh="中文",
    en="英文",
    ja="日语",
    ko="韩语",
    yue="粤语",
    vi="越南语",
    th="泰语",
    id="印尼语",
    ms="马来语",
    tl="菲律宾语",
    hi="印地语",
    ar="阿拉伯语",
    fr="法语",
    de="德语",
    es="西班牙语",
    pt="葡萄牙语",
    ru="俄语",
    it="意大利语",
    nl="荷兰语",
    sv="瑞典语",
    da="丹麦语",
    fi="芬兰语",
    no="挪威语",
    el="希腊语",
    pl="波兰语",
    cs="捷克语",
    hu="匈牙利语",
    ro="罗马尼亚语",
    bg="保加利亚语",
    hr="克罗地亚语",
    sk="斯洛伐克语",
)
MULTILINGUAL = [code for code in LABELS if code != "yue"]
RULES = [
    dict(
        provider="aliyun-asr",
        protocol="dashscope-native",
        models=["qwen-audio-3.0-asr-flash", "qwen-audio-3.1-asr-flash"],
        mode="hints",
        max_hints=4,
        codes=MULTILINGUAL,
        verified=True,
    ),
    dict(
        provider="aliyun-asr",
        protocol="dashscope-native",
        models=["fun-asr-flash-2026-06-15"],
        mode="single",
        max_hints=1,
        codes=MULTILINGUAL,
        verified=True,
    ),
    dict(
        provider="openai",
        protocol="openai-multipart",
        models=["whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"],
        endpoint_pattern=r"^https://api\.openai\.com(?::443)?/",
        mode="single",
        max_hints=1,
        codes=MULTILINGUAL,
        verified=True,
    ),
    dict(
        provider="sensevoice",
        protocol="sensevoice-multipart",
        mode="single",
        max_hints=1,
        codes=["zh", "en", "yue", "ja", "ko"],
        verified=True,
    ),
    dict(
        provider="doubao",
        protocol="doubao-native",
        mode="none",
        max_hints=0,
        codes=[],
        verified=True,
    ),
    dict(
        provider="qwen3-asr-vllm",
        protocol="chat-audio",
        mode="none",
        max_hints=0,
        codes=[],
        verified=True,
    ),
    # These adapters transmit a language field, but the remote model is unknown.
    dict(
        provider="aliyun-asr",
        protocol="dashscope-native",
        mode="single",
        max_hints=1,
        codes=[],
        verified=False,
    ),
    dict(
        provider="openai",
        protocol="openai-multipart",
        mode="single",
        max_hints=1,
        codes=[],
        verified=False,
    ),
]
UNKNOWN = dict(mode="none", max_hints=0, codes=[], verified=False)


def catalog():
    return copy.deepcopy(dict(labels=LABELS, rules=RULES, fallback=UNKNOWN))


def capabilities(profile):
    for rule in RULES:
        if (
            profile.get("provider") != rule["provider"]
            or profile.get("protocol") != rule["protocol"]
        ):
            continue
        if "models" in rule and profile.get("model") not in rule["models"]:
            continue
        if "endpoint_pattern" in rule and not re.search(
            rule["endpoint_pattern"], profile.get("endpoint", "")
        ):
            continue
        return copy.deepcopy(rule)
    return copy.deepcopy(UNKNOWN)


def validate(profile):
    language = profile.get("language", "").strip()
    if language in ("", "auto"):
        return
    cap = capabilities(profile)
    if cap["mode"] == "none":
        raise ValueError("当前适配器不接受独立的识别语言设置")
    codes = [code.strip() for code in language.split(",")]
    if len(codes) > cap["max_hints"]:
        raise ValueError("当前模型最多支持 %d 个语言提示" % cap["max_hints"])
    if any(not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", c) for c in codes):
        raise ValueError("语言代码格式错误，请选择识别语言或检查高级参数")
    if cap["verified"] and any(code not in cap["codes"] for code in codes):
        raise ValueError("当前模型不支持所选语言")
