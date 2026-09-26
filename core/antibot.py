# -*- coding: utf-8 -*-
"""core.antibot —— 抗广告/追踪干扰、Cloudflare 识别与反检测策略。

本模块做三件事，它们互相独立，可分别开关：

1. **网络层拦截追踪器**（``TrackerInterceptor``）
   广告与分析脚本对爬虫的伤害比想象中大：它们会劫持滚动位置改懒加载、
   往 DOM 里插各种浮层、在你不注意时发起几十个请求拖慢页面，
   还会把「这次访问的滚动深度与停留时长」上报给风控。
   这里在第一方域名之外按规则拦掉它们的请求。

   **只拦追踪器，不拦广告素材**（``DEFAULT_BLOCK_AD_CREATIVES = False``）：
   把 AdSense 那种可见广告位也拦掉，等于向站点的反广告脚本自首 ——
   它们正是靠「广告元素是否加载成功」来判断你装没装拦截器。
   这个取舍写在这里，免得以后有人"顺手"把广告也加上。

2. **识别 Cloudflare 挑战**（``is_cloudflare_challenge``）
   区分「能自动过的 JS 挑战」与「必须人工点的 Turnstile」。
   前者交给 Scrapling 的隐身引擎自动处理，后者直接提示用户，
   而不是像以前那样一律停下来等人。

3. **反广告检测**（``ANTI_ADBLOCK_JS`` 在 config/js_scripts.py 里）
   把常见的反广告探测变量（``canRunAds`` / ``adsbygoogle``）填成正常值，
   并拆掉「请关闭广告拦截插件」的遮罩。

明确不拦的域名
--------------
``NEVER_BLOCK`` 里是风控 / 人机校验服务（Cloudflare、DataDome、PerimeterX…）。
拦住它们**不会**让站点放行，只会让站点立刻判定你在屏蔽检测脚本，
从而从「可疑」升级为「已确认自动化」。
"""

import re
from typing import Dict, List, Optional, Tuple

from config.default_settings import (
    DEFAULT_BLOCK_AD_CREATIVES, DEFAULT_BLOCK_TRACKERS,
)
from utils.logger import log_info, log_warn

# ======================================================================
# 规则表
# ======================================================================
#: (匹配串, 分类)。匹配串规则：
#:   · 含 ``/``  -> 在完整 URL 上做**前缀/子串**匹配（用于按路径拦，如
#:                   ``google.com/ads``）
#:   · 不含 ``/`` -> 按主机名匹配，要求 ``host == 规则`` 或
#:                   ``host.endswith("." + 规则)``
#:
#: **必须是后缀匹配，不能是子串匹配**：用子串匹配的话，规则 ``ad.doubleclick.net``
#: 会误伤 ``notad.doubleclick.net.example.com``，而规则 ``ads.com`` 会误伤
#: 任何含 ``ads.com`` 的域名。这类误伤会表现出「某些站点莫名加载不全」。
TRACKER_RULES: Tuple[Tuple[str, str], ...] = (
    # ---- 分析 / 埋点 ----
    ("google-analytics.com", "analytics"),
    ("analytics.google.com", "analytics"),
    ("googletagmanager.com", "analytics"),
    ("googletagservices.com", "analytics"),
    ("ssl.google-analytics.com", "analytics"),
    ("stats.g.doubleclick.net", "analytics"),
    ("hm.baidu.com", "analytics"),
    ("tongji.baidu.com", "analytics"),
    ("cnzz.com", "analytics"),
    ("umeng.com", "analytics"),
    ("umengcloud.com", "analytics"),
    ("talkingdata.com", "analytics"),
    ("talkingdata.net", "analytics"),
    ("growingio.com", "analytics"),
    ("sensorsdata.cn", "analytics"),
    ("zhugeio.com", "analytics"),
    ("mixpanel.com", "analytics"),
    ("segment.com", "analytics"),
    ("segment.io", "analytics"),
    ("amplitude.com", "analytics"),
    ("heap.io", "analytics"),
    ("heapanalytics.com", "analytics"),
    ("matomo.cloud", "analytics"),
    ("piwik.pro", "analytics"),
    ("plausible.io", "analytics"),
    ("countly.com", "analytics"),
    ("clicky.com", "analytics"),
    ("chartbeat.com", "analytics"),
    ("chartbeat.net", "analytics"),
    ("quantserve.com", "analytics"),
    ("scorecardresearch.com", "analytics"),
    ("comscore.com", "analytics"),
    ("quantcount.com", "analytics"),
    ("newrelic.com", "analytics"),
    ("nr-data.net", "analytics"),
    ("bugsnag.com", "analytics"),
    ("logrocket.com", "analytics"),
    ("lr-ingest.io", "analytics"),
    ("mouseflow.com", "analytics"),
    ("smartlook.com", "analytics"),
    ("inspectlet.com", "analytics"),
    ("crazyegg.com", "analytics"),
    ("hotjar.com", "analytics"),
    ("hotjar.io", "analytics"),
    ("fullstory.com", "analytics"),
    ("clarity.ms", "analytics"),
    ("yandex.ru/metrika", "analytics"),
    ("mc.yandex.ru", "analytics"),
    ("stat.qq.com", "analytics"),
    ("pingjs.qq.com", "analytics"),
    ("mta.qq.com", "analytics"),
    ("dc.railgun.works", "analytics"),
    # ---- 广告 / 归因 ----
    ("doubleclick.net", "ads"),
    ("googleadservices.com", "ads"),
    ("googlesyndication.com", "ads"),
    ("adservice.google.com", "ads"),
    ("pagead2.googlesyndication.com", "ads"),
    ("adnxs.com", "ads"),
    ("adsrvr.org", "ads"),
    ("amazon-adsystem.com", "ads"),
    ("criteo.com", "ads"),
    ("criteo.net", "ads"),
    ("taboola.com", "ads"),
    ("outbrain.com", "ads"),
    ("pubmatic.com", "ads"),
    ("rubiconproject.com", "ads"),
    ("openx.net", "ads"),
    ("casalemedia.com", "ads"),
    ("smartadserver.com", "ads"),
    ("media.net", "ads"),
    ("sharethrough.com", "ads"),
    ("teads.tv", "ads"),
    ("yieldmo.com", "ads"),
    ("33across.com", "ads"),
    ("gumgum.com", "ads"),
    ("sovrn.com", "ads"),
    ("lijit.com", "ads"),
    ("districtm.io", "ads"),
    ("adform.net", "ads"),
    ("adroll.com", "ads"),
    ("bidswitch.net", "ads"),
    ("seedtag.com", "ads"),
    ("adition.com", "ads"),
    ("improvedigital.com", "ads"),
    ("360yield.com", "ads"),
    ("ads.yahoo.com", "ads"),
    ("ads.linkedin.com", "ads"),
    ("px.ads.linkedin.com", "ads"),
    ("ads-twitter.com", "ads"),
    ("analytics.tiktok.com", "ads"),
    ("business-api.tiktok.com", "ads"),
    ("bat.bing.com", "ads"),
    ("c.bing.com", "ads"),
    ("connect.facebook.net", "ads"),
    ("facebook.com/tr", "ads"),
    ("pos.baidu.com", "ads"),
    ("cpro.baidu.com", "ads"),
    ("cbjs.baidu.com", "ads"),
    ("mobads.baidu.com", "ads"),
    ("gdt.qq.com", "ads"),
    ("e.qq.com", "ads"),
    ("tanx.com", "ads"),
    ("alimama.com", "ads"),
    ("ipinyou.com", "ads"),
    ("mediav.com", "ads"),
    ("miaozhen.com", "ads"),
    ("admaster.com.cn", "ads"),
    # ---- 社交 / 会话录制（会录你的鼠标轨迹） ----
    ("platform.twitter.com/widgets", "social"),
    ("platform.instagram.com", "social"),
    ("log.pinterest.com", "social"),
)

#: 风控 / 人机校验服务：**永远不拦**。
#:
#: 拦掉它们等于当着站点的面捂住它的眼睛。特别注意 ``challenges.cloudflare.com``
#: 与 ``turnstile``：Cloudflare 挑战页自己就要从这里取 JS，
#: 拦了之后挑战永远过不去，表现为「卡在验证页」。
NEVER_BLOCK: Tuple[str, ...] = (
    "cloudflare.com", "cloudflareinsights.com", "challenges.cloudflare.com",
    "cdnjs.cloudflare.com", "cfdata", "turnstile",
    "datadome.co", "captcha-delivery.com",
    "perimeterx.net", "px-cdn.net", "px-cloud.net",
    "imperva.com", "incapsula.com",
    "akamaihd.net", "akamai.net", "akamaized.net",
    "kasada.io", "kasadaproxy.com",
    "hcaptcha.com", "recaptcha.net", "google.com/recaptcha",
    "geetest.com", "geetest.cn",
    "f5.com", "shape.io", "forter.com",
    "aliyuncs.com", "aliyun.com",   # 阿里云盾
    "tencentcloudapi.com", "captcha.qq.com",
    "fpjs.io", "fingerprintjs.com", "fingerprint.com",
    "arkoselabs.com", "funcaptcha.com",
)

#: 拦截分类的中文说明（界面与日志用）。
CATEGORY_LABELS = {
    "analytics": "分析/埋点",
    "ads": "广告/归因",
    "social": "社交组件",
}

#: 默认开关：拦追踪器，但**不拦可见广告素材**（原因见模块开头）。
#: 这两个默认值放在 config.default_settings（用户偏好的唯一真值来源），
#: 这里只是转发，避免出现「配置里写开、代码里写关」的分裂。
DEFAULT_CATEGORIES = ("analytics",) + (
    ("ads",) if DEFAULT_BLOCK_AD_CREATIVES else ())


def default_categories(block_creatives: bool = DEFAULT_BLOCK_AD_CREATIVES) -> tuple:
    """按「是否连广告素材一起拦」返回分类元组。"""
    return ("analytics", "social") + (("ads",) if block_creatives else ())


def _host_of(url: str) -> str:
    try:
        from urllib.parse import urlsplit
        return (urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def _registrable(host: str) -> str:
    parts = [p for p in (host or "").split(".") if p]
    return ".".join(parts[-2:]) if len(parts) > 2 else ".".join(parts)


def _match_rule(url: str, host: str, rules=TRACKER_RULES) -> Optional[Tuple[str, str]]:
    """返回命中的 (规则, 分类)；未命中返回 None。"""
    if not url:
        return None
    for pattern, category in rules:
        if "/" in pattern:
            if pattern in url:
                return (pattern, category)
        else:
            if host == pattern or host.endswith("." + pattern):
                return (pattern, category)
    return None


def is_never_blocked(host: str) -> bool:
    """该主机是否属于永不拦截的白名单（风控 / 校验服务）。"""
    if not host:
        return False
    for pattern in NEVER_BLOCK:
        if "/" in pattern:
            continue
        if host == pattern or host.endswith("." + pattern):
            return True
    return False


def should_block(url: str, first_party: str = "", kind: str = "xhr",
                 categories=DEFAULT_CATEGORIES) -> Optional[Tuple[str, str]]:
    """纯函数版的拦截判定（供拦截器与测试共用）。

    返回命中的 (规则, 分类) 表示应拦截；返回 None 表示放行。

    放行规则（顺序很重要）：
      1. 导航请求（document / subframe）一律放行 —— 拦掉主文档就是拦自己；
      2. 第一方（同一可注册域）一律放行；
      3. NEVER_BLOCK 一律放行；
      4. 其余按规则表与分类开关判定。
    """
    host = _host_of(url)
    if not host:
        return None
    if kind in ("document", "subframe"):
        return None
    if not categories:
        return None
    fp = _registrable(_host_of(first_party))
    if fp and _registrable(host) == fp:
        return None
    if is_never_blocked(host):
        return None
    hit = _match_rule(url, host)
    if hit and hit[1] in categories:
        return hit
    return None


# ======================================================================
# 网络层拦截器（QtWebEngine）
# ======================================================================
#: 资源类型 -> 我们自己的请求类型（决定 Accept / Sec-Fetch-*）
_RESOURCE_TO_KIND = {
    "ResourceTypeMainFrame": "document",
    "ResourceTypeSubFrame": "document",
    "ResourceTypeStylesheet": "css",
    "ResourceTypeScript": "script",
    "ResourceTypeImage": "image",
    "ResourceTypeFontResource": "font",
    "ResourceTypeMedia": "media",
    "ResourceTypeXhr": "xhr",
    "ResourceTypeFavicon": "image",
    "ResourceTypePing": "xhr",
    "ResourceTypeObject": "media",
    "ResourceTypeJson": "xhr",
}


def kind_of_resource_type(resource_type) -> str:
    """把 Qt 的 ResourceType 枚举名映射成 core.headers 的 kind。"""
    name = getattr(resource_type, "name", "") or str(resource_type)
    return _RESOURCE_TO_KIND.get(name, "xhr")


class TrackerInterceptor:  # 真正的基类在下面按需绑定，见 _interceptor_base()
    """拦截第三方追踪器，并补齐真实浏览器才有的请求头。

    为什么两件事放在一个拦截器里
    ----------------------------
    QtWebEngine 只允许 Profile 上挂**一个** ``QWebEngineUrlRequestInterceptor``
    （后设置的会替换先设置的），所以「拦追踪器」与「补请求头」必须共用
    同一个实例，否则后加的那个会静默失效。
    """

    def __init__(self, *, block_trackers: bool = DEFAULT_BLOCK_TRACKERS,
                 block_creatives: bool = DEFAULT_BLOCK_AD_CREATIVES,
                 add_headers: bool = True, parent=None):
        self._enabled = bool(block_trackers)
        self._categories = default_categories(block_creatives)
        self._headers_on = bool(add_headers)
        self._blocked: Dict[str, int] = {}
        self._samples: List[str] = []
        self._requests = 0

    # ---- 配置 ----
    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value) -> None:
        self._enabled = bool(value)

    @property
    def block_creatives(self) -> bool:
        return "ads" in self._categories

    @block_creatives.setter
    def block_creatives(self, value) -> None:
        self._categories = default_categories(bool(value))

    @property
    def add_headers(self) -> bool:
        return self._headers_on

    @add_headers.setter
    def add_headers(self, value) -> None:
        self._headers_on = bool(value)

    @property
    def categories(self) -> tuple:
        return tuple(self._categories)

    # ---- 统计 ----
    def stats(self) -> Dict[str, int]:
        """按分类返回拦截次数（副本）。"""
        return dict(self._blocked)

    def total_blocked(self) -> int:
        return sum(self._blocked.values())

    def summary(self) -> str:
        """一行可读的统计，供日志与界面显示。"""
        if not self._enabled:
            return "已关闭"
        if not self._blocked:
            return f"已开启（本次会话已检查 {self._requests} 个请求，未命中规则）"
        parts = [f"{CATEGORY_LABELS.get(k, k)} {v}"
                 for k, v in sorted(self._blocked.items())]
        return (f"已开启（拦截 {self.total_blocked()} 次："
                + "、".join(parts) + "）")

    def reset_stats(self) -> None:
        self._blocked.clear()
        self._samples.clear()
        self._requests = 0

    # ---- 核心 ----
    def decide(self, url: str, first_party: str = "", kind: str = "xhr"):
        """判定是否拦截；拦截时记一次统计。返回命中的规则或 None。"""
        self._requests += 1
        if not self._enabled:
            return None
        hit = should_block(url, first_party, kind, self._categories)
        if not hit:
            return None
        pattern, category = hit
        self._blocked[category] = self._blocked.get(category, 0) + 1
        if len(self._samples) < 5:
            self._samples.append(f"[{category}] {url[:120]}")
        return hit

    def samples(self) -> List[str]:
        """被拦请求的样例（最多 5 条），排查「页面为什么缺东西」时用。"""
        return list(self._samples)


def _qt_base():
    """返回 QWebEngineUrlRequestInterceptor 基类；Qt 不可用时返回 object。

    这样写是为了让本模块的**纯策略部分**（规则表、``should_block``、
    Cloudflare 识别）在没装 Qt 的环境里也能被导入与测试。
    """
    try:
        from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor
        return QWebEngineUrlRequestInterceptor
    except Exception:                                  # pragma: no cover
        return object


class QtTrackerInterceptor(_qt_base()):
    """``TrackerInterceptor`` 的 Qt 适配层（真正的拦截器对象）。

    与 ``TrackerInterceptor`` 分开，是因为 Qt 的拦截器必须继承
    QWebEngineUrlRequestInterceptor，而策略部分不该被 Qt 绑住 ——
    分开之后规则与判定逻辑可以脱离 Qt 单测。
    """

    def __init__(self, policy: Optional[TrackerInterceptor] = None, parent=None):
        try:
            super().__init__(parent)
        except Exception:                              # pragma: no cover
            pass
        self.policy = policy or TrackerInterceptor()

    def interceptRequest(self, info):                  # noqa: N802 - Qt 命名
        try:
            url = info.requestUrl().toString()
            first = info.firstPartyUrl().toString()
            kind = kind_of_resource_type(info.resourceType())
        except Exception:
            return

        try:
            if self.policy.decide(url, first, kind):
                info.block(True)
                return
        except Exception:
            pass

        if self.policy.add_headers:
            self._apply_headers(info, url, first, kind)

    # ------------------------------------------------------------------
    def _apply_headers(self, info, url: str, first: str, kind: str) -> None:
        """补齐 QtWebEngine 不会发的请求头（Client Hints 等）。

        QtWebEngine **不实现 Client Hints**：真 Chrome 每个文档请求都会带
        ``sec-ch-ua*``，而这里一条都没有 —— 这本身就是可被直接检测的特征。
        所以这里按请求类型补上，并且与 UA 的版本号同源（见 core.headers）。
        """
        try:
            from core import headers as H
        except Exception:                              # pragma: no cover
            return

        have = self._header_names(info)
        wanted = {}
        if kind in ("document", "xhr"):
            wanted.update(H.client_hints())
        if "accept-language" not in have:
            wanted["Accept-Language"] = H.accept_language()
        # Sec-Fetch-* 是**按请求**算的：图片是 no-cors/image，XHR 是 cors/empty，
        # 顶层导航才是 navigate/document。
        for name, value in H.sec_fetch(kind).items():
            if name.lower() not in have and value:
                wanted[name] = value
        if "sec-fetch-site" not in have:
            wanted["Sec-Fetch-Site"] = H.fetch_site(url, first)
        for name, value in wanted.items():
            if not value or name.lower() in have:
                continue
            try:
                from PySide6.QtCore import QByteArray
                info.setHttpHeader(QByteArray(name.encode("latin-1")),
                                   QByteArray(str(value).encode("latin-1")))
            except Exception:
                continue

    @staticmethod
    def _header_names(info) -> set:
        """已存在的请求头名（小写）；取不到时返回空集合。"""
        names = set()
        try:
            hdrs = info.httpHeaders()
        except Exception:
            return names
        try:
            keys = hdrs.keys()
        except Exception:
            try:
                keys = list(hdrs)
            except Exception:
                return names
        for k in keys:
            try:
                names.add(bytes(k).decode("latin-1").lower())
            except Exception:
                continue
        return names


# ======================================================================
# Cloudflare 挑战识别
# ======================================================================
#: 出现即说明是 Cloudflare 挑战 / 拦截页。
_CF_MARKS = (
    "challenge-platform", "cf-chl-", "__cf_chl_", "cf_chl_opt",
    "cf-challenge", "cf_chl_prog", "cdn-cgi/challenge-platform",
    "cf-mitigated", "cf-please-wait", "cf-error-details",
    "/cdn-cgi/styles/challenges.css",
)

#: 标题级特征（比正文关键词可靠：正文里出现 Cloudflare 字样的正常页面很多）。
_CF_TITLES = (
    "just a moment", "attention required", "checking your browser",
    "请稍候", "正在检查您的浏览器", "ddos protection by cloudflare",
)

#: 交互型挑战（必须人点）：能自动过的引擎也过不去，别浪费时间重试。
_CF_INTERACTIVE = (
    "turnstile", "cf-turnstile", "challenges.cloudflare.com/turnstile",
    "verify you are human", "确认您是真人", "请验证您是真人",
)

#: 非交互 JS 挑战（等几秒自动跳转）：隐身引擎能自动过。
_CF_JS = (
    "challenge-platform", "cf_chl_opt", "__cf_chl_", "cf_chl_prog",
    "checking your browser", "just a moment",
)

#: WAF 直接拦截（1020 / 1015 之类）：重试也没用。
_CF_BLOCKED = (
    "cf-error-details", "error 1020", "error 1015", "you have been blocked",
    "access denied", "ray id",
)


def is_cloudflare_challenge(html: str = "", title: str = "",
                            url: str = "", status: int = 0) -> dict:
    """判断页面是不是 Cloudflare 挑战 / 拦截页。

    返回 ``{"challenge": bool, "kind": str, "reason": str, "auto": bool}``：

    ==========  ==========================================  ============
    kind        含义                                        auto（可自动过）
    ==========  ==========================================  ============
    ``js``      非交互 JS 挑战（等几秒自动跳转）            是
    ``turnstile`` 交互型人机验证（需要点选）                否
    ``block``   WAF 直接拦截（1020/1015）                   否
    ``""``      不是 Cloudflare                                       —
    ==========  ==========================================  ============

    为什么要分类：以前只要命中关键词就停下等人，而 JS 挑战其实等几秒自己就过了
    （或者换个引擎请求一次就过），白让用户守着屏幕。
    """
    hay = f"{html or ''}\n{title or ''}\n{url or ''}".lower()
    if not hay.strip():
        return {"challenge": False, "kind": "", "reason": "", "auto": False}

    interactive = [m for m in _CF_INTERACTIVE if m in hay]
    blocked = [m for m in _CF_BLOCKED if m in hay]
    marks = [m for m in _CF_MARKS if m in hay]
    title_hit = [m for m in _CF_TITLES if m in hay]

    if not (marks or title_hit or interactive):
        return {"challenge": False, "kind": "", "reason": "", "auto": False}

    # 交互型优先：它必须人工处理，别被下面的 js 分支抢走
    if interactive and not any(m in hay for m in _CF_JS):
        return {"challenge": True, "kind": "turnstile", "auto": False,
                "reason": f"Cloudflare 交互式人机验证（命中「{interactive[0]}」）"}
    if interactive:
        return {"challenge": True, "kind": "turnstile", "auto": False,
                "reason": f"Cloudflare 页面同时出现挑战脚本与交互验证"
                          f"（命中「{interactive[0]}」），按交互型处理"}
    if blocked and not any(m in hay for m in _CF_JS):
        return {"challenge": True, "kind": "block", "auto": False,
                "reason": f"Cloudflare WAF 直接拦截（命中「{blocked[0]}」）"}
    js_hit = [m for m in _CF_JS if m in hay] or marks or title_hit
    return {"challenge": True, "kind": "js", "auto": True,
            "reason": f"Cloudflare JS 挑战（命中「{js_hit[0]}」），可自动绕过"}


def cloudflare_hint(kind: str = "") -> str:
    """按挑战类型给出下一步建议（写进日志与界面横幅）。"""
    if kind == "js":
        return ("这是可自动绕过的 JS 挑战：程序会自动改用隐身引擎重试；"
                "若隐身引擎不可用，请先装浏览器增强包。")
    if kind == "turnstile":
        return ("交互式人机验证必须人工完成：请在下方浏览器区域点选，"
                "完成后程序会自动继续。")
    if kind == "block":
        return ("站点 WAF 已直接拒绝本次访问：换 Profile / 放慢节奏 / "
                "稍后再试通常比反复重试有效。")
    return ""


__all__ = [
    "TRACKER_RULES", "NEVER_BLOCK", "CATEGORY_LABELS",
    "DEFAULT_BLOCK_TRACKERS", "DEFAULT_BLOCK_AD_CREATIVES",
    "DEFAULT_CATEGORIES", "default_categories",
    "should_block", "is_never_blocked", "kind_of_resource_type",
    "TrackerInterceptor", "QtTrackerInterceptor",
    "is_cloudflare_challenge", "cloudflare_hint",
]