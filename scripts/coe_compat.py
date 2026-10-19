"""Read-only Voxtype coexistence checks. Never control its recording or service."""

import os
from pathlib import Path
import shutil
import subprocess
import tomllib

BUSY_STATES = {"recording", "transcribing", "streaming", "outputting", "loading"}
SAFE_STATES = {"idle", "stopped", "not-installed"}
HOTKEY_CONFLICT = (
    "右 Alt 已被其他功能占用；Coe 未接管，请查看「服务与诊断」中的兼容性说明"
)


def config_override():
    """Honor --config on the running daemon, without exposing its command line."""
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "voxtype"
    try:
        value = (runtime / "voxtype.lock").read_text().strip()
        if not value.isdecimal() or not 1 < int(value) < 2**31:
            return None
        proc = Path("/proc") / value
        if proc.joinpath("comm").read_text().strip() != "voxtype":
            return None
        args = os.fsdecode(proc.joinpath("cmdline").read_bytes()).split("\0")
        for i, arg in enumerate(args):
            if arg in ("--config", "-c") and i + 1 < len(args):
                path = Path(args[i + 1])
                return (
                    path
                    if path.is_absolute()
                    else proc.joinpath("cwd").resolve() / path
                )
            if arg.startswith("--config="):
                path = Path(arg.split("=", 1)[1])
                return (
                    path
                    if path.is_absolute()
                    else proc.joinpath("cwd").resolve() / path
                )
    except FileNotFoundError:
        pass  # No live daemon, or it exited during inspection.
    except (OSError, ValueError):
        raise ValueError(
            "无法确认官方语音服务配置；未接管右 Alt，请检查服务与诊断"
        ) from None
    return None


def native_hotkey_conflict():
    """Voxtype can read evdev directly, independently of Hyprland bindings."""
    if not shutil.which("voxtype"):
        return False
    override = config_override()
    user = (
        Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        / "voxtype/config.toml"
    )
    path = override or (user if user.exists() else Path("/etc/voxtype/config.toml"))
    try:
        if not path.exists() and override is None:
            return False  # Upstream default is SCROLLLOCK, not RIGHTALT.
        if path.stat().st_size > 1024 * 1024:
            raise ValueError()
        with path.open("rb") as stream:
            hotkey = tomllib.load(stream).get("hotkey", {})
        if not isinstance(hotkey, dict):
            raise ValueError()
        return (
            hotkey.get("enabled", True) is not False
            and hotkey.get("key", "SCROLLLOCK") == "RIGHTALT"
        )
    except (OSError, ValueError, TypeError):
        raise ValueError(
            "无法检查官方语音快捷键配置；未接管右 Alt，请检查服务与诊断"
        ) from None


def probe_voxtype():
    """One bounded CLI query per Start; let the installed version resolve state."""
    binary = shutil.which("voxtype")
    if not binary:
        return "not-installed"
    try:
        override = config_override()
        command = [binary] + (["--config", str(override)] if override else [])
        result = subprocess.run(
            command + ["status", "--format", "text"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
        state = result.stdout.strip()
        if result.returncode == 0 and state in BUSY_STATES | {"idle", "stopped"}:
            return state
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return "unknown"  # Never forward CLI output/configuration into UI or logs.


def require_available(state):
    if state in BUSY_STATES:
        raise ValueError("官方语音输入正在工作，请结束后再按右 Alt；Coe 未启动录音")
    if state not in SAFE_STATES:
        raise ValueError(
            "无法确认官方语音输入是否空闲，已暂停开始录音；请检查服务与诊断"
        )
