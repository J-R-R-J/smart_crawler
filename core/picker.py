# -*- coding: utf-8 -*-
"""core.picker —— 页面元素拾取（CSS 选择器）控制。

- enable/disable 分别注入 PICKER_JS / PICKER_TEARDOWN_JS；
- 页面点击后经 QWebChannel 桥接回传，转发到 Picker.picked（selector, text, tag, href）。
"""

from PySide6.QtCore import QObject, Signal

from config.js_scripts import PICKER_JS, PICKER_TEARDOWN_JS


class Picker(QObject):
    picked = Signal(str, str, str, str)   # selector, text, tag, href

    def __init__(self, page, js, bridge, parent=None):
        super().__init__(parent)
        self._page = page
        self._js = js
        self._bridge = bridge
        self._active = False
        if bridge is not None:
            try:
                bridge.picked_signal.connect(self.picked)
            except (RuntimeError, TypeError):
                pass

    def enable(self) -> None:
        self._active = True
        self._js.run(PICKER_JS)

    def disable(self) -> None:
        self._active = False
        self._js.run(PICKER_TEARDOWN_JS)

    def is_active(self) -> bool:
        return self._active
