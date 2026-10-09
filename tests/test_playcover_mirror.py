from unittest.mock import Mock


def test_unknown_floor_is_zero_without_guessing_or_touch(monkeypatch):
    from module.config import cfg
    from tasks.mirror import get_floor

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover"}))
    automation = Mock()
    automation.find_element.return_value = None
    monkeypatch.setattr(get_floor, "auto", automation)
    assert get_floor.get_floor(previous_floor=3) == 0
    automation.mouse_click.assert_not_called()
