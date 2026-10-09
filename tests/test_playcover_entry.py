"""The existing Mirror entrance loop handles iOS navigation and retries."""
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("ignored", [False, True])
def test_original_mirror_entry_retries_a_still_visible_button(monkeypatch, ignored):
    from module.config import cfg
    from tasks.mirror import mirror
    from utils.image_utils import ImageUtils

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover"}))
    automation = Mock()
    state = {"page": "entrance", "clicks": 0}
    automation.find_element.side_effect = lambda path, **kwargs: (
        path == "mirror/road_to_mir/select_team_stars_assets.png" and state["page"] == "preset")
    automation.find_text_element.return_value = True
    def click(path, **kwargs):
        if path != "mirror/road_to_mir/enter_assets.png" or state["page"] != "entrance":
            return False
        state["clicks"] += 1
        if not ignored or state["clicks"] == 2:
            state["page"] = "preset"
        return True
    automation.click_element.side_effect = click
    monkeypatch.setattr(mirror, "auto", automation)
    monkeypatch.setattr(mirror, "retry", lambda: True)
    monkeypatch.setattr(mirror, "sleep", lambda _: None)
    monkeypatch.setattr(ImageUtils, "load_image", lambda _: None)
    monkeypatch.setattr(ImageUtils, "get_bbox", lambda _: (0, 0, 10, 10))
    mirror.Mirror(cfg.config.teams["1"], 1).road_to_mir()
    assert state["clicks"] == (2 if ignored else 1)


def test_original_mirror_resume_uses_current_map(monkeypatch):
    from module.config import cfg
    from tasks.mirror import mirror
    automation = Mock()
    automation.find_element.side_effect = lambda path, **kwargs: path == "mirror/road_in_mir/legend_assets.png"
    monkeypatch.setattr(mirror, "auto", automation)
    monkeypatch.setattr(mirror, "retry", lambda: True)
    mirror.Mirror(cfg.config.teams["1"], 1).road_to_mir()
    automation.click_element.assert_not_called()
