"""Read existing translations without Qt; source messages remain unchanged."""

import xml.etree.ElementTree as ET
from functools import lru_cache


@lru_cache(maxsize=1)
def catalogue():
    from utils.runtime_paths import resource_path

    result = {}
    for context in ET.parse(resource_path("i18n/myapp_en.ts")).getroot().findall("context"):
        for message in context.findall("message"):
            text = message.findtext("translation")
            if text:
                result[(context.findtext("name"), message.findtext("source"))] = text
    return result


def translate(context, text):
    import sys

    config_module = sys.modules.get("module.config")
    cfg = getattr(config_module, "cfg", None)
    if cfg is not None and cfg.language_in_program == "en":
        return catalogue().get((context, text), text)
    return text
