#!/usr/bin/env python3
"""Shell-owned D-Bus event bridge and private pipe/socket RPC. No ASR implementation."""

from __future__ import annotations

# Hotkey clients must not import the daemon/configuration dependency graph.
import sys
if __name__ == "__main__" and (len(sys.argv) < 2 or sys.argv[1] not in ("watch", "cleanup")):
    from coe_client import main
    raise SystemExit(main())
import json
import os
from pathlib import Path
import queue
import re
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

sys.dont_write_bytecode = True
import coe_config as config
import coe_hotkey as hotkey
import coe_output as output
import coe_perf as perf
import coe_compat as compat
from coe_osd import Osd

NAME = "com.mistermorph.Coe"
PATH = "/com/mistermorph/Coe"
IFACE = NAME + ".Dictation1"
RUNTIME = (
    Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/" + str(os.getuid())))
    / "coe-enhance"
)
SOCKET = RUNTIME / "bridge.sock"
HELD_FILE = RUNTIME / "held.json"
PYTHON = Path.home() / ".local/share/omarchy-coe-enhance/venv/bin/python"
COMMAND = shlex.join(
    [str(PYTHON), "-B", str(Path(__file__).resolve()), "request", "toggle"]
)
HOLD_COMMAND = shlex.join([str(PYTHON), "-B", str(Path(__file__).resolve()), "hold"])


# Never pass server error bodies to QML/journal; they can echo keys or text.
def safe_error(exc):
    msg = str(exc).lower()
    for tokens, message in [
        (("401", "unauthorized"), "认证失败（401），请检查 API Key"),
        (("429", "rate limit"), "请求过于频繁或额度不足（429）"),
        (("500", "502", "503"), "服务端暂时不可用（5xx）"),
        (("timeout", "timed out", "deadline"), "请求超时，请检查网络或增加超时"),
        (("no such host", "network", "connection", "dial tcp"), "网络连接失败"),
        (("empty", "no text", "no result"), "服务返回空文本，未执行粘贴"),
        (("api key", "api_key", "missing key"), "缺少 API Key"),
        (("decode", "unmarshal", "invalid character"), "服务响应不是兼容的 JSON"),
        (("model", "404"), "模型或 Endpoint 不兼容"),
    ]:
        if any(t in msg for t in tokens):
            return message
    return "操作失败，请检查配置、服务及协议兼容性"


class Bridge:
    def __init__(self, owner=""):
        self.owner = owner
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SessionBus()
        self.loop = GLib.MainLoop()
        self.lock = threading.RLock()
        self.print_lock = threading.Lock()
        self.state = "offline"
        self.session = ""
        self.expected_session = ""
        self.error = ""
        self.notice = ""
        self.target = {}
        self.armed = False
        self.switched = False
        self.panel = False
        self.seen = set()
        self.alive = True
        self.hotkey_error = ""
        self.voxtype_state = "not-checked"
        self.backup = ""
        self.commands = queue.Queue()
        self.hold_lock = threading.Lock()
        self.hold_id = ""
        self.hold_released = set()
        self.hold_timer = None
        self.osd = Osd(RUNTIME)
        config.initialize()
        self.bus.add_signal_receiver(
            self.state_changed,
            signal_name="StateChanged",
            dbus_interface=IFACE,
            bus_name=NAME,
            path=PATH,
        )
        self.bus.add_signal_receiver(
            self.result_ready,
            signal_name="ResultReady",
            dbus_interface=IFACE,
            bus_name=NAME,
            path=PATH,
        )
        self.bus.add_signal_receiver(
            self.error_raised,
            signal_name="ErrorRaised",
            dbus_interface=IFACE,
            bus_name=NAME,
            path=PATH,
        )
        self.bus.add_signal_receiver(
            self.owner_changed,
            signal_name="NameOwnerChanged",
            dbus_interface="org.freedesktop.DBus",
            arg0=NAME,
        )

    def iface(self):
        return dbus.Interface(self.bus.get_object(NAME, PATH, introspect=False), IFACE)

    def get_status(self):
        try:
            return tuple(str(x) for x in self.iface().Status(timeout=2))
        except dbus.DBusException:
            return ("offline", "", "")

    def snapshot(self):
        return dict(
            type="snapshot",
            state=self.state,
            session=self.session,
            error=self.error,
            notice=self.notice,
            hotkey_error=self.hotkey_error,
            backup=self.backup,
            diagnostics={
                "armed": self.armed,
                "focus_changed": self.switched,
                "panel_open": self.panel,
                "seen_results": len(self.seen),
                "original_osd_host_alive": getattr(self, "osd", None) is not None and self.osd.available(),
                "target_present": bool(output.identity(self.target)),
                "voxtype_last_start_check": self.voxtype_state,
            },
            store=config.cached_public_store(),
        )

    def emit(self, value=None):
        with self.print_lock:
            try:
                print(
                    json.dumps(value or self.snapshot(), ensure_ascii=False), flush=True
                )
            except (BrokenPipeError, OSError):
                self.shutdown()

    def sync(self):
        state, sid, _ = self.get_status()
        self.state = state
        self.session = sid
        self.emit()
        return True

    def owner_changed(self, name, old, new):
        self.clear_hold()
        self.armed = False
        self.switched = True
        self.target = {}
        self.seen.clear()
        self.expected_session = ""
        self.state = "offline"
        self.emit()
        if new:
            GLib.timeout_add(350, self.sync_once)

    def sync_once(self):
        self.sync()
        return False

    def state_changed(self, state, sid, detail):
        self.state = str(state)
        self.session = str(sid)
        if state == "recording":
            self.error = ""
            self.expected_session = str(sid)
        if state == "error":
            self.error = safe_error(detail)
            self.armed = False
        if state == "idle" and "cancel" in str(detail):
            self.armed = False
        if state == "completed":
            self.notice = "识别完成"
        self.emit()

    def error_raised(self, sid, msg):
        self.error = safe_error(msg)
        self.armed = False
        self.emit()

    def result_ready(self, sid, text):
        sid = str(sid)
        perf.mark(sid, "result_received")
        if (
            not sid
            or sid in self.seen
            or (self.armed and self.expected_session and sid != self.expected_session)
        ):
            return
        self.seen.add(sid)
        if len(self.seen) > 256:
            self.seen = {sid}
        # Shell restart never replays a result or invents a target.
        target = self.target if self.armed else {}
        switched = self.switched
        self.armed = False

        def deliver():
            try:
                mode = config.read_store()["output"]
                perf.mark(sid, "T7")
                result = output.deliver(
                    str(text),
                    target,
                    mode,
                    lambda: (
                        not switched
                        and not self.switched
                        and not self.panel
                        and self.alive
                    ),
                    trace=lambda event: perf.mark(sid, event),
                )
                perf.mark(sid, "output_returned")
                self.notice = {
                    "pasted": "已向原窗口发送粘贴快捷键",
                    "copied": "文字已复制；焦点变化或仅复制模式",
                    "empty": "空文本，未粘贴",
                    "clipboard-changed": "剪贴板已变化，未粘贴",
                }.get(result, "文字已复制")
            except Exception:
                self.error = "输出失败，未发送粘贴快捷键"
            self.emit()

        threading.Thread(target=deliver, daemon=True).start()

    def idle_required(self):
        if self.get_status()[0] in ("recording", "processing"):
            raise ValueError("录音或转写进行中，请结束后再应用设置")

    def restart(self):
        self.idle_required()
        subprocess.run(
            ["systemctl", "--user", "reset-failed", "coe.service"],
            capture_output=True,
            timeout=5,
        )
        p = subprocess.run(
            ["systemctl", "--user", "restart", "coe.service"],
            capture_output=True,
            timeout=15,
        )
        if p.returncode:
            raise RuntimeError("service restart failed")
        for _ in range(30):
            if self.get_status()[0] != "offline":
                return
            time.sleep(0.1)
        raise RuntimeError("service D-Bus not ready")

    def trigger(self, action):
        perf.mark(self.session, "command_received")
        state = self.get_status()[0]
        if state == "offline":
            raise ValueError("Coe 服务未运行，请在面板中启动")
        if state == "processing":
            raise ValueError("正在转写，请稍候")
        method = (
            "Cancel"
            if action == "cancel"
            else "Stop"
            if action == "stop" or (action == "toggle" and state == "recording")
            else "Start"
        )
        if method == "Start":
            self.voxtype_state = compat.probe_voxtype()
            compat.require_available(self.voxtype_state)
            s = config.read_store()
            if not s["active"]:
                raise ValueError("请先保存并应用一个 ASR Profile")
            p = next(
                p for p in config.cached_public_store()["profiles"] if p["id"] == s["active"]
            )
            if (
                p["provider"] in ("openai", "doubao", "aliyun-asr")
                and not p["key_present"]
            ):
                raise ValueError("请先在面板中填写 API Key")
            self.target = output.active_window()
            self.expected_session = ""
            self.switched = False
            self.armed = True
            self.notice = ""
        if method == "Cancel":
            self.armed = False
            self.clear_hold()
        try:
            perf.mark(self.session, "dbus_call")
            getattr(self.iface(), method)(timeout=650)
            perf.mark(self.session, "dbus_returned")
        except Exception:
            self.armed = False
            raise
        self.sync()

    def clear_hold(self):
        self.hold_id = ""
        if self.hold_timer is not None:
            self.hold_timer.cancel()
            self.hold_timer = None
        HELD_FILE.unlink(missing_ok=True)

    def hold_expired(self, gesture):
        with self.lock:
            if self.hold_id == gesture:
                self.trigger("cancel")
                self.notice = "120 秒未收到松键信号，已取消录音"
                self.emit()

    def hold_event(self, req):
        gesture = req.get("gesture", "")
        event = req.get("event")
        if (
            req.get("owner") != self.owner
            or not isinstance(gesture, str)
            or not re.fullmatch(r"[0-9a-f]{32}:[1-9][0-9]{0,8}", gesture)
        ):
            return {"ignored": True}
        if event not in ("press", "release"):
            raise ValueError("无效按住说话事件")
        if config.read_store().get("hotkey_mode", "toggle") != "hold":
            return {"ignored": True}
        # Record release intent before waiting on Start/Stop. Separate CLI
        # processes can reach this socket in reverse order on a quick tap.
        with self.hold_lock:
            if event == "release":
                if len(self.hold_released) >= 256:
                    self.hold_released.clear()
                self.hold_released.add(gesture)
        if event == "press":
            if not self.lock.acquire(blocking=False):
                return {"ignored": True}
            try:
                with self.hold_lock:
                    released = gesture in self.hold_released
                if (
                    released
                    or self.hold_id
                    or self.state in ("recording", "processing", "offline")
                    or self.get_status()[0] in ("recording", "processing", "offline")
                ):
                    return {"ignored": True}
                self.trigger("start")
                self.hold_id = gesture
                try:
                    config.atomic(
                        HELD_FILE,
                        json.dumps({"owner": self.owner, "session": self.session}),
                        0o600,
                    )
                    self.hold_timer = threading.Timer(
                        120, self.hold_expired, args=(gesture,)
                    )
                    self.hold_timer.daemon = True
                    self.hold_timer.start()
                except Exception:
                    self.trigger("cancel")
                    raise
            finally:
                self.lock.release()
        else:
            with self.lock:
                if self.hold_id != gesture:
                    return {"ignored": True}
                self.clear_hold()
                if self.get_status()[0] == "recording":
                    self.trigger("stop")
        self.emit()
        return {"accepted": True}

    def handle(self, req):
        action = req.get("action", "get")
        if action == "get":
            return self.snapshot()
        if action == "panel":
            self.panel = req.get("open") is True
            return {"ok": True}
        if action == "hold":
            return self.hold_event(req)
        with self.lock:
            self.error = ""
            if action in ("toggle", "start", "stop", "cancel"):
                self.trigger(action)
            elif action == "save":
                self.idle_required()
                self.backup = config.save_profile(req, self.restart)
                self.notice = "配置已应用，Coe D-Bus 已恢复"
                self.sync()
            elif action == "activate":
                self.idle_required()
                s = config.read_store()
                p = next((p for p in s["profiles"] if p["id"] == req.get("id")), None)
                if not p:
                    raise ValueError("语音识别配置不存在")
                self.backup = config.save_profile(
                    {"id": p["id"], "profile": p}, self.restart
                )
                self.notice = "模型已切换，后端已确认"
                self.sync()
            elif action == "preferences":
                self.idle_required()
                self.backup = config.update_preferences(req, self.restart)
                self.notice = "设置已应用"
                self.sync()
            elif action == "save_llm":
                self.idle_required()
                p = config.active_profile()
                self.backup = config.save_profile(
                    {
                        "id": p["id"],
                        "profile": p,
                        "llm": req["llm"],
                        "llm_key": req.get("llm_key", ""),
                        "delete_llm_key": req.get("delete_llm_key", False),
                    },
                    self.restart,
                )
                self.notice = "纠错设置已应用"
                self.sync()
            elif action == "check":
                p = config.validate_profile(req["profile"])
                saved = next(
                    (
                        p
                        for p in config.public_store()["profiles"]
                        if p["id"] == req.get("id")
                    ),
                    None,
                )
                key_present = bool(
                    req.get("api_key")
                    or (
                        saved and saved["key_present"] and not req.get("delete_api_key")
                    )
                )
                self.notice = "配置格式正确，未发送音频" + (
                    "；还需配置密钥"
                    if p["provider"] in ("openai", "doubao", "aliyun-asr")
                    and not key_present
                    else ""
                )
            elif action in ("duplicate", "delete", "default"):
                self.idle_required()
                config.profile_action(action, req["id"])
            elif action == "hotkey":
                self.idle_required()
                hotkey.save(
                    req["key"], COMMAND, self.owner, req.get("mode"), HOLD_COMMAND
                )
                self.hotkey_error = ""
                self.notice = "快捷键已更新"
            elif action == "service":
                self.idle_required()
                verb = req.get("verb")
                if verb not in ("start", "stop", "restart"):
                    raise ValueError("无效服务操作")
                if verb == "restart":
                    try:
                        self.restart()
                    except Exception:
                        self.backup = config.restore_good()
                        self.restart()
                        self.error = "启动失败，已恢复上一次可用配置（未删除任何密钥）"
                else:
                    p = subprocess.run(
                        ["systemctl", "--user", verb, "coe.service"],
                        capture_output=True,
                        timeout=15,
                    )
                    if p.returncode:
                        raise ValueError("服务操作失败，请检查诊断")
                self.sync()
            elif action == "test":
                self.idle_required()
                # A local WAV request is dispatched through the exact Go Provider, not a Python reimplementation.
                p = config.validate_profile(req["profile"])
                saved = next(
                    (
                        x
                        for x in config.read_store()["profiles"]
                        if x["id"] == req.get("id")
                    ),
                    None,
                )
                p["key_ref"] = (
                    saved.get("key_ref", "") if saved else "COE_ENHANCE_NO_KEY"
                )
                req = dict(profile=p, api_key=req.get("api_key", ""))
                probe = Path.home() / ".local/share/omarchy-coe-enhance/bin/coe-probe"
                p = subprocess.run(
                    [str(probe)],
                    input=json.dumps(req).encode(),
                    capture_output=True,
                    timeout=610,
                )
                if p.returncode:
                    raise ValueError(safe_error(p.stderr.decode(errors="replace")))
                self.notice = "识别测试成功（合成音；不代表真实语音准确率）"
            else:
                raise ValueError("未知操作")
        self.emit()
        return self.snapshot()

    def dispatch(self, req):
        try:
            result = self.handle(req)
            return {**result, "ok": True}
        except ValueError as e:
            # Only local validation strings may be shown. Never reflect arbitrary request fields.
            self.error = str(e)
            self.emit()
            return {"ok": False, "error": self.error}
        except Exception as e:
            self.error = safe_error(e)
            self.emit()
            return {"ok": False, "error": self.error}

    def worker(self):
        while self.alive:
            req = self.commands.get()
            if req is None:
                return
            result = self.dispatch(req)
            self.emit(
                {
                    **result,
                    "type": "response",
                    "request_id": req.get("request_id"),
                    "action": req.get("action"),
                }
            )

    def stdin(self):
        for line in sys.stdin:
            try:
                req = json.loads(line)
            except ValueError:
                continue
            # Panel state must be delivered even while Stop blocks on an ASR HTTP call.
            if req.get("action") == "panel":
                self.panel = req.get("open") is True
            else:
                self.commands.put(req)
        GLib.idle_add(self.shutdown)

    def socket_client(self, c):
        with c:
            try:
                c.settimeout(5)
                data = b""
                while b"\n" not in data and len(data) < 128000:
                    chunk = c.recv(8192)
                    if not chunk:
                        return
                    data += chunk
                req = json.loads(data.split(b"\n")[0])
                result = self.dispatch(req)
                c.sendall((json.dumps(result, ensure_ascii=False) + "\n").encode())
            except Exception:
                pass

    def socket_server(self):
        config.private_dir(RUNTIME)
        # Lifetime lock prevents two bridge owners, including multiple monitors.
        import fcntl

        self.fd = os.open(
            RUNTIME / "owner.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("bridge already running")
        # A Shell kill can race its cleanup helper. Once we own the lifetime
        # lock, cancel only a recording marked as held by the previous bridge.
        recover_held_recording()
        SOCKET.unlink(missing_ok=True)
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(SOCKET))
        os.chmod(SOCKET, 0o600)
        self.server.listen(8)
        config.atomic(RUNTIME / "owner.token", self.owner, 0o600)

        def serve():
            while self.alive:
                try:
                    c, _ = self.server.accept()
                    threading.Thread(
                        target=self.socket_client, args=(c,), daemon=True
                    ).start()
                except OSError:
                    break

        threading.Thread(target=serve, daemon=True).start()

    def window_events(self):
        # A focus change anywhere during a dictation forces clipboard-only delivery.
        while self.alive:
            try:
                sig = os.environ["HYPRLAND_INSTANCE_SIGNATURE"]
                s = socket.socket(socket.AF_UNIX)
                s.connect(
                    str(
                        Path(os.environ["XDG_RUNTIME_DIR"])
                        / "hypr"
                        / sig
                        / ".socket2.sock"
                    )
                )
                with s, s.makefile() as f:
                    for line in f:
                        if not self.alive:
                            return
                        if self.armed and line.startswith("activewindowv2>>"):
                            addr = "0x" + line.strip().split(">>", 1)[1].removeprefix(
                                "0x"
                            )
                            if addr != self.target.get("address"):
                                self.switched = True
            except Exception:
                time.sleep(2)

    def maintain(self):
        if not self.alive:
            return False
        self.osd.start()
        try:
            s = config.read_store()
            hotkey.install(
                s["hotkey"],
                COMMAND,
                self.owner,
                s.get("hotkey_mode", "toggle"),
                HOLD_COMMAND,
            )
            self.hotkey_error = ""
        except ValueError as e:
            self.hotkey_error = str(e)
        except Exception:
            self.hotkey_error = "Hyprland 快捷键绑定失败"
        self.emit()
        return self.alive

    def shutdown(self, *_):
        if not self.alive:
            return False
        if self.hold_id:
            try:
                self.iface().Cancel(timeout=3)
            except Exception:
                pass
            self.clear_hold()
        self.alive = False
        osd = getattr(self, "osd", None)
        if osd is not None:
            osd.close()
        self.armed = False
        try:
            hotkey.remove(self.owner)
        except Exception:
            pass
        try:
            self.server.close()
            SOCKET.unlink(missing_ok=True)
        except Exception:
            pass
        self.loop.quit()
        return False

    def run(self):
        self.socket_server()
        self.sync()
        self.maintain()
        for fn in (self.stdin, self.worker, self.window_events):
            threading.Thread(target=fn, daemon=True).start()
        GLib.timeout_add_seconds(10, self.maintain)
        for sig in (signal.SIGTERM, signal.SIGINT):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self.shutdown)
        self.loop.run()


def recover_held_recording(owner=None):
    if not HELD_FILE.exists():
        return
    try:
        held = json.loads(HELD_FILE.read_text())
        if owner is not None and held.get("owner") != owner:
            return
        bus = dbus.SessionBus()
        iface = dbus.Interface(bus.get_object(NAME, PATH, introspect=False), IFACE)
        state, session, _ = iface.Status(timeout=2)
        if str(state) == "recording" and str(session) == held.get("session"):
            iface.Cancel(timeout=3)
    except Exception:
        pass
    finally:
        # Never interfere with a newer owner's marker.
        try:
            if owner is None or json.loads(HELD_FILE.read_text()).get("owner") == owner:
                HELD_FILE.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def cleanup(owner):
    # Quickshell may kill a Process before its SIGTERM handler finishes. This
    # one-shot cleanup is tied to an instance token, so it cannot unbind a newly
    # loaded widget or unlink its socket during a reload.
    import fcntl

    hotkey.remove(owner)
    for _ in range(20):
        try:
            if (RUNTIME / "owner.token").read_text() != owner:
                return
            fd = os.open(RUNTIME / "owner.lock", os.O_RDWR | os.O_NOFOLLOW)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if (RUNTIME / "owner.token").read_text() == owner:
                    # A killed bridge may have been installing its binding
                    # when the early removal ran. Finalize after its fd closes.
                    hotkey.remove(owner)
                    recover_held_recording(owner)
                    SOCKET.unlink(missing_ok=True)
                    (RUNTIME / "owner.token").unlink(missing_ok=True)
                return
            finally:
                os.close(fd)
        except BlockingIOError:
            time.sleep(0.05)
        except FileNotFoundError:
            return


def request(req):
    c = socket.socket(socket.AF_UNIX)
    c.settimeout(660)
    try:
        c.connect(str(SOCKET))
        c.sendall((json.dumps(req) + "\n").encode())
        data = b""
        while b"\n" not in data:
            chunk = c.recv(65536)
            if not chunk:
                break
            data += chunk
        print(data.decode().strip())
    except OSError:
        print(json.dumps({"ok": False, "error": "插件未启用或桥接层未连接"}))
        return 1
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "watch":
        try:
            Bridge(sys.argv[2] if len(sys.argv) > 2 else str(os.getpid())).run()
        except Exception:
            print(
                json.dumps(
                    {
                        "type": "fatal",
                        "error": "桥接层启动失败，请检查依赖或是否重复加载",
                    }
                ),
                flush=True,
            )
            sys.exit(1)
    elif len(sys.argv) == 6 and sys.argv[1] == "hold":
        sys.exit(
            request(
                {
                    "action": "hold",
                    "owner": sys.argv[2],
                    "gesture": sys.argv[3] + ":" + sys.argv[5],
                    "event": sys.argv[4],
                }
            )
        )
    elif len(sys.argv) > 2 and sys.argv[1] == "cleanup":
        cleanup(sys.argv[2])
    else:
        req = (
            json.load(sys.stdin)
            if len(sys.argv) > 1 and sys.argv[1] == "json"
            else {"action": sys.argv[2] if len(sys.argv) > 2 else "get"}
        )
        sys.exit(request(req))
