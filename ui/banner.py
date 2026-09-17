# -*- coding: utf-8 -*-
"""人类验证横幅。"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


class HumanBanner(QFrame):
    done_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("banner")
        self.setVisible(False)
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        self.label = QLabel("检测到验证")
        self.label.setObjectName("bannerLabel")
        self.label.setWordWrap(True)

        self.btn_done = QPushButton("我已处理完成，继续抓取")
        self.btn_done.setObjectName("bannerBtn")
        self.btn_done.clicked.connect(self.done_clicked)

        lay.addWidget(self.label, 1)
        lay.addWidget(self.btn_done)

    # ------------------------------------------------------------------
    def show_for(self, level: str, reason: str):
        kind = "验证码" if level == "CAPTCHA" else "登录验证"
        self.label.setText(
            f"检测到{kind}：{reason}。已自动暂停，请直接在下方浏览器中手动完成验证。"
            f"程序会自动检测恢复，也可点击右侧按钮手动确认。"
        )
        self.setVisible(True)

    def hide_banner(self):
        self.setVisible(False)