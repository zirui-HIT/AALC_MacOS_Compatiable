"""Shared observation settings retain the original copy semantics."""

def test_observation_uses_latest_saved_team_setting_without_changing_it():
    from module.config.config_typing import TeamSetting
    from tasks.mirror.mirror import Mirror
    original = TeamSetting(observe_ego_gift=True, observe_ego_gift_selected=['general_3_4_8'])
    dungeon = Mirror(original, 1)
    assert dungeon.observe_ego_gift
    assert dungeon.observe_ego_gift_selected == ['general_3_4_8']
    dungeon.observe_ego_gift_selected.append('burn_1_1_1')
    assert original.observe_ego_gift_selected == ['general_3_4_8']
