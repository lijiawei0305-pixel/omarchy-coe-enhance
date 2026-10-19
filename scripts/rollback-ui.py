#!/usr/bin/env python3
"""Restore a saved plugin directory only. Never overwrite Coe/Profiles/keys."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

DATA = Path.home() / ".local/share/omarchy-coe-enhance"
DEST = Path.home() / ".config/omarchy/plugins/cc.coe-enhance"


def run(*args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", nargs="?", type=Path)
    args = parser.parse_args()
    backups = sorted((DATA / "ui-backups").glob("*/plugin/manifest.json"))
    backup = args.backup or (backups[-1].parent.parent if backups else None)
    if backup is None:
        parser.error("找不到 UI 备份，请提供备份目录")
    source = backup / "plugin"
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("id") != "cc.coe-enhance":
        parser.error("备份不是 cc.coe-enhance 插件")
    run("omarchy", "plugin", "validate", str(source))
    recovery = DATA / "ui-rollbacks" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    recovery.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="coe-ui-rollback-", dir=DATA) as temp:
        stage = Path(temp) / "plugin"
        shutil.copytree(
            source,
            stage,
            ignore=shutil.ignore_patterns(
                "__pycache__", ".git", ".runtime", ".ruff_cache"
            ),
        )
        run("omarchy", "plugin", "disable", "cc.coe-enhance")
        if DEST.exists():
            DEST.rename(recovery)
        try:
            shutil.move(stage, DEST)
            run("omarchy-shell", "shell", "rescanPlugins")
            run("omarchy", "plugin", "enable", "cc.coe-enhance", "--section", "right")
        except Exception:
            if DEST.exists():
                shutil.rmtree(DEST)
            if recovery.exists():
                recovery.rename(DEST)
            run("omarchy-shell", "shell", "rescanPlugins")
            run("omarchy", "plugin", "enable", "cc.coe-enhance", "--section", "right")
            raise
    print("已恢复 UI；Coe 配置、Profiles、API Key 和快捷键设置未改动。")
    print("被替换的插件副本：", recovery)


if __name__ == "__main__":
    main()
