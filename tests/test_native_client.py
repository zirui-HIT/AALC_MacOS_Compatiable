"""Pipe closure during a pending native-client write stays on the error path."""

import io
import queue
from types import SimpleNamespace

import pytest

from frontend_appkit.client import BackendClient


def test_closing_pipes_with_a_queued_request_reports_disconnection():
    client = BackendClient.__new__(BackendClient)
    client.process = SimpleNamespace(stdin=io.StringIO())
    client.incoming = queue.Queue()
    client.outgoing = queue.Queue()
    client.outgoing.put({"v": 1, "id": 1, "method": "snapshot"})

    # The UI can handle a backend EOF before the writer consumes its next request.
    client.close_pipes()
    client._write()

    message = client.incoming.get_nowait()
    assert message["event"] == "disconnected"
    assert "closed file" in message["data"]
    assert client.incoming.empty()


def test_serialization_error_is_not_reported_as_a_pipe_disconnection():
    client = BackendClient.__new__(BackendClient)
    client.process = SimpleNamespace(stdin=io.StringIO())
    client.incoming = queue.Queue()
    client.outgoing = queue.Queue()
    message = {}
    message["params"] = message
    client.outgoing.put(message)

    with pytest.raises(ValueError, match="Circular reference"):
        client._write()
    assert client.incoming.empty()
    assert client.process.stdin.getvalue() == ""
