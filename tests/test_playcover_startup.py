"""First-launch recognition must have resource search paths before retry checks."""
from unittest.mock import Mock

import pytest

from module.config import cfg
from tasks.base import script_task_scheme as script
from utils.image_utils import ImageUtils
from utils.path_manager import path_manager

RETRY_IMAGES = (
    'base/sign_in_assets.png', 'base/connecting_assets.png', 'base/retry_countdown.png',
    'base/retry.png', 'base/try_again.png', 'base/clear_all_caches_assets.png', 'base/only_option_assets.png',
)


@pytest.fixture
def empty_paths(monkeypatch):
    monkeypatch.setattr(cfg, 'config', cfg.config.model_copy(update={'backend': 'playcover', 'game_profile': 'ios_en'}))
    for name, value in vars(path_manager).copy().items():
        monkeypatch.setattr(path_manager, name, value)
    path_manager.active_paths = []


def test_standalone_init_game_resolves_every_startup_template_before_retry(monkeypatch, empty_paths):
    from module.backends import factory
    from tasks.base import retry

    automation = Mock()
    session = Mock()
    monkeypatch.setattr(script, 'auto', automation)
    monkeypatch.setattr(factory, 'get_playcover_session', lambda: session)
    def check_resources():
        for image in RETRY_IMAGES:
            assert ImageUtils.existing_image_paths(image), image
    monkeypatch.setattr(retry, 'retry', check_resources)
    script.init_game()
    session.start_game.assert_called_once()


def test_task_runner_initializes_paths_before_game_init(monkeypatch, empty_paths):
    from tasks.common import game_actions

    monkeypatch.setattr(game_actions, 'validate_task_capabilities', Mock())
    monkeypatch.setattr(script, 'auto', Mock())
    def stop_before_game_actions():
        assert path_manager.pic_path
        assert ImageUtils.existing_image_paths('base/sign_in_assets.png')
        script.auto.clear_img_cache.assert_called_once()
        raise RuntimeError('stop before game actions')
    monkeypatch.setattr(script, 'init_game', stop_before_game_actions)
    with pytest.raises(RuntimeError, match='stop before game actions'):
        script.script_task()
