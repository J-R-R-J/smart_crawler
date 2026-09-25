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

FORMAT_LABELS = {key: label for key, label, _hint in SUPPORTED_FORMATS}
FORMAT_HINTS = {key: hint for key, _label, hint in SUPPORTED_FORMATS}

# 各格式对配置项的需求（界面据此按需启用输入框；支持多选格式）
NEEDS_SELECTOR = ("records", "list")
NEEDS_FIELDS = ("records",)
NEEDS_PATTERN = ("regex",)

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

# 下载限制：单个文件的下载大小上限（MB），超过则取消
DEFAULT_MAX_DOWNLOAD_MB = 50

# 只允许下载的扩展名（英文逗号分隔，不区分大小写）；空字符串 = 允许全部
DEFAULT_DOWNLOAD_EXTS = ""

# 结果导出默认目录；空字符串表示使用 constants.EXPORT_DIR
DEFAULT_EXPORT_DIR = ""

# 反爬对抗默认开关（浏览器特征伪装 + 拟人化延迟抖动）
DEFAULT_STEALTH_ENABLED = True

# ----------------------------------------------------------------------
# 抓取引擎：决定「页面 HTML 从哪里来」。
#
# 四种引擎最终都会把 HTML 交给同一个渲染引擎与既有流程
# （检测 → 弹窗 → 提取 → 翻页），差别只在**请求是怎么发出的**：
#   · browser 由 QtWebEngine 自己请求并渲染；
#   · 其余三种由 Scrapling 先取回 HTML，再灌入渲染引擎。
# 好处是反检测发生在**请求阶段**（curl_cffi/stealth 浏览器指纹），
# 而后续解析、翻页、结果展示完全复用现有代码。
# ----------------------------------------------------------------------
ENGINE_OPTIONS = [
    ("browser", "浏览器引擎", "QtWebEngine 自行请求并渲染（默认，兼容 JS 站点）"),
    ("http", "HTTP 快速模式", "curl_cffi 伪装浏览器 TLS 指纹，不开浏览器，静态页最快"),
    ("stealth", "隐身引擎", "Scrapling StealthyFetcher，可自动过 Cloudflare 验证"),
    ("dynamic", "动态引擎", "Scrapling DynamicFetcher（Playwright），适合 JS 重的页面"),
]
ENGINE_LABELS = {key: label for key, label, _hint in ENGINE_OPTIONS}
ENGINE_HINTS = {key: hint for key, _label, hint in ENGINE_OPTIONS}

DEFAULT_ENGINE = "browser"
DEFAULT_ADAPTIVE = False          # 是否启用自适应选择器（网站改版自愈）
DEFAULT_ENGINE_TIMEOUT = 30.0     # 非浏览器引擎的单页超时（秒）

# ----------------------------------------------------------------------
# 控制台窗口：正式版 exe 用 console 子系统打包（启动期报错、Qt/Chromium 警告
# 都还能看到），默认显示；用户可在界面里随时隐藏 / 显示，偏好持久化。
# 隐藏只是 ShowWindow(SW_HIDE)，日志照常写 crawler_data\logs\。
# ----------------------------------------------------------------------
DEFAULT_SHOW_CONSOLE = True

__all__ = [
    "SUPPORTED_FORMATS", "FORMAT_LABELS", "FORMAT_HINTS",
    "CAPTCHA_KEYWORDS", "HUMAN_VERIFY_KEYWORDS",
    "LOGIN_KEYWORDS", "POPUP_STRATEGIES", "DEFAULT_POPUP_STRATEGY",
    "POPUP_CLOSE_SELECTORS", "POPUP_HINT_KEYWORDS",
    "DETECT_INTERVAL_MS", "MAX_POPUP_ROUNDS",
    "NEEDS_SELECTOR", "NEEDS_FIELDS", "NEEDS_PATTERN",
    "DEFAULT_MAX_DOWNLOAD_MB", "DEFAULT_DOWNLOAD_EXTS",
    "DEFAULT_EXPORT_DIR", "DEFAULT_STEALTH_ENABLED",
    "ENGINE_OPTIONS", "ENGINE_LABELS", "ENGINE_HINTS",
    "DEFAULT_ENGINE", "DEFAULT_ADAPTIVE", "DEFAULT_ENGINE_TIMEOUT",
    "DEFAULT_SHOW_CONSOLE",
]
