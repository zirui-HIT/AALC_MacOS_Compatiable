"""Lazy public entry points; importing an input interface must stay lightweight."""


def __getattr__(name):
    if name in {"Automation", "TextMatchResult", "auto"}:
        from module.automation.automation import Automation, TextMatchResult

        if name == "auto":
            from module.config import cfg

            value = Automation(cfg.game_title_name)
        else:
            value = {"Automation": Automation, "TextMatchResult": TextMatchResult}[name]
        globals()[name] = value
        return value
    raise AttributeError(name)
