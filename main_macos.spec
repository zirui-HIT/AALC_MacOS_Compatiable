# macOS arm64 directory bundle; user data is located at runtime.
import json
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

project_root = Path(SPECPATH)
sys.path.insert(0, str(project_root))
from utils.build_provenance import build_provenance

build_config = project_root / "build/native-build.json"
build_config.parent.mkdir(parents=True, exist_ok=True)
build_config.write_text(json.dumps(build_provenance(project_root), ensure_ascii=True))
datas = collect_data_files("rapidocr")
datas.append((str(project_root / "pyproject.toml"), "."))
datas.append((str(build_config), "assets/config"))
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
