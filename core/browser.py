# -*- coding: utf-8 -*-
"""core.browser —— QWebEngineProfile / QWebEnginePage 与 QWebChannel 桥接封装。

- 使用单一浏览器引擎（存储于 DATA_DIR/engine），ForcePersistentCookies，
  自定义 UA 含 "SmartCrawler/1.0"；「多 Profile」由 Cookie 集切换实现
  （见 core.cookie_manager），因为单进程渲染下只允许存在一个引擎实例；
- JsBridge 注册为 QWebChannel 对象 "bridge"，槽方法供页面 JS 调用；
- 注入 QWebEngineScript（DocumentReady / MainWorld）动态加载
  qrc:///qtwebchannel/qwebchannel.js，保证 config.js_scripts.QWEBCHANNEL_JS
  执行时 window.QWebChannel 可用（连接脚本幂等，由 ui 层调用）。
"""

import os
import random
import re
import shutil

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript

from config.constants import DATA_DIR, DOWNLOAD_DIR, ENGINE_DIR, PROFILE_DIR
from config.js_scripts import build_stealth_js
from core import antibot
from core import headers as _headers
from core.signals import get_signals
from utils.js_runner import JsRunner
from utils.logger import log_info, log_warn


class JsBridge(QObject):
    """暴露给页面 JS 的桥接对象（QWebChannel 注册名 "bridge"）。

    注意：QWebChannel 只会把 **@Slot 方法** 暴露为可被 JS 调用的函数，
    而 Signal 在 JS 侧只能 .connect()、不能当函数调用。因此：
    - `picked` 是 @Slot 方法（JS 调用 window.__sc_bridge.picked(...)）；
    - Python 侧通过 `picked_signal` 信号接收转发。
    """

    picked_signal = Signal(str, str, str, str)   # selector, text, tag, href
    popup_found = Signal(list)                   # 页面 JS 主动报告弹窗

    @Slot(str, str, str, str)
    def picked(self, selector: str, text: str, tag: str, href: str) -> None:
        """JS 拾取回调入口（QWebChannel 暴露给页面）。"""
        self.picked_signal.emit(selector, text, tag, href)

    @Slot(list)
    def report_popup(self, items) -> None:
        """JS 主动报告弹窗入口（可选）。"""
        self.popup_found.emit(list(items or []))


# DocumentCreation 阶段注入：动态插入 qwebchannel.js 的 <script> 标签。
# 文档未就绪时 document.head/documentElement 可能为 null，需延迟到
# DOMContentLoaded 再注入；幂等（__sc_loader_done 标志）。
QWEBCHANNEL_LOADER_JS = (
    "(function(){"
    "if(window.QWebChannel||window.__sc_loader_done){return;}"
    "window.__sc_loader_done=true;"
    "function inject(){"
    "var s=document.createElement('script');"
    "s.src='qrc:///qtwebchannel/qwebchannel.js';"
    "(document.head||document.documentElement).appendChild(s);"
    "}"
    "if(document.head||document.documentElement){inject();}"
    "else{document.addEventListener('DOMContentLoaded',inject,{once:true});}"
    "})();"
)

# 桌面 Chrome UA。
#
# 默认**不追加**任何自定义标识：UA 后缀是最好用的指纹之一，
# 带上 "SmartCrawler/1.0" 这类字样等于向站点自报「我是自动化工具」，
# 会让其他所有伪装措施失效。
# 如果你希望在被采集站点上保持可识别性（更透明的做法），
# 可以设置环境变量 SMARTCRAWLER_UA_SUFFIX 让它追加到 UA 末尾。
#
# **版本号不再写死**（曾经写死 Chrome/124，而引擎实际是 Chromium 130，
# 站点把 UA 与 Client Hints 一比就能看出是假的）。现在统一从
# core.headers 取，那里会去问运行中的 QtWebEngine 真实版本。
def desktop_ua() -> str:
    """当前应使用的桌面 UA（版本号与引擎 / Client Hints 同源）。"""
    return _headers.desktop_ua()

# Profile 目录名仅允许：字母、数字、下划线、连字符
_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _inject_base(html: str, base_url: str) -> str:
    """在 HTML 的 <head> 之后注入 ``<base href>``。

    用于把抓回来的 HTML 写到本地文件后加载的场景：此时文档的来源变成
    ``file://``，若不注入 base，页面里的相对链接与资源都会指向本地而失效。
    """
    tag = f'<base href="{base_url}">'
    low = html.lower()

    for opener, needs_head in (("<head", False), ("<html", True)):
        idx = low.find(opener)
        if idx == -1:
            continue
        close = html.find(">", idx)
        if close == -1:
            continue
        head = ("<head>" + tag + "</head>") if needs_head else tag
        return html[:close + 1] + head + html[close + 1:]

    return tag + html


class CrawlerPage(QWebEnginePage):
    """带「新窗口」兜底的页面类。

    为什么必须重写 createWindow()
    ----------------------------
    ``QWebEnginePage.createWindow()`` 的默认实现返回 ``nullptr``，于是
    ``<a target="_blank">`` 与 ``window.open()`` 发起的请求会被**静默丢弃**：
    点下去没有任何反应，控制台也不报错，看起来就像「按钮坏了」。
    这是 QtWebEngine 的既定行为，与具体站点无关。

    本项目界面只有一块渲染视图，因此策略是把新窗口请求**接回当前视图**
    （单视图爬虫的直觉行为：点了就能看到目标页，可以继续拾取 / 抓取），
    同时发出 ``new_window_requested``，让上层能区分「站点开了新窗口」
    与「页面自己跳转」。

    下载不受影响：下载走 ``QWebEngineProfile.downloadRequested``，
    与 createWindow 是两条完全独立的路径。
    """

    new_window_requested = Signal(str)      # 被接回当前视图的 URL

    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        self._redirect_new_windows = True
        self._new_window_pending = False

    @property
    def redirect_new_windows(self) -> bool:
        return self._redirect_new_windows

    def set_redirect_new_windows(self, enabled: bool) -> None:
        """置 False 可恢复 Qt 默认行为（丢弃新窗口请求）。"""
        self._redirect_new_windows = bool(enabled)

    def createWindow(self, window_type):    # noqa: N802 - 覆盖 Qt 命名
        """返回 self，让新窗口请求在当前视图打开。

        返回 self 是 Qt 允许的做法（要求新页面与请求方同 profile，
        self 自然满足）。Chromium 随后就会在**这个** page 上发起导航，
        因此接着会在 acceptNavigationRequest 里看到那个 URL。
        """
        if not self._redirect_new_windows:
            return None
        self._new_window_pending = True
        return self

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802
        """放行全部导航；顺带把「新窗口请求」上报一次。

        createWindow 拿不到目标 URL（Qt 的接口就没给），所以在这里补报：
        createWindow 与随后的导航请求是紧挨着的，用一个一次性标志配对。
        """
        if self._new_window_pending:
            self._new_window_pending = False
            if is_main_frame:
                try:
                    self.new_window_requested.emit(url.toString())
                except Exception:
                    pass
        return True


class Browser(QObject):
    """管理 WebEngine Profile / Page / JsRunner 与 QWebChannel 桥。"""

    url_changed = Signal(str)
    page_replaced = Signal()      # page 对象被替换（Profile 切换）

    def __init__(self, profile_name: str = "default", popup_strategy: str = "close",
                 stealth_enabled: bool = True, max_download_mb: int = 50,
                 allowed_download_exts: str = "",
                 block_trackers: bool = True, auto_headers: bool = True,
                 hide_canvas: bool = True, block_webrtc: bool = True):
        super().__init__()
        self._profile_name = profile_name
        self._popup_strategy = popup_strategy
        self._stealth_enabled = bool(stealth_enabled)
        self._max_download_mb = max(0, int(max_download_mb or 0))
        self._allowed_download_exts = self._parse_exts(allowed_download_exts)
        self._downloads = []      # 保活：进行中的下载对象
        self._old_refs = []       # 保留旧 page/profile/channel/bridge 引用直至销毁

        # Canvas 噪声种子：**每个进程固定一个**。
        # 同一次运行里同一个 canvas 反复读取必须得到同一个结果（确定性），
        # 换一次运行则整体变化 —— 既不像自动化，也不会成为稳定追踪标识。
        self._canvas_seed = random.randint(1, 2 ** 30)

        # ---- 反检测强化开关 ----
        self._hide_canvas = bool(hide_canvas)
        self._block_webrtc = bool(block_webrtc)

        self._profile = self._create_profile()

        # 拦截器必须**在页面加载之前**装好：它同时负责拦第三方追踪器
        # 与补齐 QtWebEngine 不会发的请求头（Client Hints 等）。
        self._policy = antibot.TrackerInterceptor(
            block_trackers=bool(block_trackers), add_headers=bool(auto_headers))
        self._interceptor = antibot.QtTrackerInterceptor(self._policy)
        self._install_interceptor()

        self._page = CrawlerPage(self._profile, self)
        self._js = JsRunner(self._page)

        # 新窗口请求被接回当前视图时记一条日志（见 CrawlerPage 的说明）
        self._page.new_window_requested.connect(self._on_new_window_requested)

        # ---- QWebChannel 桥接 ----
        self._bridge = JsBridge(self)
        self._channel = QWebChannel(self._page)
        self._channel.registerObject("bridge", self._bridge)
        self._page.setWebChannel(self._channel)
        self._install_channel_script()
        # 当前已存在的文档（如 about:blank）也立即补一次加载器
        self._js.run(QWEBCHANNEL_LOADER_JS)

        # ---- 反爬特征伪装 ----
        if self._stealth_enabled:
            self._install_stealth_script()

        # ---- 下载大小限制 ----
        try:
            self._profile.downloadRequested.connect(self._on_download_requested)
        except Exception:
            pass

        self._page.urlChanged.connect(lambda u: self.url_changed.emit(u.toString()))

    # --------------------------------------------------------------
    # 基础属性
    # --------------------------------------------------------------
    @property
    def profile_name(self) -> str:
        return self._profile_name

    @profile_name.setter
    def profile_name(self, value: str) -> None:
        self._profile_name = value

    @property
    def profile(self) -> QWebEngineProfile:
        return self._profile

    @property
    def page(self) -> QWebEnginePage:
        return self._page

    @property
    def js(self) -> JsRunner:
        return self._js

    @property
    def bridge(self) -> JsBridge:
        return self._bridge

    @property
    def channel(self) -> QWebChannel:
        return self._channel

    @property
    def popup_strategy(self) -> str:
        return self._popup_strategy

    # --------------------------------------------------------------
    # 反爬伪装 / 下载限制
    # --------------------------------------------------------------
    @property
    def stealth_enabled(self) -> bool:
        return self._stealth_enabled

    @stealth_enabled.setter
    def stealth_enabled(self, value: bool) -> None:
        self._stealth_enabled = bool(value)
        if self._stealth_enabled:
            self._install_stealth_script()
        else:
            self._remove_stealth_script()

    # ------------------------------------------------------------------
    # 反检测强化（网络层拦截器 + 伪装脚本里的三节）
    # ------------------------------------------------------------------
    @property
    def tracker_policy(self):
        """第三方追踪器拦截策略对象（开关与统计都在它身上）。"""
        return self._policy

    def tracker_summary(self) -> str:
        """一行可读的拦截统计（日志 / 界面用）。"""
        return self._policy.summary()

    @property
    def block_trackers(self) -> bool:
        return self._policy.enabled

    @block_trackers.setter
    def block_trackers(self, value) -> None:
        self._policy.enabled = bool(value)

    @property
    def auto_headers(self) -> bool:
        """是否按请求补齐 Client Hints / Sec-Fetch-* 等真实浏览器请求头。"""
        return self._policy.add_headers

    @auto_headers.setter
    def auto_headers(self, value) -> None:
        self._policy.add_headers = bool(value)

    @property
    def hide_canvas(self) -> bool:
        return self._hide_canvas

    @hide_canvas.setter
    def hide_canvas(self, value) -> None:
        self._set_stealth_flag("_hide_canvas", value)

    @property
    def block_webrtc(self) -> bool:
        return self._block_webrtc

    @block_webrtc.setter
    def block_webrtc(self, value) -> None:
        self._set_stealth_flag("_block_webrtc", value)

    def _set_stealth_flag(self, attr: str, value) -> None:
        """改伪装脚本里的开关：重建脚本并重新注入。

        伪装脚本的开关是**编译进 JS** 的（该脚本在 DocumentCreation 阶段
        执行，Python 来不及往里塞配置），所以改开关必须重建 + 重新注入。
        重新注入只对**之后**加载的页面生效，当前页面要刷新一次 ——
        写在这里，免得以后有人以为改完立刻生效。
        """
        old = bool(getattr(self, attr, False))
        new = bool(value)
        setattr(self, attr, new)
        if old == new:
            return
        if self._stealth_enabled:
            self._remove_stealth_script()
            self._install_stealth_script()

    def anti_detect_state(self) -> dict:
        """当前反检测配置快照（界面显示 / 自检 / 日志用）。"""
        return {
            "stealth": self._stealth_enabled,
            "block_trackers": self._policy.enabled,
            "auto_headers": self._policy.add_headers,
            "hide_canvas": self._hide_canvas,
            "block_webrtc": self._block_webrtc,
            "user_agent": self._profile.httpUserAgent(),
            "accept_language": self._profile.httpAcceptLanguage(),
            "tls": _headers.tls_profile(),
        }

    @property
    def max_download_mb(self) -> int:
        return self._max_download_mb

    @max_download_mb.setter
    def max_download_mb(self, value) -> None:
        try:
            self._max_download_mb = max(0, int(value))
        except (TypeError, ValueError):
            self._max_download_mb = 0

    @property
    def allowed_download_exts(self) -> set:
        """允许下载的扩展名集合（小写、不含点）；空集合 = 不限制。"""
        return set(self._allowed_download_exts)

    @allowed_download_exts.setter
    def allowed_download_exts(self, value) -> None:
        self._allowed_download_exts = self._parse_exts(value)

    @staticmethod
    def _parse_exts(value) -> set:
        """把 "pdf, .CSV , xlsx" 解析为 {"pdf", "csv", "xlsx"}。"""
        if not value:
            return set()
        if isinstance(value, (list, tuple, set)):
            items = list(value)
        else:
            items = str(value).replace("，", ",").split(",")
        out = set()
        for it in items:
            s = str(it).strip().lower().lstrip("*").lstrip(".")
            if s:
                out.add(s)
        return out

    def _ext_allowed(self, filename: str) -> bool:
        """按扩展名白名单判断是否允许下载；白名单为空时全部允许。"""
        allowed = self._allowed_download_exts
        if not allowed:
            return True
        name = (filename or "").strip().lower()
        if "." not in name:
            return False
        ext = name.rsplit(".", 1)[-1]
        return ext in allowed

    # --------------------------------------------------------------
    # 导航
    #
    # 注意：Qt6 起 QWebEnginePage 不再提供 back()/forward()/reload()/stop()，
    # 这些动作统一通过 triggerAction(WebAction) 执行（或 QWebEngineHistory）。
    # --------------------------------------------------------------
    def navigate(self, url: str) -> None:
        self._page.load(QUrl(url))

    # setHtml 内部走 data URI，Qt 限制约 2MB；超过则改走临时文件 + <base>。
    _SETHTML_MAX = 1_800_000

    def load_html(self, html: str, base_url: str = "") -> bool:
        """把外部抓到的 HTML 灌入渲染引擎（供非浏览器抓取引擎使用）。

        非浏览器引擎（HTTP / Stealth / Dynamic）由 Scrapling 负责发起请求，
        这里只把结果 HTML 交给同一个渲染引擎，从而完整复用既有的
        检测 / 弹窗 / 提取 / 翻页流程。

        返回 True 表示已提交加载。大于约 2MB 的文档不使用 setHtml
        （Qt 会失败），改为写临时文件并注入 ``<base>``，
        以保证相对链接仍按原站解析。
        """
        if not isinstance(html, str) or not html.strip():
            log_warn("[browser] load_html 收到空 HTML，忽略")
            return False

        base = base_url or "about:blank"
        if len(html) <= self._SETHTML_MAX:
            self._page.setHtml(html, QUrl(base))
            return True

        try:
            os.makedirs(ENGINE_DIR, exist_ok=True)
            path = os.path.join(ENGINE_DIR, "fetched_page.html")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(_inject_base(html, base))
            log_info(f"[browser] HTML 过大（{len(html)} 字节），改为本地文件加载")
            self._page.load(QUrl.fromLocalFile(path))
            return True
        except OSError as e:
            log_warn(f"[browser] 大文档落盘失败，退回 setHtml：{e}")
            self._page.setHtml(html, QUrl(base))
            return True

    def url(self) -> str:
        return self._page.url().toString()

    def back(self) -> None:
        self._page.triggerAction(QWebEnginePage.WebAction.Back)

    def forward(self) -> None:
        self._page.triggerAction(QWebEnginePage.WebAction.Forward)

    def reload(self) -> None:
        self._page.triggerAction(QWebEnginePage.WebAction.Reload)

    def stop(self) -> None:
        self._page.triggerAction(QWebEnginePage.WebAction.Stop)

    def can_go_back(self) -> bool:
        return self._page.history().canGoBack()

    def can_go_forward(self) -> bool:
        return self._page.history().canGoForward()

    def set_popup_strategy(self, key: str) -> None:
        if key in ("notify", "close", "remove"):
            self._popup_strategy = key

    def _on_new_window_requested(self, url: str) -> None:
        """新窗口 / 新标签请求已接回当前视图。"""
        log_info(f"[browser] 新窗口请求已接回当前视图：{url}")
        try:
            get_signals().log.emit("INFO", f"站点请求新窗口，已在当前视图打开：{url}")
        except Exception:
            pass

    # --------------------------------------------------------------
    # Profile 切换 / 销毁
    # --------------------------------------------------------------
    def switch_profile(self, name: str, popup_strategy: str) -> None:
        """切换 Profile（同一引擎，仅切换 cookie 集与标签）。

        说明：QtWebEngine 在单进程渲染模式下只能存在一个 QWebEngineProfile，
        创建第二个会崩溃；因此「多 Profile」实现为：单个引擎 + 按 Profile 名
        持久化的 cookie 集。这里只更新标签/策略并通知上层；cookie 集的
        保存/清空/载入由 core.cookie_manager.CookieManager.switch_profile 完成。
        """
        self._profile_name = name
        self._popup_strategy = popup_strategy
        try:
            get_signals().profile_changed.emit(name)
        except Exception:
            pass

    def close(self) -> None:
        """按正确顺序销毁：先 page，后 profile。

        QtWebEngine 要求 profile 销毁时不能还有存活的 page，否则会打印
        「Release of profile requested but WebEnginePage still not deleted」
        并在退出阶段崩溃。deleteLater 是异步的，因此这里强制派发一次
        DeferredDelete 事件，确保 page 真正先于 profile 被销毁。
        """
        page, profile = self._page, self._profile
        try:
            # 断开信号，避免销毁过程中回调到已失效对象
            try:
                page.loadFinished.disconnect()
            except Exception:
                pass
            try:
                page.urlChanged.disconnect()
            except Exception:
                pass
            try:
                page.setParent(None)
            except Exception:
                pass
            page.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        except Exception:
            pass

        try:
            profile.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        except Exception:
            pass

    # --------------------------------------------------------------
    # 内部
    # --------------------------------------------------------------
    def _create_profile(self) -> QWebEngineProfile:
        # 单一引擎存储目录（与「Profile=cookie 集」的目录区分开，避免被
        # list_profiles 误当作一个 profile）。
        storage = os.path.join(DATA_DIR, "engine").replace("\\", "/")
        os.makedirs(storage, exist_ok=True)
        profile = QWebEngineProfile("smartcrawler_engine", self)
        profile.setCachePath(storage + "/cache")
        profile.setPersistentStoragePath(storage)
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)

        # UA 与 Accept-Language 都从 core.headers 取，保证与
        # sec-ch-ua / navigator.languages 是**同一套口径**。
        # 以前这里写死 UA、Accept-Language 则完全不管（Qt 默认 en-US），
        # 而伪装脚本报的是 zh-CN —— 两个值对不上，是最容易被抓的一处。
        #
        # 版本号从**这个 Profile 自己的默认 UA** 里读，顺序很关键：
        # 先读再覆盖。绝不能改用 QWebEngineProfile.defaultProfile() ——
        # 那会创建第二个 Profile，而单进程渲染模式下第二个 Profile
        # 会被拒绝并直接 abort（实测启动即崩）。
        default_ua = profile.httpUserAgent() or ""
        major = _headers.major_from_ua(default_ua)
        if major:
            _headers.set_engine_major(major)
        ua = _headers.desktop_ua(major or None)
        profile.setHttpUserAgent(ua)
        try:
            profile.setHttpAcceptLanguage(_headers.accept_language())
        except Exception as e:                             # pragma: no cover
            log_warn(f"[browser] 设置 Accept-Language 失败：{e}")
        log_info(f"[browser] 引擎 UA：{default_ua}")
        log_info(f"[browser] 采用 UA：{ua}"
                 + ("" if major else "（未能从引擎读出真实版本，用兜底版本号）"))
        return profile

    def _install_interceptor(self) -> None:
        """装上网络层拦截器（拦追踪器 + 补请求头）。

        注意 QtWebEngine 一个 Profile 只能有一个拦截器，后设置的会**替换**
        先设置的（不报错），所以这两件事必须共用同一个对象。
        """
        try:
            self._profile.setUrlRequestInterceptor(self._interceptor)
        except Exception as e:                             # pragma: no cover
            log_warn(f"[browser] 安装请求拦截器失败：{e}")
            return
        if self._policy.enabled or self._policy.add_headers:
            log_info("[antibot] 请求拦截器已启用："
                     f"拦截追踪器={'开' if self._policy.enabled else '关'}，"
                     f"补齐真实请求头={'开' if self._policy.add_headers else '关'}")

    def _install_channel_script(self) -> None:
        script = QWebEngineScript()
        script.setName("sc_qwebchannel_loader")
        # DocumentReady：此时 DOM 已构建，document.head 可用，避免 null.appendChild。
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setSourceCode(QWEBCHANNEL_LOADER_JS)
        self._page.scripts().insert(script)

    def _find_script(self, name: str):
        try:
            scripts = self._page.scripts()
        except Exception:
            return None
        for s in scripts.find(name):
            return s
        return None

    def _install_stealth_script(self) -> None:
        """注入反爬特征伪装脚本（DocumentCreation，早于页面脚本）。

        脚本内容按当前开关生成：Canvas 指纹干扰 / WebRTC 泄露防护 /
        反广告探测 三节可以单独关掉，而开关是编译进 JS 的（见
        ``_set_stealth_flag``）。``major`` 传真实 Chromium 版本，
        用来把 ``navigator.userAgentData`` 与 UA 对齐。
        """
        try:
            if self._find_script("sc_stealth") is not None:
                return
            script = QWebEngineScript()
            script.setName("sc_stealth")
            script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            script.setSourceCode(build_stealth_js(
                canvas=self._hide_canvas, webrtc=self._block_webrtc,
                adblock=True, uach=True, major=_headers.chrome_major(),
                seed=self._canvas_seed))
            self._page.scripts().insert(script)
            flags = [name for name, on in (
                ("Canvas指纹干扰", self._hide_canvas),
                ("WebRTC泄露防护", self._block_webrtc),
                ("反广告探测干扰", True),
            ) if on]
            log_info("[stealth] 已启用浏览器特征伪装"
                     + (f"（{'、'.join(flags)}）" if flags else "（基础项）"))
        except Exception as e:
            log_warn(f"[stealth] 注入失败：{e}")

    def _remove_stealth_script(self) -> None:
        try:
            script = self._find_script("sc_stealth")
            if script is not None:
                self._page.scripts().remove(script)
                log_info("[stealth] 已关闭浏览器特征伪装")
        except Exception as e:
            log_warn(f"[stealth] 移除失败：{e}")

    # --------------------------------------------------------------
    # 下载：格式白名单 + 大小限制 + 归档到 crawler_data/downloads
    # --------------------------------------------------------------
    def _on_download_requested(self, download) -> None:
        try:
            name = (download.suggestedFileName()
                    or download.downloadFileName() or "download.bin")
            limit_bytes = self._max_download_mb * 1024 * 1024
            total = int(download.totalBytes() or 0)

            # ---- 1. 扩展名白名单 ----
            if not self._ext_allowed(name):
                allowed = "、".join(sorted(self._allowed_download_exts))
                log_warn(f"[download] 已拒绝 {name}：扩展名不在允许列表（{allowed}）")
                self._signals_log(
                    "WARN", f"下载被拒绝（格式不允许）：{name}")
                download.cancel()
                return

            # ---- 2. 大小上限（服务端已给出总大小）----
            if limit_bytes and total > limit_bytes:
                log_warn(f"[download] 已拒绝 {name}："
                         f"{total / 1048576:.1f} MB 超过限制 "
                         f"{self._max_download_mb} MB")
                self._signals_log("WARN", f"下载被拒绝（超出大小限制）：{name}")
                download.cancel()
                return

            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
            download.setDownloadDirectory(DOWNLOAD_DIR)
            download.setDownloadFileName(name)

            # 服务器未返回总大小时，按已接收字节中途拦截
            if limit_bytes:
                def _check(received, dl=download, limit=limit_bytes, fname=name):
                    try:
                        if int(received or 0) > limit:
                            dl.cancel()
                            log_warn(f"[download] {fname} 超过 "
                                     f"{self._max_download_mb} MB，已中断")
                    except Exception:
                        pass

                download.receivedBytesChanged.connect(
                    lambda dl=download: _check(dl.receivedBytes()))

            self._downloads.append(download)
            download.stateChanged.connect(
                lambda st, dl=download: self._on_download_state(dl, name))
            download.accept()
            log_info(f"[download] 开始下载：{name} → {DOWNLOAD_DIR}")
            self._signals_log("INFO", f"开始下载：{name}")
        except Exception as e:
            log_warn(f"[download] 处理下载请求失败：{e}")

    def _on_download_state(self, download, name: str) -> None:
        try:
            state = download.state()
            if state in (download.DownloadState.DownloadCompleted,
                         download.DownloadState.DownloadCancelled,
                         download.DownloadState.DownloadInterrupted):
                try:
                    self._downloads.remove(download)
                except ValueError:
                    pass
            if state == download.DownloadState.DownloadCompleted:
                log_info(f"[download] 完成：{name}")
                self._signals_log("INFO", f"下载完成：{name}")
            elif state == download.DownloadState.DownloadInterrupted:
                log_warn(f"[download] 中断：{name}")
        except Exception:
            pass

    @staticmethod
    def _signals_log(level: str, msg: str) -> None:
        try:
            get_signals().log.emit(level, msg)
        except Exception:
            pass


# ==================================================================
# 模块函数：Profile 目录管理
# ==================================================================
def list_profiles() -> list:
    """扫描 PROFILE_DIR 下的目录名，确保至少包含 "default"。"""
    os.makedirs(PROFILE_DIR, exist_ok=True)
    names = []
    try:
        for entry in os.listdir(PROFILE_DIR):
            if _PROFILE_NAME_RE.match(entry) and \
                    os.path.isdir(os.path.join(PROFILE_DIR, entry)):
                names.append(entry)
    except OSError:
        names = []
    if "default" not in names:
        try:
            os.makedirs(os.path.join(PROFILE_DIR, "default"), exist_ok=True)
            names.append("default")
        except OSError:
            pass
    return sorted(names)


def profile_dir(name: str) -> str:
    """返回并创建 PROFILE_DIR/<name>；非法名称抛 ValueError。"""
    if not isinstance(name, str) or not _PROFILE_NAME_RE.match(name):
        raise ValueError(
            f"非法 Profile 名称：{name!r}（只允许字母、数字、_、-）")
    path = os.path.join(PROFILE_DIR, name)
    os.makedirs(path, exist_ok=True)
    return path


def delete_profile(name: str) -> bool:
    """删除 Profile 目录；default 受保护，返回 False。"""
    if name == "default" or not isinstance(name, str) \
            or not _PROFILE_NAME_RE.match(name):
        return False
    path = os.path.join(PROFILE_DIR, name)
    if not os.path.isdir(path):
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True
