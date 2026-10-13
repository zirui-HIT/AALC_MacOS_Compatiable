"""Versioned JSON over inherited pipes; stdout is protocol only."""

import json
import sys
import threading

from backend_host.runtime import events


def run():
    output = sys.stdout
    sys.stdout = sys.stderr
    from module.logger.my_log import Logger

    Logger()
    from backend_host.service import BackendService

    lock = threading.Lock()
    closed = threading.Event()

    def send(message):
        with lock:
            try:
                output.write(json.dumps({"v": 1, **message}, ensure_ascii=False) + "\n")
                output.flush()
            except (BrokenPipeError, OSError):
                if not service.force_close:
                    events.post(service.shutdown, True)

    def publish(event, data):
        if event == "closed":
            closed.set()
        send({"event": event, "data": data})

    service = BackendService(publish, hotkeys="--no-hotkeys" not in sys.argv)

    def request(message):
        try:
            if message.get("v") != 1:
                raise ValueError("Unsupported protocol version")
            result = service.dispatch(message["method"], message.get("params", {}))
            send({"id": message.get("id"), "result": result})
        except Exception as exc:
            send({"id": message.get("id"), "error": str(exc)})

    def read():
        for line in sys.stdin:
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("Request must be an object")
            except (ValueError, TypeError) as exc:
                send({"id": None, "error": str(exc)})
                continue
            events.post(request, message)
        events.post(service.shutdown, True)

    threading.Thread(target=read, daemon=True).start()
    publish("ready", service.snapshot())
    while not closed.is_set():
        events.drain(timeout=0.1)
    return 0
