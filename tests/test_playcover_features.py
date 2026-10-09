"""Free rewards and daily-target refills remain configuration-driven."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from utils.runtime_paths import SOURCE_ROOT


def test_real_lunacy_preview_reads_actual_price_without_input():
    from tasks.base.playcover_enkephalin import RefillState, read_refill_state
    image = Image.open(SOURCE_ROOT / 'tests/fixtures/playcover/features_lunacy_panel.png')
    assert read_refill_state(SimpleNamespace(screenshot=image)) == RefillState(0, 10, 26)


@pytest.mark.parametrize('used,target,spent,purchases', [(0, 0, 0, 0), (0, 1, 26, 1), (0, 2, 78, 2),
    (1, 2, 52, 1), (2, 2, 0, 0), (3, 2, 0, 0), (8, 10, 494, 2)])
def test_refill_reaches_daily_target_instead_of_buying_extra(monkeypatch, used, target, spent, purchases):
    from tasks.base import playcover_enkephalin as energy
    auto = Mock()
    state = {'used': used}
    auto.find_element.return_value = True
    def click(path, **kwargs):
        state['used'] += 1
        return True
    auto.click_element.side_effect = click
    monkeypatch.setattr(energy, 'read_refill_state', lambda _: energy.RefillState(state['used'], 10, 26 * (state['used'] + 1)))
    for name in ('open_panel', 'select_tab', 'close_panel', 'assemble_modules'):
        monkeypatch.setattr(energy, name, Mock())
    monkeypatch.setattr(energy, 'label_point', lambda *args: (1, 1))
    monkeypatch.setattr(energy, 'wait_until', lambda auto, condition, *args, **kwargs: condition() or pytest.fail('Refill not confirmed'))
    assert energy.refill_lunacy(auto, target) == spent
    assert auto.click_element.call_count == purchases
    assert state['used'] == max(used, target)
    if target == 0:
        energy.open_panel.assert_not_called()


def test_unconfirmed_refill_does_not_purchase_again(monkeypatch):
    from tasks.base import playcover_enkephalin as energy
    auto = Mock()
    monkeypatch.setattr(energy, 'read_refill_state', lambda _: energy.RefillState(0, 10, 26))
    for name in ('open_panel', 'select_tab', 'assemble_modules'):
        monkeypatch.setattr(energy, name, Mock())
    def timeout(*args, **kwargs):
        raise RuntimeError('unconfirmed')
    monkeypatch.setattr(energy, 'wait_until', timeout)
    with pytest.raises(RuntimeError, match='unconfirmed'):
        energy.refill_lunacy(auto, 3)
    auto.click_element.assert_called_once()


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


def test_empty_mail_closes_without_claim(monkeypatch):
    from tasks.common.ios_pages import TextHit
    from tasks.daily import playcover_rewards as rewards
    auto = Mock()
    monkeypatch.setattr(rewards, 'label_point', lambda *args: (1, 1))
    monkeypatch.setattr(rewards, 'text_hits', lambda *args: [TextHit('No mail in storage.', (1, 1))])
    click = Mock(return_value=True)
    monkeypatch.setattr(rewards, 'click_label', click)
    monkeypatch.setattr(rewards, 'wait_until', lambda auto, condition, *args: condition())
    assert rewards.claim_mail(auto) == 0
    assert [c.args[1] for c in click.call_args_list] == ['Close']


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


def test_module_skip_setting_does_not_open_panel(monkeypatch):
    from importlib import import_module

    from module.config import cfg
    module = import_module('tasks.base.make_enkephalin_module')
    from tasks.base import playcover_enkephalin as energy
    assemble = Mock()
    monkeypatch.setattr(energy, 'assemble_modules', assemble)
    monkeypatch.setattr(cfg, 'config', cfg.config.model_copy(update={'backend': 'playcover', 'skip_enkephalin': True}))
    module.make_enkephalin_module()
    assemble.assert_not_called()
    module.make_enkephalin_module(skip=False, cancel=False)
    assemble.assert_called_once_with(module.auto, close=False)
