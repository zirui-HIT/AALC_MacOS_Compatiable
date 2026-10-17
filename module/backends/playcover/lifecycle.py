"""Application identity and bounded lifecycle operations, without shell strings."""

from __future__ import annotations

import plistlib
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppIdentity:
    path: Path
    bundle_id: str
    executable: Path


def read_app_identity(app_path: str | Path, bundle_id: str = "") -> AppIdentity:
    path = Path(app_path).expanduser().resolve()
    if not path.exists() and bundle_id:
        from AppKit import NSWorkspace

        url = NSWorkspace.sharedWorkspace().URLForApplicationWithBundleIdentifier_(bundle_id)
        if url is not None:
            path = Path(str(url.path())).resolve()
    if not path.is_dir() or path.suffix != ".app":
        raise ValueError("Select an installed game .app")
    info_path = path / "Contents/Info.plist"
    mac_bundle = info_path.exists()
    if not mac_bundle:
        info_path = path / "Info.plist"
    with info_path.open("rb") as file:
        info = plistlib.load(file)
    bundle_id, executable_name = info.get("CFBundleIdentifier"), info.get("CFBundleExecutable")
    if not isinstance(bundle_id, str) or not bundle_id or not isinstance(executable_name, str):
        raise ValueError("The selected app has no valid bundle identity/executable")
    executable = (path / ("Contents/MacOS" if mac_bundle else "") / executable_name).resolve()
    if not executable.is_relative_to(path) or not executable.is_file():
        raise ValueError("Invalid game executable in Info.plist")
    return AppIdentity(path, bundle_id, executable)


class PlayCoverLifecycle:
    def __init__(self, app_path: str = "", bundle_id: str = ""):
        self.identity = read_app_identity(app_path, bundle_id) if app_path else None
        if self.identity and bundle_id and self.identity.bundle_id != bundle_id:
            raise ValueError("Configured Bundle ID does not match the selected app")
        self.bundle_id = self.identity.bundle_id if self.identity else bundle_id

    def start(self) -> None:
        if self.identity is None:
            if not self.bundle_id:
                raise ValueError("Choose the installed game .app for automatic startup")
            from AppKit import NSWorkspace

            url = NSWorkspace.sharedWorkspace().URLForApplicationWithBundleIdentifier_(self.bundle_id)
            if url is None:
                raise ValueError("Cannot resolve the configured game Bundle ID; choose its installed .app")
            identity = read_app_identity(str(url.path()))
            if identity.bundle_id != self.bundle_id:
                raise ValueError("Resolved game .app does not match the configured Bundle ID")
            self.identity = identity
        subprocess.run(["/usr/bin/open", "-a", str(self.identity.path)], check=True, capture_output=True)

    def process(self):
        if self.identity is None:
            return None
        import psutil

        for process in psutil.process_iter(["exe"]):
            try:
                if process.info["exe"] and Path(process.info["exe"]).resolve() == self.identity.executable:
                    return process
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    def stop_verified_process(self, *, terminate: bool = True) -> None:
        import psutil

        process = self.process()
        if process is None:
            return
        try:
            # Recheck the executable immediately before termination (PID reuse).
            if Path(process.exe()).resolve() != self.identity.executable:
                raise RuntimeError("Game process identity changed")
            if terminate:
                process.terminate()
            # MaaTools TERM can take slightly over 5s to finish on PlayCover.
            process.wait(timeout=10)
        except psutil.NoSuchProcess:
            return  # TERM may finish between process enumeration and verification.
        except psutil.TimeoutExpired:
            raise TimeoutError("Verified game process did not exit; no forced kill performed") from None
