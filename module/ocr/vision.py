"""Isolated English Vision OCR; no game actions or task decisions."""

import logging
from threading import Event, RLock, Thread
from time import perf_counter

import cv2
import numpy as np
from PIL import Image, ImageDraw
from rapidocr.utils.output import RapidOCROutput


class VisionOCR:
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.ready = Event()
        self._lock = RLock()
        self._failed = False
        self._request = None
        Thread(target=self._warmup, name="vision-ocr-warmup", daemon=True).start()

    def _warmup(self):
        started = perf_counter()
        try:
            image = Image.new("L", (240, 80), 255)
            ImageDraw.Draw(image).text((20, 20), "Select", fill=0)
            self._recognize(image)
            self.ready.set()
            self.logger.debug("Vision OCR预热完成：%.3fs", perf_counter() - started)
        except Exception:
            self._failed = True
            self.logger.warning("Vision OCR初始化失败，保留RapidOCR", exc_info=True)

    def run(self, image):
        # Never wait for cold model loading or another Vision inference.
        if self._failed or not self.ready.is_set() or not self._lock.acquire(blocking=False):
            return None
        try:
            return self._recognize(image)
        except Exception:
            self._failed = True
            self.logger.warning("Vision OCR识别失败，回退RapidOCR", exc_info=True)
            return None
        finally:
            self._lock.release()

    def _recognize(self, image):
        import objc
        import Quartz
        import Vision
        from Foundation import NSDictionary

        started = perf_counter()
        if not isinstance(image, Image.Image):
            image = Image.fromarray(np.asarray(image))
        gray = np.asarray(image.convert("L"))
        height, width = gray.shape
        scale = 2 if height < 300 else 1.25
        pixels = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        h, w = pixels.shape
        with self._lock, objc.autorelease_pool():
            data = pixels.tobytes()
            provider = Quartz.CGDataProviderCreateWithData(None, data, len(data), None)
            cg_image = Quartz.CGImageCreate(
                w, h, 8, 8, w, Quartz.CGColorSpaceCreateDeviceGray(),
                Quartz.kCGImageAlphaNone, provider, None, False, Quartz.kCGRenderingIntentDefault,
            )
            if self._request is None:
                self._request = Vision.VNRecognizeTextRequest.alloc().init()
                self._request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
                self._request.setRecognitionLanguages_(["en-US"])
                self._request.setUsesLanguageCorrection_(False)
                self._request.setMinimumTextHeight_(0)
            handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, NSDictionary.dictionary())
            success, error = handler.performRequests_error_([self._request], None)
            if not success:
                raise RuntimeError(str(error))
            texts, scores, boxes = [], [], []
            for observation in self._request.results() or []:
                candidates = observation.topCandidates_(1)
                if not candidates:
                    continue
                box = observation.boundingBox()
                x, y = box.origin.x * width, (1 - box.origin.y - box.size.height) * height
                right, bottom = x + box.size.width * width, y + box.size.height * height
                texts.append(str(candidates[0].string()))
                scores.append(float(candidates[0].confidence()))
                boxes.append([[x, y], [right, y], [right, bottom], [x, bottom]])
        return RapidOCROutput(
            img=gray, txts=tuple(texts), scores=tuple(scores),
            boxes=np.asarray(boxes, dtype=np.float32).reshape(-1, 4, 2),
            elapse_list=[perf_counter() - started],
        )
