#!/usr/bin/env python3
"""Remove only this plugin and its binding. Keep Coe, Fcitx, configs and credentials."""

from pathlib import Path
import subprocess
import shutil
import time
import os
import coe_hotkey

plugin = Path.home() / ".config/omarchy/plugins/cc.coe-enhance"
subprocess.run(["omarchy", "plugin", "disable", "cc.coe-enhance"], check=True)
# Let Quattro destroy its Process and run the token-scoped cleanup before
# deleting the script that Component.onDestruction invokes.
runtime = Path(os.environ["XDG_RUNTIME_DIR"]) / "coe-enhance"
for _ in range(40):
    if not (runtime / "bridge.sock").exists():
        break
    time.sleep(0.05)
if (runtime / "owner.token").exists():
    subprocess.run(
        [
            str(Path.home() / ".local/share/omarchy-coe-enhance/venv/bin/python"),
            "-B",
            str(Path(__file__).with_name("coe-bridge.py")),
            "cleanup",
            (runtime / "owner.token").read_text(),
        ],
        check=True,
    )
try:
    coe_hotkey.remove()
except Exception:
    pass
if plugin.is_dir() and not plugin.is_symlink():
    shutil.rmtree(plugin)
subprocess.run(["omarchy-shell", "shell", "rescanPlugins"], check=True)
print("已卸载任务栏插件和快捷键。Coe、Fcitx5、Profiles、API Key 和备份全部保留。")
print(
    "停用本项目创建的 Coe 后台服务（可选）：systemctl --user disable --now coe.service"
)
