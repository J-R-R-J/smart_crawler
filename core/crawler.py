# -*- coding: utf-8 -*-
"""core.crawler —— 抓取任务状态机。

流程：start_task → navigate/直接提取 → loadFinished → 弹窗处理 →
detector 分类（CAPTCHA/HUMAN/LOGIN 暂停等人类，DETECT_INTERVAL_MS 轮询）→
autoscroll → extract → delay → 翻页循环（next_selector + max_pages，
翻页无 loadFinished 时 3s 兜底继续）→ finish。

所有 UI 事件经 get_signals() 总线 emit；文件日志经 utils.logger。
"""

import json
import random
import time

from PySide6.QtCore import QObject, QTimer

from config.default_settings import DETECT_INTERVAL_MS
from config.js_scripts import (
    CAPTCHA_PROBE_JS, GET_HTML_JS, GET_TEXT_JS, GET_TITLE_JS,
    LOGIN_PROBE_JS, SCROLL_JS,
)
from core.detector import Detector
from core.extractor import Extractor
from core.pager import Pager
from core.picker import Picker
from core.popup_handler import PopupHandler
from core.signals import get_signals
from models.record import RecordSet
from utils.logger import log_info, log_warn


STATES = ["IDLE", "NAVIGATING", "WAIT_LOAD", "EXTRACTING",
          "PAGINATING", "HUMAN_WAIT", "STOPPED"]

_RUNNING = ("NAVIGATING", "WAIT_LOAD", "EXTRACTING", "PAGINATING", "HUMAN_WAIT")
_BLOCKING = ("CAPTCHA", "HUMAN", "LOGIN")


class Crawler(QObject):
    """抓取任务总调度状态机。"""

    def __init__(self, browser, parent=None):
        super().__init__(parent)
        self._browser = browser
        self._signals = get_signals()

        self._state = "IDLE"
        self._cancel = False
        self._task = None
        self._records = RecordSet()
        self._page_idx = 0
        self._start_time = 0.0
        self._awaiting_load = False
        self._poll_timer = None
        self._skip_detection = False   # 用户判定误判后，本任务内不再因验证暂停

        # ---- 组件组装 ----
        self.detector = Detector(self)
        self.extractor = Extractor(browser.js, self)
        self.picker = Picker(browser.page, browser.js, browser.bridge, self)
        self.pager = Pager(browser.page, browser.js, self)
        self.popup_handler = PopupHandler(browser.page, browser.js,
                                          browser.popup_strategy, self)

        # ---- 连接 ----
        browser.page.loadFinished.connect(self._on_load_finished)
        browser.page_replaced.connect(self._on_page_replaced)

        self.popup_handler.popup_found.connect(self._signals.popup_found)
        self.popup_handler.popup_closed.connect(self._signals.popup_closed)
        browser.bridge.picked_signal.connect(self._signals.picked)
        browser.bridge.popup_found.connect(self._signals.popup_found)

    # ==================================================================
    # 公共接口（ui/main_window.py 直接调用）
    # ==================================================================
    def start_task(self, task) -> None:
        if self._state not in ("IDLE", "STOPPED"):
            log_warn(f"[crawler] 任务运行中（{self._state}），忽略重复启动")
            return
        self._cancel = False
        self._records.clear()
        self._task = task
        self._page_idx = 0
        self._start_time = time.time()
        self._awaiting_load = False
        self._poll_timer = None
        self._skip_detection = False   # 新任务重新启用检测

        self._signals.task_started.emit()
        self._signals.log.emit("INFO", f"任务启动：{task.url}")
        self._set_state("NAVIGATING")
        self.popup_handler.set_strategy(self._browser.popup_strategy)

        url = (task.url or "").strip()
        if not url:
            log_warn("[crawler] 任务 URL 为空，任务终止")
            self._finish()
            return
        if self._browser.url() != url:
            log_info(f"[crawler] 导航到 {url}")
            self._browser.navigate(url)
        else:
            # 已在目标页：直接走加载完成流程
            QTimer.singleShot(0, lambda: self._on_load_finished(True))

    def stop_task(self) -> None:
        if self._state in ("IDLE", "STOPPED"):
            return
        self._cancel = True
        self._stop_poll_timer()
        self._set_state("STOPPED")
        log_info("[crawler] 任务已被手动停止")
        self._signals.log.emit("WARN", "任务已被手动停止")

        # 必须发 task_finished：UI 依赖它复位「开始抓取」按钮并显示汇总，
        # 否则停止后按钮会一直处于禁用状态。
        elapsed = max(0.0, time.time() - self._start_time) if self._start_time else 0.0
        self._signals.task_finished.emit(self._records.count(), elapsed)

    def on_human_done(self) -> None:
        """人类处理完成：取消挂起的轮询定时器并立即轮询一次。"""
        if self._state != "HUMAN_WAIT":
            return
        self._stop_poll_timer()
        self._poll_human()

    def skip_human(self) -> None:
        """误判跳过：立即继续，并在本任务内不再因验证暂停。

        用于关键词命中但页面并不存在验证组件的误判场景。
        任务重新开始时会恢复检测。
        """
        if self._state != "HUMAN_WAIT":
            return
        self._stop_poll_timer()
        self._skip_detection = True
        msg = "已跳过验证检测（判定为误判），本任务内不再因验证暂停"
        log_warn(f"[crawler] {msg}")
        self._signals.log.emit("WARN", msg)
        self._signals.human_cleared.emit()
        self._continue_after_load()

    # ==================================================================
    # 状态机内部
    # ==================================================================
    def _on_page_replaced(self) -> None:
        """Profile 切换后重建依赖 page 的组件并重连信号。"""
        b = self._browser
        old = [self.extractor, self.picker, self.pager, self.popup_handler]

        self.extractor = Extractor(b.js, self)
        self.picker = Picker(b.page, b.js, b.bridge, self)
        self.pager = Pager(b.page, b.js, self)
        self.popup_handler = PopupHandler(b.page, b.js,
                                          b.popup_strategy, self)

        self.popup_handler.popup_found.connect(self._signals.popup_found)
        self.popup_handler.popup_closed.connect(self._signals.popup_closed)
        b.bridge.picked_signal.connect(self._signals.picked)
        b.bridge.popup_found.connect(self._signals.popup_found)
        b.page.loadFinished.connect(self._on_load_finished)

        for obj in old:
            try:
                obj.deleteLater()
            except Exception:
                pass

    def _on_load_finished(self, ok: bool) -> None:
        self._awaiting_load = False
        self._signals.page_loaded.emit(bool(ok))
        if self._state not in _RUNNING or self._cancel:
            return
        if not ok:
            log_warn("[crawler] 页面加载失败，任务终止")
            self._finish()
            return
        self._set_state("WAIT_LOAD")
        QTimer.singleShot(600, self._after_load)

    def _after_load(self) -> None:
        """步骤 1（弹窗）+ 步骤 2（detector 分类）。"""
        if self._cancel or self._state not in _RUNNING:
            return
        self.popup_handler.set_strategy(self._browser.popup_strategy)
        self.popup_handler.handle_all()

        if self._skip_detection:
            # 用户已判定为误判：本任务内不再因验证暂停
            self._continue_after_load()
            return

        html = self._get_html()
        title = self._get_title()
        text = self._get_text()
        level, reason = self.detector.classify(
            html, title, self._browser.url(), text,
            captcha_forms=self._probe_captcha(),
            login_form=self._probe_login(),
        )
        self.detector.detected.emit(level, reason)

        if level in _BLOCKING:
            self._pause_for_human(level, reason)
        else:
            self._continue_after_load()

    def _pause_for_human(self, level: str, reason: str) -> None:
        self._set_state("HUMAN_WAIT")
        log_warn(f"[crawler] 需要人工处理：{level} · {reason}")
        self._signals.human_required.emit(level, reason)
        self._poll_human()

    def _poll_human(self) -> None:
        """DETECT_INTERVAL_MS 轮询；不再 blocked 则恢复流程。"""
        if self._cancel or self._state != "HUMAN_WAIT":
            self._poll_timer = None
            return
        level, _ = self.detector.classify(
            self._get_html(), self._get_title(), self._browser.url(),
            self._get_text(),
            captcha_forms=self._probe_captcha(),
            login_form=self._probe_login(),
        )
        if level == "NONE":
            self._poll_timer = None
            log_info("[crawler] 人工验证已通过，继续任务")
            self._signals.human_cleared.emit()
            self._continue_after_load()
            return
        if self._poll_timer is None:
            self._poll_timer = QTimer()
            self._poll_timer.setSingleShot(True)
            self._poll_timer.timeout.connect(self._on_poll_tick)
            self._poll_timer.start(DETECT_INTERVAL_MS)

    def _on_poll_tick(self) -> None:
        self._poll_timer = None
        self._poll_human()

    def _continue_after_load(self) -> None:
        """步骤 3：autoscroll（后台）+ 定时提取。"""
        if self._cancel or self._task is None:
            return
        self._set_state("WAIT_LOAD")
        if self._task.autoscroll:
            self._browser.js.run(SCROLL_JS)
        QTimer.singleShot(600, self._extract)

    def _extract(self) -> None:
        if self._cancel or self._task is None:
            return
        if self._state not in ("WAIT_LOAD", "EXTRACTING", "PAGINATING"):
            return
        self._set_state("EXTRACTING")
        rows = self.extractor.extract(self._browser.page, self._task) or []
        added = self._records.add_rows(rows)
        if added > 0:
            self._signals.data_extracted.emit(list(self._records.rows[-added:]))
        log_info(f"[crawler] 第 {self._page_idx + 1} 页："
                 f"提取 {len(rows)} 条，新增 {added} 条")
        try:
            delay_ms = int(max(0.0, float(self._task.delay or 0)) * 1000)
        except (TypeError, ValueError):
            delay_ms = 1500
        # 拟人化抖动：固定间隔是最容易被识别的自动化特征之一，±30% 随机化
        if delay_ms > 0 and self._browser.stealth_enabled:
            delay_ms = int(delay_ms * random.uniform(0.7, 1.3))
        QTimer.singleShot(delay_ms, self._after_extract_delay)

    def _after_extract_delay(self) -> None:
        if self._cancel or self._task is None:
            return
        if self._state != "EXTRACTING":
            return
        self._page_idx += 1
        next_sel = (self._task.next_selector or "").strip()
        try:
            max_pages = max(1, int(self._task.max_pages or 1))
        except (TypeError, ValueError):
            max_pages = 1

        if next_sel and self._page_idx < max_pages:
            self._set_state("PAGINATING")
            if not self.pager.has_next(next_sel):
                log_info("[crawler] 未发现下一页按钮，结束分页")
                self._finish()
                return
            if self.pager.click_next(next_sel):
                self._awaiting_load = True
                QTimer.singleShot(1500, self._pagination_fallback)
            else:
                log_warn("[crawler] 下一页点击失败，结束分页")
                self._finish()
            return
        self._finish()

    def _pagination_fallback(self) -> None:
        """点击后 1.5s 无 loadFinished：再等 3s，仍无则直接提取（SPA 兜底）。"""
        if self._cancel or not self._awaiting_load:
            return
        if self.pager.wait_loaded(3000):
            return   # loadFinished 已触发，_on_load_finished 接管后续流程
        log_info("[crawler] 翻页未触发 loadFinished（SPA 页面），直接提取下一页")
        self._extract()

    def _finish(self) -> None:
        if self._state == "STOPPED":
            return
        self._set_state("STOPPED")
        elapsed = max(0.0, time.time() - self._start_time)
        total = self._records.count()
        self._signals.task_finished.emit(total, elapsed)
        summary = f"[crawler] 任务完成：共 {total} 条 · 耗时 {elapsed:.2f}s"
        log_info(summary)
        self._signals.log.emit("INFO", summary)

    def _set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        self._signals.state_changed.emit(state)

    def _stop_poll_timer(self) -> None:
        if self._poll_timer is not None:
            try:
                self._poll_timer.stop()
            except Exception:
                pass
            self._poll_timer = None

    # ==================================================================
    # 小工具
    # ==================================================================
    def _get_html(self) -> str:
        try:
            value = self._browser.js.run_sync(GET_HTML_JS, 8000)
        except Exception:
            value = None
        return value if isinstance(value, str) else ""

    def _get_text(self) -> str:
        """渲染后的可见纯文本。

        部分反爬页面把关键词用实体编码、零宽字符或 CSS 内容伪装，
        outerHTML 里看不到，但 innerText 里是明文，因此检测需要同时取二者。
        """
        try:
            value = self._browser.js.run_sync(GET_TEXT_JS, 8000)
        except Exception:
            value = None
        return value if isinstance(value, str) else ""

    def _get_title(self) -> str:
        try:
            value = self._browser.js.run_sync(GET_TITLE_JS, 8000)
        except Exception:
            value = None
        return value if isinstance(value, str) else ""

    def _run_probe(self, js_code: str) -> dict:
        """执行结构化探测脚本并解析 JSON；失败返回空 dict。"""
        try:
            raw = self._browser.js.run_sync(js_code, 6000)
        except Exception:
            return {}
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return {}
            try:
                data = json.loads(s)
            except (ValueError, TypeError):
                return {}
        else:
            data = raw
        return data if isinstance(data, dict) else {}

    def _probe_captcha(self) -> dict:
        """探测页面是否存在真正的验证码组件（输入框 / iframe / 容器 / 图形码）。"""
        return self._run_probe(CAPTCHA_PROBE_JS)

    def _probe_login(self) -> dict:
        """探测页面是否存在登录表单（密码输入框等）。"""
        return self._run_probe(LOGIN_PROBE_JS)
