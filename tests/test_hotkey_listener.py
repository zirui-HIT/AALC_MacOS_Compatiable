"""PR #921 regression tests with a fake listener; no host keyboard is monitored."""

import types

from pynput import keyboard

from module import hotkey_listener
from module.platforms import macos


class _FakeListener:
    """假监听：只记录创建/启动，不建立任何真实监听线程。"""

    instances: list["_FakeListener"] = []

    def __init__(self, on_press=None, on_release=None):
        self.on_press = on_press
        self.on_release = on_release
        self.started = False
        _FakeListener.instances.append(self)

    def canonical(self, key):
        return key

    def start(self):
        self.started = True

    def stop(self):
        self.started = False


def _make_hotkeys(monkeypatch) -> hotkey_listener.GlobalHotKeys:
    monkeypatch.setattr(macos, "hotkeys_available", lambda: True)
    _FakeListener.instances = []
    monkeypatch.setattr(
        hotkey_listener,
        "keyboard",
        types.SimpleNamespace(
            Key=keyboard.Key,
            KeyCode=keyboard.KeyCode,
            HotKey=keyboard.HotKey,
            Listener=_FakeListener,
        ),
    )
    manager = hotkey_listener.GlobalHotKeys()
    return manager


def _press(listener: _FakeListener, *keys) -> None:
    for key in keys:
        listener.on_press(key)
    for key in reversed(keys):
        listener.on_release(key)


def _shortcut(char: str):
    return keyboard.Key.ctrl, keyboard.KeyCode.from_char(char)


def test_所有注册共用同一个监听(monkeypatch):
    manager = _make_hotkeys(monkeypatch)
    calls = []

    manager.register(lambda: {"<ctrl>+q": lambda: calls.append("q")})
    manager.register(lambda: {"<ctrl>+a": lambda: calls.append("a")})

    assert len(_FakeListener.instances) == 1
    listener = _FakeListener.instances[0]
    assert listener.started

    _press(listener, *_shortcut("q"))
    _press(listener, *_shortcut("a"))

    assert calls == ["q", "a"]


def test_后注册者占用同一快捷键(monkeypatch):
    manager = _make_hotkeys(monkeypatch)
    first, second = [], []

    manager.register(lambda: {"<ctrl>+q": lambda: first.append(1)})
    manager.register(lambda: {"<ctrl>+q": lambda: second.append(1)})

    _press(_FakeListener.instances[0], *_shortcut("q"))

    assert second == [1]
    assert first == []


def test_注销后快捷键回到先注册者(monkeypatch):
    manager = _make_hotkeys(monkeypatch)
    first, second = [], []

    manager.register(lambda: {"<ctrl>+q": lambda: first.append(1)})
    token = manager.register(lambda: {"<ctrl>+q": lambda: second.append(1)})
    manager.unregister(token)

    listener = _FakeListener.instances[0]
    _press(listener, *_shortcut("q"))

    assert first == [1]
    assert second == []
    assert len(_FakeListener.instances) == 1


def test_暂停期间不派发且恢复时重读快捷键(monkeypatch):
    manager = _make_hotkeys(monkeypatch)
    calls = []
    hotkey = {"name": "<ctrl>+q"}

    manager.register(lambda: {hotkey["name"]: lambda: calls.append(1)})
    listener = _FakeListener.instances[0]

    manager.stop()
    _press(listener, *_shortcut("q"))
    assert calls == []

    hotkey["name"] = "<ctrl>+w"  # 相当于用户刚在设置里改了快捷键
    manager.start()
    _press(listener, *_shortcut("q"))
    _press(listener, *_shortcut("w"))

    assert calls == [1]
    assert len(_FakeListener.instances) == 1


def test_mac_permission_can_be_granted_later_without_recreating_listener(monkeypatch):
    manager = _make_hotkeys(monkeypatch)
    monkeypatch.setattr(hotkey_listener.sys, "platform", "darwin")
    monkeypatch.setattr(macos, "hotkeys_available", lambda: False)
    calls = []
    manager.register(lambda: {"<ctrl>+q": lambda: calls.append(1)})
    assert not _FakeListener.instances
    monkeypatch.setattr(macos, "hotkeys_available", lambda: True)
    manager.start()
    _press(_FakeListener.instances[0], *_shortcut("q"))
    assert calls == [1]
    manager.stop()
    manager.start()
    assert len(_FakeListener.instances) == 1


def test_extra_modifiers_injected_events_and_key_repeat_do_not_activate(monkeypatch):
    manager = _make_hotkeys(monkeypatch)
    calls = []
    manager.register(lambda: {"<ctrl>+q": lambda: calls.append(1)})
    listener = _FakeListener.instances[0]
    _press(listener, keyboard.Key.shift, *_shortcut("q"))
    for key in _shortcut("q"):
        listener.on_press(key, injected=True)
        listener.on_release(key, injected=True)
    assert calls == []
    for key in _shortcut("q"):
        listener.on_press(key)
    listener.on_press(keyboard.KeyCode.from_char("q"))
    assert calls == [1]
    for key in reversed(_shortcut("q")):
        listener.on_release(key)
    _press(listener, *_shortcut("q"))
    assert calls == [1, 1]


def test_suspend_clears_held_modifiers_and_unregistering_all_keeps_listener(monkeypatch):
    manager = _make_hotkeys(monkeypatch)
    calls = []
    token = manager.register(lambda: {"<ctrl>+q": lambda: calls.append(1)})
    listener = _FakeListener.instances[0]
    listener.on_press(keyboard.Key.ctrl)
    manager.stop()
    manager.start()
    _press(listener, keyboard.KeyCode.from_char("q"))
    assert calls == []
    manager.unregister(token)
    _press(listener, *_shortcut("q"))
    assert calls == []
    manager.register(lambda: {"<ctrl>+q": lambda: calls.append(1)})
    _press(listener, *_shortcut("q"))
    assert calls == [1]
    assert listener.started and len(_FakeListener.instances) == 1


def test_bad_provider_and_invalid_shortcut_leave_valid_registration_working(monkeypatch):
    manager = _make_hotkeys(monkeypatch)
    calls = []
    def bad_provider():
        raise ValueError("deleted component")
    manager.register(bad_provider)
    manager.register(lambda: {"invalid+": lambda: calls.append("invalid"), "<ctrl>+q": lambda: calls.append("q")})
    _press(_FakeListener.instances[0], *_shortcut("q"))
    assert calls == ["q"]

