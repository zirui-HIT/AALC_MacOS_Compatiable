"""Original bilingual/OCR weight synchronization, with no window dependencies."""
import copy

from frontend_appkit.theme_data import (
    CN_OCR_ALTERNATIVES,
    CN_TO_EN_HARD_NAME_MAP,
    CN_TO_EN_NAME_MAP,
    EN_OCR_ALTERNATIVES,
    THEME_PACK_HARD_NAME_MAP,
    THEME_PACK_NAME_MAP,
)


class ThemeDraft:
    def __init__(self, values):
        self.config_data = copy.deepcopy(values)
        self.is_cn = False
        self._has_unsaved_changes = False

    def _on_weight_changed(self, pack_key, weight, is_hard, is_cn):
        """处理权重改变事件，只更新内存中的配置，不保存到文件"""
        pack_key_str = str(pack_key)

        # 确定当前模式的配置键和映射表
        if is_hard:
            en_config_key = "theme_pack_list_hard"
            cn_config_key = "theme_pack_list_hard_cn"
            name_map = THEME_PACK_HARD_NAME_MAP
            reverse_map = CN_TO_EN_HARD_NAME_MAP
        else:
            en_config_key = "theme_pack_list"
            cn_config_key = "theme_pack_list_cn"
            name_map = THEME_PACK_NAME_MAP
            reverse_map = CN_TO_EN_NAME_MAP

        # 同时更新两套配置
        # 1. 更新英文配置
        en_config = copy.deepcopy(self.config_data.get(en_config_key, {}))
        en_config = {str(k): v for k, v in en_config.items()}

        # 2. 更新中文配置
        cn_config = copy.deepcopy(self.config_data.get(cn_config_key, {}))
        cn_config = {str(k): v for k, v in cn_config.items()}

        if self.is_cn:
            # 当前是中文界面，pack_key 是中文名称
            cn_config[pack_key_str] = weight

            # 检查是否有 OCR 备用名称，如果有则同步更新
            if pack_key_str in CN_OCR_ALTERNATIVES:
                # pack_key 是备用名称，找到主名称并更新
                main_name = CN_OCR_ALTERNATIVES[pack_key_str]
                if main_name in cn_config:
                    cn_config[main_name] = weight
            else:
                # pack_key 是主名称，检查是否有备用名称需要同步更新
                for alt_name, main_name in CN_OCR_ALTERNATIVES.items():
                    if main_name == pack_key_str and alt_name in cn_config:
                        cn_config[alt_name] = weight

            # 找到对应的中文名称并更新英文配置
            en_key = reverse_map.get(pack_key_str)
            if en_key and en_key in en_config:
                en_config[en_key] = weight
                # 同时检查该英文 key 是否有 OCR 备用短片段，一并更新
                for alt_key, main_key in EN_OCR_ALTERNATIVES.items():
                    if main_key == en_key and alt_key in en_config:
                        en_config[alt_key] = weight
        else:
            # 当前是英文界面，pack_key 是英文 key
            en_config[pack_key_str] = weight

            # 检查是否有英文 OCR 备用短片段，如果有则同步更新
            if pack_key_str in EN_OCR_ALTERNATIVES:
                # pack_key 是备用短片段，找到主 key 并更新
                main_key = EN_OCR_ALTERNATIVES[pack_key_str]
                if main_key in en_config:
                    en_config[main_key] = weight
            else:
                # pack_key 是主 key，检查是否有备用短片段需要同步更新
                for alt_key, main_key in EN_OCR_ALTERNATIVES.items():
                    if main_key == pack_key_str and alt_key in en_config:
                        en_config[alt_key] = weight

            # 找到对应的英文 key 并更新中文配置
            cn_key = name_map.get(pack_key_str)
            if cn_key and cn_key in cn_config:
                cn_config[cn_key] = weight
                # 同时检查该中文名称是否有 OCR 备用名称，一并更新
                for alt_name, main_name in CN_OCR_ALTERNATIVES.items():
                    if main_name == cn_key and alt_name in cn_config:
                        cn_config[alt_name] = weight

        # 只更新内存中的配置，不保存到文件
        self.config_data[en_config_key] = copy.deepcopy(en_config)
        self.config_data[cn_config_key] = copy.deepcopy(cn_config)

        # 标记有未保存的修改
        self._has_unsaved_changes = True
