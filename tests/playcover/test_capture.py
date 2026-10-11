import pytest
from PIL import Image

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


def test_content_crop_excludes_pixels_outside_game():
    image = Image.new("RGB", (80, 45), (255, 0, 0))
    image.paste((0, 0, 255), (8, 4, 72, 40))
    raw = RawCapture(80, 45, image.tobytes(), "RGB", 123.0)
    geometry = Geometry((80, 45), (80, 45), (8, 4, 64, 36), logical_size=(32, 18))
    frame = normalize_capture(raw, geometry)
    assert frame.image.size == (32, 18)
    assert frame.image.getextrema() == ((0, 0), (0, 0), (255, 255))
    assert frame.content_rect == geometry.content_rect
