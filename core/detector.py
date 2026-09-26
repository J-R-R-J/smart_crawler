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

**关于「源码里命中、可见区域没有」的误判**（实测踩过的坑）
-------------------------------------------------------
抖音笔记页曾把整个任务拦下来等人处理验证码，日志写着
「命中关键词「captcha」，但未检测到验证码组件」。原因不是关键词表太宽，
而是**搜索范围包含整份 HTML**：那份 HTML 有 1.5 MB，里面某个脚本字符串
恰好含 "captcha"，而页面上根本没有验证码。

所以在**拿到了足够长的渲染文本**（>= ``_MIN_VISIBLE_CHARS``）时，
关键词只在**可见范围**（标题 + 渲染文本 + URL）里比对；
HTML 源码里命中而可见区域没有的，只记一条 ``last_note`` 供日志提示，
**不再拦截任务**。结构探测（输入框 / 验证 iframe / 容器）仍然优先，
因此「有关键词但没有文字提示」的真实验证页依然能被识别。

拿不到渲染文本（调用方没传 text，或页面文本过短 —— 挑战页常常很短）时，
退回原来的「HTML + 可见文本一起搜」的宽松判定，宁可误拦也不漏拦。
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

#: 渲染文本短于这个长度就认为「不可信」，退回宽松判定。
#:
#: 取 20 是因为：Cloudflare 挑战页、登录墙这类页面渲染文本通常也就
#: 一二十个字（"Just a moment..." / "请稍候…"），必须让它们在宽松模式下
#: 被拦住；而正常内容页的 innerText 动辄几千字，用它来压制 HTML 噪声很安全。
_MIN_VISIBLE_CHARS = 20


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
        #: 最近一次 classify 的「非拦截型观察」，例如
        #: 「源码里出现验证码字样但页面可见区域没有」。由调用方（crawler）
        #: 取走写日志 —— 这类信息对排查很有用，但不该拦任务，也不该
        #: 混进 reason（reason 会显示在人工处理横幅上）。
        self.last_note = ""

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
        第 2~4 步的搜索范围见 ``last_note`` 处的说明：拿到足够长的渲染文本时
        只搜可见范围，避免被 HTML 里的脚本字样误伤。
        """
        self.last_note = ""

        visible = normalize_text(" ".join([title or "", text or "", url or ""]))
        visible_sq = squeeze(" ".join([title or "", text or ""]))
        combined = normalize_text(" ".join([html or "", title or "",
                                            text or "", url or ""]))
        combined_sq = squeeze(" ".join([html or "", title or "", text or ""]))
        # 渲染文本够长才敢用它压制 HTML：短文本（挑战页）仍走宽松判定
        trust_visible = len(normalize_text(text or "")) >= _MIN_VISIBLE_CHARS
        hay, hay_sq = (visible, visible_sq) if trust_visible else (combined,
                                                                   combined_sq)

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
        captcha_kws = keyword_store.load("captcha")
        hit = self._match(hay, hay_sq, captcha_kws)
        if hit:
            return ("CAPTCHA",
                    f"疑似验证码：命中关键词「{hit}」，但未检测到验证码组件。"
                    f"若为误判可点击横幅上的「跳过」继续。")
        if trust_visible:
            # 只在源码里命中 → 记录观察，但**不拦任务**（见模块开头的说明）
            html_hit = self._match(combined, combined_sq, captcha_kws)
            if html_hit:
                self.last_note = (
                    f"源码里出现验证码字样「{html_hit}」，但页面可见区域没有，"
                    f"判定为误报（多为脚本/注释里的字样），不拦截任务")

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


__all__ = ["Detector", "normalize_text", "squeeze"]
