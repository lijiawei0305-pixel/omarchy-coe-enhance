"""Mock HTTP tests call the compiled pinned Coe Go Providers, not Python ASR."""

import base64
import copy
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import coe_config as config

PROBE = Path(
    os.environ.get(
        "COE_TEST_PROBE",
        str(Path.home() / ".local/share/omarchy-coe-enhance/bin/coe-probe"),
    )
)
SECRET = "sentinel-api-key-private"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.calls.append((self.path, dict(self.headers), data))
        if self.server.case == "disconnect":
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        if self.server.case == "timeout":
            time.sleep(1.6)
        status = {"401": 401, "429": 429, "500": 500, "model": 400}.get(
            self.server.case, 200
        )
        response = self.server.payload
        if self.server.case == "invalid":
            response = b"invalid json"
        elif status != 200:
            response = json.dumps(
                {
                    "error": {
                        "message": "invalid model"
                        if self.server.case == "model"
                        else "error " + SECRET
                    }
                }
            ).encode()
        self.send_response(status)
        if self.server.provider == "doubao":
            self.send_header("X-Api-Status-Code", "20000000")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(response)
        except (BrokenPipeError, ConnectionResetError):
            pass


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PROBE.exists():
            raise unittest.SkipTest("Build Coe probe before protocol tests")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, provider, case="ok", profile_override=None):
        self.server.provider = provider
        self.server.case = case
        self.server.calls = []
        empty = case == "empty"
        text = "" if empty else "使用 VASP 和 DFT 计算 Cu(111) 表面的结合能。"
        self.server.payload = json.dumps(
            {
                "openai": {"text": text},
                "doubao": {"result": {"text": text}},
                "sensevoice": {"result": [{"text": text}]},
                "qwen3-asr-vllm": {"choices": [{"message": {"content": text}}]},
                "aliyun-asr": {"output": {"text": text}},
            }[provider],
            ensure_ascii=False,
        ).encode()
        profile = dict(
            provider=provider,
            endpoint=f"http://127.0.0.1:{self.server.server_port}/asr",
            model="mock-model",
            language="",
            prompt="术语",
            timeout=1,
            key_ref="COE_ENHANCE_TEST_MISSING",
        )
        profile.update(profile_override or {})
        return subprocess.run(
            [str(PROBE)],
            input=json.dumps(
                {"profile": profile, "api_key": "" if case == "missing-key" else SECRET}
            ).encode(),
            capture_output=True,
            timeout=5,
        )

    def wav(self, data):
        self.assertEqual(data[:4], b"RIFF")
        self.assertEqual(data[8:12], b"WAVE")
        self.assertEqual(struct.unpack("<H", data[22:24])[0], 1)
        self.assertEqual(struct.unpack("<I", data[24:28])[0], 16000)

    def multipart(self, headers, raw):
        msg = BytesParser(policy=default).parsebytes(
            (
                "Content-Type: "
                + headers["Content-Type"]
                + "\r\nMIME-Version: 1.0\r\n\r\n"
            ).encode()
            + raw
        )
        return {
            part.get_param("name", header="content-disposition"): part.get_payload(
                decode=True
            )
            for part in msg.iter_parts()
        }

    def test_request_shapes(self):
        for provider in [
            "openai",
            "doubao",
            "sensevoice",
            "qwen3-asr-vllm",
            "aliyun-asr",
        ]:
            with self.subTest(provider=provider):
                p = self.call(provider)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertNotIn(SECRET.encode(), p.stdout)
                _, h, b = self.server.calls[0]
                if provider == "openai":
                    fields = self.multipart(h, b)
                    self.wav(fields["file"])
                    self.assertEqual(fields["model"], b"mock-model")
                    self.assertEqual(fields["response_format"], b"json")
                    self.assertEqual(h["Authorization"], "Bearer " + SECRET)
                elif provider == "sensevoice":
                    fields = self.multipart(h, b)
                    self.wav(fields["files"])
                    self.assertEqual(fields["lang"], b"auto")
                    self.assertNotIn("Authorization", h)
                elif provider == "doubao":
                    j = json.loads(b)
                    self.wav(base64.b64decode(j["audio"]["data"]))
                    self.assertEqual(j["request"]["model_name"], "bigmodel")
                    self.assertEqual(h["X-Api-Key"], SECRET)
                    self.assertEqual(h["X-Api-Resource-Id"], "volc.bigasr.auc_turbo")
                    self.assertEqual(h["X-Api-Sequence"], "-1")
                elif provider == "aliyun-asr":
                    j = json.loads(b)
                    self.assertEqual(j["model"], "mock-model")
                    self.assertEqual(
                        j["input"]["messages"][0]["content"][0]["type"], "input_text"
                    )
                    uri = j["input"]["messages"][-1]["content"][0]["input_audio"][
                        "data"
                    ]
                    self.assertTrue(uri.startswith("data:audio/wav;base64,"))
                    self.wav(base64.b64decode(uri.split(",", 1)[1]))
                    self.assertEqual(
                        j["parameters"], {"format": "wav", "sample_rate": "16000"}
                    )
                    self.assertEqual(h["Authorization"], "Bearer " + SECRET)
                    self.assertEqual(h["X-Dashscope-Sse"].lower(), "disable")
                else:
                    j = json.loads(b)
                    self.assertEqual(j["model"], "mock-model")
                    audio = j["messages"][0]["content"][-1]
                    self.assertEqual(audio["type"], "input_audio")
                    self.assertEqual(audio["input_audio"]["format"], "wav")
                    self.wav(base64.b64decode(audio["input_audio"]["data"]))
                    self.assertEqual(h["Authorization"], "Bearer " + SECRET)

    def test_http_and_network_failure_matrix(self):
        for provider in [
            "openai",
            "doubao",
            "sensevoice",
            "qwen3-asr-vllm",
            "aliyun-asr",
        ]:
            for case in [
                "empty",
                "401",
                "429",
                "500",
                "invalid",
                "model",
                "disconnect",
                "timeout",
            ]:
                with self.subTest(provider=provider, case=case):
                    result = self.call(provider, case)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, b"")

    def test_required_api_key_missing(self):
        for provider in ["openai", "doubao", "aliyun-asr"]:
            with self.subTest(provider=provider):
                self.assertNotEqual(self.call(provider, "missing-key").returncode, 0)
                self.assertEqual(self.server.calls, [])

    def test_saved_language_settings_reach_actual_go_adapter_requests(self):
        # Run profile -> atomic YAML -> compiled Go adapter -> localhost HTTP.
        # No live user files, credentials or remote endpoints are used.
        matrix = [
            ("openai", "whisper-1", ["", "zh", "en"]),
            ("sensevoice", "", ["", "auto", "zh", "en", "yue"]),
            (
                "aliyun",
                "qwen-audio-3.0-asr-flash",
                ["", "zh", "en", "zh,en", "zh,en,ja,ko"],
            ),
            ("aliyun", "fun-asr-flash-2026-06-15", ["", "zh", "en"]),
            ("doubao", "bigmodel", [""]),
            ("qwen", "Qwen/Qwen3-ASR-1.7B", [""]),
        ]
        for preset, model, values in matrix:
            for language in values:
                with self.subTest(preset=preset, model=model, language=language):
                    with tempfile.TemporaryDirectory() as tmp:
                        root = Path(tmp)
                        with patch.multiple(
                            config,
                            ROOT=root / "plugin",
                            STORE=root / "plugin/profiles.json",
                            CONFIG=root / "coe/config.yaml",
                            ENV=root / "coe/env",
                        ):
                            config.initialize()
                            p = copy.deepcopy(config.PRESETS[preset])
                            p.update(
                                model=model,
                                language=language,
                                timeout=1,
                                endpoint=f"http://127.0.0.1:{self.server.server_port}/asr",
                            )
                            config.save_profile(
                                {"profile": p, "api_key": SECRET}, lambda: None
                            )
                            saved = config.yaml_load()[1]["asr"]
                            request_profile = {
                                k: saved[k]
                                for k in ("model", "language", "prompt", "endpoint")
                            }
                            result = self.call(
                                p["provider"], profile_override=request_profile
                            )
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertEqual(len(self.server.calls), 1)
                            _, headers, raw = self.server.calls[0]
                            if preset == "openai":
                                fields = self.multipart(headers, raw)
                                self.assertEqual(
                                    fields.get("language"),
                                    language.encode() if language else None,
                                )
                            elif preset == "sensevoice":
                                self.assertEqual(
                                    self.multipart(headers, raw)["lang"],
                                    (language or "auto").encode(),
                                )
                            elif preset == "aliyun":
                                params = json.loads(raw)["parameters"]
                                self.assertEqual(
                                    params.get("language_hints"),
                                    language.split(",") if language else None,
                                )
                            else:
                                payload = json.loads(raw)
                                self.assertNotIn("language", payload)
                                self.assertNotIn("language_hints", payload)


if __name__ == "__main__":
    unittest.main()
