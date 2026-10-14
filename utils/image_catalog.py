"""Keep native image rule catalogs aligned with bundled and writable resources."""

import json
import os
import sys
from functools import lru_cache
from pathlib import Path

from utils.runtime_paths import data_path, resource_path


@lru_cache(maxsize=1)
def _read_synced_image_tree(state_path: Path, modified: int, size: int) -> bool:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    manifest_id = state.get("last_applied_manifest_id") if isinstance(state, dict) else None
    return isinstance(manifest_id, str) and bool(manifest_id)


def synced_image_tree() -> bool:
    """A successful full sync makes the writable tree authoritative on macOS."""
    if sys.platform != "darwin":
        return False
    state_path = data_path("config/image_resource_state.json")
    try:
        stat = state_path.stat()
    except OSError:
        return False
    return _read_synced_image_tree(state_path, stat.st_mtime_ns, stat.st_size)


def refresh_shop_image_catalogs():
    catalog = sys.modules.get("tasks.mirror")
    if sys.platform != "darwin" or catalog is None:
        return
    for name in ("must_purchase", "must_be_abandoned", "fusion_result"):
        images = getattr(catalog, name, None)
        if images is None:
            continue
        prefix = f"mirror/shop/{name}"
        paths = (resource_path(f"assets/images/default/share/{prefix}"),
                 data_path(f"resources/images/default/share/{prefix}"))
        if synced_image_tree():
            paths = paths[1:]
        updated = []
        for path in paths:
            for folder, _, files in os.walk(path):
                for file in files:
                    relative = (Path(folder) / file).relative_to(path).as_posix()
                    target = f"{prefix}/{relative}"
                    if target not in updated:
                        updated.append(target)
        images[:] = updated
