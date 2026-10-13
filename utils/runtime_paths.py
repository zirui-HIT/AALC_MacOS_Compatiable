"""Portable paths: all application writes stay inside the project workspace.

Import is read-only. The launcher initializes directories before heavy imports.
Frozen resources are read from _MEIPASS, writable data from beside the .app.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT)).resolve()


def application_root() -> Path:
    if not getattr(sys, "frozen", False):
        return SOURCE_ROOT
    executable = Path(sys.executable).resolve()
    for parent in executable.parents:
        if parent.suffix == ".app":
            checkout = parent.parent.parent
            if (checkout / "pyproject.toml").is_file() and (checkout / "main.py").is_file():
                return checkout  # A local dist/ build shares the source checkout's data.
            return parent.parent
    return executable.parent


APP_ROOT = application_root()
DATA_ROOT = Path(os.environ.get("AALC_DATA_ROOT", APP_ROOT / ".runtime")).expanduser().resolve()


def resource_path(path: str | Path) -> Path:
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Resource path must be relative to packaged resources")
    return RESOURCE_ROOT / relative


def data_path(path: str | Path) -> Path:
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Writable path must stay inside .runtime")
    return DATA_ROOT / relative


def prepare_runtime() -> None:
    for name in ("config", "logs", "cache", "tmp", "models", "resources/images", "templates"):
        data_path(name).mkdir(parents=True, exist_ok=True)
    # Third-party caches/temporary files must obey the same portable boundary.
    os.environ["TMPDIR"] = str(data_path("tmp"))
    os.environ["XDG_CACHE_HOME"] = str(data_path("cache"))
    os.environ["PYINSTALLER_CONFIG_DIR"] = str(data_path("cache/pyinstaller"))
