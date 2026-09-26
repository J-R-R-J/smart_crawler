# -*- coding: utf-8 -*-
"""core.popup_handler —— 弹窗扫描与处理。

- scan：run_sync(POPUP_SCAN_JS) 解析 JSON，异常返回 []；
- handle：一轮处理，返回 (found, handled) 元组；
- 策略：notify（只报告）/ close（点关闭按钮）/ remove（移除 DOM）；
- handle_all：最多 max_rounds 轮，QTimer 异步，轮间 300ms，found==0 即停。
"""

import json

from PySide6.QtCore import QObject, QTimer, Signal

from config.js_scripts import POPUP_CLOSE_JS, POPUP_REMOVE_JS, POPUP_SCAN_JS
from utils.logger import log_info


class PopupHandler(QObject):
    popup_found = Signal(list)     # [{id,cls,tag,text,visible}, ...]
    popup_closed = Signal(list)

    _STRATEGIES = ("notify", "close", "remove")

    def __init__(self, page, js, strategy: str = "close", parent=None):
        super().__init__(parent)
        self._page = page
        self._js = js
        self._strategy = strategy if strategy in self._STRATEGIES else "close"
        self._round = 0
        self._max_rounds = 3

    def set_strategy(self, key: str) -> None:
        if key in self._STRATEGIES:
            self._strategy = key

    def scan(self) -> list:
        try:
            raw = self._js.run_sync(POPUP_SCAN_JS)
            if isinstance(raw, str):
                data = json.loads(raw)
            else:
                data = raw
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
            return []
        except Exception:
            return []

    def handle(self) -> tuple:
        """执行一轮处理，返回 (found, handled)。"""
        items = self.scan()
        if not items:
            return (0, 0)
        self.popup_found.emit(items)
        found = len(items)

        if self._strategy == "notify":
            return (found, 0)

        try:
            if self._strategy == "close":
                handled = int(self._js.run_sync(POPUP_CLOSE_JS) or 0)
            else:   # remove
                handled = int(self._js.run_sync(POPUP_REMOVE_JS) or 0)
        except Exception:
            handled = 0
        handled = max(0, min(handled, found))
        self.popup_closed.emit(items[:handled])
        return (found, handled)

    def handle_all(self, max_rounds: int = 3) -> None:
        """异步多轮处理：最多 max_rounds 轮，轮间 300ms，found==0 即停。

        **发现但一个也没处理掉时立刻停**（``found > 0 and handled == 0``）：
        那种情况下再转两轮结果完全一样，只是白等 600ms，还会在日志里留下
        「发现 4 个，处理 0 个」刷屏。实测某视频站在每页都触发这条路径，
        日志被刷得看不出真正的问题。
        ``notify`` 策略永远 handled==0，所以它也天然只跑一轮。
        """
        try:
            self._max_rounds = max(1, int(max_rounds))
        except (TypeError, ValueError):
            self._max_rounds = 3
        self._round = 0
        self._next_round()

    def _next_round(self) -> None:
        if self._round >= self._max_rounds:
            return
        self._round += 1
        found, handled = self.handle()
        log_info(f"[popup] 第 {self._round} 轮：发现 {found} 个，处理 {handled} 个")
        if found == 0 or self._round >= self._max_rounds:
            return
        if handled == 0:
            # 没有任何进展：再转下去也不会变，直接收工
            log_info("[popup] 本轮未处理掉任何弹窗（多为一像素诱饵或已消失的节点），"
                     "停止继续尝试")
            return
        QTimer.singleShot(300, self._next_round)
