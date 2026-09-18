# -*- coding: utf-8 -*-
"""core.detector —— 页面状态分类（CAPTCHA / HUMAN / LOGIN / NONE）。

检查顺序：CAPTCHA → HUMAN → LOGIN → NONE；
LOGIN 需同时满足关键词命中 + html 存在 password 输入框特征。

检测增强（针对常见反爬伪装手法）：

1. 同时检测 **HTML 源码**、**页面标题**、**URL** 与 **渲染后的可见纯文本**
   （innerText）。有些站点的关键词由 JS 动态渲染、或写在 CSS content 里，
   源码中根本不存在，但可见文本里是明文；
2. 归一化：去除零宽字符（\\u200b-\\u200d、\\u2060、\\ufeff、软连字符）并折叠
   空白，可识破「验\\u200b证\\u200b码」这类插入干扰字符的写法；
3. 去空白后再比对一次，可识破「验 证 码」这类字符间隔写法。

关键词来自 `config.keyword_store`（默认值取自 default_settings，
用户可在界面中自定义）。
"""

import re

from PySide6.QtCore import QObject, Signal

from config import keyword_store

# type="password"（引号可有可无）或 name 属性含 "pass"
_PASSWORD_INPUT_RE = re.compile(
    r"""type\s*=\s*["']?password(?:["'\s>/]|$)|
        name\s*=\s*["'][^"']*pass[^"']*["']""",
    re.IGNORECASE | re.VERBOSE,
)

# 零宽 / 不可见干扰字符
_INVISIBLE_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")
_WS_RE = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    """小写 + 去零宽字符 + 折叠空白。"""
    if not s:
        return ""
    s = _INVISIBLE_RE.sub("", str(s))
    s = s.replace("\u3000", " ")          # 全角空格
    return _WS_RE.sub(" ", s).strip().lower()


def squeeze(s: str) -> str:
    """在归一化基础上彻底去掉空白，用于识破字符间隔式伪装。"""
    return _WS_RE.sub("", normalize_text(s))


class Detector(QObject):
    detected = Signal(str, str)            # level, reason

    def __init__(self, parent=None):
        super().__init__(parent)

    # ------------------------------------------------------------------
    @staticmethod
    def _has_password_input(html: str) -> bool:
        if not html:
            return False
        return bool(_PASSWORD_INPUT_RE.search(html))

    @staticmethod
    def _match(hay: str, hay_squeezed: str, keywords) -> str:
        """返回命中的关键词；未命中返回空串。"""
        for kw in keywords or []:
            k = normalize_text(kw)
            if not k:
                continue
            if k in hay:
                return kw
            k2 = squeeze(kw)
            if k2 and k2 in hay_squeezed:
                return kw
        return ""

    def classify(self, html: str, title: str = "", url: str = "",
                 text: str = "", captcha_forms=None, login_form=None) -> tuple:
        """返回 (level, reason)；level ∈ {CAPTCHA, HUMAN, LOGIN, NONE}。

        参数
        ----
        text          渲染后的可见纯文本（body.innerText），强烈建议传入
        captcha_forms CAPTCHA_PROBE_JS 的结构化探测结果（dict），用于**确认**验证码
        login_form    LOGIN_PROBE_JS 的结构化探测结果，用于**确认**登录表单

        判定优先级
        ----------
        1. 探测到验证码组件（输入框 / 第三方 iframe / 已知容器）→ CAPTCHA（已确认）
        2. 仅命中验证码关键词、但没有对应组件 → CAPTCHA（疑似，可在横幅点「跳过」）
        3. 命中访问频控关键词 → HUMAN
        4. 存在密码输入框且命中登录关键词 → LOGIN
        5. 否则 NONE

        说明：第 1 步不看关键词，因此没有文字提示的裸验证组件也能被识别；
        第 2 步保留关键词兜底，避免漏判，但会在原因中标明「疑似」。
        """
        hay = normalize_text(" ".join([html or "", title or "",
                                       text or "", url or ""]))
        hay_sq = squeeze(" ".join([html or "", title or "", text or ""]))

        # ---- 1. 结构确认：验证码组件 ----
        kinds = []
        details = []
        if isinstance(captcha_forms, dict):
            kinds = [str(k) for k in (captcha_forms.get("kinds") or [])]
            details = [str(d) for d in (captcha_forms.get("details") or [])]
        if kinds:
            kind_label = {
                "input": "验证码输入框",
                "iframe": "验证组件 iframe",
                "container": "验证组件容器",
                "image": "图形验证码",
            }
            names = "、".join(kind_label.get(k, k) for k in kinds)
            sample = f"（{details[0]}）" if details else ""
            return ("CAPTCHA", f"检测到{names}{sample}，已确认为验证码")

        # ---- 2. 关键词兜底：疑似验证码 ----
        hit = self._match(hay, hay_sq, keyword_store.load("captcha"))
        if hit:
            return ("CAPTCHA",
                    f"疑似验证码：命中关键词「{hit}」，但未检测到验证码组件。"
                    f"若为误判可点击横幅上的「跳过」继续。")

        # ---- 3. 访问频控 ----
        hit = self._match(hay, hay_sq, keyword_store.load("human"))
        if hit:
            return ("HUMAN", f"检测到访问频控关键词：{hit}")

        # ---- 4. 登录墙 ----
        login_confirmed = False
        if isinstance(login_form, dict):
            login_confirmed = bool(login_form.get("found"))
        if login_confirmed or self._has_password_input(html or ""):
            hit = self._match(hay, hay_sq, keyword_store.load("login"))
            if hit:
                tail = "已确认登录表单" if login_confirmed else "检测到密码输入框"
                return ("LOGIN", f"登录墙（{tail}）：{hit}")

        return ("NONE", "")

    # ------------------------------------------------------------------
    def is_blocked(self, html: str, title: str = "", url: str = "",
                   text: str = "", captcha_forms=None, login_form=None) -> bool:
        return self.classify(html, title, url, text,
                             captcha_forms, login_form)[0] != "NONE"

    def requires_human(self, html: str, title: str = "", url: str = "",
                       text: str = "", captcha_forms=None) -> bool:
        return self.classify(html, title, url, text,
                             captcha_forms)[0] in ("CAPTCHA", "HUMAN")
