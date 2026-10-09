"""OCR helpers for English iOS pages, always using logical screenshot coordinates."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from module.ocr import ocr


@dataclass(frozen=True)
class TextHit:
    text: str
    point: tuple[int, int]


def normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def text_hits(automation, box: tuple[int, int, int, int]) -> list[TextHit]:
    result = ocr.run(automation.screenshot.crop(box))
    if result.boxes is None:
        return []
    return [TextHit(text, (round(points[:, 0].mean() + box[0]), round(points[:, 1].mean() + box[1])))
            for text, points in zip(result.txts or (), result.boxes, strict=True)]


def label_point(automation, label: str, box: tuple[int, int, int, int]) -> tuple[int, int] | None:
    target = normalized(label)
    return next((hit.point for hit in text_hits(automation, box) if normalized(hit.text) == target), None)


def click_label(automation, label: str, box: tuple[int, int, int, int]) -> bool:
    point = label_point(automation, label, box)
    if point is None:
        return False
    automation.mouse_click(*point)
    return True


def wait_until(automation, condition: Callable[[], bool], description: str, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.2)
        automation.take_screenshot()
        if condition():
            return
    raise RuntimeError(f"iOS page transition unconfirmed: {description}")
