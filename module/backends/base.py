"""Minimal session and captured-frame contracts shared with business code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from PIL.Image import Image

    from module.automation.input_handlers import AbstractInput
    from module.backends.playcover.geometry import Geometry


@dataclass(frozen=True)
class BackendCapabilities:
    touch: bool = False
    text_input: bool = False
    native_keys: bool = False
    zoom: bool = False
    lifecycle: bool = False


@dataclass(frozen=True)
class CapturedFrame:
    image: Image
    raw_size: tuple[int, int]
    touch_size: tuple[int, int]
    content_rect: tuple[int, int, int, int]
    logical_size: tuple[int, int]
    geometry_version: int
    captured_at: float
    geometry: Geometry


class BackendSession(Protocol):
    input: AbstractInput
    capabilities: BackendCapabilities

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def capture(self) -> CapturedFrame: ...
    def start_game(self) -> None: ...
    def stop_game(self) -> None: ...
    def is_game_running(self) -> bool: ...
