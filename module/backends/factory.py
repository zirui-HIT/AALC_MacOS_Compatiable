"""Lazy session construction. Configuration is accessed only when requested."""

import threading

_session = None
_settings = None
_lock = threading.RLock()


def get_playcover_session():
    with _lock:
        return _get_playcover_session()


def _get_playcover_session():
    global _session, _settings
    from module.config import cfg

    if cfg.backend != "playcover":
        raise RuntimeError("The selected backend is not PlayCover")
    keys = ("playcover_host", "playcover_port", "playcover_app_path", "playcover_bundle_id", "playcover_capture_method")
    settings = {key: cfg.get_value(key) for key in keys}
    if _session is None or settings != _settings:
        if _session is not None:
            if _session.input.active_contacts:
                raise RuntimeError("Stop the current gesture before changing backend settings")
            _session.disconnect()
        from .playcover.session import PlayCoverSession

        _session = PlayCoverSession(settings)
        _settings = settings
    return _session
