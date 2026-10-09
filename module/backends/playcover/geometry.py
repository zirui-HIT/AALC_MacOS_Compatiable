"""Immutable frame-to-touch geometry. Desktop/Retina coordinates are irrelevant."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Geometry:
    raw_size: tuple[int, int]
    touch_size: tuple[int, int]
    content_rect: tuple[int, int, int, int]
    logical_size: tuple[int, int] = (1920, 1080)
    version: int = 1

    def __post_init__(self) -> None:
        wf, hf = self.raw_size
        wt, ht = self.touch_size
        x, y, width, height = self.content_rect
        wc, hc = self.logical_size
        if min(wf, hf, wt, ht, width, height, wc, hc) <= 0:
            raise ValueError("Geometry dimensions must be positive")
        if x < 0 or y < 0 or x + width > wf or y + height > hf:
            raise ValueError("Content crop lies outside the captured frame")
        # Window bounds and ScreenCaptureKit round independently to physical pixels.
        # Allow at most four pixels, then normalize with ONE scale and subpixel padding.
        rounding_limit = 4 if max(wf, hf) >= 1920 else 1
        if abs(width - height * wc / hc) > rounding_limit:
            raise ValueError("Game content must be landscape 16:9; adjust PlayCover display settings")
        if abs(wf - hf * wt / ht) > rounding_limit:
            raise ValueError("Capture and touch surface orientations/coverage do not match")

    def logical_transform(self) -> tuple[float, float, float]:
        _, _, width, height = self.content_rect
        wc, hc = self.logical_size
        scale = min(wc / width, hc / height)
        return scale, (wc - width * scale) / 2, (hc - height * scale) / 2

    def point(self, x: float, y: float) -> tuple[int, int]:
        wf, hf = self.raw_size
        wt, ht = self.touch_size
        cx, cy, _, _ = self.content_rect
        scale, offset_x, offset_y = self.logical_transform()
        xt = round((cx + (x - offset_x) / scale) * wt / wf)
        yt = round((cy + (y - offset_y) / scale) * ht / hf)
        return max(0, min(wt - 1, xt)), max(0, min(ht - 1, yt))

    def displacement(self, dx: float, dy: float) -> tuple[float, float]:
        wf, hf = self.raw_size
        wt, ht = self.touch_size
        scale, _, _ = self.logical_transform()
        return dx / scale * wt / wf, dy / scale * ht / hf
