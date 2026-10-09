from __future__ import annotations

import threading
import time
from typing import Any

from module.backends.base import BackendCapabilities, CapturedFrame

from .capture import normalize_capture
from .geometry import Geometry
from .input import PlayCoverInput
from .lifecycle import PlayCoverLifecycle
from .transport import CaptureUnavailable, PlayCoverTransport, ProtocolError


class PlayCoverSession:
    capabilities = BackendCapabilities(touch=True, lifecycle=True)

    def __init__(self, settings: dict[str, Any]):
        self.transport = PlayCoverTransport(settings["playcover_host"], settings["playcover_port"])
        self.lifecycle = PlayCoverLifecycle(settings["playcover_app_path"], settings["playcover_bundle_id"])
        self.capture_method = settings["playcover_capture_method"]
        self.cancel = threading.Event()
        self._geometry: Geometry | None = None
        self._capture_lock = threading.RLock()
        self._pid: int | None = None
        self.input = PlayCoverInput(self.transport, self.geometry, self.cancel)

    def geometry(self) -> Geometry:
        if self._geometry is None:
            raise RuntimeError("Take a valid screenshot before touch input")
        return self._geometry

    def connect(self) -> None:
        if not self.lifecycle.bundle_id:
            raise ValueError("Choose a game .app or set its verified Bundle ID before connecting")
        previous_pid = self._pid
        process = self.lifecycle.process()
        self._pid = process.pid if process else None
        self.transport.connect(self.lifecycle.bundle_id)
        if previous_pid is not None and previous_pid != self._pid and self._geometry is not None:
            # A replacement process invalidates recognition, even at the same size.
            from dataclasses import replace

            self._geometry = replace(self._geometry, version=self._geometry.version + 1)
        if previous_pid is not None and previous_pid == self._pid:
            self.input.release_contacts()
        elif self.input.active_contacts:
            if previous_pid is None or self._pid is None:
                self.transport.disconnect()
                raise RuntimeError("Cannot verify the process after a lost touch; select the game .app before recovery")
            self.input.active_contacts.clear()  # A new process has no old touch contexts.

    def disconnect(self) -> None:
        self.transport.disconnect()

    def capture(self) -> CapturedFrame:
        self.input.check_cancel()
        with self._capture_lock:
            if not self.transport.connected:
                self.connect()  # Only read-only connection/query operations are repeated.
            deadline = time.monotonic() + 5
            while True:
                self.input.check_cancel()
                touch_size = self.transport.query_size()
                try:
                    raw = self.transport.capture(self.capture_method)
                    break
                except CaptureUnavailable:
                    if time.monotonic() >= deadline:
                        raise
                    self.cancel.wait(0.1)  # Complete empty responses permit another read-only capture.
            raw_size = (raw.width, raw.height)
            crop = (0, 0, *raw_size)  # No unverified automatic black-bar cropping.
            previous = self._geometry
            changed = previous is None or (previous.raw_size, previous.touch_size, previous.content_rect) != (raw_size, touch_size, crop)
            version = (previous.version + 1 if previous else 1) if changed else previous.version
            geometry = Geometry(raw_size, touch_size, crop, version=version)
            self._geometry = geometry
            return normalize_capture(raw, geometry)

    def start_game(self) -> None:
        self.input.check_cancel()
        if self.lifecycle.identity is not None and self.lifecycle.process() is None:
            self.lifecycle.start()
        deadline = time.monotonic() + 30
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            self.input.check_cancel()
            try:
                self.connect()
                self.capture()
                return
            except ProtocolError:
                raise  # Wrong identity/protocol is not a service-startup delay.
            except (OSError, CaptureUnavailable) as exc:
                last_error = exc
                self.disconnect()
                self.cancel.wait(0.5)
        raise ConnectionError(f"Game MaaTools service/capture not ready after 30s: {last_error}")

    def stop_game(self) -> None:
        if self.transport.connected and self.transport.bundle_id == self.lifecycle.bundle_id:
            self.input.release_contacts()
            self.transport.terminate()
        else:
            self.lifecycle.stop_verified_process()

    def is_game_running(self) -> bool:
        if self.lifecycle.identity:
            return self.lifecycle.process() is not None
        try:
            if not self.transport.connected:
                self.connect()
            return self.transport.query_bundle_id() == self.lifecycle.bundle_id
        except OSError:
            return False

    def request_stop(self) -> None:
        self.cancel.set()
