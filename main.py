"""Select the backend before importing the AppKit frontend."""
import json
import os
import sys


def main():
    os.environ.pop("SSLKEYLOGFILE", None)
    if getattr(sys, "frozen", False) and "AALC_DATA_ROOT" not in os.environ:
        from pathlib import Path
        settings = Path(sys._MEIPASS) / "assets/config/native-launch.json"
        if settings.is_file():
            os.environ["AALC_DATA_ROOT"] = json.loads(settings.read_text())["data_root"]
    from utils.runtime_paths import prepare_runtime
    prepare_runtime()
    if "--backend" in sys.argv:
        from backend_host.main import run
        return run()
    if "--ocr-smoke-test" in sys.argv:
        from PIL import Image, ImageDraw, ImageFont

        from module.logger.my_log import Logger
        from module.ocr import ocr
        from utils.runtime_paths import resource_path
        Logger()
        fixture = Image.new("RGB", (640, 120), "white")
        font = ImageFont.truetype(str(resource_path("assets/app/fonts/ChineseFont.ttf")), 48)
        ImageDraw.Draw(fixture).text((20, 20), "Win Rate", fill="black", font=font)
        result = ocr.run(fixture)
        if "winrate" not in "".join(result.txts or []).replace(" ", "").lower():
            raise RuntimeError("Offline OCR smoke failed")
        return 0
    from frontend_appkit.application import run
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
