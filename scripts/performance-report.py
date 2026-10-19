#!/usr/bin/env python3
"""Aggregate measurements; never estimate missing T8 application timestamps."""

import argparse
import json
import math
from pathlib import Path
import statistics


def stats(a):
    a = sorted(a)
    return (
        dict(
            n=len(a),
            p50=statistics.median(a),
            p95=a[math.ceil(0.95 * len(a)) - 1],
            minimum=a[0],
            maximum=a[-1],
        )
        if a
        else None
    )


def aggregate(path):
    raw = json.loads(path.read_text())
    events = json.loads(Path(str(path) + ".traces.json").read_text())
    go = {}
    for e in events:
        if e.get("trace_id"):
            go.setdefault(e["trace_id"], {})[e["event"]] = e
    samples = []
    for trace, points in go.items():
        if "T0" not in points:
            continue
        begin = points["T0"]
        end = points.get("core_finished", points.get("T4", begin))
        sid = begin["session_id"]
        for e in events:
            if (
                e["component"] == "bridge"
                and e["session_id"] == sid
                and begin["monotonic_ns"]
                <= e["monotonic_ns"]
                <= end["monotonic_ns"] + 500_000_000
            ):
                # Same session ID may repeat after daemon restart; monotonic
                # interval and unique Go trace ID disambiguate its lifecycle.
                points.setdefault(e["event"], e)
        item = {"trace_id": trace, "session_id": sid, "t0_ns": begin["monotonic_ns"]}
        for name, a, b in [
            ("stop", "T0", "T1"),
            ("prepare", "T1", "T2"),
            ("asr_http_parse", "T3", "T4"),
            ("llm", "T5", "T6"),
            ("bridge_transfer", "result_emit", "T7"),
            ("output_copy", "T7", "clipboard_owned"),
            ("output_app", "T7", "T8_application_confirmed"),
            ("output_clipboard_confirmed", "T7", "T8_clipboard_confirmed"),
            ("core_start_to_pcm", "start_received", "first_pcm"),
        ]:
            if a in points and b in points:
                item[name] = (
                    points[b]["monotonic_ns"] - points[a]["monotonic_ns"]
                ) / 1e6
        samples.append(item)
    result = {k: v for k, v in raw.items() if k != "groups"}
    result["groups"] = {}
    for name, group in raw["groups"].items():
        selected = [
            s
            for s in samples
            if "range_ns" not in group
            or group["range_ns"][0] <= s["t0_ns"] <= group["range_ns"][1]
        ]
        # Older first baselines lack range_ns; split sequentially in run order.
        if "range_ns" not in group:
            index = list(raw["groups"]).index(name)
            selected = sorted(samples, key=lambda s: s["t0_ns"])[
                index * group["total_ms"]["n"] : (index + 1) * group["total_ms"]["n"]
            ]
        stages = {
            k: stats([s[k] for s in selected if k in s])
            for k in [
                "stop",
                "prepare",
                "asr_http_parse",
                "llm",
                "bridge_transfer",
                "output_copy",
                "output_app",
                "output_clipboard_confirmed",
                "core_start_to_pcm",
            ]
        }
        result["groups"][name] = {**group, "stages_ms": stages}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    a = parser.parse_args()
    a.output.write_text(json.dumps(aggregate(a.input), indent=2) + "\n")


if __name__ == "__main__":
    main()
