#!/usr/bin/env python3
"""Run via dbus-run-session: real Coe + fixture recorder + local ASR, no user writes."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(
    os.environ.get(
        "COE_TEST_BINARY", str(Path.home() / ".local/share/omarchy-coe-enhance/bin/coe")
    )
)
TEXT = "我正在使用 Omarchy，需要在 VS Code 里面配置 GitHub。"


def wait_for(fn):
    for _ in range(100):
        if fn():
            return
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for isolated Coe")


def main():
    address = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not address or "/run/user/" in address:
        raise RuntimeError("Use dbus-run-session; never test on the desktop bus")
    with tempfile.TemporaryDirectory(prefix="coe-hold-e2e-") as tmp:
        temp = Path(tmp)
        os.environ.update(
            COE_CONFIG=str(temp / "coe/config.yaml"),
            COE_ENHANCE_CONFIG=str(temp / "plugin"),
            XDG_CONFIG_HOME=str(temp),
            COE_ENHANCE_BRIDGE="1",
        )
        sys.path.insert(0, str(ROOT / "scripts"))
        import coe_config as config

        spec = importlib.util.spec_from_file_location(
            "bridge", ROOT / "scripts/coe-bridge.py"
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        m.RUNTIME = temp / "runtime"
        config.private_dir(m.RUNTIME)
        m.HELD_FILE = m.RUNTIME / "held.json"
        delivered = []
        m.output.deliver = lambda text, *_, **kw: delivered.append(text) or "copied"
        config.initialize()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                self.server.upload = self.rfile.read(
                    int(self.headers["Content-Length"])
                )
                self.server.calls += 1
                self.send_response(200)
                self.end_headers()
                self.wfile.write(
                    json.dumps({"text": TEXT}, ensure_ascii=False).encode()
                )

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.calls = 0
        threading.Thread(target=server.serve_forever, daemon=True).start()
        p = dict(
            config.PRESETS["compatible"],
            endpoint=f"http://127.0.0.1:{server.server_port}/v1/audio/transcriptions",
            timeout=5,
        )
        config.save_profile(
            {"profile": p, "api_key": "isolated-mock-key"}, lambda: None
        )
        recorder = temp / "recorder.py"
        recorder.write_text("""#!/usr/bin/python3
import math,struct,signal,sys,time
alive=True
def stop(*a):
 global alive;alive=False
signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
pcm=b''.join(struct.pack('<h',int(5000*math.sin(i*2*math.pi*400/16000))) for i in range(1600))
while alive:
 sys.stdout.buffer.write(pcm);sys.stdout.buffer.flush();time.sleep(.1)
""")
        recorder.chmod(0o700)
        y, doc = config.yaml_load()
        doc["audio"] = {"recorder_binary": str(recorder), "sample_rate": 16000}
        import io

        buf = io.StringIO()
        y.dump(doc, buf)
        config.atomic(config.CONFIG, buf.getvalue())
        s = config.read_store()
        s["hotkey_mode"] = "hold"
        config.write_store(s)
        process = subprocess.Popen(
            [str(BINARY), "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
        b = m.Bridge("isolated-owner")
        b.emit = lambda *_: None
        threading.Thread(target=b.loop.run, daemon=True).start()
        try:
            wait_for(lambda: b.get_status()[0] == "idle")
            b.sync()
            req = {"owner": b.owner, "gesture": "a" * 32 + ":1", "event": "press"}
            # No official recording or state-file edits: simulate its public
            # state at the guard boundary, then query the real isolated Coe.
            for official_state in ("recording", "transcribing", "unknown"):
                with patch.object(
                    m.compat, "probe_voxtype", return_value=official_state
                ):
                    try:
                        b.hold_event(req)
                        raise AssertionError("Official voice conflict was not rejected")
                    except ValueError:
                        pass
                assert b.get_status()[0] == "idle" and server.calls == 0
                assert not b.hold_id and not b.armed
            b.hold_event(req)
            assert b.get_status()[0] == "recording"
            b.hold_event(req)  # repeat press ignored
            time.sleep(0.35)
            b.hold_event(dict(req, event="release"))
            wait_for(lambda: len(delivered) == 1)
            b.hold_event(dict(req, event="release"))
            assert (
                delivered == [TEXT] and server.calls == 1 and b"RIFF" in server.upload
            )
            report = {
                "isolated_bus": True,
                "user_config_untouched": True,
                "paid_requests": 0,
                "start_stop_via_real_dbus": True,
                "go_multipart_wav": True,
                "chinese_result_once": True,
                "duplicate_events_ignored": True,
                "fixture_recorder": True,
                "official_busy_or_unknown_keeps_real_coe_idle": True,
                "voxtype_state_simulated_not_official_recording": True,
            }
            (ROOT / "docs/evidence/hold-e2e.json").write_text(
                json.dumps(report, indent=2) + "\n"
            )
            print(json.dumps(report, indent=2))
        finally:
            b.clear_hold()
            b.loop.quit()
            process.terminate()
            process.wait(timeout=5)
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
