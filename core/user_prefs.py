# -*- coding: utf-8 -*-
"""core.user_prefs —— 基于 QSettings("SmartCrawler", "SmartCrawler") 的用户偏好。"""

from PySide6.QtCore import QSettings


class UserPrefs:
    """持久化用户偏好，属性均为 property（读带默认值，写 setValue）。"""

    def __init__(self):
        self._settings = QSettings("SmartCrawler", "SmartCrawler")

    def sync(self) -> None:
        """立即把未落盘的设置写入存储。"""
        self._settings.sync()

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
        self._settings.setValue("last_mode", str(value))

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
            self._settings.setValue("last_delay", float(value))
        except (TypeError, ValueError):
            self._settings.setValue("last_delay", 1.5)

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
            self._settings.setValue("last_max_pages", max(1, int(float(value))))
        except (TypeError, ValueError):
            self._settings.setValue("last_max_pages", 1)

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
        self._settings.setValue("last_autoscroll", bool(value))

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
        self._settings.setValue("last_profile", str(value))

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
        self._settings.setValue("default_profile", str(value))

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
        self._settings.setValue("popup_strategy", key)
