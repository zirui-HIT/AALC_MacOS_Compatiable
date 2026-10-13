"""Window-only adaptation for the unchanged standalone battle worker."""


class PlayCoverWindow:
    def set_win(self):
        # PlayCover captures/touches in its existing logical geometry.
        pass

    def reset_win(self, activate=True):
        return True


def __getattr__(name):
    if name != "screen":
        raise AttributeError(name)
    from module.config import cfg

    if cfg.backend == "playcover":
        return PlayCoverWindow()
    from module.game_and_screen import screen

    return screen
