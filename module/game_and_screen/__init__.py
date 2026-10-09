"""Legacy access. macOS never creates a Windows Screen/Handle."""


class UnsupportedWindow:
    def __getattr__(self, name):
        raise NotImplementedError(f"Windows window operation {name} is unavailable on this backend")


def __getattr__(name):
    from module.config import cfg

    if name == "screen":
        if cfg.backend != "windows":
            return UnsupportedWindow()
        from module.game_and_screen.screen import Screen

        value = Screen(title=cfg.game_title_name, game=__getattr__("game_process"))
    elif name == "game_process":
        if cfg.backend == "playcover":
            from module.backends.factory import get_playcover_session

            return get_playcover_session()
        from module.game_and_screen.game import Game
        from module.logger import log

        value = Game(logger=log)
    else:
        raise AttributeError(name)
    globals()[name] = value
    return value
