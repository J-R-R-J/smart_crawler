# -*- coding: utf-8 -*-
"""core.detector —— 页面状态分类（CAPTCHA / HUMAN / LOGIN / NONE）。

检查顺序：CAPTCHA → HUMAN → LOGIN → NONE；
LOGIN 需同时满足关键词命中 + html 存在 password 输入框特征。
"""

import re

from PySide6.QtCore import QObject, Signal

from config.default_settings import (
    CAPTCHA_KEYWORDS,
    HUMAN_VERIFY_KEYWORDS,
    LOGIN_KEYWORDS,
)


# type="password"（引号可有可无）或 name 属性含 "pass"
_PASSWORD_INPUT_RE = re.compile(
    r"""type\s*=\s*["']?password(?:["'\s>/]|$)|
        name\s*=\s*["'][^"']*pass[^"']*["']""",
    re.IGNORECASE | re.VERBOSE,
)


class Detector(QObject):
    detected = Signal(str, str)            # level, reason

    def __init__(self, parent=None):
        super().__init__(parent)

    @staticmethod
    def _has_password_input(html: str) -> bool:
        if not html:
            return False
        return bool(_PASSWORD_INPUT_RE.search(html))

    def classify(self, html: str, title: str = "", url: str = "") -> tuple:
        """返回 (level, reason)；level ∈ {CAPTCHA, HUMAN, LOGIN, NONE}。"""
        text = f"{html or ''} {title or ''}".lower()

        for kw in CAPTCHA_KEYWORDS:
            if kw and kw.lower() in text:
                return ("CAPTCHA", f"检测到验证码关键词：{kw}")

        for kw in HUMAN_VERIFY_KEYWORDS:
            if kw and kw.lower() in text:
                return ("HUMAN", f"检测到人工验证关键词：{kw}")

        if self._has_password_input(html or ""):
            for kw in LOGIN_KEYWORDS:
                if kw and kw.lower() in text:
                    return ("LOGIN", "检测到登录墙")

        return ("NONE", "")

    def is_blocked(self, html: str, title: str = "", url: str = "") -> bool:
        return self.classify(html, title, url)[0] != "NONE"

    def requires_human(self, html: str, title: str = "", url: str = "") -> bool:
        return self.classify(html, title, url)[0] in ("CAPTCHA", "HUMAN")
