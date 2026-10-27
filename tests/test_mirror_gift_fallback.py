"""A successful OCR fallback must tolerate an unrecognized image anchor."""

from unittest.mock import Mock, call

import pytest


def test_ocr_only_refusal_page_keeps_original_loop_recovery(monkeypatch):
    from module.config import TeamSetting, cfg
    from tasks.mirror import mirror as task

    class RecoveryRequested(Exception):
        pass

    automation = Mock()
    frames = 0

    def capture():
        nonlocal frames
        frames += 1
        assert frames <= 35, "Anchor misses must still consume the existing retry budget"
        return True

    automation.take_screenshot.side_effect = capture
    automation.find_element.return_value = None
    automation.click_element.return_value = False
    automation.find_text_element.return_value = False
    automation.find_language_text.side_effect = (
        lambda chinese, english, *args: (900, 700) if english == "refuse" else None
    )
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "battle", Mock(fail_times=0, identify_keyword_turn=False))
    monkeypatch.setattr(task, "retry", Mock(return_value=True))
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(task.ImageUtils, "load_image", Mock())
    monkeypatch.setattr(task.ImageUtils, "get_bbox", Mock(return_value=(0, 0, 100, 100)))
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"floor_3_exit": False}))
    recovery = Mock(side_effect=RecoveryRequested)
    monkeypatch.setattr(task, "back_init_menu", recovery)
    dungeon = task.Mirror(TeamSetting(), 1)
    dungeon.LOOP_COUNT = 30

    with pytest.raises(RecoveryRequested):
        dungeon.run()

    assert frames == 31
    recovery.assert_called_once_with()
    automation.mouse_click.assert_not_called()


def test_recognized_refusal_anchor_preserves_existing_selection(monkeypatch):
    from module.config import TeamSetting, cfg
    from tasks.mirror import mirror as task

    automation = Mock()
    automation.find_element.return_value = (900, 700)
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "retry", Mock(return_value=True))
    dungeon = task.Mirror(TeamSetting(), 1)

    dungeon.acquire_ego_gift(type=2)

    offset = 500 * cfg.set_win_size / 1440
    assert automation.mouse_click.call_args_list == [call(900 - offset, 700 - offset), call(900, 700 - offset)]
    automation.click_element.assert_called_once_with(
        "mirror/road_in_mir/acquire_ego_gift_select_assets.png", model="normal"
    )
