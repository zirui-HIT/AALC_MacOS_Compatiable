"""Asynchronous pipe client with no business imports."""

import itertools
import json
import os
import queue
import subprocess
import sys
import threading

from utils.runtime_paths import SOURCE_ROOT


class BackendClient:
    def __init__(self, *, smoke=False):
        command = [sys.executable, "--backend"] if getattr(sys, "frozen", False) else [sys.executable, "-u", str(SOURCE_ROOT / "main.py"), "--backend"]
        if smoke:
            command.append("--no-hotkeys")
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, cwd=SOURCE_ROOT if not getattr(sys, "frozen", False) else "/", env=os.environ.copy())
        self.incoming = queue.Queue()
        self.outgoing = queue.Queue()
        self.ids = itertools.count(1)
        self.callbacks = {}
        self.stderr = []
        self.wake = None
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._write, daemon=True).start()
        threading.Thread(target=self._read_errors, daemon=True).start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.incoming.put(json.loads(line))
                if self.wake:
                    self.wake()
        except (OSError, ValueError) as exc:
            self.stderr.append(str(exc))
        finally:
            self.process.stdout.close()
            self.incoming.put({"event": "disconnected", "data": "\n".join(self.stderr[-8:])})
            if self.wake:
                self.wake()

    def _write(self):
        while True:
            message = self.outgoing.get()
            if message is None:
                return
            line = json.dumps(message, ensure_ascii=False) + "\n"
            try:
                self.process.stdin.write(line)
                self.process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                self.incoming.put({"event": "disconnected", "data": str(exc)})
                return

    def _read_errors(self):
        for line in self.process.stderr:
            self.stderr.append(line.rstrip())
            if len(self.stderr) > 100:
                del self.stderr[:50]
        self.process.stderr.close()

    def request(self, method, params=None, callback=None, on_error=None):
        request_id = next(self.ids)
        self.callbacks[request_id] = callback, on_error
        self.outgoing.put({"v": 1, "id": request_id, "method": method, "params": params or {}})

    def drain(self, on_event, on_error):
        for _ in range(200):
            try:
                message = self.incoming.get_nowait()
            except queue.Empty:
                break
            if "event" in message:
                on_event(message["event"], message.get("data"))
            else:
                callback, failed = self.callbacks.pop(message.get("id"), (None, None))
                if "error" in message:
                    (failed or on_error)(message["error"])
                elif callback is not None:
                    callback(message.get("result"))

    def close_pipes(self):
        self.outgoing.put(None)
        self.process.stdin.close()
