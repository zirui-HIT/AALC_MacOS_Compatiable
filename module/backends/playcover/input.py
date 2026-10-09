"""Touch-only input. A gesture uses one geometry snapshot and one contact."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from module.automation.input_handlers import AbstractInput
from module.logger import log
from module.my_error.my_error import userStopError

from .geometry import Geometry
from .transport import PlayCoverTransport


@dataclass(frozen=True)
class GestureTiming:
    click_hold: float = 0.05
    sample_interval: float = 0.015
    drag_hold: float = 0.1
    repeat_interval: float = 0.1


class PlayCoverInput(AbstractInput):
    def __init__(self, transport: PlayCoverTransport, geometry: Callable[[], Geometry], cancel: threading.Event, timing: GestureTiming | None = None):
        super().__init__()
        self.transport, self._geometry, self.cancel = transport, geometry, cancel
        self.timing = timing or GestureTiming()
        self._gesture_lock = threading.RLock()
        self._local = threading.local()
        self.active_contacts: dict[int, tuple[int, int]] = {}
        self.safe_blank_point: tuple[float, float] | None = None

    @contextmanager
    def geometry_context(self, geometry: Geometry) -> Iterator[None]:
        previous = getattr(self._local, "geometry", None)
        self._local.geometry = geometry
        try:
            yield
        finally:
            self._local.geometry = previous

    def _current_geometry(self) -> Geometry:
        return getattr(self._local, "geometry", None) or self._geometry()

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise userStopError("PlayCover task stopped")

    def wait_pause(self) -> None:
        while self.is_pause:
            self.check_cancel()
            self.cancel.wait(0.05)
            self.restore_time = time.time()
        self.check_cancel()

    def _wait(self, seconds: float) -> None:
        if self.cancel.wait(max(0.0, seconds)):
            self.check_cancel()

    def _touch(self, phase: int, point: tuple[int, int], contact: int = 0) -> None:
        if phase == 0:
            # Record before send: a send failure may have reached the game.
            self.active_contacts[contact] = point
        elif contact in self.active_contacts:
            self.active_contacts[contact] = point
        self.transport.touch(phase, *point, contact)
        if phase == 3:
            self.active_contacts.pop(contact, None)

    def release_contacts(self) -> None:
        with self._gesture_lock:
            for contact, point in list(self.active_contacts.items()):
                self._touch(3, point, contact)

    @contextmanager
    def _gesture(self, start: tuple[float, float]) -> Iterator[Geometry]:
        with self._gesture_lock:
            self.wait_pause()
            geometry = self._current_geometry()
            try:
                self._touch(0, geometry.point(*start))
                yield geometry
            finally:
                if 0 in self.active_contacts and self.transport.connected:
                    try:
                        self._touch(3, self.active_contacts[0])
                    except OSError as exc:
                        log.warning(f"Touch release failed; retained for same-process reconnect: {exc}")

    def mouse_click(self, x, y, times=1, move_back=False) -> bool:
        for index in range(times):
            with self._gesture((x, y)):
                self._wait(self.timing.click_hold)
            if index + 1 < times:
                self._wait(self.timing.repeat_interval)
        return True

    def mouse_click_blank(self, coordinate=(1, 1), times=1, move_back=False) -> bool:
        if coordinate == (1, 1):
            if self.safe_blank_point is None:
                raise NotImplementedError("This iOS page has no calibrated safe blank-click position")
            coordinate = self.safe_blank_point
        return self.mouse_click(*coordinate, times=times)

    def _segment(self, geometry: Geometry, start, end, duration: float) -> None:
        if duration < 0:
            raise ValueError("Gesture duration cannot be negative")
        steps = max(1, round(duration / self.timing.sample_interval))
        for step in range(1, steps + 1):
            self.check_cancel()
            x = start[0] + (end[0] - start[0]) * step / steps
            y = start[1] + (end[1] - start[1]) * step / steps
            self._touch(1, geometry.point(x, y))
            self._wait(duration / steps)

    def mouse_drag(self, x, y, drag_time=0.1, dx=0, dy=0, move_back=True) -> None:
        with self._gesture((x, y)) as geometry:
            self._segment(geometry, (x, y), (x + dx, y + dy), drag_time)
            self._wait(self.timing.drag_hold)

    def mouse_drag_link(self, position: list, drag_time=0.1, move_back=False) -> None:
        if len(position) < 2:
            raise ValueError("A linked drag needs at least two points")
        with self._gesture(position[0]) as geometry:
            for start, end in zip(position, position[1:]):
                self._segment(geometry, start, end, drag_time)

    def mouse_swipe_for_scroll(self, x, y, duration=0.3, dx=0, dy=0, move_back=True) -> None:
        with self._gesture((x, y)) as geometry:
            # Escape the long-press region promptly, then finish without endpoint hold.
            escape = (x + dx * 0.25, y + dy * 0.25)
            self._segment(geometry, (x, y), escape, min(duration, 0.03))
            self._segment(geometry, escape, (x + dx, y + dy), max(0, duration - 0.03))

    def mouse_swipe_for_team_scroll(self, x, y, duration=0.3, dx=0, dy=0, move_back=True) -> None:
        self.mouse_swipe_for_scroll(x, y, duration, dx, dy, move_back)

    def mouse_drag_down(self, x, y, reverse=1, move_back=True) -> None:
        self.mouse_drag(x, y, dx=0, dy=360 * self._current_geometry().logical_size[1] / 1080 * reverse, move_back=move_back)

    def mouse_to_blank(self, coordinate=(1, 1), move_back=False) -> None:
        self.check_cancel()  # Touch input has no hovering cursor.

    def mouse_scroll(self, direction: int = -3) -> bool:
        raise NotImplementedError("PlayCover map zoom has not been validated; wheel input is unavailable")

    def key_press(self, key: str) -> None:
        raise NotImplementedError(f"iOS native keys are unavailable ({key}); use GameActions")

    def input_text(self, text: str) -> None:
        raise NotImplementedError("MaaTools v4 has no text-input command; disable team-code import")
