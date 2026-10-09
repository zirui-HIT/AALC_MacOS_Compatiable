import sys

from utils.runtime_paths import data_path, resource_path

VERSION_PATH = str(resource_path("assets/config/version.txt"))
EXAMPLE_PATH = str(resource_path("assets/config/config.example.yaml"))
CONFIG_PATH = str(data_path("config/config.yaml") if sys.platform == "darwin" else resource_path("config.yaml"))
THEME_PACK_LIST_EXAMPLE_PATH = str(resource_path("assets/config/theme_pack_list.example.yaml"))
THEME_PACK_LIST_PATH = str(data_path("config/theme_pack_list.yaml") if sys.platform == "darwin" else resource_path("theme_pack_list.yaml"))
THEME_PACK_WEIGHT_PATH = str(data_path("config/theme_pack_weight") if sys.platform == "darwin" else resource_path("theme_pack_weight"))
