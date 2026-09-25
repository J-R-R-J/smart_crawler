# -*- coding: utf-8 -*-
"""core.scrapling_engine —— Scrapling 融合层（可选依赖 · 惰性导入 · 自动降级）。

设计原则
--------
1. **可选依赖**：scrapling 未安装时，本模块所有能力返回「不可用」而不是抛异常，
   程序其余功能完全不受影响。这样正式版打包可以不带 scrapling 及其浏览器
   （playwright / camoufox 会把包体撑大数百 MB）。
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

import os
import sys
import threading
from dataclasses import dataclass, field as _dc_field
from typing import Any, Dict, List, Optional

from config.constants import BASE_DIR, DATA_DIR, SITE_PACKAGES_DIR
from utils.logger import log_info, log_warn

# 自适应特征库：放在应用数据目录，而不是 cwd，
# 这样打包后不会写进 _internal\ 或用户当前目录。
ADAPTIVE_DB = os.path.join(DATA_DIR, "scrapling_adaptive.db")

# 默认的自适应相似度阈值（%）；越高越严格
DEFAULT_PERCENTAGE = 40

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
    packaging/SmartCrawler.spec 的说明：playwright / camoufox 合计数百 MB，
    运行时还要另外下载浏览器，与「解压即用」的免安装包定位冲突）。

    但冻结后程序会把这个目录追加到 sys.path，于是想用非浏览器引擎的用户
    可以用一条 pip 命令把 scrapling 装进来，而不必动安装目录里的其它文件：

        python -m pip install --target "<该目录>" "scrapling[all]"

    版本必须与主程序一致（当前为 Python 3.13），否则带 C 扩展的
    curl_cffi / greenlet 无法导入。
    """
    return SITE_PACKAGES_DIR


def site_packages_hint() -> str:
    """把 scrapling **装到外挂目录**的命令（界面提示用）。

    注意与下面另一个 ``install_hint()`` 区分，两者解决的是不同问题：

    · ``site_packages_hint()``（本函数）：scrapling **包本身**没装 ——
      尤其是冻结版，exe 的 sys.path 指向包内部，不看你项目里的 .venv；
    · ``install_hint()``：包装好了，但**浏览器**还没下载
      （只有隐身 / 动态引擎需要）。

    这两个函数曾经同名，后者静默覆盖了前者，导致「装到外挂目录」的提示
    永远不显示（而测试查的是旧的那个，还以为通过）。
    tests/test_scrapling.py 里有「顶层不得重名」的守卫，防止再次发生。
    """
    return f'python -m pip install --target "{SITE_PACKAGES_DIR}" "scrapling[all]"'


def _prepare_import_path() -> None:
    """把外挂依赖目录加入 sys.path，并补齐 Playwright 的浏览器目录。

    幂等，且在任何情况下都不抛异常 —— 这一步失败最坏只是「scrapling 不可用」。
    """
    global _path_ready
    with _lock:
        if _path_ready:
            return
        _path_ready = True

        try:
            # 追加到**末尾**：包内模块优先，避免外挂目录劫持标准库或 PySide6
            if os.path.isdir(SITE_PACKAGES_DIR) and SITE_PACKAGES_DIR not in sys.path:
                sys.path.append(SITE_PACKAGES_DIR)
        except Exception:
            pass

        # Playwright 的浏览器存放目录：用户已设置的环境变量永远优先，
        # 没设置时再找外挂目录 / exe 同级下的 ms-playwright。
        try:
            if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
                for cand in (os.path.join(SITE_PACKAGES_DIR, "ms-playwright"),
                             os.path.join(BASE_DIR, "ms-playwright")):
                    if os.path.isdir(cand):
                        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = cand
                        log_info(f"[scrapling] 使用浏览器目录：{cand}")
                        break
        except Exception:
            pass


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
        if os.path.isdir(SITE_PACKAGES_DIR):
            return f"{_error}（已搜索外挂目录 {SITE_PACKAGES_DIR}）"
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


def install_hint() -> str:
    """浏览器引擎缺失时给用户的安装提示。"""
    return ("浏览器类引擎（StealthyFetcher / DynamicFetcher）需要额外下载浏览器，"
            "请在项目 venv 下执行： scrapling install")


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


def _to_result(resp, engine: str) -> FetchResult:
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

    return FetchResult(ok=True, url=url, status=status, html=html,
                       text=text, title=title, engine=engine)


# ----------------------------------------------------------------------
# HTTP 引擎（curl_cffi，TLS 指纹伪装，无需浏览器）
# ----------------------------------------------------------------------
def http_get(url: str, *, timeout: float = 30, impersonate: str = "",
             stealthy_headers: bool = True, headers: Optional[dict] = None,
             proxy: str = "", retries: Optional[int] = None) -> FetchResult:
    """用 ``scrapling.fetchers.Fetcher`` 发起纯 HTTP 抓取。

    这是「快速模式」：不启动浏览器，靠 curl_cffi 伪装浏览器 TLS 指纹，
    静态页面比 QtWebEngine 快一个数量级。
    """
    if not available():
        return FetchResult(ok=False, url=url, engine="http",
                           error=f"scrapling 不可用：{unavailable_reason()}")
    try:
        from scrapling.fetchers import Fetcher
        kw: Dict[str, Any] = {"timeout": timeout}
        if stealthy_headers:
            kw["stealthy_headers"] = True
        if impersonate:
            kw["impersonate"] = impersonate
        if headers:
            kw["headers"] = headers
        if proxy:
            kw["proxy"] = proxy
        if retries is not None:
            kw["retries"] = int(retries)
        resp = Fetcher.get(url, **kw)
        result = _to_result(resp, "http")
        log_info(f"[scrapling] HTTP {result.status} {url}（{result.length} 字节）")
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
        resp = StealthyFetcher.fetch(url, **kw)
        result = _to_result(resp, "stealth")
        log_info(f"[scrapling] Stealth {result.status} {url}（{result.length} 字节）")
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
        resp = DynamicFetcher.fetch(url, **kw)
        result = _to_result(resp, "dynamic")
        log_info(f"[scrapling] Dynamic {result.status} {url}（{result.length} 字节）")
        return result
    except Exception as e:
        log_warn(f"[scrapling] Dynamic 抓取失败 {url}：{type(e).__name__}: {e}")
        hint = install_hint() if _looks_like_missing_browser(e) else ""
        return FetchResult(ok=False, url=url, engine="dynamic",
                           error=f"{type(e).__name__}: {e}" + (f"\n{hint}" if hint else ""))


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
    "ADAPTIVE_DB", "DEFAULT_PERCENTAGE", "FetchResult",
    "available", "version", "unavailable_reason", "reset_cache",
    "install_hint", "site_packages_hint", "http_get", "stealth_get",
    "dynamic_get",
    "make_selector", "extract_records", "find_similar", "field_value",
    "seconds_to_ms",
]
