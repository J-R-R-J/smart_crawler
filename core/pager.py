# -*- coding: utf-8 -*-
"""core.pager —— 翻页检测与下一页点击。

- has_next：run_sync 判断选择器存在且可见；
- click_next：scrollIntoView + click()，返回布尔并 emit page_advanced；
- wait_loaded：QEventLoop 等待 loadFinished，超时返回 False。
"""

import json

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal


class Pager(QObject):
    page_advanced = Signal(bool)

    def __init__(self, page, js, parent=None):
        super().__init__(parent)
        self._page = page
        self._js = js

    def has_next(self, next_selector: str) -> bool:
        if not next_selector:
            return False
        sel = json.dumps(str(next_selector))
        code = (
            "(function(){"
            f"var e=document.querySelector({sel});"
            "if(!e){return false;}"
            "var r=e.getBoundingClientRect();"
            "var st=window.getComputedStyle(e);"
            "return r.width>0&&r.height>0&&"
            "st.display!=='none'&&st.visibility!=='hidden';"
            "})()"
        )
        try:
            return bool(self._js.run_sync(code))
        except Exception:
            return False

    def click_next(self, next_selector: str) -> bool:
        if not next_selector:
            self.page_advanced.emit(False)
            return False
        sel = json.dumps(str(next_selector))
        code = (
            "(function(){"
            f"var e=document.querySelector({sel});"
            "if(!e){return false;}"
            "try{e.scrollIntoView({block:'center',behavior:'instant'});"
            "e.click();return true;}"
            "catch(err){return false;}"
            "})()"
        )
        try:
            ok = bool(self._js.run_sync(code))
        except Exception:
            ok = False
        self.page_advanced.emit(ok)
        return ok

    def wait_loaded(self, timeout_ms: int = 15000) -> bool:
        """等待一次 loadFinished；超时返回 False。"""
        loop = QEventLoop(self)
        timer = QTimer(self)
        timer.setSingleShot(True)
        got = {"ok": False}

        def _on_loaded(_ok):
            got["ok"] = True
            loop.quit()

        try:
            self._page.loadFinished.connect(_on_loaded)
            timer.timeout.connect(loop.quit)
            timer.start(int(timeout_ms))
            loop.exec()
        finally:
            try:
                self._page.loadFinished.disconnect(_on_loaded)
            except (RuntimeError, TypeError):
                pass
        return got["ok"]
