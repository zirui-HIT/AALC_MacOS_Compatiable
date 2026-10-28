"""Read the current shop's numeric prices without selecting a gift or service."""

import math
import re
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image

from module.logger import log
from module.ocr import ocr
from utils.image_utils import ImageUtils


@dataclass(frozen=True)
class ShopItem:
    row: int
    column: int
    price: int
    position: tuple[float, float]


@lru_cache(maxsize=4)
def _cached_service_template(height, path, mtime_ns, size):
    """Cache only successfully read patterns, isolated by source and revision."""
    with Image.open(path) as source:
        image = np.asarray(source.convert("L"))
    pattern = ImageUtils.crop(image, ImageUtils.get_bbox(image))
    scale = height / 1440
    return cv2.resize(pattern, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def _marker_template(height, target):
    for profile in ImageUtils.existing_image_paths(target):
        try:
            path = ImageUtils.resolve_path(profile, target).resolve()
            status = path.stat()
        except OSError:
            continue
        try:
            return _cached_service_template(height, str(path), status.st_mtime_ns, status.st_size)
        except (OSError, ValueError, IndexError, cv2.error):
            return None  # Failed reads raise out of the cache and can recover next frame.
    return None


def _service_template(height):
    return _marker_template(height, "mirror/shop/skill_replacement_assets.png")


def _purchased_template(height):
    return _marker_template(height, "mirror/shop/ID_skill_replace_0_purchased_assets.png")


def _price_line(pixels, center_y, scale):
    """Use bright strokes to locate the price, preserving grayscale for OCR."""
    mask = pixels > 100
    rows = np.flatnonzero(mask.any(axis=1))
    runs = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
    runs = [run for run in runs if len(run) >= max(2, round(12 * scale))]
    if not runs:
        return None
    run = min(runs, key=lambda group: abs((group[0] + group[-1]) / 2 - center_y))
    top, bottom = int(run[0]), int(run[-1]) + 1
    columns = np.flatnonzero(mask[top:bottom].any(axis=0))
    # A cropped coin rim can touch the left edge. Separate it only across a
    # wide blank gap, retaining the smaller gaps between the numeric glyphs.
    gaps = np.flatnonzero(np.diff(columns) > 6 * scale)
    if columns[0] == 0 and gaps.size:
        columns = columns[gaps[0] + 1:]
    tight = pixels[top:bottom, columns[0]:columns[-1] + 1]
    padding = max(1, round(scale))
    padded = cv2.copyMakeBorder(tight, padding, padding, padding, padding, cv2.BORDER_CONSTANT, value=0)
    return cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)


def current_page_items(image: Image.Image, coins: tuple) -> list[ShopItem]:
    """Return priced gifts from one frame; row/column indices start at zero.

    ``coins`` is the balance-coin anchor matched on this exact frame. Price rows
    use one batch recognition call, avoiding full-frame text detection. Service
    slots are identified by their question-mark price, without fixed positions.
    """
    if image is None or not coins or len(coins) != 2:
        return []
    if not all(math.isfinite(float(value)) for value in coins):
        return []
    scale = image.height / 1440
    first_x = float(coins[0]) + 150 * scale
    first_y = float(coins[1]) + 360 * scale
    step = 300 * scale
    left, right = round(first_x - step / 2), round(first_x + 3.5 * step)
    bands = [(round(first_y + row * step - 40 * scale),
              round(first_y + row * step + 40 * scale)) for row in range(2)]
    if left < 0 or right > image.width or bands[0][0] < 0 or bands[1][1] > image.height:
        return []
    template = _service_template(image.height)
    if template is None:
        return []  # An unavailable service guard must not turn services into gifts.
    purchased_template = _purchased_template(image.height)

    price_bounds = [(round(first_x + column * step - 20 * scale),
                     round(first_x + column * step + 110 * scale)) for column in range(4)]
    source = image.convert("L")
    slots, crops = [], []
    for row, (top, bottom) in enumerate(bands):
        pixels = np.asarray(source.crop((left, top, right, bottom)))
        for column in range(4):
            center = first_x + column * step - left
            if purchased_template is not None:
                x = first_x + column * step
                y = first_y + row * step - 180 * scale
                header = np.asarray(source.crop((round(x - 130 * scale), round(y - 35 * scale),
                                                 round(x + 130 * scale), round(y + 35 * scale))))
                if (header.shape[0] >= purchased_template.shape[0]
                        and header.shape[1] >= purchased_template.shape[1]
                        and cv2.minMaxLoc(cv2.matchTemplate(
                            header, purchased_template, cv2.TM_CCOEFF_NORMED))[1] >= 0.8):
                    continue
            cell = pixels[:, max(0, round(center - 90 * scale)):round(center + 90 * scale)]
            if cell.shape[0] >= template.shape[0] and cell.shape[1] >= template.shape[1]:
                similarity = cv2.minMaxLoc(cv2.matchTemplate(cell, template, cv2.TM_CCOEFF_NORMED))[1]
                if similarity >= 0.85:
                    continue
            start, end = price_bounds[column]
            line = _price_line(np.asarray(source.crop((start, top, end, bottom))),
                               first_y + row * step - top, scale)
            if line is not None:
                slots.append((row, column))
                crops.append(line)
    if not crops:
        return []
    try:
        with ocr._inference_lock:
            result = ocr.engine.get_rec_res(crops)
    except Exception:
        log.warning("商店价格识别失败", exc_info=True)
        return []
    texts = result.txts if result is not None and result.txts is not None else ()
    scores = result.scores if result is not None and result.scores is not None else ()
    if len(texts) != len(slots) or len(scores) != len(slots):
        return []
    items = []
    for (row, column), text, score in zip(slots, texts, scores):
        if not re.fullmatch(r"[0-9]+", str(text).strip()):
            continue
        try:
            confidence = float(score)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(confidence) or not 0.8 <= confidence <= 1:
            continue
        items.append(ShopItem(row, column, int(str(text).strip()),
                              (first_x + column * step, first_y + row * step - 100 * scale)))
    return items
