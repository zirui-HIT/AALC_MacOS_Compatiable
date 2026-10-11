import sys
from enum import Enum

from PySide6.QtGui import QIcon
from qfluentwidgets import FluentIconBase, Theme, getIconColor, isDarkTheme

from utils.runtime_paths import resource_path


def application_icon() -> QIcon:
    filename = "aalc.png" if sys.platform == "darwin" else "my_icon_256X256.ico"
    return QIcon(str(resource_path(f"assets/logo/{filename}")))


class OverflowIcons(FluentIconBase, Enum):
    """放一些超出了渲染范围的svg图标

    即范围外还有数据的图标"""

    DOUBLE_ADD = "double_add"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.reverse = False

    def path(self, theme=Theme.AUTO):
        if self.reverse:
            theme = Theme.DARK if not isDarkTheme() else Theme.LIGHT
        return str(resource_path(f"assets/app/svgs/icons/{self.value}_{getIconColor(theme)}.svg"))

    def set_reverse(self, reverse: bool):
        self.reverse = reverse
