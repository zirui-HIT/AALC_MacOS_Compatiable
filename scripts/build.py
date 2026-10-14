"""Build the native macOS bundle; installation is an explicit local option."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]


def ensure_bundle_stopped(bundle):
    """Lazy PYZ imports reopen the executable using the running app's old offsets."""
    executable = (bundle / 'Contents/MacOS/AALC').resolve()
    running = []
    for process in psutil.process_iter(['pid', 'exe', 'cmdline']):
        paths = [process.info['exe'], *(process.info['cmdline'] or [])[:1]]
        if any(path and Path(path).resolve() == executable for path in paths):
            running.append(str(process.info['pid']))
    if running:
        raise SystemExit(f'Quit AALC (PIDs {", ".join(running)}) before replacing {bundle}. '
                         'Updating a running bundle breaks subsequent task imports.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--install', action='store_true')
    arguments = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('The AppKit frontend requires macOS')
    ensure_bundle_stopped(ROOT / 'dist/AALC.app')
    env = {**os.environ, 'PYINSTALLER_CONFIG_DIR': str(ROOT / '.runtime/cache/pyinstaller'), 'TMPDIR': str(ROOT / '.runtime/tmp')}
    subprocess.run([sys.executable, '-m', 'PyInstaller', str(ROOT / 'main_macos.spec'), '--clean', '--noconfirm'], cwd=ROOT, env=env, check=True)
    bundle = ROOT / 'dist/AALC.app'
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    if arguments.install:
        destination = Path('/Applications/AALC.app')
        staged = Path('/Applications/.AALC-install.app')
        backup = ROOT / '.runtime/app-backups/AALC-before-native.app'
        if destination.exists() and not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['/usr/bin/ditto', str(destination), str(backup)], check=True)
        import shutil
        import uuid

        if staged.exists():
            shutil.rmtree(staged)
        subprocess.run(['/usr/bin/ditto', str(bundle), str(staged)], check=True)
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(staged)], check=True)
        ensure_bundle_stopped(destination)
        previous = destination.with_name('.AALC-previous-' + uuid.uuid4().hex + '.app')
        if destination.exists():
            destination.rename(previous)
        try:
            staged.rename(destination)
        except OSError:
            if previous.exists():
                previous.rename(destination)
            raise
        if previous.exists():
            shutil.rmtree(previous)


if __name__ == '__main__':
    main()
