# -*- coding: utf-8 -*-
"""主窗口：组装所有面板 + 绑定信号。"""

import os
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter, QMessageBox, QDialog,
)

from config.constants import APP_TITLE, APP_VERSION, DEFAULT_PROFILE
from config.js_scripts import QWEBCHANNEL_JS
from config.welcome import WELCOME_HTML
from core.browser      import Browser
from core.cookie_manager import CookieManager
from core.crawler      import Crawler
from core.signals      import get_signals
from core.user_prefs   import UserPrefs
from utils.logger      import log_info, log_warn

from .top_bar      import TopBar
from .banner       import HumanBanner
from .left_panel   import LeftPanel
from .center_panel import CenterPanel
from .right_panel  import RightPanel
from .keyword_dialog import KeywordDialog


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE}  v{APP_VERSION}")
        self._apply_initial_size()

        self.signals = get_signals()
        self.prefs   = UserPrefs()

        # ---------- 初始化 core ----------
        self.browser = Browser(
            profile_name=self.prefs.last_profile or DEFAULT_PROFILE,
            popup_strategy=self.prefs.popup_strategy,
            stealth_enabled=self.prefs.stealth_enabled,
            max_download_mb=self.prefs.max_download_mb,
            allowed_download_exts=self.prefs.download_exts,
        )
        self.cookie_manager = CookieManager(self.browser.profile, self)
        # Profile=cookie 集：绑定当前 profile 名，并载入其已保存的 cookie
        self.cookie_manager.set_profile_name(self.browser.profile_name)
        self.cookie_manager.load_from_profile(self.browser.profile_name)
        self.crawler = Crawler(self.browser, self)

        # ---------- UI ----------
        self._build_ui()
        self._load_qss()
        self._wire()

        # ---------- 初始状态同步 ----------
        self.top_bar.set_popup_strategy(self.prefs.popup_strategy)
        self.right_panel.cookie_panel.attach_cookie_manager(self.cookie_manager)
        self.right_panel.cookie_panel.set_current_profile(self.browser.profile_name)

        # 自动注入 WebChannel（首次打开 about:blank 时）
        self.browser.js.run(QWEBCHANNEL_JS)
        # 启动占位页：浏览器区域显示使用说明，而不是空白页
        self.browser.page.setHtml(WELCOME_HTML)

        log_info("=" * 52)
        log_info(f"SmartCrawler v{APP_VERSION} 已启动 · Profile='{self.browser.profile_name}' · "
                 f"弹窗策略='{self.prefs.popup_strategy}' · "
                 f"反爬伪装={'开' if self.browser.stealth_enabled else '关'}")
        self.signals.log.emit("INFO", "就绪。输入网址并加载，选择抓取格式，然后开始抓取。")

    # ==================================================================
    # 窗口尺寸
    # ==================================================================
    def _apply_initial_size(self) -> None:
        """按可用屏幕自适应初始尺寸，避免默认窗口高过屏幕、底部看不到。

        同时设置最小尺寸，防止窗口过小把控件挤在一起
        （左侧配置面板已改为可滚动，内容不会因此丢失）。
        """
        self.setMinimumSize(1000, 620)
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                w = min(1560, max(1000, int(avail.width() * 0.90)))
                h = min(940, max(620, int(avail.height() * 0.90)))
                self.resize(w, h)
                log_info(f"[ui] 初始窗口 {w}x{h}（可用屏幕 "
                         f"{avail.width()}x{avail.height()}）")
                return
        except Exception:
            pass
        self.resize(1280, 800)

    # ==================================================================
    # UI 组装
    # ==================================================================
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- TopBar ---
        self.top_bar = TopBar()
        root.addWidget(self.top_bar)

        # --- Banner ---
        self.banner = HumanBanner()
        root.addWidget(self.banner)

        # --- Splitter ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        self.left_panel   = LeftPanel(self.prefs)
        self.center_panel = CenterPanel(self.browser.page)
        self.right_panel  = RightPanel(self.prefs)

        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.center_panel)
        splitter.addWidget(self.right_panel)
        splitter.setSizes([330, 760, 470])

        self.status = self.statusBar()
        self.status.showMessage("就绪")

    def _load_qss(self):
        qss_path = os.path.join(os.path.dirname(__file__), "styles.qss")
        try:
            with open(qss_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        except Exception as e:
            log_warn(f"QSS 加载失败：{e}")

    # ==================================================================
    # 信号绑定
    # ==================================================================
    def _wire(self):
        # --- TopBar ---
        self.top_bar.go_requested.connect(self._on_go)
        self.top_bar.back_clicked.connect(self.browser.back)
        self.top_bar.forward_clicked.connect(self.browser.forward)
        self.top_bar.reload_clicked.connect(self.browser.reload)
        self.top_bar.pick_toggled.connect(self._on_pick_toggled)
        self.top_bar.popup_strategy_changed.connect(self._on_popup_strategy)

        # --- Banner ---
        self.banner.done_clicked.connect(self.crawler.on_human_done)
        self.banner.skip_clicked.connect(self.crawler.skip_human)

        # --- LeftPanel ---
        self.left_panel.start_clicked.connect(self._on_start)
        self.left_panel.stop_clicked.connect(self.crawler.stop_task)
        self.left_panel.clear_clicked.connect(self.right_panel.clear)
        self.left_panel.keywords_clicked.connect(self._on_keywords)
        self.left_panel.settings_changed.connect(self._on_run_settings)

        # --- Browser → URL ---
        self.browser.url_changed.connect(self.top_bar.set_url)
        self.browser.page_replaced.connect(self._on_page_replaced)

        # --- CookiePanel 请求切换 Profile ---
        self.right_panel.cookie_panel.profile_switch_requested.connect(
            self._on_switch_profile)

        # --- 全局信号 ---
        s = self.signals
        s.log.connect(self._on_log)
        s.state_changed.connect(self._on_state_changed)
        s.page_loaded.connect(self._on_page_loaded)
        s.human_required.connect(self._on_human_required)
        s.human_cleared.connect(self._on_human_cleared)
        s.data_extracted.connect(self.right_panel.append_rows)
        s.task_started.connect(lambda: self.left_panel.set_running(True))
        s.task_finished.connect(self._on_task_finished)
        s.picked.connect(self._on_picked)
        s.popup_found.connect(self._on_popup_found)
        s.popup_closed.connect(self._on_popup_closed)
        s.profile_changed.connect(self._on_profile_changed)

    # ==================================================================
    # 处理函数
    # ==================================================================
    def _on_go(self, url: str):
        # 纯浏览（不启动抓取任务）
        self.browser.navigate(url)

    def _on_start(self):
        task = self.left_panel.collect_task()
        url = self.top_bar.url_edit.text().strip()
        if not url:
            QMessageBox.information(self, "提示", "请先输入要抓取的网址。")
            return
        if "://" not in url:
            url = "https://" + url
            self.top_bar.set_url(url)
        task.url = url
        self.crawler.start_task(task)

    def _on_pick_toggled(self, active: bool):
        if active:
            self.crawler.picker.enable()
        else:
            self.crawler.picker.disable()

    def _on_popup_strategy(self, key: str):
        self.prefs.popup_strategy = key
        self.browser.set_popup_strategy(key)

    # ------------------------------------------------------------------
    def _on_keywords(self):
        """打开检测关键词设置对话框。"""
        dlg = KeywordDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.signals.log.emit("INFO", "检测关键词已更新，立即生效。")
            log_info("[ui] 检测关键词已更新")

    def _on_run_settings(self):
        """反爬伪装 / 下载上限 / 下载格式变化：同步到浏览器并持久化。"""
        stealth = self.left_panel.stealth_enabled()
        limit = self.left_panel.max_download_mb()
        exts = self.left_panel.download_exts()

        self.prefs.stealth_enabled = stealth
        self.prefs.max_download_mb = limit
        self.prefs.download_exts = exts

        self.browser.stealth_enabled = stealth
        self.browser.max_download_mb = limit
        self.browser.allowed_download_exts = exts

        size_txt = f"{limit} MB" if limit else "不限大小"
        ext_txt = exts if exts else "不限格式"
        self.signals.log.emit(
            "INFO",
            f"运行设置已更新：反爬伪装 {'开' if stealth else '关'}，"
            f"下载上限 {size_txt}，下载格式 {ext_txt}")

    # ------------------------------------------------------------------
    def _on_log(self, level: str, msg: str):
        self.right_panel.log(level, msg)

    def _on_state_changed(self, state: str):
        self.status.showMessage(f"状态：{state}")

    def _on_page_loaded(self, ok: bool):
        self.status.showMessage("加载完成" if ok else "加载失败")

    def _on_human_required(self, level: str, reason: str):
        self.banner.show_for(level, reason)

    def _on_human_cleared(self):
        self.banner.hide_banner()

    def _on_task_finished(self, total: int, elapsed: float):
        self.left_panel.set_running(False)
        summary = (f"任务完成\n"
                   f"总数: {total}\n"
                   f"耗时: {elapsed:.2f}s\n"
                   f"URL : {self.browser.url()}\n"
                   f"Profile: {self.browser.profile_name}\n"
                   f"弹窗策略: {self.prefs.popup_strategy}")
        self.right_panel.set_task_summary(summary)

    def _on_picked(self, selector: str, text: str, tag: str, href: str):
        self.left_panel.apply_picked_selector(selector, text, tag)
        # 自动关闭拾取模式
        self.top_bar.set_pick_active(False)
        self.crawler.picker.disable()

    def _on_popup_found(self, items: list):
        # 记录到日志 Tab
        self.signals.log.emit("INFO", f"[popup] 检测到 {len(items)} 个弹窗")

    def _on_popup_closed(self, items: list):
        self.signals.log.emit("INFO", f"[popup] 已处理 {len(items)} 个")

    # ------------------------------------------------------------------
    # Profile 切换
    # ------------------------------------------------------------------
    def _on_switch_profile(self, name: str):
        if name == self.browser.profile_name:
            return
        log_info(f"[ui] 切换 Profile：{self.browser.profile_name} 改为 {name}")

        # 同一引擎内切换 cookie 集：保存旧 → 清空 → 载入新
        self.cookie_manager.switch_profile(name)
        self.browser.switch_profile(name, self.prefs.popup_strategy)

        self.right_panel.cookie_panel.set_current_profile(name)
        self.prefs.last_profile = name

    def _on_profile_changed(self, name: str):
        self.right_panel.cookie_panel.set_current_profile(name)
        self.signals.log.emit("INFO", f"已切换 Profile：{name}")

    def _on_page_replaced(self):
        # Browser 换了 page，需要让 view 重新 setPage
        self.center_panel.set_page(self.browser.page)
        # 重新注入 WebChannel
        QTimer.singleShot(300, lambda: self.browser.js.run(QWEBCHANNEL_JS))

    # ==================================================================
    # 退出清理
    # ==================================================================
    def closeEvent(self, event):
        """关闭窗口：停止任务并按要求顺序销毁浏览器引擎。

        必须先销毁 page 再销毁 profile，否则 QtWebEngine 会在退出阶段报
        「Release of profile requested but WebEnginePage still not deleted」
        并可能崩溃。
        """
        try:
            self.crawler.stop_task()
        except Exception:
            pass
        try:
            self.center_panel.view.setPage(None)
        except Exception:
            pass
        try:
            self.browser.close()
        except Exception:
            pass
        try:
            self.prefs.sync()
        except Exception:
            pass
        super().closeEvent(event)