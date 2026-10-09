from PIL import Image

from module.backends.base import CapturedFrame

from .geometry import Geometry
from .transport import RawCapture


def normalize_capture(raw: RawCapture, geometry: Geometry) -> CapturedFrame:
    if (raw.width, raw.height) != geometry.raw_size:
        raise ValueError("Frame does not match its geometry snapshot")
    image = Image.frombytes("RGB", geometry.raw_size, raw.pixels, "raw", raw.mode)
    x, y, width, height = geometry.content_rect
    image = image.crop((x, y, x + width, y + height))
    if image.size != geometry.logical_size:
        scale, offset_x, offset_y = geometry.logical_transform()
        if abs(offset_x) < 1e-9 and abs(offset_y) < 1e-9:
            image = image.resize(geometry.logical_size, Image.Resampling.LANCZOS)
        else:
            image = image.transform(geometry.logical_size, Image.Transform.AFFINE,
                                    (1 / scale, 0, -offset_x / scale, 0, 1 / scale, -offset_y / scale),
                                    resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0))
    return CapturedFrame(image, geometry.raw_size, geometry.touch_size, geometry.content_rect, geometry.logical_size, geometry.version, raw.captured_at, geometry)
