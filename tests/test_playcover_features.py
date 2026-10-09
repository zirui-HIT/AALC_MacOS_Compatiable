"""Free rewards and daily-target refills remain configuration-driven."""
from unittest.mock import Mock

import pytest
from PIL import Image

from utils.runtime_paths import SOURCE_ROOT


@pytest.mark.parametrize('scope,expected', [(0, ['pass', 'mail']), (1, ['pass']), (2, ['mail'])])
def test_reward_scope_drives_task_order(monkeypatch, scope, expected):
    from module.config import cfg
    from tasks.base import script_task_scheme as script
    monkeypatch.setattr(cfg, 'config', cfg.config.model_copy(update={'set_get_prize': scope}))
    calls = []
    monkeypatch.setattr(script, 'back_init_menu', Mock())
    monkeypatch.setattr(script, 'get_pass_prize', lambda: calls.append('pass'))
    monkeypatch.setattr(script, 'get_mail_prize', lambda: calls.append('mail'))
    script.to_get_reward()
    assert calls == expected


@pytest.mark.parametrize('page,targets', [
    ('features_enkephalin_panel', ['enkephalin/charge_ios_assets.png', 'enkephalin/all_in_assets.png',
        'enkephalin/enkephalin_cancel_assets.png', 'enkephalin/enkephalin_confirm_assets.png']),
    ('features_mail', ['mail/close_assets.png', 'mail/claim_all_assets.png']),
    ('features_pass_overview', ['pass/pass_missions_assets.png']),
    ('features_pass_missions', ['pass/pass_coin.png', 'pass/daily_ios_assets.png', 'pass/weekly_assets.png']),
])
def test_real_new_ios_actions_are_recognized(monkeypatch, page, targets):
    from module.automation import auto
    from module.config import cfg
    from utils.path_manager import path_manager
    monkeypatch.setattr(cfg, 'config', cfg.config.model_copy(update={'game_profile': 'ios_en', 'set_win_size': 1080}))
    path_manager.initialize_paths()
    auto.clear_img_cache()
    monkeypatch.setattr(auto, 'screenshot', Image.open(SOURCE_ROOT / f'tests/fixtures/playcover/{page}.png').convert('L'))
    for target in targets:
        assert auto.find_element(target, model='normal', threshold=0.8), target
