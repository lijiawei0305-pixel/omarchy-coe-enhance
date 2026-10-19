"""One owner for complete UTF-8 clipboard delivery; never type transcript keys."""

import json
import subprocess

TERMINALS = {
    "kitty",
    "alacritty",
    "foot",
    "footclient",
    "org.wezfurlong.wezterm",
    "com.mitchellh.ghostty",
    "ghostty",
    "org.gnome.terminal",
    "wezterm",
    "xterm",
    "st-256color",
    "com.lazycat.terminal",
}


def run(args, **kw):
    # wl-copy forks a selection-owner child which retains captured pipes on this
    # version. DEVNULL lets the launcher exit promptly; never capture its streams.
    if args[0] == "wl-copy":
        return subprocess.run(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
            check=True,
            **kw,
        )
    return subprocess.run(args, capture_output=True, timeout=4, check=True, **kw)


def active_window():
    try:
        w = json.loads(run(["hyprctl", "-j", "activewindow"]).stdout)
        return {
            k: w.get(k) for k in ("address", "pid", "class", "initialClass", "tags")
        }
    except Exception:
        return {}


def identity(w):
    return (
        (w.get("address"), w.get("pid"), w.get("class"))
        if w.get("address") and w.get("pid")
        else None
    )


def shortcut(w):
    # Same tag convention as Omarchy default/hypr/bindings/clipboard.lua.
    terminal = (
        any(str(t).rstrip("*") == "terminal" for t in (w.get("tags") or []))
        or (w.get("class") or "").lower() in TERMINALS
        or (w.get("initialClass") or "").lower() in TERMINALS
    )
    return ("SHIFT", "Insert") if terminal else ("CTRL", "V")


def deliver(text, target, mode="smart", safe=lambda: True, trace=lambda event: None):
    if not isinstance(text, str) or not text.strip():
        return "empty"
    # Always write this result first. Never consume an old clipboard on failure.
    run(
        ["wl-copy", "--sensitive", "--type", "text/plain;charset=utf-8"],
        input=text.encode("utf-8"),
    )
    trace("clipboard_owned")
    if (
        mode != "smart"
        or not identity(target)
        or not safe()
        or identity(active_window()) != identity(target)
    ):
        return "copied"
    # Check exact UTF-8 ownership/data, not just a hash difference (identical dictations are valid).
    if run(["wl-paste", "--no-newline"]).stdout != text.encode("utf-8"):
        return "clipboard-changed"
    trace("clipboard_verified")
    if not safe() or identity(active_window()) != identity(target):
        return "copied"
    mods, key = shortcut(target)
    # Lua checks the destination again in the compositor immediately before key-down.
    # Refuse any mapped interactive layer; send_key_state uses ASCII key names only.
    addr = target["address"].removeprefix("0x")
    if not addr or any(c not in "0123456789abcdefABCDEF" for c in addr):
        return "copied"
    expression = (
        "local blocked=false; for _,l in ipairs(hl.get_layers()) do if l.mapped and l.interactivity > 0 then blocked=true end end; "
        f'local w=hl.get_active_window(); if blocked or not w or w.pid ~= {int(target["pid"])} or tostring(w.address):gsub("0x","") ~= "{addr}" then error("COE_OUTPUT_COPIED_ONLY") end; '
        f'hl.dispatch(hl.dsp.send_key_state({{mods="{mods}",key="{key}",state="down"}})); '
        f'hl.timer(function() hl.dispatch(hl.dsp.send_key_state({{mods="{mods}",key="{key}",state="up"}})) end, {{timeout=50,type="oneshot"}})'
    )
    result = run(["hyprctl", "eval", expression])
    trace("paste_dispatched")
    return "copied" if b"error:" in (result.stdout or b"") else "pasted"
