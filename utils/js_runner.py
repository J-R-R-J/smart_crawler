# -*- coding: utf-8 -*-
"""runJavaScript 封装：限流 + 同步等待。

QtWebEngine 同时挂起的 runJavaScript 调用有上限（约 25 个），
这里限制在途调用数，超出的排队，用 QTimer 依次出队。
"""

from collections import deque

from PySide6.QtCore import QEventLoop, QTimer


class JsRunner:
    MAX_PENDING = 20

    def __init__(self, page):
        self.page = page
        self._pending = 0
        self._queue = deque()
        self._timer = QTimer()
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._drain)

    # ------------------------------------------------------------------
    def run(self, code: str, callback=None) -> None:
        """异步执行 JS；在途调用超限时入队。"""
        if not code:
            return

        def _done(result):
            self._pending -= 1
            if callback is not None:
                callback(result)
            self._drain()

        if self._pending < self.MAX_PENDING:
            self._pending += 1
            self.page.runJavaScript(code, _done)
        else:
            self._queue.append((code, callback))

    def _drain(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
        while self._queue and self._pending < self.MAX_PENDING:
            code, callback = self._queue.popleft()
            self._pending += 1

            def _done(result, cb=callback):
                self._pending -= 1
                if cb is not None:
                    cb(result)

            self.page.runJavaScript(code, _done)
        if not self._queue and not self._pending:
            self._timer.stop()

    # ------------------------------------------------------------------
    def run_sync(self, code: str, timeout_ms: int = 10000):
        """同步执行 JS 并返回结果；超时返回 None。"""
        if not code:
            return None
        loop = QEventLoop()
        result = []

        def _cb(r):
            result.append(r)
            loop.quit()

        timeout_timer = QTimer()
        timeout_timer.setSingleShot(True)
        timeout_timer.timeout.connect(loop.quit)

        self.run(code, _cb)
        timeout_timer.start(timeout_ms)
        loop.exec()
        timeout_timer.stop()
        return result[0] if result else None
