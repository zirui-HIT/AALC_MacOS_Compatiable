from unittest.mock import Mock, patch

import pytest

from module.backends.base import BackendCancelled
from module.backends.playcover.session import PlayCoverSession
from module.backends.playcover.transport import ProtocolError
from tests.playcover.fake_server import FakeServer


def settings(port):
    return {"playcover_host": "127.0.0.1", "playcover_port": port,
            "playcover_app_path": "", "playcover_bundle_id": "company.test",
            "playcover_capture_method": "bgr"}


def test_session_normalizes_capture_and_disconnect_does_not_stop_game():
    with FakeServer() as server:
        session = PlayCoverSession(settings(server.port))
        frame = session.capture()
        assert frame.raw_size == frame.touch_size == (16, 9)
        assert frame.image.size == (1920, 1080)
        assert frame.image.getpixel((960, 540)) == (255, 0, 0)
        assert session.capture().geometry_version == frame.geometry_version
        session.disconnect()
        assert not any(b"TERM" in packet for packet in server.requests)


def test_wrong_application_fails_immediately_without_touch_or_termination():
    with FakeServer(bundle=b"wrong.game") as server:
        session = PlayCoverSession(settings(server.port))
        with pytest.raises(ProtocolError):
            session.start_game()
        assert server.connections == 1
        assert not any(b"TUCH" in p or b"TERM" in p for p in server.requests)


def test_cancelled_start_never_relaunches_or_connects():
    session = PlayCoverSession(settings(1717))
    session.cancel.set()
    with patch.object(session.lifecycle, "start") as start, patch.object(session, "connect") as connect:
        with pytest.raises(BackendCancelled):
            session.start_game()
    start.assert_not_called()
    connect.assert_not_called()


def test_reconnect_releases_old_contact_only_to_same_verified_process():
    with FakeServer() as server:
        session = PlayCoverSession(settings(server.port))
        session.lifecycle.process = Mock(return_value=Mock(pid=23))
        session.capture()
        session.transport.touch(0, 4, 3)
        session.input.active_contacts[0] = (4, 3)
        session.transport.query_version()  # Ensure the server observed the initial no-ACK down before closing.
        session.disconnect()
        session.connect()
        session.transport.query_version()  # Drain the server's observation of the no-ACK release.
        assert not session.input.active_contacts
        assert sum(b"TUCH" in p for p in server.requests) == 2
        assert [p for p in server.requests if b"TUCH" in p][-1][6] == 3
        session.disconnect()


def test_unknown_process_after_lost_contact_blocks_recovery():
    with FakeServer() as server:
        session = PlayCoverSession(settings(server.port))
        session.input.active_contacts[0] = (4, 3)
        with pytest.raises(RuntimeError, match="verify the process"):
            session.connect()
        assert not session.transport.connected


def test_complete_empty_transition_frame_waits_without_replaying_input():
    with FakeServer(captures=[bytes(12)]) as server:
        session = PlayCoverSession(settings(server.port))
        frame = session.capture()
        assert frame.image.size == (1920, 1080)
        assert sum(b"BGR" in p for p in server.requests) == 2
        assert not any(b"TUCH" in p for p in server.requests)
        session.disconnect()


def test_unavailable_service_launches_registered_app_once_then_waits():
    session = PlayCoverSession(settings(1717))
    session.cancel.wait = Mock()
    with patch.object(session, "connect", side_effect=[ConnectionRefusedError(), None]) as connect, \
            patch.object(session, "capture") as capture, patch.object(session.lifecycle, "start") as start:
        session.start_game()
    assert connect.call_count == 2
    capture.assert_called_once()
    start.assert_called_once()
    session.cancel.wait.assert_called_once_with(0.5)


def test_term_waits_for_verified_exit_before_original_start_check(tmp_path):
    from tests.playcover.test_lifecycle import make_app

    options = settings(1717)
    options["playcover_app_path"] = str(make_app(tmp_path))
    session = PlayCoverSession(options)
    process = Mock()
    process.exe.return_value = str(session.lifecycle.identity.executable)
    session.lifecycle.process = Mock(return_value=process)
    process.wait.side_effect = lambda **kwargs: setattr(session.lifecycle.process, "return_value", None)
    session.transport = Mock(connected=True, bundle_id="company.test")
    session.stop_game()
    session.transport.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=10)
    process.terminate.assert_not_called()
    process.kill.assert_not_called()
    with patch.object(session.lifecycle, "start") as start, \
            patch.object(session, "connect"), patch.object(session, "capture"):
        session.start_game()
    start.assert_called_once()
