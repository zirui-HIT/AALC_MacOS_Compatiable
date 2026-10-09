"""Small macOS host services. No writes to global preferences or PlayCover."""

import atexit
import subprocess
import threading

_lock = threading.Lock()
_awake: subprocess.Popen | None = None
_depth = 0


def keep_awake(enable: bool) -> None:
    global _awake, _depth
    with _lock:
        if enable:
            if _depth == 0:
                _awake = subprocess.Popen(["/usr/bin/caffeinate", "-di"])
            _depth += 1
        else:
            _depth = max(0, _depth - 1)
            if _depth == 0 and _awake is not None:
                _awake.terminate()
                _awake.wait(timeout=2)
                _awake = None


def hotkeys_available() -> bool:
    from Quartz import CGPreflightListenEventAccess

    return bool(CGPreflightListenEventAccess())


def cleanup() -> None:
    global _depth
    with _lock:
        _depth = 1
    keep_awake(False)


atexit.register(cleanup)
