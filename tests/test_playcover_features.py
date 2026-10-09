"""Free rewards and daily-target refills remain configuration-driven."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from utils.runtime_paths import SOURCE_ROOT


@pytest.mark.parametrize('page,used,cost', [('features_lunacy_panel', 0, 26), ('energy_lunacy_after_refill', 1, 52)])
def test_real_lunacy_preview_reads_actual_price_without_input(page, used, cost):
    from tasks.base.playcover_enkephalin import RefillState, read_refill_state
    image = Image.open(SOURCE_ROOT / f'tests/fixtures/playcover/{page}.png')
    assert read_refill_state(SimpleNamespace(screenshot=image)) == RefillState(used, 10, cost)


@pytest.mark.parametrize('page,owned,energy,amount', [
    ('features_enkephalin_panel', 202, 61, 1), ('energy_module_max', 194, 76, 3),
    ('energy_modules_after_first', 197, 19, 1), ('energy_modules_after_refill', 204, 18, 1),
    ('energy_max_disabled', 204, 22, 1),
    ('energy_single_module_converted', 205, 3, 1),
])
def test_real_module_quantity_inventory_and_energy(page, owned, energy, amount):
    from tasks.base.playcover_enkephalin import ModuleState, read_module_state
    image = Image.open(SOURCE_ROOT / f'tests/fixtures/playcover/{page}.png')
    assert read_module_state(SimpleNamespace(screenshot=image)) == ModuleState(owned, energy, amount)


@pytest.mark.parametrize('close', [False, True])
@pytest.mark.parametrize('panel_stays_open', [False, True])
def test_conversion_waits_for_maximum_and_inventory_update(monkeypatch, close, panel_stays_open):
    from tasks.base import playcover_enkephalin as energy
    automation = Mock()
    automation.find_element.return_value = panel_stays_open
    state = {'owned': 194, 'energy': 76, 'amount': 1, 'pending_max': False}
    reads_after_max = []
    def click(path, **kwargs):
        if path.endswith('all_in_assets.png'):
            state['pending_max'] = True
        else:
            assert state['amount'] == 3
            state.update(owned=197, energy=16, amount=1)
        return True
    def read(auto):
        result = energy.ModuleState(state['owned'], state['energy'], state['amount'])
        if state['pending_max']:
            reads_after_max.append(result.amount)
            state.update(amount=3, pending_max=False)
        return result
    def wait(auto, condition, *args):
        for _ in range(3):
            if condition():
                return
        pytest.fail('Conversion transition not confirmed')
    automation.click_element.side_effect = click
    monkeypatch.setattr(energy, 'read_module_state', read)
    monkeypatch.setattr(energy, 'wait_until', wait)
    for name in ('open_panel', 'select_tab', 'close_panel'):
        monkeypatch.setattr(energy, name, Mock())
    assert energy.assemble_modules(automation, close=close)
    assert reads_after_max == [1]
    assert [c.args[0] for c in automation.click_element.call_args_list] == [
        'enkephalin/all_in_assets.png', 'enkephalin/enkephalin_confirm_assets.png']
    assert energy.close_panel.call_count == int(close)


@pytest.mark.parametrize('available,amount', [(20, 1), (22, 1), (39, 1), (60, 3), (139, 6)])
def test_already_maximum_quantity_does_not_require_enabled_max_button(monkeypatch, available, amount):
    from tasks.base import playcover_enkephalin as energy
    automation = Mock()
    state = {'owned': 204, 'energy': available, 'amount': amount}
    def click(path, **kwargs):
        assert path == 'enkephalin/enkephalin_confirm_assets.png'
        state.update(owned=204 + amount, energy=available - 20 * amount, amount=1)
        return True
    automation.click_element.side_effect = click
    monkeypatch.setattr(energy, 'read_module_state', lambda _: energy.ModuleState(**state))
    for name in ('open_panel', 'select_tab', 'close_panel'):
        monkeypatch.setattr(energy, name, Mock())
    monkeypatch.setattr(energy, 'wait_until', lambda auto, condition, *args: condition() or pytest.fail('Wrong conversion state'))
    assert energy.assemble_modules(automation)
    automation.click_element.assert_called_once_with('enkephalin/enkephalin_confirm_assets.png', offset=False)


@pytest.mark.parametrize('available', [0, 1, 19])
def test_insufficient_energy_skips_conversion_confirm(monkeypatch, available):
    from tasks.base import playcover_enkephalin as energy
    automation = Mock()
    for name in ('open_panel', 'select_tab', 'close_panel'):
        monkeypatch.setattr(energy, name, Mock())
    monkeypatch.setattr(energy, 'read_module_state', lambda _: energy.ModuleState(194, available, 1))
    assert not energy.assemble_modules(automation)
    automation.click_element.assert_not_called()
    energy.close_panel.assert_called_once()


@pytest.mark.parametrize('name', ['Modules', 'Use Lunacy'])
def test_tab_selection_waits_for_animation_and_target_content(monkeypatch, name):
    from tasks.base import playcover_enkephalin as energy
    automation = Mock()
    labels = iter([(760, 359), (760, 339), (1100, 425)])
    monkeypatch.setattr(energy, 'label_point', lambda *args: next(labels))
    click = Mock(return_value=True)
    monkeypatch.setattr(energy, 'click_label', click)
    monkeypatch.setattr(energy, 'read_module_state', lambda _: energy.ModuleState(194, 76, 1))
    monkeypatch.setattr(energy, '_read_refill_state', lambda _: energy.RefillState(0, 10, 26))
    checks = []
    def wait(auto, condition, *args):
        checks.append(condition())
        if not checks[-1]:
            click.assert_not_called()
            assert condition()
    monkeypatch.setattr(energy, 'wait_until', wait)
    energy.select_tab(automation, name)
    assert checks == [False, True]
    click.assert_called_once()


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
    monkeypatch.setattr(energy, '_read_refill_state', energy.read_refill_state)
    for name in ('open_panel', 'select_tab', 'close_panel', 'assemble_modules'):
        monkeypatch.setattr(energy, name, Mock())
    monkeypatch.setattr(energy, 'label_point', lambda *args: (1, 1))
    monkeypatch.setattr(energy, 'wait_until', lambda auto, condition, *args, **kwargs: condition() or pytest.fail('Refill not confirmed'))
    assert energy.refill_lunacy(auto, target) == spent
    assert auto.click_element.call_count == purchases
    assert state['used'] == max(used, target)
    assert energy.refill_lunacy(auto, target) == 0
    assert auto.click_element.call_count == purchases
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
