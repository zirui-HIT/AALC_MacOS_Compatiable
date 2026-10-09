import argparse
import tempfile
import unittest
from pathlib import Path

from tests.playcover.fake_server import FakeServer
from tools.playcover_probe import PROJECT_ROOT, run


class ProbeTests(unittest.TestCase):
    def test_default_probe_is_read_only_and_records_png(self):
        temp_root = PROJECT_ROOT / ".runtime/tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as directory, FakeServer() as server:
            args = argparse.Namespace(output=directory, host="127.0.0.1", port=server.port, timeout=1, expect_bundle_id="", samples=3, method="bgr", tap_native=None, drag_native=None)
            result = run(args)
            self.assertFalse(result["errors"])
            self.assertEqual(len(result["samples"]), 3)
            self.assertTrue((Path(directory) / "diagnostics.json").exists())
            self.assertTrue((Path(directory) / "screenshot.png").read_bytes().startswith(b"\x89PNG"))
            self.assertFalse(any(b"TUCH" in packet or b"TERM" in packet for packet in server.requests))
