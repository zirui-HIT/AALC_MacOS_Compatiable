"""Pure backend config migration; no Config singleton or platform imports."""

from __future__ import annotations

import sys
from typing import Any

from .playcover.transport import validate_endpoint

BACKENDS = frozenset({"windows", "android_mumu", "android_adb", "playcover"})


def migrate_backend(values: dict[str, Any], platform: str | None = None) -> dict[str, Any]:
    result = dict(values)
    platform = platform or sys.platform
    backend = result.get("backend")
    if not backend:
        if platform == "darwin":
            backend = "playcover"
        elif result.get("simulator", False):
            backend = "android_mumu" if result.get("simulator_type", 0) == 0 else "android_adb"
        else:
            backend = "windows"
    if backend not in BACKENDS:
        raise ValueError(f"Unknown automation backend: {backend}")
    result["backend"] = backend
    if backend == "playcover":
        result["game_profile"] = "ios_zh_cn" if result.get("game_profile") == "ios_zh_cn" else "ios_en"
        result["set_win_size"] = 1080
        validate_endpoint(result.get("playcover_host", "127.0.0.1"), result.get("playcover_port", 1717))
        if result.get("playcover_capture_method", "bgr") not in {"bgr", "scrn"}:
            raise ValueError("PlayCover capture must be bgr or scrn")
        if (result.get("playcover_logical_width", 1920), result.get("playcover_logical_height", 1080)) != (1920, 1080):
            raise ValueError("First release requires logical resolution 1920x1080")
    # Legacy implementations still read these fields internally.
    result["simulator"] = backend in {"android_mumu", "android_adb"}
    if backend == "android_mumu":
        result["simulator_type"] = 0
    elif backend == "android_adb" and result.get("simulator_type", 0) == 0:
        result["simulator_type"] = 10
    return result
