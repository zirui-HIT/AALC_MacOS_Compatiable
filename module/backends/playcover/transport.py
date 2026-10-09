"""MaaTools v4 transport, independent of Qt, Pillow, OCR and application config.

Each transaction owns the stream until its command-specific response is read.
No mutating command is retried automatically, including touch and termination.
"""

from __future__ import annotations

import ipaddress
import socket
import struct
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


class ProtocolError(ConnectionError):
    """The peer is incompatible or returned a malformed message."""


class CaptureUnavailable(RuntimeError):
    """A complete response reported that capture is currently unavailable."""


@dataclass(frozen=True)
class RawCapture:
    width: int
    height: int
    pixels: bytes
    mode: str
    captured_at: float


def validate_endpoint(host: str, port: int) -> None:
    if host != "localhost":
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("MaaTools host must be localhost or a loopback IP address") from exc
        if not address.is_loopback:
            raise ValueError("Only loopback MaaTools connections are supported")
    if not 1 <= port <= 65535:
        raise ValueError("MaaTools port must be between 1 and 65535")


class PlayCoverTransport:
    SUPPORTED_VERSIONS = frozenset({4})
    MAX_DIMENSION = 8192
    MAX_IMAGE_BYTES = 128 * 1024 * 1024
    MAX_BUNDLE_BYTES = 4096

    def __init__(self, host: str = "127.0.0.1", port: int = 1717, timeout: float = 5.0):
        validate_endpoint(host, port)
        if timeout <= 0:
            raise ValueError("Timeout must be positive")
        self.host, self.port, self.timeout = host, port, timeout
        self._socket: socket.socket | None = None
        self._lock = threading.RLock()
        self._deadline = 0.0
        self.version: int | None = None
        self.bundle_id: str | None = None

    @property
    def connected(self) -> bool:
        return self._socket is not None

    def disconnect(self) -> None:
        with self._lock:
            if self._socket is not None:
                self._socket.close()
                self._socket = None
            self.version = None
            self.bundle_id = None

    def connect(self, expected_bundle_id: str = "") -> None:
        with self._lock:
            self.disconnect()
            try:
                self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout)
                self._deadline = time.monotonic() + self.timeout
                self._socket.sendall(b"MAA\x00")
                if self.recv_exact(4) != b"OKAY":
                    raise ProtocolError("Invalid MaaTools handshake")
                version = self.query_version()
                if version not in self.SUPPORTED_VERSIONS:
                    raise ProtocolError(f"Unsupported MaaTools protocol {version}; expected v4")
                bundle_id = self.query_bundle_id()
                if not bundle_id or (expected_bundle_id and bundle_id != expected_bundle_id):
                    raise ProtocolError(f"Unexpected game identity: {bundle_id!r}")
                self.version, self.bundle_id = version, bundle_id
            except (OSError, ProtocolError):
                self.disconnect()
                raise

    def recv_exact(self, length: int) -> bytes:
        """Read a bounded response, respecting a deadline for the whole transaction."""
        if length < 0 or length > self.MAX_IMAGE_BYTES:
            raise ProtocolError(f"Invalid read length: {length}")
        if self._socket is None:
            raise ConnectionError("MaaTools is disconnected")
        result = bytearray()
        while len(result) < length:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("MaaTools response deadline exceeded")
            self._socket.settimeout(remaining)
            chunk = self._socket.recv(min(length - len(result), 1024 * 1024))
            if not chunk:
                raise ProtocolError("MaaTools closed the connection during a response")
            result.extend(chunk)
        return bytes(result)

    @contextmanager
    def _request(self, payload: bytes) -> Iterator[None]:
        with self._lock:
            if self._socket is None:
                raise ConnectionError("MaaTools is disconnected")
            self._deadline = time.monotonic() + self.timeout
            try:
                self._socket.settimeout(self.timeout)
                self._socket.sendall(struct.pack(">H", len(payload)) + payload)
                yield
            except (OSError, ProtocolError):
                # A partial response must never be reused for another request.
                self.disconnect()
                raise

    def query_version(self) -> int:
        with self._request(b"VERN"):
            return struct.unpack(">I", self.recv_exact(4))[0]

    def query_bundle_id(self) -> str:
        with self._request(b"BNDL"):
            length = struct.unpack(">I", self.recv_exact(4))[0]
            if length > self.MAX_BUNDLE_BYTES:
                raise ProtocolError("Bundle ID exceeds size limit")
            try:
                return self.recv_exact(length).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ProtocolError("Bundle ID is not UTF-8") from exc

    def query_size(self) -> tuple[int, int]:
        with self._request(b"SIZE"):
            width, height = struct.unpack(">HH", self.recv_exact(4))
            self._validate_image(width, height, width * height * 3, 3)
            return width, height

    def _validate_image(self, width: int, height: int, length: int, channels: int) -> None:
        if not (0 < width <= self.MAX_DIMENSION and 0 < height <= self.MAX_DIMENSION):
            raise ProtocolError(f"Invalid frame dimensions: {width}x{height}")
        if length != width * height * channels or length > self.MAX_IMAGE_BYTES:
            raise ProtocolError(f"Invalid frame length: {length} for {width}x{height}")

    def capture(self, method: str = "bgr") -> RawCapture:
        with self._lock:
            if method == "bgr":
                with self._request(b"BGR\x01"):
                    width, height, length = struct.unpack(">III", self.recv_exact(12))
                    if width == height == length == 0:
                        raise CaptureUnavailable("MaaTools BGR capture returned an empty frame")
                    self._validate_image(width, height, length, 3)
                    pixels = self.recv_exact(length)
                mode = "BGR"
            elif method == "scrn":
                width, height = self.query_size()
                with self._request(b"SCRN"):
                    length = struct.unpack(">I", self.recv_exact(4))[0]
                    if length == 0:
                        raise CaptureUnavailable("MaaTools SCRN capture returned an empty frame")
                    self._validate_image(width, height, length, 4)
                    pixels = self.recv_exact(length)
                mode = "RGBX"
            else:
                raise ValueError("Capture method must be bgr or scrn")
            return RawCapture(width, height, pixels, mode, time.monotonic())

    def touch(self, phase: int, x: int, y: int, contact: int = 0) -> None:
        if phase not in (0, 1, 3) or not 0 <= contact <= 255:
            raise ValueError("Invalid touch phase or contact")
        if not (0 <= x <= 65535 and 0 <= y <= 65535):
            raise ValueError("Native touch coordinates exceed protocol bounds")
        with self._request(b"TUCH" + struct.pack(">BHHB", phase, x, y, contact)):
            pass  # TUCH has no response. Confirmation belongs to the task layer.

    def terminate(self) -> None:
        with self._request(b"TERM"):
            pass
        self.disconnect()
