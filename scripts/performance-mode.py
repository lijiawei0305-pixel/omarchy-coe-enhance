#!/usr/bin/env python3
"""Explicit opt-in for bounded stage metadata. User service only, no secrets."""

import argparse
import os
from pathlib import Path
import subprocess
import time
import dbus


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["on", "off", "status"])
    args = parser.parse_args()
    home = Path.home()
    root = home / ".local/state/omarchy-coe-enhance"
    trace = root / "performance.jsonl"
    unit = home / ".config/systemd/user/coe.service.d/90-coe-enhance-performance.conf"
    marker = (
        Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        / "coe-enhance/perf.enabled"
    )
    if args.mode == "status":
        print("性能诊断：" + ("开启" if unit.exists() else "关闭"))
        print(trace)
        return
    bus = dbus.SessionBus()

    def ready():
        for _ in range(50):
            try:
                if bus.name_has_owner("com.mistermorph.Coe"):
                    iface = dbus.Interface(
                        bus.get_object(
                            "com.mistermorph.Coe",
                            "/com/mistermorph/Coe",
                            introspect=False,
                        ),
                        "com.mistermorph.Coe.Dictation1",
                    )
                    return tuple(str(x) for x in iface.Status(timeout=1))
            except dbus.DBusException:
                pass
            time.sleep(0.1)
        raise RuntimeError("Coe D-Bus unavailable")

    try:
        state = ready()[0]
    except RuntimeError:
        raise SystemExit("Coe 服务未就绪，请先启动服务。") from None
    if state in ("recording", "processing"):
        raise SystemExit("录音或识别进行中，请结束后再切换性能诊断。")
    signature = "# Omarchy Coe Enhance performance diagnostics\n"
    if unit.exists() and not unit.read_text().startswith(signature):
        raise SystemExit("存在非本插件的配置，停止。")
    old = unit.read_bytes() if unit.exists() else None
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.mode == "on":
        if trace.exists() and (
            trace.is_symlink() or trace.stat().st_mode & 0o777 != 0o600
        ):
            raise SystemExit("诊断文件权限不安全，停止。")
        unit.parent.mkdir(parents=True, exist_ok=True)
        # systemd quotes arbitrary HOME safely; escape specifiers and quotes.
        value = str(trace).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
        unit.write_text(
            signature + '[Service]\nEnvironment="COE_PERF_TRACE=' + value + '"\n'
        )
    else:
        unit.unlink(missing_ok=True)
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "restart", "coe.service"], check=True)
        ready()
    except Exception:
        if old is None:
            unit.unlink(missing_ok=True)
        else:
            unit.write_bytes(old)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "restart", "coe.service"], check=False)
        raise SystemExit("切换失败，已恢复服务设置。") from None
    if args.mode == "on":
        marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(
            marker, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "w") as f:
            f.write(str(trace))
    else:
        marker.unlink(missing_ok=True)
    print(
        "性能诊断："
        + (
            "开启；最多 10 MiB，正文和音频不记录"
            if args.mode == "on"
            else "关闭；保留已有诊断文件"
        )
    )


if __name__ == "__main__":
    main()
