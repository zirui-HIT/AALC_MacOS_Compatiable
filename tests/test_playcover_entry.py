from unittest.mock import Mock

from tasks.mirror import playcover_entry as entry


def test_ios_preparation_uses_preset_then_grace_then_one_gift(monkeypatch):
    pages = [
        {"home/mail_assets.png", "home/drive_assets.png"},
        {"home/mirror_dungeons_assets.png"},
        {entry.ENTRY + "landing_enter_assets.png"},
        {entry.ENTRY + "entry_prompt_assets.png", entry.ENTRY + "entry_confirm_assets.png"},
        {entry.ENTRY + "preset_assets.png", entry.ENTRY + "preset_confirm_assets.png"},
        {entry.ENTRY + "grace_assets.png", entry.ENTRY + "grace_enter_assets.png"},
        {entry.ENTRY + "grace_prompt_assets.png", entry.ENTRY + "convert_checked_assets.png",
         entry.ENTRY + "grace_confirm_assets.png"},
        {entry.ENTRY + "grace_prompt_assets.png", entry.ENTRY + "grace_confirm_assets.png"},
        {entry.ENTRY + "gift_page_assets.png", entry.ENTRY + "search_on_assets.png"},
        {entry.ENTRY + "gift_page_assets.png", entry.ENTRY + "bleed_assets.png"},
        {entry.ENTRY + "gift_page_assets.png", entry.ENTRY + "bleed_assets.png", entry.ENTRY + "wound_clerid_assets.png"},
        {entry.ENTRY + "gift_page_assets.png", entry.ENTRY + "gift_select_assets.png"},
        {"mirror/theme_pack/feature_theme_pack_assets.png"},
    ]
    state = {"page": 0}
    automation = Mock()
    automation.find_element.side_effect = lambda path: path in pages[state["page"]]

    def click(path, **kwargs):
        assert path in pages[state["page"]]
        state["page"] += 1
        return True

    automation.click_element.side_effect = click
    monkeypatch.setattr(entry.time, "sleep", lambda _: None)
    entry.prepare_normal_mirror(automation, 1)
    assert state["page"] == len(pages) - 1
    automation.mouse_click.assert_called_once_with(195, 470)
    assert automation.mouse_swipe_for_team_scroll.call_count == 10
    automation.key_press.assert_not_called()


def test_resuming_current_map_does_not_repeat_preparation(monkeypatch):
    automation = Mock()
    automation.find_element.side_effect = lambda path: path == "mirror/road_in_mir/legend_assets.png"
    entry.prepare_normal_mirror(automation, 1)
    automation.click_element.assert_not_called()
    automation.mouse_click.assert_not_called()
