import pytest

from module.backends.playcover.geometry import Geometry


@pytest.mark.parametrize("size", [(1920, 1080), (3840, 2160)])
def test_retina_and_standard_capture_map_to_same_touch_surface(size):
    geometry = Geometry(size, (1920, 1080), (0, 0, *size))
    assert geometry.point(960, 540) == (960, 540)
    assert geometry.point(-1, -1) == (0, 0)
    assert geometry.point(1920, 1080) == (1919, 1079)
    assert geometry.displacement(100, -50) == (100, -50)


def test_crop_offset_only_applies_to_absolute_points():
    geometry = Geometry((2000, 1200), (2000, 1200), (40, 60, 1920, 1080))
    assert geometry.point(0, 0) == (40, 60)
    assert geometry.point(960, 540) == (1000, 600)
    assert geometry.displacement(100, 50) == (100, 50)


def test_measured_sck_rounding_preserves_uniform_scale_and_center():
    geometry = Geometry((3942, 2216), (5120, 2880), (0, 0, 3942, 2216))
    scale, offset_x, offset_y = geometry.logical_transform()
    assert scale == 1920 / 3942
    assert offset_x == 0
    assert 0 < offset_y < 1
    assert geometry.point(960, 540) == (2560, 1440)
    assert geometry.point(0, 0) == (0, 0)
    with pytest.raises(ValueError):
        Geometry((3960, 2216), (5120, 2880), (0, 0, 3960, 2216))


@pytest.mark.parametrize("raw,touch,crop", [((100, 100), (100, 100), (0, 0, 100, 100)), ((1920, 1080), (1080, 1920), (0, 0, 1920, 1080)), ((1920, 1080), (1920, 1080), (1, 0, 1920, 1080))])
def test_invalid_geometry_is_rejected(raw, touch, crop):
    with pytest.raises(ValueError):
        Geometry(raw, touch, crop)
