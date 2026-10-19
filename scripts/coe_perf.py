"""Opt-in metadata only, shared CLOCK_MONOTONIC with Go; 10 MiB hard cap."""

import json
import os
import stat
import threading
import time

_lock = threading.Lock()


def mark(session, event, **fields):
    path = os.environ.get("COE_PERF_TRACE")
    if not path:
        # Explicit manual diagnostic mode can enable the already-running bridge.
        marker = os.path.join(
            os.environ.get("XDG_RUNTIME_DIR", "/run/user/" + str(os.getuid())),
            "coe-enhance/perf.enabled",
        )
        try:
            fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd) as f:
                st = os.fstat(f.fileno())
                if (
                    st.st_uid != os.getuid()
                    or not stat.S_ISREG(st.st_mode)
                    or stat.S_IMODE(st.st_mode) != 0o600
                ):
                    return
                path = f.read(4096).strip()
        except OSError:
            return
    # No strings derived from API responses, text or URL accepted as extra fields.
    if any(not isinstance(v, (int, float, bool)) for v in fields.values()):
        return
    row = dict(
        component="bridge",
        session_id=session,
        event=event,
        monotonic_ns=time.monotonic_ns(),
        **fields,
    )
    encoded = (json.dumps(row) + "\n").encode()
    try:
        with _lock:
            fd = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
            )
            try:
                st = os.fstat(fd)
                if (
                    st.st_uid == os.getuid()
                    and stat.S_ISREG(st.st_mode)
                    and stat.S_IMODE(st.st_mode) == 0o600
                    and st.st_nlink == 1
                    and st.st_size + len(encoded) <= 10 * 1024 * 1024
                ):
                    os.write(fd, encoded)
            finally:
                os.close(fd)
    except OSError:
        pass  # Diagnostics can never break recording/output.
