#!/usr/bin/env python3
"""Build the pinned Coe backend in a user-selected directory; no desktop changes."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess

SOURCE = Path(__file__).resolve().parent.parent
PIN = "1345eccb5129cb067a49646e6b73572562d38521"


def run(args, **kw):
    return subprocess.run([str(x) for x in args], check=True, **kw)


def build_backend(data, go, coe_source=None, plugin_source=SOURCE):
    data = Path(data).resolve()
    plugin_source = Path(plugin_source).resolve()
    if (
        data == plugin_source
        or plugin_source in data.parents
        or data in plugin_source.parents
    ):
        raise ValueError("Build output must be outside the plugin source tree")
    if not go or not shutil.which(str(go)):
        raise ValueError("Go is required; install Go >= 1.24 or pass --go /path/to/go")
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    core = data / "core"
    if not core.exists():
        run(
            [
                "git",
                "clone",
                "--no-checkout",
                coe_source or "https://github.com/quailyquaily/coe.git",
                core,
            ]
        )
        run(["git", "-C", core, "checkout", "--detach", PIN])
    if (
        subprocess.check_output(
            ["git", "-C", str(core), "rev-parse", "HEAD"], text=True
        ).strip()
        != PIN
    ):
        raise SystemExit("Coe 源码版本不符合固定版本，停止")
    for name in (
        "coe-1345ecc-privacy-output.patch",
        "coe-1345ecc-aliyun.patch",
        "coe-1345ecc-performance-sum.patch",
        "coe-1345ecc-performance-trace.patch",
        "coe-1345ecc-performance-http.patch",
        "coe-1345ecc-performance-audio.patch",
        "coe-1345ecc-performance-providers.patch",
        "coe-1345ecc-osd.patch",
    ):
        patch = plugin_source / "patches" / name
        command = ["git", "-C", str(core), "apply"]
        if (
            subprocess.run(
                command + ["--reverse", "--check", str(patch)], capture_output=True
            ).returncode
            == 0
        ):
            continue
        if subprocess.run(
            command + ["--check", str(patch)], capture_output=True
        ).returncode:
            raise SystemExit(
                "Coe 构建副本与补丁不一致；请把数据目录 core 改名备份后重新安装。"
            )
        run(command + [patch])
    shutil.copy2(plugin_source / "core/aliyun.go", core / "internal/asr/aliyun.go")
    shutil.copy2(
        plugin_source / "core/aliyun_test.go",
        core / "internal/asr/aliyun_enhance_test.go",
    )
    shutil.copy2(
        plugin_source / "core/enhance_privacy_test.go",
        core / "internal/app/enhance_privacy_test.go",
    )
    shutil.copy2(
        plugin_source / "core/pwrecord_enhance_test.go",
        core / "internal/audio/pwrecord_enhance_test.go",
    )
    shutil.copytree(
        plugin_source / "core/perf", core / "internal/perf", dirs_exist_ok=True
    )
    for source, target in (
        ("perf_reader.go", "internal/audio/perf_reader.go"),
        ("osd_levels.go", "internal/audio/osd_levels.go"),
        ("osd_levels_test.go", "internal/audio/osd_levels_test.go"),
        ("performance_test.go", "internal/pipeline/performance_test.go"),
        ("llm_performance_test.go", "internal/llm/performance_test.go"),
        ("audio_performance_test.go", "internal/audio/performance_test.go"),
    ):
        shutil.copy2(plugin_source / "core" / source, core / target)
    probe = core / "cmd/coe-enhance-probe"
    probe.mkdir(exist_ok=True)
    shutil.copy2(plugin_source / "core/coe-probe.go", probe / "main.go")
    bins = data / "bin"
    bins.mkdir(exist_ok=True)
    run(
        [
            go,
            "build",
            "-ldflags",
            "-X main.version=0.1.0-enhance-osd1 -X main.commit=" + PIN + "+enhance",
            "-o",
            bins / "coe.new",
            "./cmd/coe",
        ],
        cwd=core,
    )
    run(
        [go, "build", "-o", bins / "coe-probe.new", "./cmd/coe-enhance-probe"],
        cwd=core,
    )
    os.replace(bins / "coe.new", bins / "coe")
    os.replace(bins / "coe-probe.new", bins / "coe-probe")
    return core


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--go", default=shutil.which("go"))
    parser.add_argument("--coe-source", type=Path)
    args = parser.parse_args()
    try:
        core = build_backend(args.output_dir, args.go, args.coe_source)
    except ValueError as exc:
        parser.error(str(exc))
    print("Pinned Coe source:", PIN)
    print("Built backend:", core.parent / "bin/coe")
    print("Built protocol probe:", core.parent / "bin/coe-probe")


if __name__ == "__main__":
    main()
