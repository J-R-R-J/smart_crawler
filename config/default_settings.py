# -*- coding: utf-8 -*-
"""默认设置：支持的提取格式、关键词表、弹窗策略与选择器表。"""

SUPPORTED_FORMATS = [
    ("records", "结构化记录", "容器选择器 + 字段映射，适合列表详情页"),
    ("list", "列表文本", "容器选择器下所有文本行"),
    ("table", "表格数据", "提取页面 <table> 的二维数据"),
    ("links", "链接列表", "所有 <a> 的文本与 href"),
    ("images", "图片列表", "所有 <img> 的 src/alt"),
    ("text", "页面文本", "页面纯文本"),
    ("html", "页面 HTML", "完整 HTML 源码"),
    ("regex", "正则提取", "用正则从 HTML 中提取"),
    ("jsonld", "JSON-LD", "结构化数据 <script type=application/ld+json>"),
    ("meta", "Meta 信息", "title/description/keywords 等"),
    ("forms", "表单数据", "所有 <form> 的字段"),
    ("video", "视频地址", "所有 <video>/<source> 地址"),
    ("iframe", "iframe 地址", "所有 <iframe> 的 src"),
    ("rss", "RSS 订阅", "页面声明的 RSS/Atom feed"),
    ("sitemap", "Sitemap", "页面声明的 sitemap 链接"),
    ("contacts", "联系方式", "邮箱/电话"),
    ("embedded_json", "内嵌 JSON", "页面中内嵌的 JSON 脚本块"),
    ("page_cookies", "页面 Cookie", "当前页面的 Cookie 快照"),
]

CAPTCHA_KEYWORDS = [
    "captcha", "验证码", "人机验证", "verify you are human", "are you a robot",
    "请完成验证", "请完成安全验证", "拖动滑块", "滑块验证", "slider verification",
    "security check", "安全检查", "cf-challenge", "challenge-platform", "turnstile",
    "hcaptcha", "recaptcha", "cloudflare", "ray id",
]

HUMAN_VERIFY_KEYWORDS = [
    "访问过于频繁", "请求过于频繁", "abnormal access", "unusual traffic",
    "请稍后再试", "temporarily blocked", "access denied",
]

LOGIN_KEYWORDS = [
    "login", "sign in", "log in", "请先登录", "请登录", "登录后", "账号", "密码",
    "password", "登入",
]

POPUP_STRATEGIES = [
    ("notify", "只报告", "只在日志里记录弹窗信息，不干预"),
    ("close", "点关闭按钮", "尝试点击关闭按钮（默认，推荐）"),
    ("remove", "直接移除 DOM", "强行删除弹窗节点，最强力，可能误伤"),
]

DEFAULT_POPUP_STRATEGY = "close"

POPUP_CLOSE_SELECTORS = [
    ".close",
    ".modal-close",
    "[aria-label='Close']",
    "[aria-label='close']",
    "[data-dismiss='modal']",
    ".btn-close",
    ".popup-close",
    ".dialog-close",
    "button.close",
    "[class*='close']:not([class*='closet'])",
]

POPUP_HINT_KEYWORDS = [
    "modal", "dialog", "popup", "弹窗", "pop-over", "lightbox", "overlay",
]

DETECT_INTERVAL_MS = 2000      # 人类验证轮询间隔（毫秒）
MAX_POPUP_ROUNDS = 3           # 每次加载后弹窗处理最大轮数

__all__ = [
    "SUPPORTED_FORMATS", "CAPTCHA_KEYWORDS", "HUMAN_VERIFY_KEYWORDS",
    "LOGIN_KEYWORDS", "POPUP_STRATEGIES", "DEFAULT_POPUP_STRATEGY",
    "POPUP_CLOSE_SELECTORS", "POPUP_HINT_KEYWORDS",
    "DETECT_INTERVAL_MS", "MAX_POPUP_ROUNDS",
]
