"""macOS libarchive tools for resource packages, without Windows executables."""

import subprocess
from pathlib import Path


def _run(arguments: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["/usr/bin/tar", *arguments], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8", check=True)


def create(source: Path, archive: Path) -> None:
    _run(["--format=7zip", "-cf", str(archive.resolve()), "."], cwd=source)


def members(archive: Path) -> list[Path]:
    return [Path(name) for name in _run(["-tf", str(archive.resolve())]).stdout.splitlines()]


def extract(archive: Path, destination: Path) -> None:
    _run(["-xf", str(archive.resolve()), "-C", str(destination.resolve()), "--no-same-owner"])
