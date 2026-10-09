"""Lazy OCR facade: opening the GUI never downloads or loads models."""

import threading

from .ocr import OCR


class LazyOCR:
    _instance = None
    _lock = threading.RLock()

    def __getattr__(self, name):
        with self._lock:
            if self._instance is None:
                from module.logger import log

                self._instance = OCR(log)
        return getattr(self._instance, name)


ocr = LazyOCR()
