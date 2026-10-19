#!/usr/bin/env python3
"""Rollback this audit's plugin/binaries/source; user config and keys untouched."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from datetime import datetime


def main():
    home = Path.home()
    data = home / ".local/share/omarchy-coe-enhance"
    plugin = home / ".config/omarchy/plugins/cc.coe-enhance"
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("backup", nargs="?", type=Path)
    args = ap.parse_args()
    candidates = sorted((data / "performance-backups").glob("*/manifest.json"))
    backup = args.backup or (candidates[-1].parent if candidates else None)
    if (
        backup is None
        or json.loads((backup / "plugin/manifest.json").read_text()).get("id")
        != "cc.coe-enhance"
    ):
        raise SystemExit("找不到有效性能审计备份")
    # Refuse interrupting a user's recording.
    import dbus

    iface = dbus.Interface(
        dbus.SessionBus().get_object(
            "com.mistermorph.Coe", "/com/mistermorph/Coe", introspect=False
        ),
        "com.mistermorph.Coe.Dictation1",
    )
    if str(iface.Status(timeout=2)[0]) in ("recording", "processing"):
        raise SystemExit("请先结束录音或识别")

    def run(*args):
        subprocess.run(args, check=True)

    run("omarchy", "plugin", "validate", str(backup / "plugin"))
    recovery = data / "performance-rollbacks" / datetime.now().strftime("%Y%m%d-%H%M%S")
    recovery.mkdir(parents=True, mode=0o700)
    run("omarchy", "plugin", "disable", "cc.coe-enhance")
    run("systemctl", "--user", "stop", "coe.service")
    try:
        # The core checkout retains .git. Back up complete current files and
        # restore old source without destroying worktree metadata.
        for name, target in [("plugin", plugin), ("bin", data / "bin")]:
            target.rename(recovery / name)
            shutil.copytree(backup / name, target)
        core = data / "core"
        shutil.copytree(core, recovery / "core", ignore=shutil.ignore_patterns(".git"))
        for p in core.iterdir():
            if p.name == ".git":
                continue
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        shutil.copytree(backup / "core", core, dirs_exist_ok=True)
    finally:
        run("systemctl", "--user", "start", "coe.service")
        run("omarchy-shell", "shell", "rescanPlugins")
        run("omarchy", "plugin", "enable", "cc.coe-enhance", "--section", "right")
    print(
        "已恢复审计前后端和插件。配置、密钥、Profiles、Alt_R 未修改。当前版本备份："
        + str(recovery)
    )


if __name__ == "__main__":
    main()
