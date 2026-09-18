# -*- coding: utf-8 -*-
"""顶部地址栏 + 导航 + 拾取 + 弹窗策略。"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton, QComboBox, QLabel
)

from config.default_settings import POPUP_STRATEGIES


class TopBar(QWidget):
    go_requested   = Signal(str)      # url
    back_clicked   = Signal()
    forward_clicked= Signal()
    reload_clicked = Signal()
    pick_toggled   = Signal(bool)     # 是否开启拾取
    popup_strategy_changed = Signal(str)  # notify/close/remove

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.btn_back    = QPushButton("后退"); self.btn_back.setFixedWidth(52)
        self.btn_fwd     = QPushButton("前进"); self.btn_fwd.setFixedWidth(52)
        self.btn_reload  = QPushButton("刷新"); self.btn_reload.setFixedWidth(52)
        self.btn_back.setToolTip("后退")
        self.btn_fwd.setToolTip("前进")
        self.btn_reload.setToolTip("刷新")

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(
            "输入网址，例如：https://news.ycombinator.com/")
        self.url_edit.returnPressed.connect(self._on_go)

        self.btn_go = QPushButton("加载")
        self.btn_go.setObjectName("primary")

        self.btn_pick = QPushButton("拾取元素")
        self.btn_pick.setCheckable(True)
        self.btn_pick.setToolTip(
            "开启后点击页面任意元素即可生成 CSS 选择器（Esc 退出）")

        # 弹窗策略
        self.popup_label = QLabel("弹窗：")
        self.popup_label.setObjectName("hintLabel")
        self.popup_combo = QComboBox()
        for key, label, hint in POPUP_STRATEGIES:
            self.popup_combo.addItem(label, key)
            self.popup_combo.setItemData(
                self.popup_combo.count() - 1, hint, 3)  # ToolTipRole = 3
        self.popup_combo.setFixedWidth(120)
        self.popup_combo.setToolTip("页面弹窗处理策略")

        # 组装
        lay.addWidget(self.btn_back)
        lay.addWidget(self.btn_fwd)
        lay.addWidget(self.btn_reload)
        lay.addWidget(self.url_edit, 1)
        lay.addWidget(self.btn_go)
        lay.addWidget(self.btn_pick)
        lay.addWidget(self.popup_label)
        lay.addWidget(self.popup_combo)

        # 信号
        self.btn_back.clicked.connect(self.back_clicked)
        self.btn_fwd.clicked.connect(self.forward_clicked)
        self.btn_reload.clicked.connect(self.reload_clicked)
        self.btn_go.clicked.connect(self._on_go)
        self.btn_pick.toggled.connect(self.pick_toggled)
        self.popup_combo.currentIndexChanged.connect(self._on_popup_changed)

    # ------------------------------------------------------------------
    def _on_go(self):
        url = self.url_edit.text().strip()
        if not url:
            return
        # 仅在完全没有协议头时补全 https://，避免破坏 file:// 等其它协议
        if "://" not in url:
            url = "https://" + url
            self.url_edit.setText(url)
        self.go_requested.emit(url)

    def _on_popup_changed(self, idx: int):
        key = self.popup_combo.itemData(idx)
        if key:
            self.popup_strategy_changed.emit(key)

    # ------------------------------------------------------------------
    def set_url(self, url: str):
        self.url_edit.setText(url or "")

    def set_popup_strategy(self, key: str):
        for i in range(self.popup_combo.count()):
            if self.popup_combo.itemData(i) == key:
                self.popup_combo.blockSignals(True)
                self.popup_combo.setCurrentIndex(i)
                self.popup_combo.blockSignals(False)
                break

    def set_pick_active(self, active: bool):
        self.btn_pick.blockSignals(True)
        self.btn_pick.setChecked(active)
        self.btn_pick.blockSignals(False)