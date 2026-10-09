"""Application zoom, separate from the game's capture/recognition resolution."""

import sys


def readable_ui_scale(configured_scale: int, platform: str | None = None) -> int:
    """Migrate undersized Mac UI settings; Qt handles Retina pixel density itself."""
    platform = sys.platform if platform is None else platform
    if platform == "darwin" and configured_scale < 100:
        return 125
    return configured_scale
