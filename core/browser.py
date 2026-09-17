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
import re
import shutil

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript

from config.constants import DATA_DIR, PROFILE_DIR
from core.signals import get_signals
from utils.js_runner import JsRunner


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

# 桌面 Chrome UA（含 SmartCrawler/1.0 标识）
_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 SmartCrawler/1.0"
)

# Profile 目录名仅允许：字母、数字、下划线、连字符
_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class Browser(QObject):
    """管理 WebEngine Profile / Page / JsRunner 与 QWebChannel 桥。"""

    url_changed = Signal(str)
    page_replaced = Signal()      # page 对象被替换（Profile 切换）

    def __init__(self, profile_name: str = "default", popup_strategy: str = "close"):
        super().__init__()
        self._profile_name = profile_name
        self._popup_strategy = popup_strategy
        self._old_refs = []       # 保留旧 page/profile/channel/bridge 引用直至销毁

        self._profile = self._create_profile()
        self._page = QWebEnginePage(self._profile, self)
        self._js = JsRunner(self._page)

        # ---- QWebChannel 桥接 ----
        self._bridge = JsBridge(self)
        self._channel = QWebChannel(self._page)
        self._channel.registerObject("bridge", self._bridge)
        self._page.setWebChannel(self._channel)
        self._install_channel_script()
        # 当前已存在的文档（如 about:blank）也立即补一次加载器
        self._js.run(QWEBCHANNEL_LOADER_JS)

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
    # 导航
    # --------------------------------------------------------------
    def navigate(self, url: str) -> None:
        self._page.load(QUrl(url))

    def url(self) -> str:
        return self._page.url().toString()

    def back(self) -> None:
        self._page.back()

    def forward(self) -> None:
        self._page.forward()

    def reload(self) -> None:
        self._page.reload()

    def set_popup_strategy(self, key: str) -> None:
        if key in ("notify", "close", "remove"):
            self._popup_strategy = key

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
        try:
            self._page.deleteLater()
            self._profile.deleteLater()
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
        profile.setHttpUserAgent(_DESKTOP_UA)
        return profile

    def _install_channel_script(self) -> None:
        script = QWebEngineScript()
        script.setName("sc_qwebchannel_loader")
        # DocumentReady：此时 DOM 已构建，document.head 可用，避免 null.appendChild。
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setSourceCode(QWEBCHANNEL_LOADER_JS)
        self._page.scripts().insert(script)


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
