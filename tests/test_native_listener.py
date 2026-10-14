"""A failed resident-command client must not stop later scheduled commands."""

import queue
import socket
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

pytest.importorskip("AppKit")

from frontend_appkit.application import Application  # noqa: E402


@pytest.mark.parametrize("failure", [socket.timeout("idle client"), OSError("client reset"), b"\xff"])
def test_failed_client_does_not_stop_the_next_resident_command(failure):
    app = Application.__new__(Application)
    app.backend_closed = False
    app.client = SimpleNamespace(incoming=queue.Queue())
    failed, valid = MagicMock(), MagicMock()
    if isinstance(failure, bytes):
        failed.recv.side_effect = [failure, b""]
    else:
        failed.recv.side_effect = failure

    def receive(_):
        app.backend_closed = True
        return b"start|--exit|autodaily\n"

    valid.recv.side_effect = receive
    app.listener = Mock()
    app.listener.accept.side_effect = [(failed, None), (valid, None)]

    app.listen()

    assert app.listener.accept.call_count == 2
    failed.__exit__.assert_called_once()
    valid.__exit__.assert_called_once()
    assert app.client.incoming.get_nowait() == {
        "event": "command", "data": ["start", "--exit", "autodaily"],
    }
    assert app.client.incoming.empty()


@pytest.mark.parametrize("parts", [
    [b"start|--ex", b"it|autodaily2", b"\n"],
    [b"start|--ex", b"it|autodaily2", b""],
])
def test_resident_command_is_assembled_before_parsing(parts):
    app = Application.__new__(Application)
    app.backend_closed = False
    app.client = SimpleNamespace(incoming=queue.Queue())
    connection = MagicMock()
    connection.recv.side_effect = parts
    app.listener = Mock()
    app.listener.accept.side_effect = [(connection, None), OSError("listener closed")]

    app.listen()

    assert app.client.incoming.get_nowait() == {"event": "command", "data": ["start", "--exit", "autodaily2"]}
    assert app.client.incoming.empty()


def test_closed_listener_still_exits_without_a_command():
    app = Application.__new__(Application)
    app.backend_closed = False
    app.client = SimpleNamespace(incoming=queue.Queue())
    app.listener = Mock()
    app.listener.accept.side_effect = OSError("listener closed")

    app.listen()

    app.listener.accept.assert_called_once()
    assert app.client.incoming.empty()


def test_resident_entry_rebinds_after_a_command_without_allowing_a_second_listener(monkeypatch):
    from frontend_appkit import application

    real_socket = socket.socket
    with real_socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    class Listener:
        def __init__(self, *args):
            self.socket = real_socket(*args)

        def bind(self, _):
            self.socket.bind(("127.0.0.1", port))

        def __getattr__(self, name):
            return getattr(self.socket, name)

    def open_app(arguments, listener):
        with real_socket() as client:
            client.settimeout(2)
            client.connect(("127.0.0.1", port))
            client.sendall(b"|")
            accepted, _ = listener.accept()
            with accepted:
                accepted.settimeout(2)
                assert accepted.recv(16) == b"|"
            assert client.recv(1) == b""  # Server closes first, creating TIME_WAIT.
        listener.close()
        return SimpleNamespace(exit_code=0)

    fallback = Mock(side_effect=AssertionError("There is no resident instance to forward to"))
    monkeypatch.setattr(application, "socket", SimpleNamespace(socket=Listener, AF_INET=socket.AF_INET,
        SOCK_STREAM=socket.SOCK_STREAM, SOL_SOCKET=socket.SOL_SOCKET, SO_REUSEADDR=socket.SO_REUSEADDR,
        create_connection=fallback))
    monkeypatch.setattr(application, "Application", open_app)
    monkeypatch.setattr(application.AppHelper, "runEventLoop", lambda: None)
    assert application.run([]) == 0
    assert application.run([]) == 0
    fallback.assert_not_called()

    with real_socket() as active, real_socket() as second:
        for listener in (active, second):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        active.bind(("127.0.0.1", port))
        active.listen()
        with pytest.raises(OSError):
            second.bind(("127.0.0.1", port))
            second.listen()
