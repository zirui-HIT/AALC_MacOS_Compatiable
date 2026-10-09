"""Read-only MaaTools diagnostics. Uses only the Python standard library."""

from __future__ import annotations

import argparse
import json
import math
import struct
import time
import zlib
from pathlib import Path

from module.backends.playcover.transport import CaptureUnavailable, PlayCoverTransport, RawCapture

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def save_png(frame: RawCapture, path: Path) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    pixels = frame.pixels
    channels = 3 if frame.mode == "BGR" else 4
    rows = bytearray()
    for y in range(frame.height):
        rows.append(0)
        for x in range(frame.width):
            offset = (y * frame.width + x) * channels
            color = pixels[offset:offset + 3]
            rows.extend(color[::-1] if frame.mode == "BGR" else color)
    header = struct.pack(">IIBBBBB", frame.width, frame.height, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def run(args: argparse.Namespace) -> dict:
    output = Path(args.output).resolve()
    if not output.is_relative_to(PROJECT_ROOT.parent):
        raise ValueError("Diagnostic output must stay inside the LimbusCompany workspace")
    output.mkdir(parents=True, exist_ok=True)
    transport = PlayCoverTransport(args.host, args.port, args.timeout)
    diagnostics: dict = {"protocol": None, "bundle_id": None, "method": args.method, "samples": [], "errors": []}
    try:
        transport.connect(args.expect_bundle_id)
        diagnostics.update(protocol=transport.version, bundle_id=transport.bundle_id, touch_size=transport.query_size())
        last = None
        for index in range(args.samples):
            started = time.monotonic()
            last = transport.capture(args.method)
            diagnostics["samples"].append({"index": index, "size": [last.width, last.height], "ms": (time.monotonic() - started) * 1000})
        if last is not None:
            save_png(last, output / "screenshot.png")
        # Explicit native touch diagnostics require an identity supplied by the operator.
        if args.tap_native or args.drag_native:
            if not args.expect_bundle_id:
                raise ValueError("Active touch diagnostics require --expect-bundle-id")
            width, height = diagnostics["touch_size"]
            points = args.tap_native or args.drag_native
            if any(not 0 <= value < (width if i % 2 == 0 else height) for i, value in enumerate(points)):
                raise ValueError("Native diagnostic coordinates are outside SIZE")
            x, y = points[:2]
            try:
                transport.touch(0, x, y)
                if args.drag_native:
                    for step in range(1, 21):
                        x = round(points[0] + (points[2] - points[0]) * step / 20)
                        y = round(points[1] + (points[3] - points[1]) * step / 20)
                        transport.touch(1, x, y)
                        time.sleep(0.015)
                else:
                    time.sleep(0.05)
            finally:
                if transport.connected:
                    transport.touch(3, x, y)
    except (OSError, CaptureUnavailable, ValueError) as exc:
        diagnostics["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        transport.disconnect()
        elapsed = sorted(sample["ms"] for sample in diagnostics["samples"])
        if elapsed:
            diagnostics.update(average_ms=sum(elapsed) / len(elapsed), p95_ms=elapsed[math.ceil(len(elapsed) * 0.95) - 1])
        (output / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
    return diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1717)
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--expect-bundle-id", default="")
    parser.add_argument("--method", choices=("bgr", "scrn"), default="bgr")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "artifacts/playcover-probe"))
    gestures = parser.add_mutually_exclusive_group()
    gestures.add_argument("--tap-native", type=int, nargs=2, metavar=("X", "Y"))
    gestures.add_argument("--drag-native", type=int, nargs=4, metavar=("X1", "Y1", "X2", "Y2"))
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    result = run(args)
    parser.exit(1 if result["errors"] else 0, json.dumps({key: value for key, value in result.items() if key != "samples"}, indent=2) + "\n")


if __name__ == "__main__":
    main()
