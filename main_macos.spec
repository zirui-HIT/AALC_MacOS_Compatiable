# macOS arm64 directory bundle; build and writable runtime remain in the workspace.
import json
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

project_root = Path(SPECPATH)
launch_config = project_root / "build/native-launch.json"
launch_config.parent.mkdir(parents=True, exist_ok=True)
launch_config.write_text(json.dumps({"data_root": str(project_root / ".runtime")}))
datas = collect_data_files("rapidocr")
datas.append((str(project_root / "pyproject.toml"), "."))
datas.append((str(launch_config), "assets/config"))
for directory in ("assets", "i18n"):
    for path in (project_root / directory).rglob("*"):
        if path.is_file() and "minitouch" not in path.parts and path.suffix.lower() not in {".exe", ".dll", ".bat", ".pyc", ".qm"}:
            datas.append((str(path), str(path.parent.relative_to(project_root))))

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    datas=datas,
    binaries=[],
    hiddenimports=["pynput.keyboard._darwin", "pynput.mouse._darwin", "Quartz", "AppKit", "Foundation", "Vision"],
    excludes=["PySide6", "PyQt6", "shiboken6", "qfluentwidgets", "qframelesswindow", "tkinter", "FixTk", "win32api", "win32con", "win32gui", "win32process", "win32ui", "pywintypes", "pyuac", "windows_toasts"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="AALC", console=False,
    debug=False, strip=False, upx=False, target_arch="arm64", codesign_identity=None,
    argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AALC", strip=False, upx=False)
app = BUNDLE(
    coll, name="AALC.app", bundle_identifier="io.aalc.PlayCover",
    icon=str(project_root / "assets/logo/aalc.icns"),
    info_plist={"CFBundleDisplayName": "AALC", "NSHighResolutionCapable": True,
                "NSPrincipalClass": "NSApplication",
                "NSInputMonitoringUsageDescription": "Optional global pause and stop hotkeys."},
)
