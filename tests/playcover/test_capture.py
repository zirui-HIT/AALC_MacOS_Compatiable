import pytest

from module.backends.playcover.capture import normalize_capture
from module.backends.playcover.geometry import Geometry
from module.backends.playcover.transport import RawCapture


@pytest.mark.parametrize("mode,pixel", [("BGR", bytes([0, 0, 255])), ("RGBX", bytes([255, 0, 0, 19]))])
def test_raw_color_logical_size_and_gray(mode, pixel):
    raw = RawCapture(16, 9, pixel * 144, mode, 123.0)
    frame = normalize_capture(raw, Geometry((16, 9), (1920, 1080), (0, 0, 16, 9)))
    assert frame.image.mode == "RGB"
    assert frame.image.size == (1920, 1080)
    assert frame.image.getpixel((960, 540)) == (255, 0, 0)
    assert frame.image.convert("L").getpixel((960, 540)) == 76
    assert frame.captured_at == 123.0
