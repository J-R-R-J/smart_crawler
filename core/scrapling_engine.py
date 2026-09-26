# -*- coding: utf-8 -*-
"""core.scrapling_engine —— Scrapling 融合层（可选依赖 · 惰性导入 · 自动降级）。

设计原则
--------
1. **可选依赖**：scrapling 未安装时，本模块所有能力返回「不可用」而不是抛异常，
   程序其余功能完全不受影响。这样正式版打包可以不带 scrapling 及其浏览器
   （playwright / patchright / curl_cffi 的 wheel 加上浏览器合计数百 MB）。
2. **惰性导入**：只有在真正用到时才 ``import scrapling``，避免拖慢启动。
3. **统一契约**：``extract_records`` 返回与 ``core.extractor`` 相同形状的
   ``list[dict]``，可直接并入现有结果表。
4. **离线可测**：解析类能力不依赖网络，单元测试可完全离线跑。

本模块实测基于 scrapling 0.4.15（Python 3.13）：
  · 入口类为 ``Selector``（旧文档里的 ``Adaptor`` 已改名）
  · ``css(selector, identifier='', adaptive=False, auto_save=False, percentage=40)``
  · 自适应必须先 ``Selector(html, adaptive=True)``，否则 ``auto_save`` 被忽略
  · 存储用 ``storage_args={"storage_file": <db>, "url": <url>}`` 指定落盘位置
"""

import json
import logging
import os
import sys
import threading
from dataclasses import dataclass, field as _dc_field
from typing import Any, Dict, List, Optional

from config.constants import BASE_DIR, DATA_DIR, SITE_PACKAGES_DIR
from core import antibot
from core import headers as _headers
from utils.logger import log_info, log_warn

# 自适应特征库：放在应用数据目录，而不是 cwd，
# 这样打包后不会写进 _internal\ 或用户当前目录。
ADAPTIVE_DB = os.path.join(DATA_DIR, "scrapling_adaptive.db")

# 默认的自适应相似度阈值（%）；越高越严格
DEFAULT_PERCENTAGE = 40

#: 让用户安装的 extra 名。
#:
#: **用 ``fetchers`` 而不是 ``all``**。实测 scrapling 0.4.15 的
#: ``Provides-Extra``：``all = ai,shell``，而 ``ai`` / ``shell`` 除了
#: ``fetchers`` 还各自拉 ``mcp`` / ``IPython`` 与 ``markdownify``
#: （连同各自的依赖树，本机实测多出约 56 MB）。
#: 本项目只用四个引擎，不用 scrapling 的交互式 shell 与 MCP 服务，所以不需要。
#:
#: 四个能力对应的依赖全在 ``fetchers`` 里：
#:   · HTTP 快速模式 -> curl_cffi
#:   · 隐身引擎       -> patchright
#:   · 动态引擎       -> playwright
#:   · 自适应选择器   -> 只用基础包的 lxml / cssselect
#: 另外 ``scrapling install`` 这个控制台脚本依赖 ``click``，也在 ``fetchers`` 里。
SCRAPLING_EXTRA = "fetchers"

# ----------------------------------------------------------------------
# 超时单位：同一库里的两套刻度（**踩过的坑，勿改**）
#
#   Fetcher.get(...)               timeout 单位 = 秒（默认 30）
#   StealthyFetcher.fetch(...)     timeout 单位 = 毫秒（默认 30_000）
#   DynamicFetcher.fetch(...)      timeout 单位 = 毫秒（默认 30_000）
#
# 依据：scrapling/engines/_browsers/_controllers.py 明确写着
# "The timeout in milliseconds ... The default is 30,000"，
# 且在 _base.py 里直接交给 Playwright 的
# page.set_default_navigation_timeout(timeout)（Playwright 用毫秒）。
#
# 本模块对外**统一用秒**，浏览器引擎在传参前换算；否则 60 秒会被当成
# 60 毫秒，页面必然导航超时（Page.goto: Timeout 60ms exceeded）。
# ----------------------------------------------------------------------
_BROWSER_TIMEOUT_FLOOR_S = 30.0


def seconds_to_ms(value, *, floor_s: float = _BROWSER_TIMEOUT_FLOOR_S) -> int:
    """秒 → 毫秒（浏览器引擎专用），并施加下限，避免出现几毫秒的超时。"""
    try:
        sec = float(value)
    except (TypeError, ValueError):
        sec = floor_s
    if sec <= 0:
        sec = floor_s
    return int(max(sec, floor_s) * 1000)


# ----------------------------------------------------------------------
# 运行期开关：真实请求头 / TLS 指纹伪装
#
# 放成模块级状态而不是让每个引擎函数多两个参数，是因为调用链有三层
# （UI → Crawler → QThread → engine），逐层透传容易漏；
# 而且这些开关是**全局策略**，不是单次请求的属性。
# ----------------------------------------------------------------------
_RUNTIME: Dict[str, bool] = {"auto_headers": True, "tls_spoof": True}


def set_runtime_options(*, auto_headers: Optional[bool] = None,
                        tls_spoof: Optional[bool] = None) -> Dict[str, bool]:
    """设置「真实请求头 / TLS 指纹伪装」开关，返回设置后的快照。"""
    if auto_headers is not None:
        _RUNTIME["auto_headers"] = bool(auto_headers)
    if tls_spoof is not None:
        _RUNTIME["tls_spoof"] = bool(tls_spoof)
    return dict(_RUNTIME)


def runtime_options() -> Dict[str, bool]:
    """当前运行期开关快照。"""
    return dict(_RUNTIME)


# ----------------------------------------------------------------------
# 用户自定义的「外挂包目录」与「浏览器目录」
#
# 为什么要有这个：用户完全可能把 scrapling 装到别处（比如空间更大的
# D 盘），或者让 playwright 把浏览器下到了默认位置
# （%LOCALAPPDATA%\ms-playwright），**不想为了程序去搬几百 MB 的文件**。
# 命令行时代只能靠环境变量，界面上没法配 —— 这两个目录必须是可在界面里
# 指定的，而且改完立刻生效（不必重启）。
#
# 优先级（明确写死，避免"到底听谁的"这种问题）：
#   浏览器目录：环境变量 PLAYWRIGHT_BROWSERS_PATH > 界面自定义 > 自动探测
#   —— 环境变量是系统级、显式设置的，且本项目早就有「不覆盖用户已设置
#      的环境变量」这条不变式（tests/test_scrapling.py 守着它）。
# ----------------------------------------------------------------------
_CUSTOM: Dict[str, str] = {"site_packages": "", "browsers": ""}
#: 本进程为外挂目录追加过哪些 sys.path 条目（换目录时要把旧的撤掉）
_added_paths: List[str] = []
#: 本进程**自己写进** PLAYWRIGHT_BROWSERS_PATH 的值（空串 = 没写过）。
#:
#: 记「值」而不是一个布尔标志：用户随时可能自己设/改这个环境变量，
#: 只看布尔量会把「用户刚设的值」也当成我们的，然后在换目录时**把它删掉**。
_env_written = ""


def _env_is_ours() -> bool:
    """当前 PLAYWRIGHT_BROWSERS_PATH 是不是本进程写进去的。"""
    v = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "") or ""
    return bool(v) and v == _env_written


def _norm_dir(path: str) -> str:
    """规格化用户给的目录：去引号/空白、展开 ~ 与环境变量、转绝对路径。"""
    p = str(path or "").strip().strip('"').strip("'").strip()
    if not p:
        return ""
    try:
        return os.path.abspath(os.path.expanduser(os.path.expandvars(p)))
    except Exception:                                  # pragma: no cover
        return p


def set_custom_paths(*, site_packages: Optional[str] = None,
                     browsers: Optional[str] = None) -> Dict[str, str]:
    """设置/清除界面上的自定义目录（空串 = 恢复默认），返回设置后的快照。

    换目录时会把旧的 sys.path 条目撤掉、并清掉本进程写过的
    ``PLAYWRIGHT_BROWSERS_PATH``，否则会出现「界面改了目录，程序还从旧目录
    导入」这种最难查的问题。scrapling 的惰性加载状态一并重置 —— 用户在
    旧目录里装过、现在换到新目录，必须重新判定可用性。
    """
    global _path_ready, _env_written
    with _lock:
        if site_packages is not None:
            _CUSTOM["site_packages"] = _norm_dir(site_packages)
        if browsers is not None:
            _CUSTOM["browsers"] = _norm_dir(browsers)

        for p in list(_added_paths):
            try:
                while p in sys.path:
                    sys.path.remove(p)
            except Exception:                          # pragma: no cover
                pass
        _added_paths.clear()

        # 只清掉**我们自己写进去**的那个值：用户可能刚刚手动设过
        if _env_is_ours():
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
        _env_written = ""

        _path_ready = False
        _REGISTRY_CACHE.clear()          # 换目录后版本表要重新读
        reset_cache()
        _prepare_import_path()
    return custom_paths()


def custom_paths() -> Dict[str, str]:
    """当前的自定义目录快照（空串表示用默认值）。"""
    return dict(_CUSTOM)


def browsers_dir_source() -> str:
    """浏览器目录**是谁定的**：env / custom / auto / 空串（还没定下来）。

    ⚠ `_prepare_import_path()` 会把选中的目录写进 ``PLAYWRIGHT_BROWSERS_PATH``
    （playwright 只认这个环境变量），所以光看环境变量会把「界面自定义」
    误报成「环境变量」。用 ``_env_is_ours()`` 区分：本进程写进去的不算用户设的。
    """
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "") or ""
    if env and not _env_is_ours():
        return "env"
    if _CUSTOM.get("browsers"):
        return "custom"
    if env:
        return "auto"
    browsers_dir()                     # 触发一次探测（可能填上环境变量）
    return "auto" if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") else ""


def browser_target_dir() -> str:
    """**建议用户放浏览器**的位置（解压浏览器增强包 / 联网下载的落点）。

    默认是 exe（源码运行即项目根）同级的 ms-playwright；用户在界面上
    指定了自定义目录时就以他指定的为准 —— 提示文案与「打开目录」按钮
    必须跟着走，否则界面让人解压到 A、程序却去看 B。
    """
    return _CUSTOM.get("browsers") or browser_drop_dirs()[1]


def headers_for(url: str, *, kind: str = "document",
                referer: str = "") -> Dict[str, str]:
    """按当前开关生成请求头；关掉「真实请求头」时返回空 dict。

    HTTP 引擎专用：**必须整份给**（UA + 与 UA 同源的 sec-ch-ua +
    Sec-Fetch-* + Referer），因为 Scrapling 的 ``_headers_job`` 里
    用户提供的头**优先级最高**，会覆盖 curl 自己生成的那套；
    只给一半就会造出「UA 是 130、sec-ch-ua 是别家的」这种
    比不伪装还糟的组合。

    浏览器引擎（隐身 / 动态）**不**走这里：Playwright 的 Chromium 自己
    就会发完整且与引擎版本自洽的请求头，硬塞一份版本对不上的反而露馅。
    那边只对齐 locale / 时区（见 ``browser_identity``）。
    """
    if not _RUNTIME.get("auto_headers", True):
        return {}
    return _headers.build_headers(url, kind=kind, referer=referer)


def browser_identity() -> Dict[str, str]:
    """隐身 / 动态引擎要用的地区身份（locale + 时区）；关掉时返回空。"""
    if not _RUNTIME.get("auto_headers", True):
        return {}
    return {"locale": _headers.locale(),
            "timezone_id": _headers.timezone_id()}


# ----------------------------------------------------------------------
# 压掉 Scrapling 自己那条会吓人的 ERROR 日志
#
# 开了 solve_cloudflare 之后，只要页面**没有** Cloudflare 挑战
# （绝大多数正常页面都是这样），Scrapling 就用 ``log.error`` 打一行
# "No Cloudflare challenge found."。它写的是它自己的 stdout handler，
# 格式与本程序无关，用户看到的是一条刺眼的 ERROR，实则完全是正常情况。
# 日志噪声会掩盖真正的错误，所以这里把它丢掉，并改用自己的 INFO 记一次。
# ----------------------------------------------------------------------
_CF_NOISE = "no cloudflare challenge found"
_cf_noise_seen = 0


def _quiet_scrapling_logs() -> None:
    """给 scrapling 的 logger 挂一个过滤器（幂等，失败不影响功能）。"""
    try:
        logger = logging.getLogger("scrapling")
    except Exception:                                  # pragma: no cover
        return
    for f in list(getattr(logger, "filters", [])):
        if isinstance(f, _ScraplingNoiseFilter):
            return
    try:
        logger.addFilter(_ScraplingNoiseFilter())
    except Exception:                                  # pragma: no cover
        pass


class _ScraplingNoiseFilter(logging.Filter):
    """丢弃 / 降级 Scrapling 的噪声日志。"""

    def filter(self, record: logging.LogRecord) -> bool:
        global _cf_noise_seen
        try:
            msg = record.getMessage().lower()
        except Exception:
            return True
        if _CF_NOISE in msg:
            _cf_noise_seen += 1
            return False          # 丢弃：这不是错误，见上面的说明
        return True


def cloudflare_noise_count() -> int:
    """被压掉的「没有 Cloudflare 挑战」日志条数（自检 / 测试用）。"""
    return int(_cf_noise_seen)


# ----------------------------------------------------------------------
# 惰性加载与可用性
# ----------------------------------------------------------------------
_lock = threading.RLock()
_tried = False
_module: Optional[Any] = None
_error: str = ""
_path_ready = False


def site_packages_dir() -> str:
    """外挂依赖目录（crawler_data/site-packages）。

    正式版 exe **有意不打包** scrapling 及其浏览器依赖（见
    packaging/SmartCrawler.spec 的说明：playwright / patchright / curl_cffi
    的 wheel 加上浏览器合计数百 MB，与「解压即用」的免安装包定位冲突）。

    但冻结后程序会把这个目录追加到 sys.path，于是想用非浏览器引擎的用户
    可以用一条 pip 命令把 scrapling 装进来，而不必动安装目录里的其它文件：

        python -m pip install --target "<该目录>" "scrapling[fetchers]"

    版本必须与主程序一致（见 python_tag()：外挂目录里装的是带 C 扩展的包，
    curl_cffi / greenlet / lxml 与解释器次版本绑定），否则导不进来。

    用户可以在界面上把它指到别的盘（见 ``set_custom_paths``）——
    几百 MB 的包塞在程序目录里未必是他想要的。
    """
    return _CUSTOM.get("site_packages") or SITE_PACKAGES_DIR


def site_packages_hint() -> str:
    """把 scrapling **装到外挂目录**的命令（界面提示用）。

    注意与下面另一个 ``install_hint()`` 区分，两者解决的是不同问题：

    · ``site_packages_hint()``（本函数）：scrapling **包本身**没装 ——
      尤其是冻结版，exe 的 sys.path 指向包内部，不看你项目里的 .venv；
    · ``install_hint()``：包装好了，但**浏览器**还没就位
      （只有隐身 / 动态引擎需要）。

    这两个函数曾经同名，后者静默覆盖了前者，导致「装到外挂目录」的提示
    永远不显示（而测试查的是旧的那个，还以为通过）。
    tests/test_scrapling.py 里有「顶层不得重名」的守卫，防止再次发生。
    """
    return (f'python -m pip install --target "{site_packages_dir()}" '
            f'"scrapling[{SCRAPLING_EXTRA}]"')


def python_tag() -> str:
    """当前进程的 Python 版本号（如 "3.13"），用于安装提示。

    不要把这个版本号写死在提示文案里：外挂目录里装的是带 C 扩展的包
    （curl_cffi / greenlet / lxml），**必须与本程序同一个次版本**，
    否则导不进来。写死会在换 Python 重新打包后给出错误的指引。
    """
    return f"{sys.version_info.major}.{sys.version_info.minor}"


#: 判定「浏览器已就位」时认的相对可执行文件路径。
#:
#: 依据 playwright / patchright **1.63.0** 的 registry 表（两者完全一致）：
#:   chromium                 -> chromium-<rev>\chrome-win64\chrome.exe
#:   chromium-headless-shell  -> chromium_headless_shell-<rev>\
#:                               chrome-headless-shell-win64\
#:                               chrome-headless-shell.exe
#:
#: **两个都要有**：StealthyFetcher 走的是 patchright
#: （scrapling/engines/_browsers/_stealth.py: ``from patchright.sync_api import
#: sync_playwright``），headless=True（默认）启动的是 headless shell，
#: 只有 headless=False 才用完整的 chromium。
_BROWSER_EXE_RELPATHS = (
    os.path.join("chrome-win64", "chrome.exe"),
    os.path.join("chrome-headless-shell-win64", "chrome-headless-shell.exe"),
)


def browser_drop_dirs() -> tuple:
    """浏览器可以放的**默认**两个位置，按优先级排列（供提示文案与 README 引用）。

    ``_prepare_import_path()`` 按同样顺序挑第一个**存在**的目录设为
    ``PLAYWRIGHT_BROWSERS_PATH``；用户自己设过该环境变量时永远优先，
    在界面上指定了自定义目录时排在这两个之前（见 ``browser_target_dir``）。

    注意这里**只列默认落点**，不含自定义目录 —— 返回值被界面与测试按
    「两个标准落点」使用（tests/test_scrapling.py 钉住了这一点）。
    """
    return (os.path.join(SITE_PACKAGES_DIR, "ms-playwright"),
            os.path.join(BASE_DIR, "ms-playwright"))


def _browser_candidates() -> tuple:
    """实际探测顺序：自定义目录 → 两个默认落点。"""
    custom = _CUSTOM.get("browsers")
    return ((custom,) if custom else ()) + browser_drop_dirs()


def browsers_dir() -> str:
    """Playwright 浏览器的存放目录；未确定时返回空串。

    优先取环境变量（可能是用户设的，也可能是本进程按落点填的），
    其次是界面上的自定义目录。
    """
    _prepare_import_path()
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "") or ""
    return env or _CUSTOM.get("browsers", "")


def browsers_ready() -> bool:
    """隐身 / 动态引擎需要的 Playwright 浏览器是否已经**就位**。

    与 ``probe()`` 的区别很重要：``probe()`` 只说明 **scrapling 包**能导入，
    而 HTTP 快速模式与自适应选择器确实只要包就够了；
    隐身 / 动态引擎还额外需要**几百 MB 的浏览器**。
    两者混为一谈就会出现「界面说四种引擎都可用，一抓就失败」。

    **判定标准是「找得到浏览器可执行文件」，而不是「目录非空」。**
    免安装版会预置一个空的 ``ms-playwright\\`` 文件夹给用户解压用，
    若只看目录里有没有东西，用户往里丢一个说明 txt 就会让界面谎报
    「四种引擎均可用」——这与本函数存在的意义正好相反。
    """
    d = browsers_dir()
    if not d or not os.path.isdir(d):
        return False
    try:
        with os.scandir(d) as it:
            subdirs = [e.path for e in it
                       if e.is_dir() and e.name.lower().startswith("chromium")]
    except Exception:
        return False
    for path in subdirs:
        for rel in _BROWSER_EXE_RELPATHS:
            if os.path.isfile(os.path.join(path, rel)):
                return True
    return False


def _prepare_import_path() -> None:
    """把外挂依赖目录加入 sys.path，并补齐 Playwright 的浏览器目录。

    幂等，且在任何情况下都不抛异常 —— 这一步失败最坏只是「scrapling 不可用」。

    **为什么不能「只执行一次」**：这个外挂目录本来就是让用户自己往里
    装 scrapling 用的，他在程序**已经运行之后**才把这个目录建出来/填上，
    是完全正常的用法。如果第一次检查时目录还不存在就把结果记死，
    那么之后再调用也不会重新判断，表现为「照提示装好了，程序却一直说
    未检测到 Scrapling」。所以这里每次都重新检查 ——
    代价只是两次 ``os.path.isdir`` 加一次 list 包含判断，可以忽略。
    """
    global _path_ready, _env_written
    with _lock:
        try:
            # 追加到**末尾**：包内模块优先，避免外挂目录劫持标准库或 PySide6
            extra = site_packages_dir()
            if extra and os.path.isdir(extra) and extra not in sys.path:
                sys.path.append(extra)
                if extra not in _added_paths:
                    _added_paths.append(extra)
                log_info(f"[scrapling] 外挂依赖目录已加入 sys.path：{extra}")
        except Exception:
            pass

        # Playwright 的浏览器存放目录：用户设的环境变量永远优先，
        # 没设置时再看界面上的自定义目录 / 默认落点。
        try:
            if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
                for cand in _browser_candidates():
                    if os.path.isdir(cand):
                        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = cand
                        _env_written = cand
                        if not _path_ready:
                            log_info(f"[scrapling] 使用浏览器目录：{cand}")
                        break
        except Exception:
            pass

        _path_ready = True


def _load() -> Optional[Any]:
    """首次调用时尝试导入 scrapling；失败则记下原因并永久降级。"""
    global _tried, _module, _error
    with _lock:
        if _tried:
            return _module
        _tried = True
        _prepare_import_path()
        try:
            import scrapling  # noqa: F401  (惰性导入点)
            _module = scrapling
            _error = ""
            _quiet_scrapling_logs()
            # 用 __version__ 直接读，不调用 version() —— 后者会重新进入本函数
            # （RLock 允许，但没必要绕这一圈）
            log_info(f"[scrapling] 已加载 {getattr(scrapling, '__version__', '?')}"
                     f"（{os.path.dirname(getattr(scrapling, '__file__', '') or '')}）")
        except Exception as e:                      # pragma: no cover - 取决于环境
            _module = None
            _error = f"{type(e).__name__}: {e}"
        return _module


def probe() -> bool:
    """scrapling 是否**可以**导入（不真正导入）。

    与 ``available()`` 的区别：本函数用 ``importlib.util.find_spec``，
    不会把 scrapling / playwright 拉进内存，因此可以在界面刷新提示时
    安全调用（启动阶段也扛得住）。真正的导入仍发生在开始抓取时。
    """
    if _module is not None:
        return True
    _prepare_import_path()
    try:
        import importlib.util
        return importlib.util.find_spec("scrapling") is not None
    except Exception:
        return False


def available() -> bool:
    """scrapling 是否可用（已安装且能导入）。"""
    return _load() is not None


def version() -> str:
    """已安装的 scrapling 版本号；不可用时返回空串。"""
    m = _load()
    if m is None:
        return ""
    return str(getattr(m, "__version__", "") or "")


def unavailable_reason() -> str:
    """scrapling 不可用的原因；可用时返回空串。

    冻结版里这条信息要能被用户看懂 —— 「No module named 'scrapling'」
    本身没错，但没说清楚「可以装到哪」，所以补上已搜索的外挂目录。
    """
    _load()
    if not _error:
        return ""
    try:
        extra = site_packages_dir()
        if os.path.isdir(extra):
            return f"{_error}（已搜索外挂目录 {extra}）"
    except Exception:
        pass
    return _error


def reset_cache() -> None:
    """清空惰性加载状态（仅供测试使用）。"""
    global _tried, _module, _error
    with _lock:
        _tried = False
        _module = None
        _error = ""


def _selector_cls():
    """返回 scrapling.Selector 类；不可用时返回 None。"""
    m = _load()
    if m is None:
        return None
    return getattr(m, "Selector", None)


def _storage_cls():
    """返回 scrapling 的 SQLite 存储类；不可用时返回 None。

    该类用 lru_cache 包装，必须原样传入 Selector 的 storage 参数
    （Selector 会检查 ``__wrapped__``）。
    """
    try:
        from scrapling.core import storage as _st
        return getattr(_st, "SQLiteStorageSystem", None)
    except Exception:
        return None


def scrapling_cli() -> str:
    """在外挂目录里找出 scrapling 可执行文件的真实路径；找不到返回空串。

    为什么要找而不是写死：``pip install --target`` 把控制台脚本放到目标目录下
    的脚本子目录里，而这个子目录在 Windows 上可能是 ``Scripts`` 也可能是
    ``bin``（取决于 pip 版本）。写死任一个都会给一部分用户错误命令，
    所以干脆两个都看，找到哪个就报哪个。
    """
    dirs = [os.path.join(site_packages_dir(), sub) for sub in ("Scripts", "bin")]
    # 源码 / venv 运行时，脚本就在当前解释器旁边
    try:
        dirs.append(os.path.dirname(sys.executable))
    except Exception:
        pass
    for d in dirs:
        for name in ("scrapling.exe", "scrapling"):
            path = os.path.join(d, name)
            if os.path.isfile(path):
                return path
    return ""


def install_hint() -> str:
    """**包已经装好、但浏览器还没就位**时的提示。

    场景区分（这两个函数以前同名互相覆盖，别再合并）：
      · ``site_packages_hint()``：scrapling 包本身没装；
      · ``install_hint()``（本函数）：包装好了，缺的是隐身 / 动态引擎要用的
        Playwright 浏览器（约 700 MB）。

    **两条路都要给，且把「解压浏览器增强包」放前面**：免安装版面向的正是
    「不想碰命令行」的用户，让他为了一个可选引擎在线下载 700 MB 是下策；
    仓库的 Release 里另有一个浏览器增强包，解压即可。

    命令用 **``scrapling install``（控制台脚本）**，不要写
    ``python -m scrapling install`` —— scrapling 包里没有 ``__main__.py``，
    那样写会直接报 "No module named scrapling.__main__"（实测）。

    **冻结版还要额外给两个环境变量，否则那条命令根本跑不起来**：
    ``pip install --target`` 会把控制台脚本放到 ``<外挂目录>\\Scripts\\``，
    脚本启动时 ``sys.path[0]`` 是脚本自己所在目录，**不含外挂目录**，
    于是 ``from scrapling.cli import main`` 直接 ModuleNotFoundError。
    程序自己能用是因为 ``_prepare_import_path()`` 往 sys.path 里加了外挂目录，
    但那是**本进程**的事，管不到用户在命令行里新起的进程 —— 只能靠 PYTHONPATH。
    ``PLAYWRIGHT_BROWSERS_PATH`` 同理：不设的话浏览器会下到
    ``%LOCALAPPDATA%``，而不是程序预留的 ms-playwright。
    """
    cli = scrapling_cli()
    cmd = f'"{cli}" install' if cli else "scrapling install"
    # 推荐落点：用户自定义目录优先，否则 exe 同级（源码运行即项目根）
    drop = browser_target_dir()
    head = ("隐身 / 动态引擎还需要 Playwright 浏览器（约 700 MB），二选一：\n"
            "1) 解压「浏览器增强包」，把里面的 ms-playwright 文件夹放到\n"
            f"   {drop}\n")
    if getattr(sys, "frozen", False):
        # 免安装版必须带上两个环境变量，否则 scrapling.exe 连自己都导不进来
        tail = ("2) 联网下载，在 PowerShell 里执行这三行：\n"
                f'   $env:PYTHONPATH="{site_packages_dir()}"\n'
                f'   $env:PLAYWRIGHT_BROWSERS_PATH="{drop}"\n'
                f"   & {cmd}")
    else:
        # 源码运行时控制台脚本就在项目 .venv 里，路径本来就通
        tail = f"2) 在项目目录执行  {cmd}"
    return head + tail


# ----------------------------------------------------------------------
# 安装指引用的「事实」：版本号、镜像地址、目录树
#
# 这些东西**必须与真实依赖对得上**，所以尽量从已安装的 playwright /
# patchright 的 browsers.json 里读，读不到才退回本文件里的常量
# （常量对应 playwright / patchright **1.63.0**，见下）。
# 写成一份"照着做但做不通"的文档，比不写文档更浪费时间。
# ----------------------------------------------------------------------
#: playwright / patchright 1.63.0 的 browsers.json 实测值
BROWSER_REV_FALLBACK = "1243"
BROWSER_VERSION_FALLBACK = "153.0.8010.12"
FFMPEG_REV_FALLBACK = "1011"
WINLDD_REV_FALLBACK = "1007"

#: npmmirror 的两条镜像路径（都实测存在同名同大小的文件）：
#:   ① registry 的 binary 页面（用户给的这种，人点着方便）
#:   ② 直链前缀（给脚本用）
MIRROR_PAGE_CFT = ("https://registry.npmmirror.com/binary.html"
                   "?path=playwright/builds/cft/{version}/")
MIRROR_PAGE_WINLDD = ("https://registry.npmmirror.com/binary.html"
                      "?path=playwright/builds/winldd/{rev}/")
MIRROR_FILE_CFT = ("https://cdn.npmmirror.com/binaries/playwright/builds/cft/"
                   "{version}/win64/{name}")
MIRROR_FILE_CFT_ALT = ("https://cdn.npmmirror.com/binaries/chrome-for-testing/"
                       "{version}/win64/{name}")
MIRROR_FILE_WINLDD = ("https://cdn.npmmirror.com/binaries/playwright/builds/"
                      "winldd/{rev}/winldd-win64.zip")

_REGISTRY_CACHE: Dict[str, Any] = {}


def browser_registry() -> Dict[str, str]:
    """从已安装的 playwright / patchright 读浏览器版本表；读不到用常量。

    返回 ``{chromium_rev, chromium_version, ffmpeg_rev, winldd_rev, source}``。

    为什么要读而不是写死：镜像地址与目录名都带**版本号**
    （``.../cft/<版本>/``、``chromium-<rev>\\``）。用户装的 playwright 一旦
    升级，revision 就会变，写死的指引立刻变成"照着做但做不通"。
    """
    if _REGISTRY_CACHE:
        return dict(_REGISTRY_CACHE)

    out = {"chromium_rev": BROWSER_REV_FALLBACK,
           "chromium_version": BROWSER_VERSION_FALLBACK,
           "ffmpeg_rev": FFMPEG_REV_FALLBACK,
           "winldd_rev": WINLDD_REV_FALLBACK,
           "source": "内置常量（playwright 1.63.0）"}
    extra = site_packages_dir()
    for pkg, path in _browsers_json_candidates(extra):
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for item in data.get("browsers", []):
                name = str(item.get("name", ""))
                if name == "chromium":
                    out["chromium_rev"] = str(item.get("revision") or
                                              out["chromium_rev"])
                    out["chromium_version"] = str(item.get("browserVersion") or
                                                  out["chromium_version"])
                elif name == "ffmpeg":
                    out["ffmpeg_rev"] = str(item.get("revision") or
                                            out["ffmpeg_rev"])
                elif name == "winldd":
                    out["winldd_rev"] = str(item.get("revision") or
                                            out["winldd_rev"])
            out["source"] = f"{pkg}/browsers.json"
            break
        except Exception:                              # pragma: no cover
            continue
    _REGISTRY_CACHE.update(out)
    return dict(out)


def _browsers_json_candidates(extra: str) -> List[tuple]:
    """browsers.json 的候选位置：外挂目录 → 当前解释器里已装的包。"""
    out: List[tuple] = []
    for pkg in ("playwright", "patchright"):
        out.append((pkg, os.path.join(extra, pkg, "driver", "package",
                                      "browsers.json")))
    # 源码 / venv 运行时（开发态）：按 import 定位真实安装位置
    try:
        import importlib.util
        for pkg in ("playwright", "patchright"):
            try:
                spec = importlib.util.find_spec(pkg)
            except Exception:
                spec = None
            for root in list(getattr(spec, "submodule_search_locations", []) or []):
                out.append((pkg, os.path.join(root, "driver", "package",
                                              "browsers.json")))
    except Exception:                                  # pragma: no cover
        pass
    return out


def default_download_dir() -> str:
    """playwright **不指定目录时**的落点：%LOCALAPPDATA%\\ms-playwright。

    这条必须写进指引：很多人联网下载完之后去程序目录里找，找不到就以为
    失败了 —— 其实浏览器在用户目录下。而且**不用搬**：界面上的
    「浏览器目录」指过去即可（见 ``set_custom_paths``）。
    """
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser(
        r"~\AppData\Local")
    return os.path.join(local, "ms-playwright")


def browser_tree_text(root: str = "") -> str:
    """解压完成后**应该看到的目录树**（一份，界面与文档共用）。

    上一版把两三个目录挤在一行，用户反馈「结构不清晰」——
    所以这里一个条目一行，并标出哪些是必需的、哪些可有可无。
    """
    reg = browser_registry()
    top = root or browser_target_dir()
    return (
        f"{top}\\\n"
        f"├─ chromium-{reg['chromium_rev']}\\\n"
        f"│  └─ chrome-win64\\\n"
        f"│     ├─ chrome.exe            ← 必需（完整 Chromium）\n"
        f"│     └─ 其它 dll / pak / locales…\n"
        f"├─ chromium_headless_shell-{reg['chromium_rev']}\\\n"
        f"│  └─ chrome-headless-shell-win64\\\n"
        f"│     ├─ chrome-headless-shell.exe  ← 必需（默认就它启动）\n"
        f"│     └─ 其它 dll / pak…\n"
        f"├─ ffmpeg-{reg['ffmpeg_rev']}\\            ← 可选（只有录像时才用）\n"
        f"├─ winldd-{reg['winldd_rev']}\\PrintDeps.exe  ← 必需（缺了会报依赖校验失败）\n"
        f"└─ 浏览器增强包说明.txt      ← 说明文件，留着不影响\n"
        f"\n判据：两个 .exe 都在 → 引擎就绪（程序只看这两个文件，"
        f"不看目录大小）")


def dry_run_hint() -> str:
    """查「本机到底要哪个版本 / 下到哪」的命令（界面里给用户复制）。"""
    if getattr(sys, "frozen", False):
        head = ("# 免安装版：先让外挂目录可见，再问 playwright 要哪个版本\n"
                f'$env:PYTHONPATH="{site_packages_dir()}"\n')
        tail = "python -m playwright install --dry-run"
    else:
        head = "# 源码版：直接问项目里的 playwright\n"
        tail = (f'"{sys.executable}" -m playwright install --dry-run')
    return (head + tail + "\n\n"
            "# 输出里会有两行关键信息：\n"
            "#   Install location : 浏览器会被放到哪（默认 "
            f"{default_download_dir()}）\n"
            "#   Download url     : 形如 .../builds/cft/<版本号>/win64/"
            "chrome-win64.zip\n"
            "# 记住其中的 <版本号> 与 revision，下面路线 3 要用")


def mirror_hint() -> str:
    """路线 3：走 npmmirror 手动下载（官方 CDN 慢 / 不通时用）。

    为什么是「手动下载」而不是设个环境变量让 playwright 自己走镜像：
    playwright **1.58 起**把 Chromium 换成了 Chrome for Testing，下载路径
    ``builds/cft/<版本>/<平台>/...`` 是**硬编码**的，而
    ``PLAYWRIGHT_DOWNLOAD_HOST`` 只替换域名 —— 拼到 npmmirror 上就是 404。
    这条路只能手动下、再按 playwright 要求的目录名摆好（含两个标记文件）。
    """
    reg = browser_registry()
    ver = reg["chromium_version"]
    rev = reg["chromium_rev"]
    drop = browser_target_dir()
    cft = MIRROR_PAGE_CFT.format(version=ver)
    return (
        f"本程序对应的版本：{ver}（revision {rev}）\n"
        f"\n"
        f"1) 打开这个页面（可以点上面的「复制命令」拿走）：\n"
        f"   {cft}\n"
        f"   进入 win64\\ 目录，下载这两个文件：\n"
        f"     chrome-win64.zip                （{MIRROR_FILE_CFT.format(version=ver, name='chrome-win64.zip')}）\n"
        f"     chrome-headless-shell-win64.zip （{MIRROR_FILE_CFT.format(version=ver, name='chrome-headless-shell-win64.zip')}）\n"
        f"   备用直链（同一份文件、另一条路径）：\n"
        f"     {MIRROR_FILE_CFT_ALT.format(version=ver, name='chrome-win64.zip')}\n"
        f"\n"
        f"2) 解压到下面这两个位置（目录名**必须一模一样**，多套一层等于没装）：\n"
        f"   {os.path.join(drop, 'chromium-' + rev)}\\chrome-win64\\chrome.exe\n"
        f"   {os.path.join(drop, 'chromium_headless_shell-' + rev)}\\"
        f"chrome-headless-shell-win64\\chrome-headless-shell.exe\n"
        f"\n"
        f"3) 每个 chromium* 目录里建**两个空标记文件**（PowerShell，直接粘贴）：\n"
        f"   缺了它们，playwright 会把这份手动装的当成「没安装」重新下载。\n"
        f'   $r = "{drop}"\n'
        f'   New-Item -ItemType File -Force "$r\\chromium-{rev}\\INSTALLATION_COMPLETE"\n'
        f'   New-Item -ItemType File -Force "$r\\chromium-{rev}\\DEPENDENCIES_VALIDATED"\n'
        f'   New-Item -ItemType File -Force "$r\\chromium_headless_shell-{rev}\\INSTALLATION_COMPLETE"\n'
        f'   New-Item -ItemType File -Force "$r\\chromium_headless_shell-{rev}\\DEPENDENCIES_VALIDATED"\n'
        f"\n"
        f"4) （可选，但建议）依赖校验每 30 天会重跑一次，重跑需要\n"
        f"   winldd-{reg['winldd_rev']}\\PrintDeps.exe（很小，128 KB），也从镜像拿：\n"
        f"   {MIRROR_PAGE_WINLDD.format(rev=reg['winldd_rev'])}\n"
        f"   解压成 {os.path.join(drop, 'winldd-' + reg['winldd_rev'])}"
        f"{os.sep}PrintDeps.exe\n"
        f"\n"
        f"5) 回到本窗口点「刷新状态」：显示「隐身 / 动态引擎：可用」就成功了。")


# ----------------------------------------------------------------------
# 抓取结果
# ----------------------------------------------------------------------
@dataclass
class FetchResult:
    """统一的抓取结果（HTTP / 浏览器引擎共用）。"""

    ok: bool = False
    url: str = ""
    status: int = 0
    html: str = ""
    text: str = ""
    title: str = ""
    engine: str = ""
    error: str = ""
    extra: Dict[str, Any] = _dc_field(default_factory=dict)

    @property
    def length(self) -> int:
        return len(self.html or "")


def _selector_text(sel) -> str:
    """从 Selector 取可见纯文本；失败返回空串。"""
    try:
        value = sel.get_all_text()
        return value if isinstance(value, str) else str(value or "")
    except Exception:
        return ""


def _to_result(resp, engine: str, *, cloudflare: Optional[dict] = None) -> FetchResult:
    """把 scrapling 的 Response 归一化为 FetchResult。"""
    html = ""
    try:
        html = resp.html_content or ""
    except Exception:
        html = ""
    if not isinstance(html, str):
        html = str(html or "")

    url = str(getattr(resp, "url", "") or "")
    try:
        status = int(getattr(resp, "status", 0) or 0)
    except (TypeError, ValueError):
        status = 0

    text = ""
    title = ""
    sel_cls = _selector_cls()
    if html and sel_cls is not None:
        try:
            page = sel_cls(html, url=url)
            text = _selector_text(page)
            title = page.css("title::text").get() or ""
        except Exception:
            pass

    extra: Dict[str, Any] = {}
    # 把 Cloudflare 判定结果随结果一起带上：上游（crawler）不必重新猜，
    # 也让「自动绕过」的决策与这里的抓取结果是同一份数据。
    cf = cloudflare
    if cf is None and html:
        cf = antibot.is_cloudflare_challenge(html, title, url, status)
    if cf and cf.get("challenge"):
        extra["cloudflare"] = cf

    return FetchResult(ok=True, url=url, status=status, html=html,
                       text=text, title=title, engine=engine, extra=extra)


# ----------------------------------------------------------------------
# HTTP 引擎（curl_cffi，TLS 指纹伪装，无需浏览器）
# ----------------------------------------------------------------------
def http_get(url: str, *, timeout: float = 30, impersonate: str = "",
             stealthy_headers: bool = True, headers: Optional[dict] = None,
             proxy: str = "", retries: Optional[int] = None) -> FetchResult:
    """用 ``scrapling.fetchers.Fetcher`` 发起纯 HTTP 抓取。

    这是「快速模式」：不启动浏览器，靠 curl_cffi 伪装浏览器 TLS 指纹
    （JA3/JA4），静态页面比 QtWebEngine 快一个数量级。

    TLS 伪装与请求头都受运行期开关控制（见 ``set_runtime_options``）：
      · ``tls_spoof`` 关掉 → 不传 impersonate，用 curl_cffi / scrapling 的默认档；
      · ``auto_headers`` 关掉 → 不注入自己生成的头，交给 scrapling 自己造。

    **Referer 必须与 Sec-Fetch-Site 对上**：scrapling 在 stealth 模式下
    会补一个 ``referer: https://www.google.com/``（模拟从搜索点进来，
    这是它自己的隐身策略）。如果不告诉 ``build_headers`` 这件事，
    我们会发出 ``Sec-Fetch-Site: none`` + Google referer 的矛盾组合。
    所以这里显式把同一个 referer 传下去，让两者一致。
    """
    if not available():
        return FetchResult(ok=False, url=url, engine="http",
                           error=f"scrapling 不可用：{unavailable_reason()}")
    try:
        from scrapling.fetchers import Fetcher
        opts = runtime_options()
        kw: Dict[str, Any] = {"timeout": timeout}
        if stealthy_headers:
            kw["stealthy_headers"] = True

        referer = ""
        if stealthy_headers:
            referer = "https://www.google.com/"
        gen = headers_for(url, kind="document", referer=referer)
        if gen:
            kw["headers"] = {**gen, **(headers or {})}
        elif headers:
            kw["headers"] = headers

        target = impersonate
        if not target and opts.get("tls_spoof", True):
            target = _headers.impersonate_for()
        if target:
            kw["impersonate"] = target
        if proxy:
            kw["proxy"] = proxy
        if retries is not None:
            kw["retries"] = int(retries)

        resp = Fetcher.get(url, **kw)
        result = _to_result(resp, "http")
        log_info(f"[scrapling] HTTP {result.status} {url}（{result.length} 字节）"
                 + (f" · TLS={target}" if target else ""))
        return result
    except Exception as e:
        log_warn(f"[scrapling] HTTP 抓取失败 {url}：{type(e).__name__}: {e}")
        return FetchResult(ok=False, url=url, engine="http",
                           error=f"{type(e).__name__}: {e}")


# ----------------------------------------------------------------------
# 浏览器引擎（需先执行 scrapling install 下载浏览器）
# ----------------------------------------------------------------------
def stealth_get(url: str, *, timeout: float = 90, headless: bool = True,
                solve_cloudflare: bool = False, hide_canvas: bool = True,
                block_webrtc: bool = True, block_ads: bool = True,
                network_idle: bool = True, wait: float = 0,
                useragent: str = "", real_chrome: bool = False,
                proxy: str = "") -> FetchResult:
    """用 ``StealthyFetcher`` 抓取，可自动过 Cloudflare Turnstile。

    需要先执行 ``scrapling install`` 下载 stealth 浏览器。

    ``timeout`` / ``wait`` 的单位是**秒**（对外统一），内部换算成毫秒传给
    Scrapling —— 浏览器引擎的超时单位是毫秒，默认 30000。

    关于 ``hide_canvas`` / ``block_webrtc`` / ``block_ads``
    ----------------------------------------------------
    这三个是 **StealthySession 级别的参数**，不是 fetch 级参数。
    Scrapling 的 ``StealthyFetcher.fetch`` 是 classmethod，会把 kwargs 全部
    丢给 ``StealthySession(**kwargs)``，所以从这一层传进去是**有效**的；
    但如果有人（后来的我）以为可以直接在 ``engine.fetch(url, ...)`` 上传，
    那就会被 ``validate_fetch`` 静默丢掉 —— 它只认 fetch 级字段。
    这也是本程序自己那套 Canvas / WebRTC 处理放在 core.js_scripts 里
    再注入一次的原因：两套机制互不依赖，任何一边失效都还有另一边。

    地区身份（locale / 时区）由 ``browser_identity()`` 统一给出，
    保证 navigator.language、Accept-Language 与时区是同一个地区。
    """
    if not available():
        return FetchResult(ok=False, url=url, engine="stealth",
                           error=f"scrapling 不可用：{unavailable_reason()}")
    try:
        from scrapling.fetchers import StealthyFetcher
        kw: Dict[str, Any] = {
            "headless": headless,
            "timeout": seconds_to_ms(timeout),
            "network_idle": network_idle,
            "block_ads": block_ads,
        }
        if solve_cloudflare:
            kw["solve_cloudflare"] = True
        if hide_canvas:
            kw["hide_canvas"] = True
        if block_webrtc:
            kw["block_webrtc"] = True
        if wait and float(wait) > 0:
            kw["wait"] = seconds_to_ms(wait, floor_s=0.1)
        if useragent:
            kw["useragent"] = useragent
        if real_chrome:
            kw["real_chrome"] = True
        if proxy:
            kw["proxy"] = proxy
        kw.update(browser_identity())
        resp = StealthyFetcher.fetch(url, **kw)
        result = _to_result(resp, "stealth")
        log_info(f"[scrapling] Stealth {result.status} {url}（{result.length} 字节）")
        _log_cf_noise_once(result)
        return result
    except Exception as e:
        log_warn(f"[scrapling] Stealth 抓取失败 {url}：{type(e).__name__}: {e}")
        hint = install_hint() if _looks_like_missing_browser(e) else ""
        return FetchResult(ok=False, url=url, engine="stealth",
                           error=f"{type(e).__name__}: {e}" + (f"\n{hint}" if hint else ""))


def dynamic_get(url: str, *, timeout: float = 90, headless: bool = True,
                network_idle: bool = True, load_dom: bool = True,
                wait_selector: str = "", wait: float = 0,
                block_ads: bool = False, useragent: str = "",
                real_chrome: bool = False, proxy: str = "") -> FetchResult:
    """用 ``DynamicFetcher``（Playwright）抓取 JS 重的页面。

    ``timeout`` / ``wait`` 单位同样是**秒**，内部换算为毫秒。
    """
    if not available():
        return FetchResult(ok=False, url=url, engine="dynamic",
                           error=f"scrapling 不可用：{unavailable_reason()}")
    try:
        from scrapling.fetchers import DynamicFetcher
        kw: Dict[str, Any] = {
            "headless": headless,
            "timeout": seconds_to_ms(timeout),
            "network_idle": network_idle,
            "load_dom": load_dom,
        }
        if wait_selector:
            kw["wait_selector"] = wait_selector
        if wait and float(wait) > 0:
            kw["wait"] = seconds_to_ms(wait, floor_s=0.1)
        if block_ads:
            kw["block_ads"] = True
        if useragent:
            kw["useragent"] = useragent
        if real_chrome:
            kw["real_chrome"] = True
        if proxy:
            kw["proxy"] = proxy
        kw.update(browser_identity())
        resp = DynamicFetcher.fetch(url, **kw)
        result = _to_result(resp, "dynamic")
        log_info(f"[scrapling] Dynamic {result.status} {url}（{result.length} 字节）")
        return result
    except Exception as e:
        log_warn(f"[scrapling] Dynamic 抓取失败 {url}：{type(e).__name__}: {e}")
        hint = install_hint() if _looks_like_missing_browser(e) else ""
        return FetchResult(ok=False, url=url, engine="dynamic",
                           error=f"{type(e).__name__}: {e}" + (f"\n{hint}" if hint else ""))


def _log_cf_noise_once(result) -> None:
    """把被压掉的「没有 Cloudflare 挑战」改记成一条 INFO（每次抓取最多一条）。"""
    before = cloudflare_noise_count()
    if before and not getattr(_log_cf_noise_once, "_done", False):
        _log_cf_noise_once._done = True
        log_info("[scrapling] 本次抓取没有遇到 Cloudflare 挑战"
                 "（正常情况，已不再打印 ERROR 日志）")


def _looks_like_missing_browser(exc: Exception) -> bool:
    """粗略判断异常是否由「浏览器未下载」引起。"""
    text = f"{type(exc).__name__} {exc}".lower()
    keys = ("executable doesn't exist", "browser", "playwright install",
            "camoufox", "nosuchfile", "filenotfound")
    return any(k in text for k in keys)


# ----------------------------------------------------------------------
# 解析引擎（Selector，支持自适应与高级选择器）
# ----------------------------------------------------------------------
def make_selector(html: str, url: str = "", *, adaptive: bool = False,
                  db_path: str = ""):
    """构造 ``Selector``；不可用时返回 None。

    adaptive=True 时必须指定落盘位置，否则默认会写到 scrapling 自己的目录。
    这里统一改写到 ``crawler_data/scrapling_adaptive.db``。
    """
    sel_cls = _selector_cls()
    if sel_cls is None:
        return None
    if not adaptive:
        return sel_cls(html or "<html/>", url=url or "")

    storage = _storage_cls()
    if storage is None:                       # pragma: no cover - 取决于版本
        return sel_cls(html or "<html/>", url=url or "", adaptive=True)

    db = db_path or ADAPTIVE_DB
    try:
        os.makedirs(os.path.dirname(db), exist_ok=True)
    except OSError:
        pass
    return sel_cls(html or "<html/>", url=url or "", adaptive=True,
                   storage=storage,
                   storage_args={"storage_file": db, "url": url or ""})


# 高级选择器语法标记：出现这些就不再补 ::text
_ADVANCED_MARKS = ("::text", "::attr(", "::", "text()", "@")


def field_value(node, field) -> Any:
    """按 Field 的类型从 node 中取值。

    - text : 子选择器文本（``selector`` 已含 ::text 时原样使用）
    - href : href 属性
    - src  : src 属性
    - html : 子节点内部 HTML
    - attr : field.attr 指定的属性
    """
    sel = (getattr(field, "selector", "") or "").strip()
    ftype = (getattr(field, "type", "") or "text").lower()

    if ftype == "html":
        if not sel:
            return _inner_html(node)
        try:
            hit = node.css(sel)
            first = hit[0] if len(hit) else None
        except Exception:
            first = None
        return _inner_html(first if first is not None else node)

    if ftype in ("href", "src"):
        attr = ftype
    elif ftype == "attr":
        attr = (getattr(field, "attr", "") or "").strip()
        if not attr:
            return ""
    else:
        attr = ""

    if attr:
        target = node
        if sel:
            try:
                hit = node.css(sel)
                target = hit[0] if len(hit) else None
            except Exception:
                target = None
        if target is None:
            return ""
        return _attr_of(target, attr)

    # text
    if not sel:
        return node.get_all_text() if hasattr(node, "get_all_text") else ""
    try:
        if any(m in sel for m in _ADVANCED_MARKS):
            hit = node.css(sel)
            return hit.get() if hasattr(hit, "get") else (hit[0] if len(hit) else "")
        hit = node.css(sel)
        if len(hit) == 0:
            return ""
        return hit[0].get_all_text()
    except Exception:
        return ""


def _attr_of(node, attr: str) -> str:
    try:
        value = node.attrib.get(attr, "")
    except Exception:
        return ""
    return value if isinstance(value, str) else str(value or "")


def _inner_html(node) -> str:
    if node is None:
        return ""
    for getter in ("html_content", "prettify"):
        try:
            value = getattr(node, getter)
            if callable(value):
                value = value()
            if isinstance(value, str) and value:
                return value
        except Exception:
            continue
    try:
        return str(node.extract() or "")
    except Exception:
        return ""


def extract_records(html: str, url: str, container: str, fields,
                    *, adaptive: bool = False, auto_save: bool = False,
                    identifier: str = "", percentage: int = DEFAULT_PERCENTAGE,
                    db_path: str = "") -> List[Dict[str, Any]]:
    """用 scrapling 在已抓到的 HTML 上做结构化提取。

    返回 ``list[dict]``，与 ``core.extractor`` 的输出形状一致，
    但不含 ``_mode``（由调用方补充）。

    adaptive + auto_save 的组合实现「网站改版自愈」：
    首次抓到元素时保存其结构特征，之后选择器失效时按相似度重新定位。
    """
    if not available():
        log_warn(f"[scrapling] extract_records 跳过：{unavailable_reason()}")
        return []
    if not container:
        return []

    page = make_selector(html, url, adaptive=adaptive, db_path=db_path)
    if page is None:
        return []

    kwargs: Dict[str, Any] = {}
    if adaptive:
        kwargs["adaptive"] = True
        kwargs["identifier"] = identifier or container
        kwargs["percentage"] = int(percentage)
        if auto_save:
            kwargs["auto_save"] = True

    try:
        nodes = page.css(container, **kwargs)
    except Exception as e:
        log_warn(f"[scrapling] 容器选择器失败 {container!r}：{type(e).__name__}: {e}")
        return []

    try:
        total = len(nodes)
    except TypeError:
        total = 0
    if total == 0:
        return []

    rows: List[Dict[str, Any]] = []
    for node in nodes:
        row: Dict[str, Any] = {}
        for f in (fields or []):
            name = getattr(f, "name", "") or ""
            if not name:
                continue
            try:
                row[name] = field_value(node, f)
            except Exception as e:
                log_warn(f"[scrapling] 字段 {name!r} 提取失败：{type(e).__name__}: {e}")
                row[name] = ""
        rows.append(row)
    return rows


def find_similar(html: str, url: str, selector: str, *, index: int = 0,
                 threshold: float = 0.2, match_text: bool = False) -> List[str]:
    """找到与第 index 个命中元素相似的元素，返回其 CSS 选择器列表。

    用于界面上「这个元素还有哪些同类」的辅助提示。
    注意：scrapling 的参数是 ``similarity_threshold``（0~1 浮点），
    与 ``css(percentage=)`` 的 0~100 整数不是同一个刻度。
    """
    page = make_selector(html, url)
    if page is None:
        return []
    try:
        hits = page.css(selector)
        if len(hits) == 0:
            return []
        target = hits[index]
        similar = target.find_similar(similarity_threshold=float(threshold),
                                      match_text=bool(match_text))
        out = []
        for el in similar:
            # 注意：generate_css_selector 在 0.4.15 是**属性**（str），
            # 不是方法；这里兼容两种形态，避免 TypeError: 'str' object is not callable。
            for name in ("generate_full_css_selector", "generate_css_selector"):
                try:
                    value = getattr(el, name)
                except Exception:
                    continue
                if callable(value):
                    try:
                        value = value()
                    except Exception:
                        continue
                if isinstance(value, str) and value:
                    out.append(value)
                    break
        return out
    except Exception as e:
        log_warn(f"[scrapling] find_similar 失败：{type(e).__name__}: {e}")
        return []


__all__ = [
    "ADAPTIVE_DB", "DEFAULT_PERCENTAGE", "FetchResult", "SCRAPLING_EXTRA",
    "available", "version", "unavailable_reason", "reset_cache",
    "install_hint", "site_packages_hint", "site_packages_dir",
    "python_tag", "browsers_dir", "browsers_ready", "scrapling_cli",
    "browser_drop_dirs", "browser_target_dir", "browsers_dir_source",
    "set_custom_paths", "custom_paths",
    "browser_registry", "browser_tree_text", "default_download_dir",
    "dry_run_hint", "mirror_hint",
    "MIRROR_PAGE_CFT", "MIRROR_PAGE_WINLDD",
    "MIRROR_FILE_CFT", "MIRROR_FILE_CFT_ALT", "MIRROR_FILE_WINLDD",
    "probe", "http_get", "stealth_get",
    "dynamic_get",
    "make_selector", "extract_records", "find_similar", "field_value",
    "seconds_to_ms",
    "set_runtime_options", "runtime_options", "headers_for", "browser_identity",
    "cloudflare_noise_count",
]
