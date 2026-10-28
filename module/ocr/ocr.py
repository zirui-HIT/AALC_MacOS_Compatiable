import logging
import sys
from copy import deepcopy
from pathlib import Path
from threading import RLock
from time import monotonic

import cv2
import numpy as np
import rapidocr
from cv2 import createCLAHE
from PIL import Image
from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR
from rapidocr.utils.output import RapidOCROutput

from utils.runtime_paths import resource_path
from utils.singletonmeta import SingletonMeta


class OCR(metaclass=SingletonMeta):
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._inference_lock = RLock()
        self._vision = None
        self._vision_zh_cn = None
        if sys.platform == "darwin":
            from module.config import cfg

            if cfg.game_profile == "ios_en":
                from .vision import VisionOCR

                self._vision = VisionOCR(logger)
            elif cfg.game_profile == "ios_zh_cn":
                from .vision import VisionOCR

                self._vision_zh_cn = VisionOCR(logger, languages=("zh-Hant", "en-US"))
        models = Path(rapidocr.__file__).resolve().parent / "models"
        self.engine = RapidOCR(
            params={
                "Det.model_path": str(models / "ch_PP-OCRv4_det_infer.onnx"),
                "Cls.model_path": str(models / "ch_ppocr_mobile_v2.0_cls_infer.onnx"),
                "Rec.model_path": str(models / "ch_PP-OCRv4_rec_infer.onnx"),
                "Rec.rec_keys_path": str(models / "ppocr_keys_v1.txt"),
                "Global.font_path": str(resource_path("assets/app/fonts/ChineseFont.ttf")),
                "Det.engine_type": EngineType.ONNXRUNTIME,
                "Det.lang_type": LangDet.CH,
                "Det.model_type": ModelType.MOBILE,
                "Det.ocr_version": OCRVersion.PPOCRV4,
                "Rec.engine_type": EngineType.ONNXRUNTIME,
                "Rec.lang_type": LangRec.CH,
                "Rec.model_type": ModelType.MOBILE,
                "Rec.ocr_version": OCRVersion.PPOCRV4,
            },
            config_path=str(resource_path("assets/config/default_rapidocr.yaml")),
        )

    def run(self, image: Image.Image | np.ndarray | str) -> RapidOCROutput:
        """执行OCR识别，支持Image对象、文件路径和np.ndarray对象"""
        try:
            if sys.platform == "darwin":
                from module.config import cfg

                # Original tasks pass preprocessed grayscale arrays for digits.
                # Keep their RapidOCR path; native Chinese OCR handles UI frames.
                if cfg.game_profile == "ios_zh_cn" and not (isinstance(image, np.ndarray) and image.ndim == 2):
                    if self._vision_zh_cn is None:
                        from .vision import VisionOCR

                        with self._inference_lock:
                            if self._vision_zh_cn is None:
                                self._vision_zh_cn = VisionOCR(self.logger, languages=("zh-Hant", "en-US"))
                    if isinstance(image, str):
                        with Image.open(image) as image_file:
                            result = self._vision_zh_cn.run(image_file)
                    else:
                        result = self._vision_zh_cn.run(image)
                    if result is not None and result.txts:
                        self.log_results(result)
                        return result
            if isinstance(image, str):
                with Image.open(image) as image_file:
                    image_array = np.array(image_file)
            elif isinstance(image, Image.Image):
                image_array = np.array(image)
            elif isinstance(image, np.ndarray):
                image_array = image
            else:
                image_array = np.array(image)

            if image_array.ndim == 2:
                img_cv_gray = image_array
            elif image_array.ndim == 3:
                channel_count = image_array.shape[2]
                if channel_count == 1:
                    img_cv_gray = image_array[:, :, 0]
                elif channel_count == 3:
                    img_cv = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
                    img_cv_gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
                elif channel_count == 4:
                    img_cv = cv2.cvtColor(image_array, cv2.COLOR_RGBA2BGR)
                    img_cv_gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
                else:
                    raise ValueError(f"不支持的图像通道数: {channel_count}")
            else:
                raise ValueError(f"不支持的图像维度: {image_array.ndim}")

            # 自适应均衡化(均值化后更亮)
            clahe = createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            processed_image = clahe.apply(img_cv_gray)
            with self._inference_lock:
                # Original retry loops can read the same small grayscale crop
                # repeatedly. Reuse only identical input for at most one second;
                # keep independent outputs and every caller's original log.
                profile = cfg.game_profile if sys.platform == "darwin" else None
                cacheable = (profile in {"ios_en", "ios_zh_cn"}
                             and isinstance(image, np.ndarray) and image.ndim == 2
                             and processed_image.size <= 65536)
                cached = getattr(self, "_small_crop_cache", None)
                results = None
                if (cacheable and cached is not None and cached[0] is self.engine
                        and cached[1] == profile and monotonic() < cached[4]
                        and np.array_equal(processed_image, cached[2])):
                    try:
                        results = deepcopy(cached[3])
                    except Exception:
                        pass  # A cache-copy failure must still run normal OCR.
                if results is None:
                    self._small_crop_cache = None
                    results = self.engine(processed_image)
                    if cacheable and results.txts:
                        try:
                            self._small_crop_cache = (
                                self.engine, profile, processed_image.copy(),
                                deepcopy(results), monotonic() + 1.0,
                            )
                        except Exception:
                            pass  # Caching is optional; keep a valid OCR result.
            self.log_results(results)
            return results
        except Exception as e:
            self.logger.error(e)
            return RapidOCROutput()

    def run_vision(self, image: Image.Image) -> RapidOCROutput | None:
        """Optional fast recognition; None asks the caller to use RapidOCR."""
        if self._vision is None and sys.platform == "darwin":
            from .vision import VisionOCR

            with self._inference_lock:
                if self._vision is None:
                    self._vision = VisionOCR(self.logger)
        result = self._vision.run(image) if self._vision is not None else None
        if result is not None:
            self.log_results(result)
        return result

    def log_results(self, ocr_results: RapidOCROutput) -> None:
        """记录OCR识别记录"""
        self.logger.debug(f"OCR识别结果：{ocr_results.txts}")
