"""Compatibility notification entry point; Windows implementation is lazy."""

import sys
from enum import Enum


class TemplateToast(Enum):
    NoneTemplate = 0
    TestTemplate = 1
    NormalTemplate = 2


def send_toast(title, content=None, **kwargs):
    if sys.platform == "win32":
        from app.windows_toast_impl import TemplateToast as WindowsTemplate
        from app.windows_toast_impl import send_toast as windows_send_toast

        template = kwargs.get("template")
        if isinstance(template, TemplateToast):
            kwargs["template"] = WindowsTemplate(template.value)
        return windows_send_toast(title, content, **kwargs)
    from app import mediator

    text = "\n".join(content) if isinstance(content, list) else str(content or "")
    mediator.warning.emit(f"{title}\n{text}")
