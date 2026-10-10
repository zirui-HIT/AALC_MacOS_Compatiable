"""Offline recognition checks: extract methods without initializing the application."""

import ast
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ORB_PARAMETERS = (("nfeatures", 1000), ("scaleFactor", 1.2), ("edgeThreshold", 10))


@pytest.fixture
def images():
    tree = ast.parse((ROOT / "utils/image_utils.py").read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in {
        "_orb_template_features", "feature_matching", "match_template_with_multiple_targets", "get_image_info", "crop",
    }]
    namespace = {"cv2": cv2, "np": np, "lru_cache": lru_cache,
                 "cfg": SimpleNamespace(set_win_size=1080), "log": Mock()}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), "image_utils", "exec"), namespace)
    return namespace["ImageUtils"], namespace["cfg"]


def template(name):
    path = ROOT / "assets/images/default/share/mirror/road_in_mir" / f"{name}.png"
    with Image.open(path) as image:
        return cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)


@pytest.mark.parametrize("name", ["event", "shop", "battle", "risky_encounter", "focused_encounter"])
def test_orb_cached_features_and_matching_equal_uncached(images, name):
    utils, _ = images
    source = template(name)
    arguments = (source.tobytes(), source.shape, source.dtype.str, 1080, ORB_PARAMETERS)
    cached = utils._orb_template_features
    kp, descriptors = cached(*arguments)
    fresh_kp, fresh_descriptors = cached.__wrapped__(*arguments)
    assert [point.pt for point in kp] == [point.pt for point in fresh_kp]
    np.testing.assert_array_equal(descriptors, fresh_descriptors)
    target = np.pad(source, 15)
    for minimum in (8, 50):
        cv2.setRNGSeed(42)
        actual = utils.feature_matching(source, target, minimum)
        utils._orb_template_features = cached.__wrapped__
        cv2.setRNGSeed(42)
        expected = utils.feature_matching(source, target, minimum)
        utils._orb_template_features = cached
        assert actual == expected
    assert cached.cache_info().hits >= 2


def test_orb_cache_keys_content_resolution_and_parameters(images):
    utils, cfg = images
    source = template("event")
    utils.feature_matching(source, source)
    utils.feature_matching(source.copy(), source)
    assert utils._orb_template_features.cache_info().hits == 1
    changed = source.copy()
    changed[0, 0] ^= 255
    utils.feature_matching(changed, source)
    cfg.set_win_size = 1440
    utils.feature_matching(source, source)
    utils._orb_template_features(source.tobytes(), source.shape, source.dtype.str, 1440,
                                 (("nfeatures", 500), ("scaleFactor", 1.2), ("edgeThreshold", 10)))
    assert utils._orb_template_features.cache_info().misses == 4


def test_orb_cache_is_bounded_and_empty_descriptors_keep_negative_result(images):
    utils, _ = images
    source = np.zeros((20, 20), dtype=np.uint8)
    assert utils.feature_matching(source, source) == (False, 0)
    for size in range(33):
        utils._orb_template_features(source.tobytes(), source.shape, source.dtype.str, size, ORB_PARAMETERS)
    assert utils._orb_template_features.cache_info().currsize == 32

def detector(outputs, *, height=1080):
    tree = ast.parse((ROOT / "tasks/mirror/search_road.py").read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "identify_nodes")
    session = SimpleNamespace(run=Mock(return_value=[outputs]), get_inputs=lambda: [SimpleNamespace(name="images")])
    namespace = {"cv2": cv2, "np": np, "cfg": SimpleNamespace(set_win_size=height),
                 "ROAD_COLUMN_GAP": 520, "_node_detection_session": lambda: session}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "identify_nodes", "exec"), namespace)
    return namespace["identify_nodes"]


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_node_threshold_ties_nms_order_and_bus_filter(dtype):
    rows = np.zeros((5, 11), dtype=dtype)
    rows[:, :4] = [[500, 100, 40, 40], [300, 200, 40, 40], [700, 300, 40, 40],
                   [500, 100, 40, 40], [850, 400, 40, 40]]
    rows[0, 4:6] = .9  # First class wins ties; overlapping lower score must be suppressed.
    rows[1, 9] = .8
    rows[2, 6] = .7
    rows[3, 5] = .6
    rows[4, 4] = np.nextafter(dtype(.4), dtype(0))
    identify = detector(rows.T[None])
    image = Image.new("RGB", (1920, 1080))
    assert identify(0, image=image) == [["battle", (1000, 196)], ["shop", (600, 396)], ["event", (1400, 596)]]
    assert identify(800, image=image) == [["battle", (1000, 196)], ["event", (1400, 596)]]


def test_node_no_nms_result_keeps_none():
    rows = np.zeros((3, 11), dtype=np.float32)
    rows[:, :4] = [500, 100, 40, 40]
    rows[:, 4:] = .3
    assert detector(rows.T[None])(0, image=Image.new("RGB", (1920, 1080))) is None


@pytest.mark.parametrize("score", [.4, .9])
def test_node_all_filtered_keeps_empty_list(score):
    rows = np.zeros((1, 11), dtype=np.float32)
    rows[0, :4] = [500, 100, 40, 40]
    rows[0, 4] = score
    # OpenCV NMS rejects a score exactly equal to its threshold.
    expected = None if score == .4 else []
    assert detector(rows.T[None])(2000, image=Image.new("RGB", (1920, 1080))) == expected
