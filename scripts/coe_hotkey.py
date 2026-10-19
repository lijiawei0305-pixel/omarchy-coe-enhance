"""Hyprland Lua binding handles: never unbind a key owned by another plugin."""

import json
import re
import subprocess
import shlex
import uuid
from coe_compat import HOTKEY_CONFLICT, native_hotkey_conflict

DESCRIPTIONS = ("Coe Enhance 语音输入", "Coe Enhance 松开识别")


def validate_mode(key, mode):
    if mode not in ("toggle", "hold"):
        raise ValueError("无效录音快捷键模式")
    if mode == "hold" and normalize(key) != "Alt_R":
        raise ValueError("按住说话目前支持 Alt_R（右 Alt）")
    return mode


def run(args):
    return subprocess.run(
        args, capture_output=True, text=True, timeout=5, check=True
    ).stdout


def normalize(key):
    if not isinstance(key, str):
        raise ValueError("快捷键格式错误")
    if key.strip().upper() == "ALT_R":
        return "Alt_R"
    parts = [x.strip().upper() for x in key.split("+")]
    if not parts or len(set(parts)) != len(parts):
        raise ValueError("快捷键格式错误")
    if any(
        x not in ("SUPER", "CTRL", "ALT", "SHIFT") for x in parts[:-1]
    ) or not re.fullmatch(r"(F(?:[1-9]|[12][0-9]|3[0-5])|[A-Z0-9])", parts[-1]):
        raise ValueError(
            "使用 Alt_R、F1–F35 或修饰键 + 字母/数字，例如 SUPER + CTRL + D"
        )
    if len(parts) == 1 and not parts[0].startswith("F"):
        raise ValueError("字母快捷键必须包含修饰键")
    return " + ".join(parts)


def conflict(key):
    key = normalize(key)
    if key == "Alt_R" and native_hotkey_conflict():
        return True
    parts = key.split(" + ")
    mask = sum({"SHIFT": 1, "CTRL": 4, "ALT": 8, "SUPER": 64}[x] for x in parts[:-1])
    for b in json.loads(run(["hyprctl", "-j", "binds"])):
        if (
            (
                b["modmask"] == mask
                or (key == "Alt_R" and (b["modmask"] == 8 or b.get("ignore_mods")))
            )
            and b["key"].upper() == parts[-1].upper()
            and b.get("description") not in DESCRIPTIONS
        ):
            return True
    return False


def remove(owner=None):
    condition = (
        "" if owner is None else "if _G.cc_coe_owner == " + json.dumps(owner) + " then "
    )
    run(
        [
            "hyprctl",
            "eval",
            condition
            + "if _G.cc_coe_binding then pcall(function() _G.cc_coe_binding:unbind() end) end; if _G.cc_coe_release_binding then pcall(function() _G.cc_coe_release_binding:unbind() end) end; _G.cc_coe_binding=nil; _G.cc_coe_release_binding=nil; _G.cc_coe_key=nil; _G.cc_coe_owner=nil; _G.cc_coe_mode=nil; _G.cc_coe_down=false; _G.cc_coe_press=nil; _G.cc_coe_release=nil"
            + (" end" if owner is not None else ""),
        ]
    )


def install(key, command, owner="", mode="toggle", event_command=None):
    owner = str(owner)
    key = normalize(key)
    validate_mode(key, mode)
    if mode == "hold" and not event_command:
        raise ValueError("缺少按住说话事件命令")
    try:
        occupied = conflict(key)
    except ValueError:
        remove(owner)
        raise
    if occupied:
        # A foreign binding may have appeared since the previous maintain pass.
        # Remove only this bridge owner's handles, never the foreign binding.
        remove(owner)
        raise ValueError(
            HOTKEY_CONFLICT if key == "Alt_R" else "快捷键已被占用；Coe 未接管"
        )
    # JSON quoted strings are valid Lua for these restricted ASCII values/paths.
    setup = (
        "if _G.cc_coe_binding then pcall(function() _G.cc_coe_binding:unbind() end) end; "
        "if _G.cc_coe_release_binding then pcall(function() _G.cc_coe_release_binding:unbind() end) end; "
        "_G.cc_coe_release_binding=nil; _G.cc_coe_down=false; _G.cc_coe_press=nil; _G.cc_coe_release=nil; "
    )
    if mode == "hold":
        prefix = event_command + " " + shlex.quote(owner) + " " + uuid.uuid4().hex
        setup += (
            "local serial=0; local gesture=''; "
            "_G.cc_coe_press=function() if _G.cc_coe_down then return end; _G.cc_coe_down=true; serial=serial+1; gesture=tostring(serial); "
            "hl.dispatch(hl.dsp.exec_cmd("
            + json.dumps(prefix + " press ")
            + "..gesture)) end; "
            "_G.cc_coe_release=function() if not _G.cc_coe_down then return end; _G.cc_coe_down=false; hl.dispatch(hl.dsp.exec_cmd("
            + json.dumps(prefix + " release ")
            + "..gesture)) end; "
            '_G.cc_coe_binding=hl.bind("Alt_R", _G.cc_coe_press, {description="Coe Enhance 语音输入"}); '
            '_G.cc_coe_release_binding=hl.bind("ALT + Alt_R", _G.cc_coe_release, {release=true,ignore_mods=true,description="Coe Enhance 松开识别"}); '
        )
    else:
        setup += (
            "_G.cc_coe_binding=hl.bind("
            + json.dumps(key)
            + ", hl.dsp.exec_cmd("
            + json.dumps(command)
            + '), {description="Coe Enhance 语音输入"}); '
        )
    expr = (
        "if _G.cc_coe_key ~= "
        + json.dumps(key)
        + " or _G.cc_coe_owner ~= "
        + json.dumps(owner)
        + " or _G.cc_coe_mode ~= "
        + json.dumps(mode)
        + " or not _G.cc_coe_binding then "
        + setup
        + "_G.cc_coe_key="
        + json.dumps(key)
        + "; _G.cc_coe_owner="
        + json.dumps(owner)
        + "; _G.cc_coe_mode="
        + json.dumps(mode)
        + " end"
    )
    run(["hyprctl", "eval", expr])


def save(key, command, owner="", mode=None, event_command=None):
    from coe_config import read_store, write_store, locked

    key = normalize(key)
    with locked():
        s = read_store()
        mode = mode if mode is not None else s.get("hotkey_mode", "toggle")
        install(key, command, owner, mode, event_command)
        s["hotkey"] = key
        s["hotkey_mode"] = mode
        write_store(s)
