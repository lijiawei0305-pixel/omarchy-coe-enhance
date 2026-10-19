#!/usr/bin/env python3
"""Explicit local-only phase resource sampling; never loaded by production."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", required=True)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    executable = str(Path(args.binary).resolve()).encode()
    samples = {}
    phases = dict(
        start_received="recording_start",
        first_pcm="recording",
        T0="recorder_stop",
        T1="audio_prepare",
        T3="asr_http",
        T4="asr_done",
        T5="llm_http",
        T6="llm_done",
        core_finished="idle",
    )
    with tempfile.TemporaryDirectory(prefix="coe-resources-") as tmp:
        report = Path(tmp) / "pipeline.json"
        with (Path(tmp) / "run.log").open("wb") as log:
            child = subprocess.Popen(
                [
                    "dbus-run-session",
                    "--config-file",
                    str(ROOT / "tests/dbus-isolated.conf"),
                    "--",
                    sys.executable,
                    "-B",
                    str(ROOT / "tests/performance.py"),
                    "--binary",
                    args.binary,
                    "--n",
                    "3",
                    "--durations",
                    "1",
                    "--output",
                    str(report),
                ],
                stdout=log,
                stderr=log,
            )
            last = {}
            while child.poll() is None:
                for path in Path("/proc").glob("[0-9]*/cmdline"):
                    try:
                        if path.read_bytes().split(b"\0")[0] != executable:
                            continue
                        environment = dict(
                            x.split(b"=", 1)
                            for x in (path.parent / "environ").read_bytes().split(b"\0")
                            if b"=" in x
                        )
                        trace_path = environment.get(b"COE_PERF_TRACE", b"").decode()
                        if not trace_path.startswith("/tmp/coe-perf-"):
                            continue
                        rows = [
                            json.loads(x)
                            for x in Path(trace_path).read_text().splitlines()
                            if x.endswith("}")
                        ]
                        phase = "idle"
                        for row in rows:
                            if row["component"] == "coe" and row["event"] in phases:
                                phase = phases[row["event"]]
                        status = (path.parent / "status").read_text().splitlines()
                        rss = int(
                            next(x.split()[1] for x in status if x.startswith("VmRSS:"))
                        )
                        stat = (path.parent / "stat").read_text().split()
                        ticks = int(stat[13]) + int(stat[14])
                        now = time.monotonic()
                        item = samples.setdefault(
                            phase,
                            {
                                "samples": 0,
                                "rss_min_kib": rss,
                                "rss_max_kib": rss,
                                "sampled_cpu_ticks": 0,
                                "sampled_wall_seconds": 0,
                            },
                        )
                        item["samples"] += 1
                        item["rss_min_kib"] = min(item["rss_min_kib"], rss)
                        item["rss_max_kib"] = max(item["rss_max_kib"], rss)
                        previous = last.get(path.parent.name)
                        if previous and previous[0] == phase:
                            item["sampled_cpu_ticks"] += max(0, ticks - previous[1])
                            item["sampled_wall_seconds"] += now - previous[2]
                        last[path.parent.name] = (phase, ticks, now)
                    except (OSError, ValueError, StopIteration):
                        pass
                time.sleep(0.005)
            if child.returncode:
                raise SystemExit(
                    "Isolated resource audit failed; inspect its local log before retrying"
                )
        counts = {
            k: sum(
                v["calls"][k] for v in json.loads(report.read_text())["groups"].values()
            )
            for k in ["asr", "llm"]
        }
    for item in samples.values():
        item["sampled_cpu_ms"] = (
            item["sampled_cpu_ticks"] * 1000 / os.sysconf("SC_CLK_TCK")
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "scope": "Isolated real daemon + fixture/local HTTP; short sampled intervals, tick quantization, not production CPU percent",
                "paid_requests": 0,
                "extra_mock_calls": counts,
                "phases": samples,
            },
            indent=2,
        )
        + "\n"
    )
    print("Local recording/ASR/LLM resource phase audit complete.")


if __name__ == "__main__":
    main()
