import re
import sys
from enum import Enum

import requests
from markdown_it import MarkdownIt
from packaging.version import parse

from backend_host.runtime import Signal
from backend_host.runtime import WorkerThread as QThread
from module.config import cfg
from module.logger import log
from utils.utils import decrypt_string

md_renderer = MarkdownIt("gfm-like", {"html": True})

class UpdateStatus(Enum):
    SUCCESS = 1
    UPDATE_AVAILABLE = 2
    FAILURE = 0


class UpdateThread(QThread):
    """
    更新线程类，用于在后台检查和处理软件更新。
    该类继承自 QThread，使用 Qt 的信号机制来通知 GUI 线程更新状态。
    """

    # 定义更新信号，用于通知主线程更新状态
    updateSignal = Signal(UpdateStatus)

    def __init__(self, timeout, flag):
        """
        初始化更新线程。

        参数:
        timeout -- 更新检查请求的超时时间（秒）
        flag -- 是否强制遵循配置项 check_update 来决定是否执行检查
        """
        super().__init__()
        self.timeout = timeout  # 超时时间
        self.flag = flag  # 标志位，用于控制是否执行检查更新
        self.error_msg = ""  # 错误信息

        self.user = "KIYI671"
        self.repo = "AhabAssistantLimbusCompany"
        self.new_version = ""
        # 记录本次检查后“当前版本是否已追平最新版本”，供资源同步门禁读取。
        self.is_current_version_latest = False

    def _set_version_gate_state(self, version: str):
        """
        刷新版本门禁所需的最新版本信息与比较结果。

        参数:
        version -- 本轮检查得到的最新版本号

        返回:
        当前版本对象与最新版本对象组成的二元组
        """
        self.new_version = version
        current_version = parse(cfg.version.lstrip("Vv"))
        latest_version = parse(version.lstrip("Vv"))
        self.is_current_version_latest = current_version == latest_version
        # 记录本地版本是否为预发布版（alpha/beta/rc），供资源同步门禁跳过测试版。
        self.is_prerelease = current_version.is_prerelease
        return current_version, latest_version

    def _build_release_note_content(self, raw_content: str) -> str:
        """
        统一整理更新日志正文，供不同更新源复用。

        参数:
        raw_content -- 原始的更新日志 Markdown 文本

        返回:
        清理并补充说明后的更新日志文本
        """
        content = self.remove_images_from_markdown(raw_content)
        content = re.sub(
            r"\r\n\r\n\[.*?Mirror酱.*?CDK.*?下载\]\(https?://.*?mirrorchyan\.com[^\)]*\)",
            "",
            content,
            flags=re.IGNORECASE,
        )
        if cfg.update_source == "GitHub":
            content = content + "\n\n若下载速度较慢，可尝试使用 Mirror酱（设置 → 关于 → 更新源） 高速下载"
        return content

    def _emit_version_check_result(self, version: str, current_version, latest_version, content: str) -> None:
        """
        统一根据版本比较结果发出更新状态信号，并在有更新时准备弹窗展示内容。

        参数:
        version -- 本轮检查得到的最新版本号
        current_version -- 当前软件版本解析后的对象
        latest_version -- 远端最新版本解析后的对象
        content -- 已清理完成、可直接渲染的更新日志正文
        """
        # 第一步：若远端版本更高，则准备更新弹窗标题与渲染后的正文。
        if latest_version > current_version:
            self.title = self.tr("发现新版本：{Old_version} ——> {New_version}\n更新日志:").format(
                Old_version=cfg.version, New_version=version
            )
            self.content = "<style>a {color: #586f50; font-weight: bold;}</style>" + md_renderer.render(content)
            self.updateSignal.emit(UpdateStatus.UPDATE_AVAILABLE)
            return

        # 第二步：若当前版本已追平最新版本，则统一发出“已是最新”信号。
        self.updateSignal.emit(UpdateStatus.SUCCESS)

    def run(self) -> None:
        """
        更新线程的主逻辑。
        检查是否有新版本，如果有则发送更新可用信号；否则发送成功信号。
        """
        try:
            # 如果标志位为 False 且配置中的检查更新标志也为 False，则直接返回
            if self.flag and not cfg.get_value("check_update"):
                return

            # 第一步：优先从 Mirror酱 获取最新版本信息，并同步记录版本门禁需要的数据。
            data = self.check_update_info_mirrorchyan()
            version = data["version_name"]
            # 同步记录本次检查得到的最新版本号与比较结果，供资源同步门禁直接复用。
            current_version, latest_version = self._set_version_gate_state(version)
            # 第二步：整理更新日志正文，去掉图片，生成可展示文本。
            content = self._build_release_note_content(data["release_note"])

            # 第三步：比较当前版本与最新版本，并统一发出检查结果信号。
            self._emit_version_check_result(version, current_version, latest_version, content)
        except Exception as e:
            # Mirror酱 失败后自动回退到 GitHub，保持原有软件更新逻辑不变。
            log.error(f"从Mirror酱源检查更新失败:{e},尝试使用GitHub源检查更新")
            try:
                data = self.check_update_info_github()
                version = data["tag_name"]
                # 当回退到 GitHub 源时，同样刷新版本比较结果，避免后续门禁读取到旧值。
                current_version, latest_version = self._set_version_gate_state(version)
                # 回退到 GitHub 后同样整理更新日志正文。
                content = self._build_release_note_content(data["body"])
                assets_url = self.get_download_url_from_assets(data["assets"])

                # 若当前回退源未携带可下载资产，则按“当前无需更新”处理。
                if assets_url is None:
                    self.updateSignal.emit(UpdateStatus.SUCCESS)
                    return

                # 最后继续复用同一套版本比较逻辑，决定是否弹出更新提示。
                self._emit_version_check_result(version, current_version, latest_version, content)
            except Exception as e:
                # 异常处理，发送失败信号
                log.error(f"Mirror酱源与GitHub源均检查更新失败:{e}")
                self.updateSignal.emit(UpdateStatus.FAILURE)

    def check_update_info_github(self):
        """
        从 GitHub 获取最新发布版本的信息。

        返回:
        最新发布版本的信息（JSON 格式）
        """
        if not cfg.update_prerelease_enable:
            response = requests.get(
                f"https://api.github.com/repos/{self.user}/{self.repo}/releases/latest",
                timeout=10,
                headers=cfg.useragent,
            )
        else:
            response = requests.get(
                f"https://api.github.com/repos/{self.user}/{self.repo}/releases",
                timeout=10,
                headers=cfg.useragent,
            )
        response.raise_for_status()
        # 根据配置决定是否包含预发布版本
        return response.json()[0] if cfg.update_prerelease_enable else response.json()

    def check_update_info_mirrorchyan(self, cdk=""):
        """
        从 mirror酱 获取最新发布版本的信息。

        参数:
        cdk -- Mirror酱 CDK

        返回:
        最新发布版本的信息（JSON 格式）
        """
        if not cfg.update_prerelease_enable:
            response = requests.get(
                f"https://mirrorchyan.com/api/resources/AALC/latest?current_version={cfg.version}&user_agent={self.repo}&cdk={cdk}",
                timeout=10,
                headers=cfg.useragent,
            )
        else:
            response = requests.get(
                f"https://mirrorchyan.com/api/resources/AALC/latest?current_version={cfg.version}&user_agent={self.repo}&channel=beta&cdk={cdk}",
                timeout=10,
                headers=cfg.useragent,
            )
        if cdk == "":
            # 返回获取的最新发布版本信息
            return response.json()["data"]
        else:
            return response

    def remove_images_from_markdown(self, markdown_content):
        """
        从 Markdown 内容中移除图片。

        参数:
        markdown_content -- Markdown 格式的文本

        返回:
        移除图片后的 Markdown 文本
        """
        img_pattern = re.compile(r"!\[.*?\]\(.*?\)")
        return img_pattern.sub("", markdown_content)

    def get_download_url_from_assets(self, assets):
        """
        从资产列表中获取 .7z 文件的下载 URL。

        参数:
        assets -- 资产列表（JSON 格式）

        返回:
        .7z 文件的下载 URL，如果没有找到则返回 None
        """
        if sys.platform == "darwin":
            return None
        for asset in assets:
            if asset["name"].endswith(".7z"):
                return asset["browser_download_url"]
        return None

    def get_assets_url(self):
        try:
            if cfg.update_source == "MirrorChyan":
                if cfg.mirrorchyan_cdk == "":
                    self.error_msg = "未设置 Mirror酱 CDK"
                    self.updateSignal.emit(UpdateStatus.FAILURE)
                    return None
                # 符合Mirror酱条件
                cdk = decrypt_string(cfg.mirrorchyan_cdk)
                response = self.check_update_info_mirrorchyan(cdk)
                if response.status_code == 200:
                    mirrorchyan_data = response.json()
                    if mirrorchyan_data["code"] == 0 and mirrorchyan_data["msg"] == "success":
                        url = mirrorchyan_data["data"]["url"]
                        return url
                else:
                    try:
                        mirrorchyan_data = response.json()
                        self.code = mirrorchyan_data["code"]
                        self.error_msg = mirrorchyan_data["msg"]

                        cdk_error_messages = {
                            7001: "Mirror酱 CDK 已过期",
                            7002: "Mirror酱 CDK 错误",
                            7003: "Mirror酱 CDK 今日下载次数已达上限",
                            7004: "Mirror酱 CDK 类型和待下载的资源不匹配",
                            7005: "Mirror酱 CDK 已被封禁",
                        }
                        if self.code in cdk_error_messages:
                            self.error_msg = cdk_error_messages[self.code]
                    except:
                        self.error_msg = "Mirror酱API请求失败"
                    self.updateSignal.emit(UpdateStatus.FAILURE)
                    return None
            else:
                # 复用统一的 GitHub release 查询逻辑，避免重复维护接口路径与预发布分支判断。
                data = self.check_update_info_github()
                assets_url = self.get_download_url_from_assets(data["assets"])

                # 如果没有可用的下载 URL，则发送成功信号并返回
                if assets_url is None and sys.platform != "darwin":
                    self.updateSignal.emit(UpdateStatus.SUCCESS)
                    return
                return assets_url
        except Exception as e:
            # 异常处理，发送失败信号
            log.error(f"更新失败:{e}")
            self.updateSignal.emit(UpdateStatus.FAILURE)
