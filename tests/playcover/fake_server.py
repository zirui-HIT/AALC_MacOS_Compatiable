"""Local MaaTools fixture. Intentionally fragments every response."""

import socket
import struct
import threading
import time
from contextlib import AbstractContextManager


class FakeServer(AbstractContextManager):
    def __init__(self, *, version=4, bundle=b"company.test", capture=None, delay=0, handshake=b"OKAY", eof_after_capture=False):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.listener.settimeout(0.1)
        self.port = self.listener.getsockname()[1]
        self.version, self.bundle, self.delay, self.handshake = version, bundle, delay, handshake
        self.eof_after_capture = eof_after_capture
        self.frame = capture if capture is not None else struct.pack(">III", 16, 9, 16 * 9 * 3) + bytes([0, 0, 255]) * 16 * 9
        self.requests = []
        self.connections = 0
        self.error = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    @staticmethod
    def receive(connection, count):
        result = bytearray()
        while len(result) < count:
            chunk = connection.recv(count - len(result))
            if not chunk:
                return None
            result.extend(chunk)
        return bytes(result)

    def _run(self):
        while not self.stop.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.connections += 1
            with connection:
                connection.settimeout(0.3)
                try:
                    if self.receive(connection, 4) != b"MAA\0":
                        raise AssertionError("Bad handshake")
                    connection.sendall(self.handshake)
                    while not self.stop.is_set():
                        header = self.receive(connection, 2)
                        if header is None:
                            break
                        payload = self.receive(connection, struct.unpack(">H", header)[0])
                        self.requests.append(header + payload)
                        replies = {
                            b"VERN": struct.pack(">I", self.version),
                            b"BNDL": struct.pack(">I", len(self.bundle)) + self.bundle,
                            b"SIZE": struct.pack(">HH", 16, 9),
                            b"BGR\1": self.frame,
                            b"SCRN": struct.pack(">I", 16 * 9 * 4) + bytes([255, 0, 0, 0]) * 16 * 9,
                        }
                        if payload == b"TERM":
                            break
                        response = replies.get(payload, b"")
                        if payload == b"BGR\1" and self.delay:
                            time.sleep(self.delay)
                        for offset in range(0, len(response), 3):
                            connection.sendall(response[offset:offset + 3])
                        if payload == b"BGR\1" and self.eof_after_capture:
                            break
                except (OSError, TypeError):
                    pass  # Peer intentionally disconnects in failure tests.
                except AssertionError as exc:
                    self.error = exc

    def __exit__(self, *args):
        self.stop.set()
        self.listener.close()
        self.thread.join(timeout=1)
        if self.error:
            raise self.error
