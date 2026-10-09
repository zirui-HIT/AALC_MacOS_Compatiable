import struct
import unittest
from concurrent.futures import ThreadPoolExecutor

from module.backends.playcover.transport import CaptureUnavailable, PlayCoverTransport, ProtocolError
from tests.playcover.fake_server import FakeServer


class TransportTests(unittest.TestCase):
    def test_fragmented_queries_bgr_scrn_and_touch_without_ack(self):
        with FakeServer() as server:
            client = PlayCoverTransport(port=server.port)
            client.connect("company.test")
            self.assertEqual(client.version, 4)
            self.assertEqual(client.query_size(), (16, 9))
            self.assertEqual(client.capture().pixels[:3], bytes([0, 0, 255]))
            self.assertEqual(client.capture("scrn").pixels[:4], bytes([255, 0, 0, 0]))
            client.touch(0, 960, 540)
            self.assertEqual(client.query_version(), 4)
            self.assertIn(bytes.fromhex("00 0a 54 55 43 48 00 03 c0 02 1c 00"), server.requests)
            client.disconnect()

    def test_bad_identity_version_and_handshake_close(self):
        for options in ({"version": 3}, {"bundle": b"other"}, {"handshake": b"NOPE"}, {"bundle": b"\xff"}):
            with self.subTest(options=options), FakeServer(**options) as server:
                client = PlayCoverTransport(port=server.port)
                with self.assertRaises(ProtocolError):
                    client.connect("company.test")
                self.assertFalse(client.connected)

    def test_invalid_length_and_eof_close_stream(self):
        for frame in (struct.pack(">III", 16, 9, 1), struct.pack(">III", 9000, 9, 0), struct.pack(">III", 16, 9, 432) + b"short"):
            with self.subTest(frame=frame), FakeServer(capture=frame, eof_after_capture=True) as server:
                client = PlayCoverTransport(port=server.port, timeout=0.2)
                client.connect()
                with self.assertRaises((OSError, ProtocolError)):
                    client.capture()
                self.assertFalse(client.connected)

    def test_empty_capture_is_complete_but_unavailable(self):
        with FakeServer(capture=bytes(12)) as server:
            client = PlayCoverTransport(port=server.port)
            client.connect()
            with self.assertRaises(CaptureUnavailable):
                client.capture()
            self.assertEqual(client.query_version(), 4)
            client.disconnect()

    def test_timeout_reconnect_does_not_replay_touch(self):
        with FakeServer(delay=0.2) as server:
            client = PlayCoverTransport(port=server.port, timeout=0.1)
            client.connect()
            client.touch(0, 1, 1)
            with self.assertRaises(TimeoutError):
                client.capture()
            self.assertFalse(client.connected)
            client.timeout = 1
            client.connect()
            self.assertEqual(server.connections, 2)
            self.assertEqual(sum(b"TUCH" in packet for packet in server.requests), 1)
            client.disconnect()

    def test_concurrent_transactions_do_not_interleave(self):
        with FakeServer() as server:
            client = PlayCoverTransport(port=server.port)
            client.connect()
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: client.capture().width, range(20)))
            self.assertEqual(results, [16] * 20)
            client.terminate()
            self.assertFalse(client.connected)

    def test_loopback_only(self):
        with self.assertRaises(ValueError):
            PlayCoverTransport("192.168.1.1")


if __name__ == "__main__":
    unittest.main()
