#!/usr/bin/env python3
"""Audit retained keys without displaying them; read-only, local to this user."""

import json
import os
from pathlib import Path
import stat
import subprocess
import coe_config as cfg

root = Path(__file__).resolve().parents[1]
keys = {
    v.encode()
    for k, v in cfg.env_values().items()
    if k.startswith("COE_ENHANCE_") and len(v) > 8
}


def hits(data):
    return sum(k in data for k in keys)


def capture(args):
    return subprocess.run(args, capture_output=True, timeout=20).stdout


source = capture(["rg", "--files", str(root)]).decode().splitlines()
source_hits = sum(hits(Path(p).read_bytes()) for p in source if Path(p).is_file())
argv_hits = 0
for path in Path("/proc").glob("[0-9]*/cmdline"):
    try:
        if path.stat().st_uid == os.getuid():
            argv_hits += hits(path.read_bytes())
    except OSError:
        pass
report = {
    "retained_distinct_keys": len(keys),
    "env_mode": oct(stat.S_IMODE(cfg.ENV.stat().st_mode)),
    "profile_plaintext_key_hits": hits(cfg.STORE.read_bytes()),
    "yaml_plaintext_key_hits": hits(cfg.CONFIG.read_bytes()),
    "source_key_hits": source_hits,
    "git_history_key_hits": hits(
        capture(["git", "-C", str(root), "log", "-p", "--all"])
    ),
    "process_argv_key_hits": argv_hits,
    "coe_journal_key_hits": hits(
        capture(
            [
                "journalctl",
                "--user",
                "-u",
                "coe.service",
                "--since",
                "today",
                "--no-pager",
            ]
        )
    ),
    "quickshell_log_key_hits": hits(
        capture(["qs", "log", "-p", "/usr/share/omarchy/shell", "--tail", "10000"])
    ),
    "staging_credential_removed": not (
        cfg.ROOT / "aliyun-test-credential.json"
    ).exists(),
    "service_output": capture(
        [
            "systemctl",
            "--user",
            "show",
            "coe.service",
            "-p",
            "StandardOutput",
            "-p",
            "StandardError",
        ]
    )
    .decode()
    .strip(),
}
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(
    1
    if any(v for k, v in report.items() if k.endswith("_hits"))
    or report["env_mode"] != "0o600"
    else 0
)
