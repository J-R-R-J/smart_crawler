# -*- coding: utf-8 -*-
"""core.headers —— 自动生成「自洽」的真实请求头，以及 TLS 指纹档案。

为什么需要这个模块
------------------
反爬系统判断「你是不是浏览器」时，**很少只看 User-Agent**，而是看一整套
互相印证的证据链：

    UA 里的 Chrome 版本  ←→  sec-ch-ua 里的品牌版本
    UA 里的平台字样      ←→  sec-ch-ua-platform
    Accept-Language      ←→  navigator.languages
    Referer / Origin     ←→  Sec-Fetch-Site
    Accept               ←→  Sec-Fetch-Dest / Sec-Fetch-Mode

只要其中一对打不上，就算每一条单独看都很正常，也会被判为自动化工具。

本模块把「发出请求时该带哪些头」收敛成一个函数 ``build_headers()``，
浏览器引擎（QtWebEngine）与 Scrapling 三个引擎共用同一份口径，
避免出现「浏览器引擎一套头、HTTP 引擎另一套头」的两张皮。

**实测踩过的坑**：本项目原先在 core/browser.py 里把 UA 写死成
``Chrome/124.0.0.0``，而 QtWebEngine 6.9.3 内嵌的是 Chromium 130 ——
站点只要把 UA 版本和 Client Hints 里的版本对一下，立刻就能看出 UA 是假的
（真浏览器绝不会出现这种组合）。所以这里改成**从运行中的引擎反查真实
Chromium 主版本号**，再据此生成 UA 与 Client Hints，默认值只作为兜底。

TLS 指纹部分说明
----------------
HTTP 快速模式用 curl_cffi，它能伪装成指定浏览器的 **TLS 握手特征**
（JA3/JA4、扩展顺序、密码套件）。可选的档位由 curl_cffi 版本决定，
不同版本差异很大（本机 0.16.3 有 chrome100~chrome150），写死任何一个
都会在别人的环境里报错，因此这里**先问 curl_cffi 支持哪些档位**，
再挑一个与 UA 版本最接近的。
"""

import os
import re
from typing import Dict, List, Optional

#: 兜底用的 Chromium 主版本号。
#:
#: 只在「拿不到引擎真实版本」（例如纯 Python 环境跑测试）时才会用到。
#: 取值依据：PySide6 6.9.3 内嵌 Chromium 130（实测
#: ``QWebEngineProfile.defaultProfile().httpUserAgent()``）。
DEFAULT_CHROME_MAJOR = 130

#: 桌面 Windows 平台串，同时用于 UA 与 sec-ch-ua-platform。
WINDOWS_PLATFORM = "Windows NT 10.0; Win64; x64"

#: 与 STEALTH_JS 里 navigator.languages 保持一致的默认语言列表。
#:
#: 这两处**必须同源**：JS 报 zh-CN、请求头却是 en-US，是最经典的
#: 「反爬秒识别」组合之一。
DEFAULT_LANGUAGES = ("zh-CN", "zh", "en-US", "en")

#: 由 DEFAULT_LANGUAGES 推出的 Accept-Language 头（q 值递减）。
DEFAULT_ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"

_UA_RE = re.compile(r"Chrome/(\d+)(?:\.\d+)*")
_ENGINE_MAJOR_CACHE: Optional[int] = None


# ======================================================================
# 版本 / UA / Client Hints
# ======================================================================
def major_from_ua(ua: str) -> int:
    """从 UA 里取 Chrome 主版本号；取不到返回 0。"""
    m = _UA_RE.search(ua or "")
    if not m:
        return 0
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return 0


def set_engine_major(major: int) -> None:
    """记录引擎真实 Chromium 主版本号（由 core.browser 首次读到 UA 时调用）。

    **为什么不让本模块自己去问 Qt**：``QWebEngineProfile.defaultProfile()``
    会**创建默认 Profile**。而 QtWebEngine 在单进程渲染模式下只允许存在一个
    Profile，第二个会被拒绝并直接 abort —— 实测就是这个原因让程序在启动
    阶段崩掉（日志停在 "Single mode supports only single profile."）。
    所以真实版本号只能由**已经存在的那个 Profile** 反向提供：
    core.browser 建好 Profile 后先读它的 ``httpUserAgent()``，
    再把版本号写到这里。
    """
    global _ENGINE_MAJOR_CACHE
    try:
        value = int(major or 0)
    except (TypeError, ValueError):
        value = 0
    if value >= 80:
        _ENGINE_MAJOR_CACHE = value


def engine_chrome_major() -> int:
    """已记录的真实 Chromium 主版本号；还没记录时返回 0。"""
    return int(_ENGINE_MAJOR_CACHE or 0)


def chrome_major() -> int:
    """对外暴露的 Chromium 主版本号。

    优先级：环境变量 ``SMARTCRAWLER_CHROME_MAJOR`` > 记录到的引擎真实版本
    > 兜底值。留环境变量是为了让用户在站点风控升级、程序还没跟着更新时，
    不改代码就能把版本号对齐。
    """
    raw = os.environ.get("SMARTCRAWLER_CHROME_MAJOR", "").strip()
    if raw.isdigit() and int(raw) >= 80:
        return int(raw)
    if _ENGINE_MAJOR_CACHE and _ENGINE_MAJOR_CACHE >= 80:
        return int(_ENGINE_MAJOR_CACHE)
    return DEFAULT_CHROME_MAJOR


def reset_cache() -> None:
    """清空引擎版本缓存（仅供测试）。"""
    global _ENGINE_MAJOR_CACHE
    _ENGINE_MAJOR_CACHE = None


def desktop_ua(major: Optional[int] = None) -> str:
    """生成桌面 Chrome UA，版本号与引擎/Client Hints 同源。

    **不带任何自定义后缀**：``SmartCrawler/1.0`` 这类字样等于自报家门。
    确实需要标识自己时用环境变量 ``SMARTCRAWLER_UA_SUFFIX`` 显式追加。
    """
    m = int(major or chrome_major())
    ua = (f"Mozilla/5.0 ({WINDOWS_PLATFORM}) AppleWebKit/537.36 "
          f"(KHTML, like Gecko) Chrome/{m}.0.0.0 Safari/537.36")
    suffix = os.environ.get("SMARTCRAWLER_UA_SUFFIX", "").strip()
    return f"{ua} {suffix}" if suffix else ua


def accept_language() -> str:
    """Accept-Language 头；可用环境变量覆盖以对齐目标站点地区。"""
    return os.environ.get("SMARTCRAWLER_ACCEPT_LANGUAGE",
                          "").strip() or DEFAULT_ACCEPT_LANGUAGE


def locale() -> str:
    """与 Accept-Language 同源的 locale（如 ``zh-CN``）。

    给 Playwright 系引擎用：浏览器上下文设了 locale 之后，
    ``navigator.language`` 与 Accept-Language 会一起变，
    不需要（也不应该）另塞一个 Accept-Language 头。
    """
    raw = os.environ.get("SMARTCRAWLER_LOCALE", "").strip()
    if raw:
        return raw
    first = accept_language().split(",")[0].split(";")[0].strip()
    return first or "zh-CN"


def timezone_id() -> str:
    """与 locale 匹配的时区；环境变量可覆盖。

    locale 和时区必须成对：Chrome 的 ``Intl.DateTimeFormat().resolvedOptions()
    .timeZone`` 会暴露时区，一个「中文环境 + UTC 时区」的组合是典型的
    代理/自动化特征。
    """
    raw = os.environ.get("SMARTCRAWLER_TIMEZONE", "").strip()
    if raw:
        return raw
    table = {
        "zh": "Asia/Shanghai", "zh-cn": "Asia/Shanghai",
        "zh-tw": "Asia/Taipei", "zh-hk": "Asia/Hong_Kong",
        "en": "America/New_York", "en-us": "America/New_York",
        "en-gb": "Europe/London", "ja": "Asia/Tokyo",
        "ko": "Asia/Seoul", "de": "Europe/Berlin", "fr": "Europe/Paris",
        "ru": "Europe/Moscow", "es": "Europe/Madrid", "pt": "Europe/Lisbon",
    }
    low = locale().lower()
    return table.get(low) or table.get(low.split("-")[0]) or "Asia/Shanghai"


def client_hints(major: Optional[int] = None) -> Dict[str, str]:
    """与 UA 版本一致的 Client Hints（sec-ch-ua 系列）。

    Chromium 从 113 起把 ``sec-ch-ua`` 精简成三个品牌：
    Chromium / Google Chrome / Not?A_Brand。三者的版本号**必须**一致，
    否则是明显伪造痕迹。
    """
    m = int(major or chrome_major())
    full = f'{m}.0.0.0'
    return {
        "sec-ch-ua": (f'"Chromium";v="{m}", "Google Chrome";v="{m}", '
                      f'"Not?A_Brand";v="24"'),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        # 完整版本列表只有部分站点会读，但给了就更像真浏览器
        "sec-ch-ua-full-version-list": (
            f'"Chromium";v="{full}", "Google Chrome";v="{full}", '
            f'"Not?A_Brand";v="24.0.0.0"'),
    }


# ======================================================================
# 请求头
# ======================================================================
#: 支持的请求类型。决定了 Accept / Sec-Fetch-Dest / Sec-Fetch-Mode 三件套。
HEADER_KINDS = ("document", "xhr", "image", "media", "script", "css", "font")

_ACCEPT = {
    "document": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                 "image/avif,image/webp,image/apng,*/*;q=0.8,"
                 "application/signed-exchange;v=b3;q=0.7"),
    "xhr": "*/*",
    "image": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "media": "*/*",
    "script": "*/*",
    "css": "text/css,*/*;q=0.1",
    "font": "*/*",
}

_SEC_FETCH_DEST = {
    "document": "document",
    "xhr": "empty",
    "image": "image",
    "media": "video",
    "script": "script",
    "css": "style",
    "font": "font",
}

_SEC_FETCH_MODE = {
    "document": "navigate",
    "xhr": "cors",
    "image": "no-cors",
    "media": "no-cors",
    "script": "no-cors",
    "css": "no-cors",
    "font": "cors",
}


def sec_fetch(kind: str = "document") -> Dict[str, str]:
    """按请求类型返回 Sec-Fetch-Dest / Sec-Fetch-Mode 两件套。

    单独开一个函数，是因为拦截器要**按每个请求**算这两个头
    （一张图片和一个 XHR 的值不同），不能只取文档那一份。
    """
    k = kind if kind in HEADER_KINDS else "document"
    return {"Sec-Fetch-Dest": _SEC_FETCH_DEST[k],
            "Sec-Fetch-Mode": _SEC_FETCH_MODE[k]}


def _host(url: str) -> str:
    """从 URL 里取主机名（小写）；失败返回空串。"""
    if not url:
        return ""
    try:
        from urllib.parse import urlsplit
        return (urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def _registrable(host: str) -> str:
    """取可注册域（粗暴版：取最后两段）。

    只用于判断 same-site / cross-site，不需要公共后缀表的精度：
    判断错最坏是 Sec-Fetch-Site 写成 same-site（真实浏览器也会这么写
    的情况很多），不会造成请求失败。
    """
    parts = [p for p in (host or "").split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    return ".".join(parts[-2:])


def fetch_site(url: str, first_party: str = "") -> str:
    """按两个 URL 推断 Sec-Fetch-Site（none/same-origin/same-site/cross-site）。"""
    a, b = _host(url), _host(first_party)
    if not b:
        return "none"
    if a == b:
        return "same-origin"
    if a and _registrable(a) == _registrable(b):
        return "same-site"
    return "cross-site"


def build_headers(url: str = "", *, kind: str = "document",
                  ua: str = "", referer: str = "", major: Optional[int] = None,
                  site: str = "", language: str = "",
                  extra: Optional[dict] = None) -> Dict[str, str]:
    """生成一整套自洽的请求头。

    参数
    ----
    url        目标 URL（用于推导 Host 与 Sec-Fetch-Site）
    kind       HEADER_KINDS 之一
    ua         显式指定 UA；留空则用 ``desktop_ua()``
    referer    来源页；给了就写 Referer 并按它重算 Sec-Fetch-Site
    site       显式指定 Sec-Fetch-Site；留空则按 referer/url 推断
    extra      额外/覆盖的头（值为 None 表示删除该头）

    返回的 dict 里**不含** Cookie / Host / Content-Length ——
    这三个由传输层自己管，手工塞进去只会出错。
    """
    k = kind if kind in HEADER_KINDS else "document"
    ua = ua or desktop_ua(major)
    if not site:
        site = fetch_site(url, referer)

    headers: Dict[str, str] = {
        "User-Agent": ua,
        "Accept": _ACCEPT[k],
        "Accept-Language": language or accept_language(),
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": _SEC_FETCH_DEST[k],
        "Sec-Fetch-Mode": _SEC_FETCH_MODE[k],
        "Sec-Fetch-Site": site,
    }
    if k == "document":
        headers["Sec-Fetch-User"] = "?1"
        # 顶层导航不带 Referer（地址栏输入 / 书签），带上反而奇怪；
        # 但用户在界面里手填 URL 时，站点常要求有个来源，故允许显式给。
    if referer:
        headers["Referer"] = referer

    # Client Hints **只加在文档与 XHR 上**：真 Chrome 并不会给每张图片
    # 都带上 sec-ch-ua，多送反而是新的破绽。宁可少一条，也不多一条假的。
    # （此前这里还加过 X-Requested-With: XMLHttpRequest —— 那是 jQuery 时代
    #   的写法，现代 Chrome 的 XHR 根本不发这个头，属于典型的画蛇添足。）
    if k in ("document", "xhr"):
        headers.update(client_hints(major))

    if extra:
        for name, value in extra.items():
            if value is None:
                headers.pop(name, None)
            else:
                headers[str(name)] = str(value)
    return headers


# ======================================================================
# 自洽性自检
# ======================================================================
def ua_metadata(ua: str) -> dict:
    """从 UA 里拆出浏览器 / 主版本 / 平台。"""
    ua = ua or ""
    m = _UA_RE.search(ua)
    major = int(m.group(1)) if m else 0
    if "Firefox/" in ua:
        browser = "firefox"
    elif "Edg/" in ua:
        browser = "edge"
    elif "Chrome/" in ua:
        browser = "chrome"
    else:
        browser = "unknown"
    if "Windows" in ua:
        platform = "Windows"
    elif "Android" in ua:
        platform = "Android"
    elif "iPhone" in ua or "iPad" in ua:
        platform = "iOS"
    elif "Macintosh" in ua:
        platform = "macOS"
    elif "Linux" in ua:
        platform = "Linux"
    else:
        platform = "unknown"
    return {"browser": browser, "major": major, "platform": platform,
            "mobile": "Mobile" in ua}


def consistency_issues(ua: str = "", headers: Optional[dict] = None) -> List[str]:
    """检查 UA 与请求头是否自洽，返回问题列表（空 = 自洽）。

    这是本模块最重要的一条防线：**以后再有人把 UA 写死成某个旧版本**，
    自检马上就能报出来，而不是等站点封了才发现。
    """
    headers = dict(headers or {})
    meta = ua_metadata(ua or headers.get("User-Agent", ""))
    issues: List[str] = []

    if meta["major"]:
        ch = headers.get("sec-ch-ua", "")
        # 只有文档 / XHR 才要求必须有 Client Hints（见 build_headers 的说明）；
        # 但只要有，就必须与 UA 对得上。
        want_hints = headers.get("Sec-Fetch-Dest") in ("document", "empty")
        m = re.search(r"v=\"(\d+)\"", ch)
        if not ch and want_hints:
            issues.append("缺少 sec-ch-ua（有 UA 却没有 Client Hints）")
        elif ch and not m:
            issues.append("sec-ch-ua 里没有版本号")
        elif ch and int(m.group(1)) != meta["major"]:
            issues.append(f"UA 版本 {meta['major']} 与 sec-ch-ua 版本 "
                          f"{m.group(1)} 不一致")

    platform = headers.get("sec-ch-ua-platform", "")
    if meta["platform"] != "unknown" and platform:
        want = f'"{meta["platform"]}"'
        if platform != want:
            issues.append(f"UA 平台 {meta['platform']} 与 sec-ch-ua-platform "
                          f"{platform} 不一致")

    if not headers.get("Accept-Language"):
        issues.append("缺少 Accept-Language")
    if not headers.get("Accept"):
        issues.append("缺少 Accept")
    if meta["browser"] == "chrome" and headers.get("Sec-Fetch-Site") is None:
        issues.append("缺少 Sec-Fetch-Site")
    return issues


# ======================================================================
# TLS 指纹（curl_cffi 档位）
# ======================================================================
def impersonate_targets() -> List[str]:
    """curl_cffi 支持的伪装档位；未安装 curl_cffi 时返回空列表。

    **不写死档位**：curl_cffi 每个版本都会增删目标（0.16.3 有
    chrome100~chrome150），写死的名字在别人环境里会直接抛
    ``ImpersonateError``。
    """
    try:
        from curl_cffi.requests import BrowserType
    except Exception:
        return []
    out = []
    for name in dir(BrowserType):
        if name.startswith("_"):
            continue
        value = getattr(BrowserType, name, None)
        if isinstance(value, str) and value == name:
            out.append(name)
    return sorted(out)


def _target_major(name: str) -> int:
    m = re.search(r"(\d{2,3})", name)
    return int(m.group(1)) if m else 0


def impersonate_for(major: Optional[int] = None,
                    targets: Optional[List[str]] = None) -> str:
    """挑一个与目标版本最接近的 chrome 档位；没有可用档位返回空串。

    取「最接近」而不是「不高于」：UA 写 Chrome/130 而 TLS 用 chrome124，
    两者差 6 个大版本，同样是可对出来的破绽；131 只差 1，更自然。
    """
    major = int(major or chrome_major())
    cands = [t for t in (targets if targets is not None
                         else impersonate_targets())
             if t.startswith("chrome") and t.islower()]
    if not cands:
        return ""
    # 排除带后缀的（chrome133a / chrome99_android），它们不是标准桌面档
    plain = [t for t in cands if t[len("chrome"):].isdigit()]
    pool = plain or cands
    return min(pool, key=lambda t: (abs(_target_major(t) - major),
                                    -_target_major(t)))


def tls_profile() -> dict:
    """当前生效的 TLS 指纹档案（供界面显示与排查）。

    返回 ``{"target": 档位名, "source": 来源说明, "available": 档位总数}``；
    没有可用档位时 ``target`` 为空串，调用方应退回 scrapling 的默认行为。
    """
    targets = impersonate_targets()
    target = impersonate_for(targets=targets)
    if targets:
        source = f"curl_cffi 提供 {len(targets)} 个档位"
    else:
        source = "未安装 curl_cffi，退回 Scrapling 默认档位"
    return {"target": target, "source": source, "available": len(targets)}


__all__ = [
    "DEFAULT_CHROME_MAJOR", "WINDOWS_PLATFORM", "DEFAULT_LANGUAGES",
    "DEFAULT_ACCEPT_LANGUAGE", "HEADER_KINDS",
    "engine_chrome_major", "set_engine_major", "major_from_ua",
    "chrome_major", "reset_cache", "desktop_ua",
    "accept_language", "client_hints", "build_headers", "fetch_site",
    "sec_fetch", "locale", "timezone_id",
    "ua_metadata", "consistency_issues", "impersonate_targets",
    "impersonate_for", "tls_profile",
]
