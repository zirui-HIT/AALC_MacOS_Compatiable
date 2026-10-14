"""Exercise custom report paths and the uncropped assets comparison."""

import re
from html.parser import HTMLParser
from urllib.parse import unquote, urlparse

import numpy as np
import pytest
from PIL import Image

from scripts import image_similarity as similarity


@pytest.mark.parametrize("crop_assets", [False, True])
@pytest.mark.parametrize("model", ["clam", "normal", "aggressive"])
def test_identical_positioned_images_match_with_and_without_crop(tmp_path, crop_assets, model):
    image = np.zeros((512, 512), dtype=np.uint8)
    image[240:260, 240:268] = np.random.default_rng(42).integers(80, 256, (20, 28), dtype=np.uint8)
    path = tmp_path / "probe_assets.png"
    Image.fromarray(image).save(path)
    entry, _ = similarity.prepare_entry(path, tmp_path, crop_assets, False)
    score = similarity.positioned_assets_score(entry, entry, model)
    assert score is not None and score > .99


def test_cropped_mode_keeps_position_constraints_for_a_full_bbox(tmp_path):
    pixels = np.random.default_rng(42).integers(80, 256, (20, 28), dtype=np.uint8)
    template_path = tmp_path / "small_assets.png"
    Image.fromarray(pixels).save(template_path)
    screenshot = np.zeros((512, 512), dtype=np.uint8)
    screenshot[400:420, 400:428] = pixels
    screenshot_path = tmp_path / "screenshot.png"
    Image.fromarray(screenshot).save(screenshot_path)
    shot, _ = similarity.prepare_entry(screenshot_path, tmp_path, True, False)
    positioned, _ = similarity.prepare_entry(template_path, tmp_path, True, False)
    full, _ = similarity.prepare_entry(template_path, tmp_path, False, False)
    assert similarity.positioned_assets_score(shot, positioned, "clam") < .99
    assert similarity.positioned_assets_score(shot, full, "clam") > .99


def test_reports_link_to_actual_custom_input_and_output_directories(tmp_path):
    folder = tmp_path / "analysis input"
    folder.mkdir()
    names = ["a 图#1.png", "b.png"]
    images = []
    for name in names:
        path = folder / name
        Image.fromarray(np.arange(400, dtype=np.uint8).reshape(20, 20)).save(path)
        images.append(similarity.prepare_entry(path, folder, True, False)[0])
    markdown = tmp_path / "markdown output" / "report.md"
    html = tmp_path / "html output" / "report.html"
    markdown.parent.mkdir()
    html.parent.mkdir()
    pairs = [(names[0], names[1], 1., 1., 1., "non-assets", "different-target")]
    issues = [similarity.NamingIssue("path_layout", names[0], "fixture naming issue")]
    counts = {"assets-assets": 0, "non-assets": 1, "mixed": 0}
    similarity.write_report(markdown, folder, images, .75, 1, counts, pairs, issues, html)
    similarity.write_html_report(html, folder, images, .75, 1, counts, pairs, issues)

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.hrefs = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                self.hrefs.extend(value for key, value in attrs if key == "href")

    links = Links()
    links.feed(html.read_text())
    for output, hrefs in [(html, links.hrefs), (markdown, re.findall(r'\]\(([^)]+)\)', markdown.read_text()))]:
        actual = [(output.parent / unquote(urlparse(href).path)).resolve() for href in hrefs]
        assert all(path.exists() for path in actual)
        assert all((folder / name).resolve() in actual for name in names)
        assert folder.resolve() in actual
