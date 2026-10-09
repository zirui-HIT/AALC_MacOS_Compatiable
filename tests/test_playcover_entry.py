from unittest.mock import Mock

from tasks.mirror import playcover_entry as entry


def test_ios_preparation_uses_preset_then_grace_then_one_gift(monkeypatch):
    from tasks.common import ios_pages
    from tasks.mirror import playcover_opening
    from tasks.teams import playcover

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
    select = Mock()
    monkeypatch.setattr(playcover, "select_preset", select)
    graces = Mock()
    monkeypatch.setattr(playcover_opening, "configure_graces", graces)
    def gifts(auto, setting):
        state["page"] = 12

    monkeypatch.setattr(playcover_opening, "configure_gifts", gifts)
    monkeypatch.setattr(ios_pages, "click_label", lambda *args: click(entry.ENTRY + "convert_checked_assets.png"))
    monkeypatch.setattr(entry.time, "sleep", lambda _: None)
    entry.prepare_normal_mirror(automation, 1)
    assert state["page"] == len(pages) - 1
    select.assert_called_once_with(1, by_order=False)
    graces.assert_called_once_with(automation, [0] * 10)
    automation.key_press.assert_not_called()


def test_resuming_current_map_does_not_repeat_preparation(monkeypatch):
    automation = Mock()
    automation.find_element.side_effect = lambda path: path == "mirror/road_in_mir/legend_assets.png"
    entry.prepare_normal_mirror(automation, 1)
    automation.click_element.assert_not_called()
    automation.mouse_click.assert_not_called()
