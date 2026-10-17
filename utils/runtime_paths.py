"""Read-only bundle resources and user-specific macOS data directories."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT)).resolve()
BUNDLE_ID = "io.aalc.PlayCover"


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


def runtime_directories() -> dict[str, Path]:
    override = os.environ.get("AALC_DATA_ROOT")
    if override is not None:
        root = Path(override).expanduser()
        if not override or not root.is_absolute():
            raise ValueError("AALC_DATA_ROOT must be an absolute path")
        root = root.resolve()
    elif sys.platform == "darwin":
        from Foundation import (
            NSApplicationSupportDirectory,
            NSCachesDirectory,
            NSLibraryDirectory,
            NSPicturesDirectory,
            NSSearchPathForDirectoriesInDomains,
            NSTemporaryDirectory,
            NSUserDomainMask,
        )

        def directory(kind):
            return Path(NSSearchPathForDirectoriesInDomains(kind, NSUserDomainMask, True)[0])

        return {
            "data": directory(NSApplicationSupportDirectory) / BUNDLE_ID,
            "cache": directory(NSCachesDirectory) / BUNDLE_ID,
            "logs": directory(NSLibraryDirectory) / "Logs" / BUNDLE_ID,
            "tmp": Path(NSTemporaryDirectory()) / BUNDLE_ID,
            "screenshots": directory(NSPicturesDirectory) / "AALC",
        }
    else:
        root = APP_ROOT / ".runtime"
    return {"data": root, **{name: root / name for name in ("cache", "logs", "tmp", "screenshots")}}


DIRECTORIES = runtime_directories()
DATA_ROOT = DIRECTORIES["data"]


def resource_path(path: str | Path) -> Path:
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Resource path must be relative to packaged resources")
    return RESOURCE_ROOT / relative


def data_path(path: str | Path) -> Path:
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Writable path must stay inside application data directories")
    if relative.parts and relative.parts[0] in {"cache", "logs", "tmp", "screenshots"}:
        return DIRECTORIES[relative.parts[0]].joinpath(*relative.parts[1:])
    return DATA_ROOT / relative


def prepare_runtime() -> None:
    for name in ("config", "logs", "cache", "tmp", "models", "resources/images", "templates", "screenshots"):
        data_path(name).mkdir(parents=True, exist_ok=True)
    # Preserve the system temporary directory across frontend/backend launches.
    if "AALC_DATA_ROOT" in os.environ:
        os.environ["TMPDIR"] = str(data_path("tmp"))
    os.environ["XDG_CACHE_HOME"] = str(data_path("cache"))
    os.environ["PYINSTALLER_CONFIG_DIR"] = str(data_path("cache/pyinstaller"))
