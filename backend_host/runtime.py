"""Small thread/event adapters; no GUI toolkit and no task decisions."""

import logging
import queue
import sys
import threading
import time


def worker_sleep(seconds):
    """Let native worker cancellation wake a wait; ordinary waits keep their duration."""
    interrupted = getattr(threading.current_thread(), "_aalc_interrupted", None)
    if sys.platform != "darwin" or interrupted is None or seconds <= 0:
        return time.sleep(seconds)
    if interrupted.wait(seconds):
        from module.backends.base import BackendCancelled

        raise BackendCancelled("Worker stopped during wait")


class EventLoop:
    def __init__(self):
        self.pending = queue.Queue()

    def post(self, callback, *args):
        self.pending.put((callback, args))

    def later(self, milliseconds, callback, *args):
        timer = threading.Timer(milliseconds / 1000, self.post, (callback, *args))
        timer.daemon = True
        timer.start()
        return timer

    def drain(self, timeout=0):
        try:
            callback, args = self.pending.get(timeout=timeout)
        except queue.Empty:
            return False
        try:
            callback(*args)
        except Exception:
            logging.getLogger("AALC").exception("Backend event failed")
        return True


events = EventLoop()


class BoundSignal:
    def __init__(self):
        self._lock = threading.RLock()
        self._callbacks = []

    def connect(self, callback, *, queued=False):
        with self._lock:
            self._callbacks.append((callback, queued))

    def disconnect(self, callback=None):
        with self._lock:
            self._callbacks = [] if callback is None else [item for item in self._callbacks if item[0] != callback]

    def emit(self, *args):
        with self._lock:
            callbacks = list(self._callbacks)
        for callback, queued in callbacks:
            if queued:
                events.post(callback, *args)
            else:
                callback(*args)


class Signal:
    def __init__(self, *types):
        self.name = ""

    def __set_name__(self, owner, name):
        self.name = "_signal_" + name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        # Instance creation/connection happens before starting each worker.
        if self.name not in instance.__dict__:
            instance.__dict__[self.name] = BoundSignal()
        return instance.__dict__[self.name]


class Mutex:
    def __init__(self):
        self._lock = threading.Lock()

    def lock(self):
        self._lock.acquire()

    def unlock(self):
        self._lock.release()

    def tryLock(self, milliseconds=0):
        return self._lock.acquire(timeout=milliseconds / 1000)


class WorkerThread:
    finished = Signal()

    def __init__(self, parent=None):
        self._thread = None
        self._interrupted = threading.Event()
        self.exception = None
        self.after_run = None
        self.before_run = None

    def start(self):
        if self.isRunning():
            raise RuntimeError("Worker is already running")
        self._interrupted.clear()
        self._thread = threading.Thread(target=self._entry, daemon=True)
        self._thread._aalc_interrupted = self._interrupted
        self._thread.start()

    def _entry(self):
        try:
            if self.isInterruptionRequested():
                return
            if self.before_run is not None:
                self.before_run()
            self.run()
        except BaseException as exc:
            self.exception = exc
            from module.backends.base import BackendCancelled

            if not isinstance(exc, BackendCancelled):
                logging.getLogger("AALC").exception("Worker failed")
        finally:
            try:
                if self.after_run is not None:
                    self.after_run()
            except Exception as exc:
                self.exception = self.exception or exc
                logging.getLogger("AALC").exception("Worker cleanup failed")
            finally:
                # Queued receivers run on the host loop after this thread exits.
                self.finished.emit()

    def run(self):
        raise NotImplementedError

    def isRunning(self):
        return self._thread is not None and self._thread.is_alive()

    def wait(self, milliseconds=None):
        if self._thread is None:
            return True
        if threading.current_thread() is self._thread:
            return False
        self._thread.join(None if milliseconds is None else milliseconds / 1000)
        return not self.isRunning()

    def requestInterruption(self):
        self._interrupted.set()

    def isInterruptionRequested(self):
        return self._interrupted.is_set()

    def terminate(self):
        self.requestInterruption()
        from module.automation import auto

        auto.request_stop()

    def deleteLater(self):
        pass

    @staticmethod
    def msleep(milliseconds):
        time.sleep(milliseconds / 1000)

    def tr(self, text):
        from backend_host.translation import translate

        return translate(type(self).__name__, text)
