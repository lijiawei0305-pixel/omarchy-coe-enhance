#!/usr/bin/env python3
"""User-only installation. No sudo, pacman, remote installer execution or shell edits."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from package_plugin import version_qml
import coe_hotkey as hotkey
from coe_compat import HOTKEY_CONFLICT
from build_backend import build_backend

SOURCE = Path(__file__).resolve().parent.parent
HOME = Path.home()
DATA = HOME / ".local/share/omarchy-coe-enhance"
PLUGIN = HOME / ".config/omarchy/plugins/cc.coe-enhance"


def run(args, **kw):
    return subprocess.run([str(x) for x in args], check=True, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coe-source", type=Path)
    ap.add_argument("--go", default=shutil.which("go"))
    args = ap.parse_args()
    for cmd in (
        "pw-record",
        "wl-copy",
        "wl-paste",
        "hyprctl",
        "omarchy",
        "git",
        "systemctl",
    ):
        if not shutil.which(cmd):
            raise SystemExit("缺少依赖: " + cmd + "；请先授权安装相应系统包")
    # Fail before builds, backups, service/config writes or plugin enablement.
    # Stock Omarchy F9 / SUPER+CTRL+X remain owned by Voxtype.
    try:
        if hotkey.conflict("Alt_R"):
            raise SystemExit(HOTKEY_CONFLICT + "。安装已停止，未更改官方语音输入。")
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    except (OSError, subprocess.SubprocessError):
        raise SystemExit(
            "无法检查 Hyprland 快捷键，安装已停止；请在 Omarchy 会话内运行。"
        ) from None
    if SOURCE.resolve() == PLUGIN.resolve():
        raise SystemExit(
            "请先将源码克隆到插件目录之外，再运行安装器；避免覆盖 Git 源码目录。"
        )
    if not args.go or not shutil.which(str(args.go)):
        raise SystemExit("缺少 Go（需要 >= 1.24）；请先安装或传入 --go /path/to/go")
    unit = HOME / ".config/systemd/user/coe.service"
    if unit.exists() and "Omarchy Coe Enhance" not in unit.read_text():
        raise SystemExit("已有其他 coe.service，安装已停止，不覆盖其二进制或配置。")
    if subprocess.run(
        [sys.executable, "-c", "import dbus, gi"], capture_output=True
    ).returncode:
        raise SystemExit(
            "缺少 Python D-Bus / PyGObject；请先安装 python-dbus、python-gobject"
        )
    run(["omarchy", "plugin", "validate", SOURCE])
    run([sys.executable, SOURCE / "scripts/lint.py"])
    # An upgrade changes the running backend, so refuse interrupting dictation.
    probe_python = DATA / "venv/bin/python"
    was_active = (
        subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", "coe.service"]
        ).returncode
        == 0
    )
    if was_active and not probe_python.exists():
        raise SystemExit("Coe 已运行，但无法检查录音状态；请先修复 venv 后再升级。")
    if was_active:
        check = subprocess.run(
            [
                str(probe_python),
                "-c",
                """import dbus,sys
try:
 b=dbus.SessionBus();i=dbus.Interface(b.get_object('com.mistermorph.Coe','/com/mistermorph/Coe',introspect=False),'com.mistermorph.Coe.Dictation1')
 sys.exit(2 if str(i.Status(timeout=2)[0]) in ('recording','processing') else 0)
except dbus.DBusException: sys.exit(0)
""",
            ],
            capture_output=True,
        )
        if check.returncode:
            raise SystemExit("录音或识别进行中，请结束后再升级")
    DATA.mkdir(parents=True, exist_ok=True)
    backup = DATA / "installation-backups" / time.strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, mode=0o700)
    shell = HOME / ".config/omarchy/shell.json"
    if shell.exists():
        shutil.copy2(shell, backup / "shell.json")
    if unit.exists():
        shutil.copy2(unit, backup / "coe.service")
    if PLUGIN.exists():
        shutil.copytree(PLUGIN, backup / "plugin", symlinks=False)
    build_backend(DATA, args.go, args.coe_source)
    bins = DATA / "bin"
    venv = DATA / "venv"
    if not venv.exists():
        run([sys.executable, "-m", "venv", "--system-site-packages", venv])
    run([venv / "bin/pip", "install", "-r", SOURCE / "requirements.txt"])
    run([venv / "bin/python", "-c", "import dbus, gi, ruamel.yaml"])
    # Keep an existing coe binary on PATH; unit always uses the audited build explicitly.
    link = HOME / ".local/bin/coe"
    link.parent.mkdir(parents=True, exist_ok=True)
    if not link.exists():
        link.symlink_to(bins / "coe")
    unit.parent.mkdir(parents=True, exist_ok=True)
    if unit.exists() and "Omarchy Coe Enhance" not in unit.read_text():
        raise SystemExit("已有其他 coe.service：已构建但不覆盖，请先审阅服务配置。")
    unit.write_text(f"""[Unit]
Description=Coe dictation daemon (Omarchy Coe Enhance)
After=graphical-session.target
PartOf=graphical-session.target
StartLimitIntervalSec=30
StartLimitBurst=30
[Service]
Type=simple
ExecStart={bins}/coe serve
Environment=COE_ENHANCE_BRIDGE=1
Environment=XDG_RUNTIME_DIR=%t
EnvironmentFile=-%h/.config/coe/env
Restart=on-failure
RestartSec=2
UMask=0077
# Remote APIs may echo secrets/transcripts in error bodies. UI receives sanitized errors.
StandardOutput=null
StandardError=null
[Install]
WantedBy=graphical-session.target
""")
    run(["systemctl", "--user", "daemon-reload"])
    # Preserve existing configurations. A first install gets an applied placeholder without credentials.
    sys.path.insert(0, str(SOURCE / "scripts"))
    # Current installer interpreter may be system Python; use the venv for configuration.
    init = """import sys,subprocess; sys.path.insert(0,sys.argv[1]); import coe_config as c
c.initialize()
if not c.CONFIG.exists():
 s=c.read_store(); p=s['profiles'][0]
 c.save_profile({'profile':p,'id':p['id']},lambda:subprocess.run(['systemctl','--user','restart','coe.service'],check=True))
"""
    run([venv / "bin/python", "-c", init, SOURCE / "scripts"])
    run(["omarchy", "plugin", "validate", SOURCE])
    run([sys.executable, SOURCE / "scripts/lint.py"])
    # Stage complete folder outside plugin registry, then rename in one operation.
    stage = DATA / "plugin-stage"
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(
        SOURCE,
        stage,
        ignore=shutil.ignore_patterns(
            ".git", ".runtime", "__pycache__", "test-results", ".ruff_cache"
        ),
    )
    version_qml(stage)
    run(["omarchy", "plugin", "validate", stage])
    if PLUGIN.exists():
        shutil.rmtree(PLUGIN)
    shutil.move(stage, PLUGIN)
    # Retire only the old prototype symlink belonging to this source tree.
    old = HOME / ".config/omarchy/plugins/coe-omarchy"
    if old.is_symlink() and old.resolve() == SOURCE:
        old.unlink()
        doc = json.loads(shell.read_text())
        for section, rows in doc.get("bar", {}).get("layout", {}).items():
            doc["bar"]["layout"][section] = [
                r for r in rows if r.get("id") != "coe-omarchy"
            ]
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile("w", dir=shell.parent, delete=False) as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            temp = f.name
        os.replace(temp, shell)
    run(["omarchy-shell", "shell", "rescanPlugins"])
    run(["omarchy", "plugin", "enable", "cc.coe-enhance", "--section", "right"])
    run(["systemctl", "--user", "enable", "--now", "coe.service"])
    if was_active:
        run(["systemctl", "--user", "restart", "coe.service"])
    print("Installed:", PLUGIN, "Backup:", backup)


if __name__ == "__main__":
    main()
