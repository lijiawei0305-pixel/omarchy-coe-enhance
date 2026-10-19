#!/usr/bin/env python3
"""Private D-Bus, actual Coe/GTK4/Wayland, paced PCM + localhost ASR/LLM.
The final real pw-record capture is cancelled: no microphone audio is uploaded.
"""

import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "docs/evidence/osd-waveform-only"
BIN = Path(
    os.environ.get(
        "COE_OSD_TEST_BINARY",
        str(Path.home() / ".local/share/omarchy-coe-enhance/bin/coe"),
    )
)


def wait(fn, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.02)
    raise AssertionError("Timed out: " + str(fn))


def layers(pid=None):
    doc = json.loads(subprocess.check_output(["hyprctl", "-j", "layers"]))
    return [
        v
        for monitor in doc.values()
        for layer in monitor["levels"].values()
        for v in layer
        if v["namespace"] == "voxtype-osd" and (pid is None or v["pid"] == pid)
    ]


def resources(pid):
    status = Path(f"/proc/{pid}/status").read_text().splitlines()
    stat = Path(f"/proc/{pid}/stat").read_text().split()
    return {
        "rss_kib": int(next(l.split()[1] for l in status if l.startswith("VmRSS:"))),
        "fds": len(list(Path(f"/proc/{pid}/fd").iterdir())),
        "cpu_ticks": int(stat[13]) + int(stat[14]),
        "threads": int(stat[19]),
    }


def crop(layer, name):
    subprocess.run(
        [
            "grim",
            "-g",
            f"{layer['x']},{layer['y']} {layer['w']}x{layer['h']}",
            str(ART / name),
        ],
        check=True,
    )


def main():
    if (
        not os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        or "/run/user/" in os.environ["DBUS_SESSION_BUS_ADDRESS"]
    ):
        raise RuntimeError("Run on the activation-free tests/dbus-isolated.conf bus")
    ART.mkdir(parents=True, exist_ok=True)
    original = [
        int(x)
        for x in subprocess.check_output(
            ["pgrep", "-f", "^/usr/lib/voxtype/voxtype-osd-gtk4$"], text=True
        ).split()
    ]
    report = {
        "paid_requests": 0,
        "original_osd_pids": original,
        "checkpoints": {},
        "native_binary": "/usr/lib/voxtype/voxtype-osd-gtk4",
    }
    with tempfile.TemporaryDirectory(prefix="coe-osd-test-") as td:
        tmp = Path(td)
        rt = tmp / "runtime"
        rt.mkdir(mode=0o700)
        os.environ.update(
            COE_CONFIG=str(tmp / "coe/config.yaml"),
            COE_ENHANCE_CONFIG=str(tmp / "plugin"),
            XDG_CONFIG_HOME=str(tmp),
            COE_ENHANCE_BRIDGE="1",
            COE_ENHANCE_OSD_SOCKET=str(rt / "osd/audio.sock"),
            HTTP_PROXY="http://127.0.0.1:9",
            HTTPS_PROXY="http://127.0.0.1:9",
            NO_PROXY="localhost,127.0.0.1",
        )
        sys.path.insert(0, str(ROOT / "scripts"))
        import coe_config as cfg

        spec = importlib.util.spec_from_file_location(
            "osd_bridge", ROOT / "scripts/coe-bridge.py"
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        m.RUNTIME = rt
        cfg.initialize()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                pass

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                llm = self.path.endswith("/chat/completions")
                self.server.calls["llm" if llm else "asr"] += 1
                if not llm:
                    wav = base64.b64decode(
                        data["input"]["messages"][-1]["content"][0]["input_audio"][
                            "data"
                        ].split(",", 1)[1]
                    )
                    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
                time.sleep(self.server.llm_delay if llm else self.server.asr_delay)
                body = json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "使用 VASP 和 DFT 计算 Cu(111) 表面的结合能。",
                                }
                            }
                        ]
                    }
                    if llm
                    else {
                        "output": {
                            "text": "我正在使用 Omarchy，并通过 Qwen Audio 进行中文语音识别。"
                        }
                    },
                    ensure_ascii=False,
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        server.calls = {"asr": 0, "llm": 0}
        server.llm_delay = 0.03
        server.asr_delay = 0.03
        threading.Thread(target=server.serve_forever, daemon=True).start()
        endpoint = f"http://127.0.0.1:{server.server_port}"
        cfg.save_profile(
            {
                "profile": dict(
                    cfg.PRESETS["aliyun"],
                    endpoint=endpoint + "/api",
                    model="qwen-audio-3.0-asr-flash",
                ),
                "api_key": "mock-only",
            },
            lambda: None,
        )
        recorder = tmp / "recorder.py"
        recorder.write_text("""#!/usr/bin/python3
import signal,sys,time,math,struct
alive=True
def stop(*_):
 global alive;alive=False
signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
i=0
while alive:
 amplitude=[0,1000,14000,1000][(i//30)%4]
 p=b''.join(struct.pack('<h',int(amplitude*math.sin(j*2*math.pi*400/16000))) for j in range(160))
 sys.stdout.buffer.write(p);sys.stdout.buffer.flush();i+=1;time.sleep(.01)
""")
        recorder.chmod(0o700)

        def audio(binary):
            y, d = cfg.yaml_load()
            d["audio"] = {
                "recorder_binary": binary,
                "sample_rate": 16000,
                "channels": 1,
                "format": "s16",
            }
            buf = io.StringIO()
            y.dump(d, buf)
            cfg.atomic(cfg.CONFIG, buf.getvalue())

        audio(str(recorder))
        b = m.Bridge("isolated-osd")
        b.emit = lambda *_: None
        delivered = []
        m.output.deliver = lambda text, *_, **kw: delivered.append(text) or "copied"
        events = []
        b.bus.add_signal_receiver(
            lambda state, sid, detail: events.append([str(state), str(detail)]),
            signal_name="StateChanged",
            dbus_interface=m.IFACE,
            bus_name=m.NAME,
            path=m.PATH,
        )
        threading.Thread(target=b.loop.run, daemon=True).start()
        p = None
        observer = None
        collect_stop = threading.Event()
        peaks = []

        def start_core():
            nonlocal p
            if p:
                p.terminate()
                p.wait(5)
            p = subprocess.Popen(
                [str(BIN), "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            wait(lambda: b.get_status()[0] == "idle")
            b.sync()

        def connect_observer():
            nonlocal observer
            observer = socket.socket(socket.AF_UNIX)
            observer.connect(str(rt / "osd/audio.sock"))
            observer.settimeout(0.1)

        def collector():
            connection = observer
            buf = b""
            while not collect_stop.is_set():
                try:
                    chunk = connection.recv(8192)
                    if not chunk:
                        return
                    buf += chunk
                    while len(buf) >= 16:
                        f, buf = buf[:16], buf[16:]
                        peaks.append((time.monotonic(), *struct.unpack("=Ifff", f)))
                except socket.timeout:
                    pass
                except OSError:
                    return

        original_run = subprocess.run
        shown_messages = []

        def audited_run(args, **kw):
            if list(args[:2]) in (["omarchy", "osd"], ["omarchy-shell", "osd"]):
                # Record a regression without showing popups on the user's desktop.
                shown_messages.append(list(args))
                return subprocess.CompletedProcess(args, 0, stdout="closed\n")
            return original_run(args, **kw)

        subprocess.run = audited_run
        try:
            start_core()
            b.osd.start()
            wait(
                lambda: (
                    b.osd.process
                    and subprocess.run(
                        [
                            "pgrep",
                            "-P",
                            str(b.osd.process.pid),
                            "-f",
                            "voxtype-osd-gtk4",
                        ],
                        capture_output=True,
                    ).returncode
                    == 0
                )
            )
            gtk = int(
                subprocess.check_output(
                    ["pgrep", "-P", str(b.osd.process.pid), "-f", "voxtype-osd-gtk4"],
                    text=True,
                ).strip()
            )
            time.sleep(0.3)
            connect_observer()
            threading.Thread(target=collector, daemon=True).start()
            initial_focus = json.loads(
                subprocess.check_output(["hyprctl", "-j", "activewindow"])
            ).get("address")
            # A complete quiet -> low -> high -> quiet source cycle, at true 100Hz.
            b.trigger("start")
            shown = wait(lambda: layers(gtk))[0]
            time.sleep(0.13)
            crop(layers(gtk)[0], "original-gtk-silence.png")
            time.sleep(0.60)
            report["waveform_geometry"] = layers(gtk)[0]
            crop(layers(gtk)[0], "original-gtk-waveform.png")
            time.sleep(0.65)
            b.trigger("cancel")
            wait(lambda: not layers(gtk))
            assert server.calls == {"asr": 0, "llm": 0}
            assert min(f[4] for f in peaks) == -120 and max(f[4] for f in peaks) > -8
            report["fixture_levels"] = {
                "frames": len(peaks),
                "min_dbfs": min(f[4] for f in peaks),
                "max_dbfs": max(f[4] for f in peaks),
                "silence_dbfs": -120,
                "first_to_last_hz": (len(peaks) - 1) / (peaks[-1][0] - peaks[0][0]),
            }
            report["focus_unchanged"] = initial_focus == json.loads(
                subprocess.check_output(["hyprctl", "-j", "activewindow"])
            ).get("address")
            report["auto_hide_after_cancel"] = True
            report["checkpoints"]["0"] = {
                "core": resources(p.pid),
                "gtk": resources(gtk),
            }
            for i in range(1, 31):
                server.asr_delay = 0.5 if i == 1 else 0.03
                # Recorder begins with silence; >300ms includes real fixture tone.
                b.trigger("start")
                time.sleep(0.35)
                b.trigger("stop")
                wait(lambda: len(delivered) == i)
                if i in (1, 10, 30):
                    report["checkpoints"][str(i)] = {
                        "core": resources(p.pid),
                        "gtk": resources(gtk),
                        "frames": len(peaks),
                        "asr_calls": server.calls["asr"],
                    }
            wait(lambda: not layers(gtk))
            report["thirty_sessions"] = server.calls == {"asr": 30, "llm": 0}
            assert report["thirty_sessions"] and len(delivered) == 30
            report["output_once_per_session"] = True
            server.llm_delay = 1.3
            # The chosen real LLM stage emits a genuine existing StateChanged detail.
            s = cfg.read_store()
            llm = dict(
                s["llm"], enabled=True, endpoint=endpoint + "/v1", model="mock-llm"
            )
            cfg.save_profile(
                {
                    "id": s["active"],
                    "profile": cfg.active_profile(s),
                    "llm": llm,
                    "llm_key": "mock-only",
                },
                lambda: None,
            )
            collect_stop.set()
            observer.close()
            observer = None
            start_core()
            time.sleep(1.1)
            b.trigger("start")
            time.sleep(0.35)
            b.trigger("stop")
            wait(lambda: len(delivered) == 31)
            report["llm_stage_real_dbus"] = any(
                e[0] == "processing" and e[1].split(";", 1)[0] == "processing llm"
                for e in events
            )
            if not (
                report["llm_stage_real_dbus"] and server.calls == {"asr": 31, "llm": 1}
            ):
                print(
                    json.dumps(
                        {
                            "counts": server.calls,
                            "events_tail": events[-12:],
                            "delivered_count": len(delivered),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            assert report["llm_stage_real_dbus"] and server.calls == {
                "asr": 31,
                "llm": 1,
            }
            report["post_recording_popup_commands"] = shown_messages
            assert not shown_messages
            # Real microphone capture -> original renderer, Cancel prevents ASR.
            audio("/usr/bin/pw-record")
            start_core()
            time.sleep(1.1)
            peaks.clear()
            collect_stop.clear()
            connect_observer()
            threading.Thread(target=collector, daemon=True).start()
            b.trigger("start")
            shown = wait(lambda: layers(gtk))[0]
            time.sleep(1.0)
            crop(layers(gtk)[0], "real-microphone-original-gtk.png")
            b.trigger("cancel")
            wait(lambda: not layers(gtk))
            report["real_microphone"] = {
                "frame_count": len(peaks),
                "min_dbfs": min(f[4] for f in peaks),
                "max_dbfs": max(f[4] for f in peaks),
                "cloud_requests": 0,
                "cancelled": True,
            }
            assert peaks and server.calls == {"asr": 31, "llm": 1}
            report["existing_voxtype_untouched"] = all(
                Path(f"/proc/{pid}").exists() for pid in original
            )
            report["original_single_renderer"] = len(layers()) == 0
            report["mock_calls"] = server.calls
            report["real_cloud_asr"] = "NOT RUN"
        finally:
            collect_stop.set()
            if observer:
                observer.close()
            b.osd.close()
            b.loop.quit()
            if p:
                p.terminate()
                p.wait(5)
            server.shutdown()
            server.server_close()
            subprocess.run = original_run
        report["owned_children_stopped"] = not Path(f"/proc/{gtk}").exists()
        report["audio_socket_cleaned"] = not (rt / "osd/audio.sock").exists()
        assert report["owned_children_stopped"] and report["audio_socket_cleaned"]
    (ART / "e2e.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
