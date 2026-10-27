from __future__ import annotations

import itertools
import sys
import threading
from collections.abc import Callable

from pynput import keyboard

from module.logger import log

_MODIFIER_KEYS = {
    keyboard.Key.alt,
    keyboard.Key.alt_gr,
    keyboard.Key.cmd,
    keyboard.Key.ctrl,
    keyboard.Key.shift,
}

HotkeyProvider = Callable[[], dict[str, Callable[[], None]]]


class _ExactHotKey:
    def __init__(self, keys: list[keyboard.Key | keyboard.KeyCode], on_activate: Callable[[], None]):
        self._keys = set(keys)
        self._state: set[keyboard.Key | keyboard.KeyCode] = set()
        self._required_modifiers = {key for key in self._keys if key in _MODIFIER_KEYS}
        self._is_active = False
        self._on_activate = on_activate

    def press(
        self,
        key: keyboard.Key | keyboard.KeyCode,
        pressed_modifiers: set[keyboard.Key],
    ) -> None:
        if key in self._keys:
            self._state.add(key)

        should_activate = self._state == self._keys and pressed_modifiers == self._required_modifiers
        if should_activate and not self._is_active:
            self._is_active = True
            self._on_activate()
        elif not should_activate:
            self._is_active = False

    def release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        self._state.discard(key)
        self._is_active = False


class GlobalHotKeys:
    """复用一个 pynput 监听器；后注册的组件优先，关闭时注销自己的 token。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._listener: keyboard.Listener | None = None
        self._registrations: dict[int, HotkeyProvider] = {}
        self._tokens = itertools.count()
        self._suspended = False
        self._hotkeys: list[_ExactHotKey] = []
        self._pressed_keys: set[keyboard.Key | keyboard.KeyCode] = set()
        self._canonicalize = lambda key: key

    def register(self, provider: HotkeyProvider) -> int:
        with self._lock:
            token = next(self._tokens)
            self._registrations[token] = provider
            self._refresh()
            return token

    def unregister(self, token: int) -> None:
        with self._lock:
            if self._registrations.pop(token, None) is not None:
                self._refresh()

    def stop(self) -> None:
        """录入新快捷键时只暂停派发，保留底层监听器。"""
        with self._lock:
            self._suspended = True
            self._refresh()

    def start(self) -> None:
        """恢复派发，重新读取当前配置。"""
        with self._lock:
            self._suspended = False
            self._refresh()

    def _refresh(self) -> None:
        self._hotkeys = [] if self._suspended else self._collect_hotkeys()
        self._pressed_keys.clear()
        if self._listener is not None or not self._hotkeys:
            return
        try:
            if sys.platform == "darwin":
                from module.platforms.macos import hotkeys_available

                if not hotkeys_available():
                    log.info("Global hotkeys unavailable: enable Input Monitoring; GUI Stop remains available")
                    return
            listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self._canonicalize = listener.canonical
            listener.start()
        except Exception as e:
            log.error(f"快捷键监听启动失败: {e}")
            return
        self._listener = listener

    def _collect_hotkeys(self) -> list[_ExactHotKey]:
        resolved: dict[str, Callable[[], None]] = {}
        for provider in self._registrations.values():
            try:
                resolved.update(provider())
            except Exception as e:
                log.error(f"读取快捷键配置失败: {e}")
        collected = []
        for hotkey, callback in resolved.items():
            try:
                keys = keyboard.HotKey.parse(hotkey)
            except ValueError:
                log.error(f"快捷键 {hotkey} 格式无效，请确认设置的快捷键格式有效")
                continue
            collected.append(_ExactHotKey(keys, callback))
        return collected

    def _canonical_key(self, key):
        if sys.platform == "darwin" and isinstance(key, keyboard.KeyCode) and key.vk is not None:
            from pynput._util.darwin import keycode_context, keycode_to_string

            # Option produces characters such as π/®; match the configured
            # letter using the current layout without altering modifier state.
            with keycode_context() as context:
                char = keycode_to_string(context, key.vk) if context[1] is not None else ""
            if len(char) == 1:
                key = keyboard.KeyCode.from_char(char)
        return self._canonicalize(key)

    def _on_press(self, key, injected=False):
        if injected:
            return

        with self._lock:
            canonical_key = self._canonical_key(key)
            self._pressed_keys.add(canonical_key)
            pressed_modifiers = {key for key in self._pressed_keys if key in _MODIFIER_KEYS}
            for hotkey in self._hotkeys:
                hotkey.press(canonical_key, pressed_modifiers)

    def _on_release(self, key, injected=False):
        if injected:
            return

        with self._lock:
            canonical_key = self._canonical_key(key)
            for hotkey in self._hotkeys:
                hotkey.release(canonical_key)
            self._pressed_keys.discard(canonical_key)


global_hotkeys = GlobalHotKeys()
