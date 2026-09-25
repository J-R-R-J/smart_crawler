# -*- coding: utf-8 -*-
"""core.user_prefs —— 用户偏好持久化。

使用 QSettings 的 **INI 文件**后端（`crawler_data/settings.ini`），而不是
系统默认的注册表 / plist：

- 便携：配置随程序目录走，删除目录即彻底清除；
- 可读可改：纯文本，用户能直接查看与备份；
- 可靠：不依赖注册表写入权限（受限环境、绿色版、CI 下同样可用）。
"""

import os

from PySide6.QtCore import QSettings

from config.constants import DATA_DIR
from config.default_settings import (
    DEFAULT_DOWNLOAD_EXTS, DEFAULT_MAX_DOWNLOAD_MB, DEFAULT_STEALTH_ENABLED,
    DEFAULT_SHOW_CONSOLE,
)

SETTINGS_PATH = os.path.join(DATA_DIR, "settings.ini")


class UserPrefs:
    """持久化用户偏好，属性均为 property（读带默认值，写 setValue）。"""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._settings = QSettings(SETTINGS_PATH, QSettings.Format.IniFormat)
        self._warned = False

    def sync(self) -> None:
        """立即把未落盘的设置写入存储。"""
        self._settings.sync()
        self._check_status()

    def _check_status(self) -> None:
        """配置文件不可写时提示一次（不抛异常，功能降级为「本次运行有效」）。"""
        if self._warned:
            return
        if self._settings.status() != QSettings.Status.NoError:
            self._warned = True
            try:
                from utils.logger import log_warn
                log_warn(f"[prefs] 配置文件不可写，偏好设置本次运行有效：{SETTINGS_PATH}")
            except Exception:
                pass

    def _set(self, key: str, value) -> None:
        """写入并立即落盘（偏好项数量少，逐项同步可避免退出时丢失）。"""
        self._settings.setValue(key, value)
        self._settings.sync()
        self._check_status()

    # --------------------------------------------------------------
    # last_mode: str = "records"
    # --------------------------------------------------------------
    @property
    def last_mode(self) -> str:
        try:
            v = self._settings.value("last_mode", "records")
            return str(v) if v else "records"
        except Exception:
            return "records"

    @last_mode.setter
    def last_mode(self, value) -> None:
        self._set("last_mode", str(value))

    # --------------------------------------------------------------
    # last_delay: float = 1.5
    # --------------------------------------------------------------
    @property
    def last_delay(self) -> float:
        try:
            return float(self._settings.value("last_delay", 1.5))
        except (TypeError, ValueError):
            return 1.5

    @last_delay.setter
    def last_delay(self, value) -> None:
        try:
            self._set("last_delay", float(value))
        except (TypeError, ValueError):
            self._set("last_delay", 1.5)

    # --------------------------------------------------------------
    # last_max_pages: int = 1
    # --------------------------------------------------------------
    @property
    def last_max_pages(self) -> int:
        try:
            return max(1, int(float(self._settings.value("last_max_pages", 1))))
        except (TypeError, ValueError):
            return 1

    @last_max_pages.setter
    def last_max_pages(self, value) -> None:
        try:
            self._set("last_max_pages", max(1, int(float(value))))
        except (TypeError, ValueError):
            self._set("last_max_pages", 1)

    # --------------------------------------------------------------
    # last_autoscroll: bool = True
    # --------------------------------------------------------------
    @property
    def last_autoscroll(self) -> bool:
        v = self._settings.value("last_autoscroll", True)
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("true", "1", "yes", "on")

    @last_autoscroll.setter
    def last_autoscroll(self, value) -> None:
        self._set("last_autoscroll", bool(value))

    # --------------------------------------------------------------
    # last_engine: str = "browser"  (browser / http / stealth / dynamic)
    # --------------------------------------------------------------
    @property
    def last_engine(self) -> str:
        try:
            v = str(self._settings.value("last_engine", "browser") or "browser")
        except Exception:
            return "browser"
        valid = ("browser", "http", "stealth", "dynamic")
        return v if v in valid else "browser"

    @last_engine.setter
    def last_engine(self, value) -> None:
        self._set("last_engine", str(value or "browser"))

    # --------------------------------------------------------------
    # last_adaptive: bool = False  自适应选择器（网站改版自愈）
    # --------------------------------------------------------------
    @property
    def last_adaptive(self) -> bool:
        v = self._settings.value("last_adaptive", False)
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("true", "1", "yes", "on")

    @last_adaptive.setter
    def last_adaptive(self, value) -> None:
        self._set("last_adaptive", bool(value))

    # --------------------------------------------------------------
    # last_profile: str = "default"
    # --------------------------------------------------------------
    @property
    def last_profile(self) -> str:
        try:
            v = self._settings.value("last_profile", "default")
            return str(v) if v else "default"
        except Exception:
            return "default"

    @last_profile.setter
    def last_profile(self, value) -> None:
        self._set("last_profile", str(value))

    # --------------------------------------------------------------
    # default_profile: str = "default"
    # --------------------------------------------------------------
    @property
    def default_profile(self) -> str:
        try:
            v = self._settings.value("default_profile", "default")
            return str(v) if v else "default"
        except Exception:
            return "default"

    @default_profile.setter
    def default_profile(self, value) -> None:
        self._set("default_profile", str(value))

    # --------------------------------------------------------------
    # popup_strategy: str = "close"  (notify/close/remove)
    # --------------------------------------------------------------
    @property
    def popup_strategy(self) -> str:
        try:
            v = str(self._settings.value("popup_strategy", "close"))
        except Exception:
            v = "close"
        return v if v in ("notify", "close", "remove") else "close"

    @popup_strategy.setter
    def popup_strategy(self, value) -> None:
        key = str(value)
        if key not in ("notify", "close", "remove"):
            key = "close"
        self._set("popup_strategy", key)

    # --------------------------------------------------------------
    # last_modes: list[str]  上次勾选的抓取格式（可多选）
    # --------------------------------------------------------------
    @property
    def last_modes(self) -> list:
        raw = self._settings.value("last_modes", "")
        if isinstance(raw, (list, tuple)):
            return [str(x) for x in raw if str(x).strip()]
        if isinstance(raw, str) and raw.strip():
            return [x.strip() for x in raw.split(",") if x.strip()]
        return []

    @last_modes.setter
    def last_modes(self, value) -> None:
        if isinstance(value, (list, tuple)):
            items = [str(x).strip() for x in value if str(x).strip()]
        else:
            items = [x.strip() for x in str(value or "").split(",") if x.strip()]
        self._set("last_modes", ",".join(items))

    # --------------------------------------------------------------
    # export_dir: str  结果导出的默认目录（空 = 使用 EXPORT_DIR）
    # --------------------------------------------------------------
    @property
    def export_dir(self) -> str:
        try:
            v = self._settings.value("export_dir", "")
        except Exception:
            v = ""
        return str(v or "")

    @export_dir.setter
    def export_dir(self, value) -> None:
        self._set("export_dir", str(value or ""))

    # --------------------------------------------------------------
    # max_download_mb: int  单个文件下载大小上限（MB）
    # --------------------------------------------------------------
    @property
    def max_download_mb(self) -> int:
        try:
            v = int(float(self._settings.value(
                "max_download_mb", DEFAULT_MAX_DOWNLOAD_MB)))
        except (TypeError, ValueError):
            v = DEFAULT_MAX_DOWNLOAD_MB
        return v if v >= 0 else DEFAULT_MAX_DOWNLOAD_MB

    @max_download_mb.setter
    def max_download_mb(self, value) -> None:
        try:
            v = max(0, int(float(value)))
        except (TypeError, ValueError):
            v = DEFAULT_MAX_DOWNLOAD_MB
        self._set("max_download_mb", v)

    # --------------------------------------------------------------
    # download_exts: str  只允许下载的扩展名（逗号分隔，空=全部）
    # --------------------------------------------------------------
    @property
    def download_exts(self) -> str:
        try:
            v = self._settings.value("download_exts", DEFAULT_DOWNLOAD_EXTS)
        except Exception:
            v = DEFAULT_DOWNLOAD_EXTS
        return str(v or "")

    @download_exts.setter
    def download_exts(self, value) -> None:
        self._set("download_exts", str(value or ""))

    # --------------------------------------------------------------
    # stealth_enabled: bool  反爬对抗（特征伪装 + 延迟抖动）
    # --------------------------------------------------------------
    @property
    def stealth_enabled(self) -> bool:
        v = self._settings.value("stealth_enabled", DEFAULT_STEALTH_ENABLED)
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("true", "1", "yes", "on")

    @stealth_enabled.setter
    def stealth_enabled(self, value) -> None:
        self._set("stealth_enabled", bool(value))

    # --------------------------------------------------------------
    # show_console: bool = True  是否显示控制台窗口（正式版默认显示）
    # --------------------------------------------------------------
    @property
    def show_console(self) -> bool:
        v = self._settings.value("show_console", DEFAULT_SHOW_CONSOLE)
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("true", "1", "yes", "on")

    @show_console.setter
    def show_console(self, value) -> None:
        self._set("show_console", bool(value))
