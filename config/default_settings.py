# -*- coding: utf-8 -*-
"""默认设置：支持的提取格式、关键词表、弹窗策略与选择器表。"""

SUPPORTED_FORMATS = [
    ("records", "结构化记录", "容器选择器 + 字段映射，适合列表详情页"),
    ("list", "列表文本", "容器选择器下所有文本行"),
    ("table", "表格数据", "提取页面 <table> 的二维数据"),
    ("links", "链接列表", "所有 <a> 的文本与 href"),
    ("images", "图片列表（全格式）", "img/srcset/lazy/背景图/picture/og:image 全覆盖"),
    ("text", "页面文本", "页面纯文本"),
    ("html", "页面 HTML", "完整 HTML 源码"),
    ("regex", "正则提取", "用正则从 HTML 中提取"),
    ("jsonld", "JSON-LD", "结构化数据 <script type=application/ld+json>"),
    ("meta", "Meta 信息", "title/description/keywords 等"),
    ("forms", "表单数据", "所有 <form> 的字段"),
    ("video", "视频地址（全格式）", "video/source/poster/HLS(m3u8)/og:video/内嵌 JSON"),
    ("audio", "音频地址（全格式）", "audio/source/og:audio/内嵌 JSON 里的音频直链"),
    ("media", "全部媒体（图+视+音）", "一次抓齐三类媒体，带 kind 列区分来源"),
    ("iframe", "iframe 地址", "所有 <iframe> 的 src"),
    ("rss", "RSS 订阅", "页面声明的 RSS/Atom feed"),
    ("sitemap", "Sitemap", "页面声明的 sitemap 链接"),
    ("contacts", "联系方式", "邮箱/电话"),
    ("embedded_json", "内嵌 JSON", "页面中内嵌的 JSON 脚本块"),
    ("page_cookies", "页面 Cookie", "当前页面的 Cookie 快照"),
]

# ----------------------------------------------------------------------
# 媒体扩展名表（图片 / 视频 / 音频）
#
# 这是**唯一真值来源**：提取脚本（config.js_scripts）用它生成识别 URL 的
# 正则，下载白名单预设（DOWNLOAD_PRESET_*）用它拼扩展名列表。
# 两处各写一份是以前的坑 —— 加了新格式只改了一边，另一边静默不认。
#
# 视频里的 m3u8 / mpd 不是「文件扩展名」而是流媒体清单；它们同样算视频，
# 因为抓下来之后用户真正要的是那个清单（可交给 ffmpeg / N_m3u8DL 下载），
# 而且站点几乎总是把真正的分片地址写在清单里。
# ----------------------------------------------------------------------
IMAGE_EXTS = (
    "jpg", "jpeg", "jfif", "png", "apng", "gif", "webp", "avif", "bmp",
    "svg", "ico", "cur", "tif", "tiff", "heic", "heif", "jxl",
)
VIDEO_EXTS = (
    "mp4", "m4v", "webm", "mkv", "mov", "qt", "avi", "flv", "f4v", "wmv",
    "mpg", "mpeg", "mpe", "ts", "m2ts", "mts", "3gp", "3g2", "ogv", "rmvb",
    "rm", "vob", "asf", "divx", "m3u8", "m3u", "mpd", "m4s", "ism",
)
AUDIO_EXTS = (
    "mp3", "m4a", "m4b", "aac", "wav", "flac", "ogg", "oga", "opus", "wma",
    "aiff", "aif", "amr", "ac3", "ape", "mid", "midi", "weba", "mka", "ra",
)

#: 三类媒体扩展名（key -> tuple），供界面与提取脚本遍历。
MEDIA_EXTS = {
    "image": IMAGE_EXTS,
    "video": VIDEO_EXTS,
    "audio": AUDIO_EXTS,
}

#: 全部媒体扩展名（去重保序），下载白名单「仅媒体」预设用。
ALL_MEDIA_EXTS = tuple(dict.fromkeys(IMAGE_EXTS + VIDEO_EXTS + AUDIO_EXTS))

#: 文档类扩展名（下载白名单「文档」预设用）。
DOC_EXTS = (
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md", "csv",
    "tsv", "json", "xml", "rtf", "odt", "ods", "odp", "epub", "mobi", "azw3",
)

# ----------------------------------------------------------------------
# 下载格式预设：把扩展名白名单从「手打一串」变成「选一类」。
#
# 为什么要预设：图片/视频/音频的扩展名加起来有 60 多个，
# 让用户自己敲既容易漏（漏一个格式就静默不下载），也容易敲错。
# ----------------------------------------------------------------------
DOWNLOAD_PRESET_KEYS = ("all", "media", "image", "video", "audio",
                        "image_video", "doc", "archive")

DOWNLOAD_PRESET_LABELS = {
    "all": "不限格式（全部允许）",
    "media": "仅媒体（图片+视频+音频）",
    "image": "仅图片",
    "video": "仅视频（含 m3u8 / mpd 流）",
    "audio": "仅音频",
    "image_video": "图片 + 视频",
    "doc": "文档（pdf / office / 文本）",
    "archive": "压缩包与安装包",
}

_ARCHIVE_EXTS = ("zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz", "iso")
#: 公开别名：utils.media_files 判断「能不能当文件导出」时要用
ARCHIVE_EXTS = _ARCHIVE_EXTS


def preset_exts(key: str) -> str:
    """把预设 key 展开成逗号分隔的扩展名串；未知 key 返回空串（=不限）。"""
    key = (key or "").strip().lower()
    if key in ("", "all"):
        return ""
    table = {
        "media": ALL_MEDIA_EXTS,
        "image": IMAGE_EXTS,
        "video": VIDEO_EXTS,
        "audio": AUDIO_EXTS,
        "image_video": IMAGE_EXTS + VIDEO_EXTS,
        "doc": DOC_EXTS,
        "archive": _ARCHIVE_EXTS,
    }
    return ",".join(table.get(key, ()))


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
# 反检测强化：六个子项，默认全开
#
# 为什么默认全开：这六项都是「只有好处、没有代价」的方向 ——
# 它们让浏览器的行为更接近真用户，而不是更像自动化工具。
# 唯一的例外是「拦截广告素材」，那一条默认**关**（见 core.antibot 的说明：
# 拦掉可见广告位会被站点的反广告脚本识破）。
#
# 唯一可能影响抓取结果的是「拦截追踪器」：极少数站点把业务接口放在
# 被拦的第三方域名上（罕见）。所以界面里给它单独一个开关 + 一条
# 「页面缺内容时先关它」的提示。
# ----------------------------------------------------------------------
DEFAULT_BLOCK_TRACKERS = True        # 抗广告/追踪器干扰（拦第三方埋点请求）
DEFAULT_BLOCK_AD_CREATIVES = False   # 是否连可见广告素材一起拦（默认关）
DEFAULT_HIDE_CANVAS = True           # Canvas / WebGL 指纹干扰
DEFAULT_BLOCK_WEBRTC = True          # WebRTC 真实 IP 泄露防护
DEFAULT_AUTO_CLOUDFLARE = True       # 识别并自动绕过 Cloudflare JS 挑战
DEFAULT_AUTO_HEADERS = True          # 自动生成自洽的真实请求头
DEFAULT_TLS_SPOOF = True             # TLS 指纹伪装（curl_cffi 档位）

#: 反检测强化总开关的默认值（关掉它 = 六项全部关闭，用于排查「是不是伪装导致的」）
DEFAULT_ANTIBOT_ENABLED = True

#: 界面里「反检测强化」子项的展示顺序与文案：(prefs 键, 名称, 说明)
ANTIBOT_ITEMS = (
    ("block_trackers", "抗广告/追踪器干扰",
     "拦截第三方埋点/广告域名请求，避免它们扰动滚动、插浮层、上报行为"),
    ("auto_headers", "自动生成真实请求头",
     "按请求类型补齐 Accept / Sec-Fetch-* / sec-ch-ua，并与 UA 版本同源"),
    ("tls_spoof", "TLS 指纹伪装",
     "HTTP 快速模式用 curl_cffi 伪装浏览器 TLS 握手特征（JA3/JA4）"),
    ("hide_canvas", "Canvas 指纹干扰",
     "给 canvas / WebGL 读像素加每次都一致的微小噪声，打断指纹唯一性"),
    ("block_webrtc", "WebRTC 泄露防护",
     "禁止 WebRTC 收集本机/内网 IP，避免真实地址绕过代理泄露"),
    ("auto_cloudflare", "Cloudflare 自动绕过",
     "识别 JS 挑战后自动改用隐身引擎重试；交互式验证仍交由人工"),
)


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
    "IMAGE_EXTS", "VIDEO_EXTS", "AUDIO_EXTS", "MEDIA_EXTS", "ALL_MEDIA_EXTS",
    "DOC_EXTS", "ARCHIVE_EXTS", "DOWNLOAD_PRESET_KEYS", "DOWNLOAD_PRESET_LABELS",
    "preset_exts",
    "CAPTCHA_KEYWORDS", "HUMAN_VERIFY_KEYWORDS",
    "LOGIN_KEYWORDS", "POPUP_STRATEGIES", "DEFAULT_POPUP_STRATEGY",
    "POPUP_CLOSE_SELECTORS", "POPUP_HINT_KEYWORDS",
    "DETECT_INTERVAL_MS", "MAX_POPUP_ROUNDS",
    "NEEDS_SELECTOR", "NEEDS_FIELDS", "NEEDS_PATTERN",
    "DEFAULT_MAX_DOWNLOAD_MB", "DEFAULT_DOWNLOAD_EXTS",
    "DEFAULT_EXPORT_DIR", "DEFAULT_STEALTH_ENABLED",
    "DEFAULT_BLOCK_TRACKERS", "DEFAULT_BLOCK_AD_CREATIVES",
    "DEFAULT_HIDE_CANVAS", "DEFAULT_BLOCK_WEBRTC",
    "DEFAULT_AUTO_CLOUDFLARE", "DEFAULT_AUTO_HEADERS", "DEFAULT_TLS_SPOOF",
    "DEFAULT_ANTIBOT_ENABLED", "ANTIBOT_ITEMS",
    "ENGINE_OPTIONS", "ENGINE_LABELS", "ENGINE_HINTS",
    "DEFAULT_ENGINE", "DEFAULT_ADAPTIVE", "DEFAULT_ENGINE_TIMEOUT",
    "DEFAULT_SHOW_CONSOLE",
]
