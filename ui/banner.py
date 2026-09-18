# -*- coding: utf-8 -*-
"""人类验证横幅：在检测到验证码 / 登录墙时提示，并提供确认与跳过两个出口。"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


class HumanBanner(QFrame):
    done_clicked = Signal()      # 我已处理完成
    skip_clicked = Signal()      # 跳过（判定为误判）

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

        self.btn_skip = QPushButton("跳过（误判）")
        self.btn_skip.setObjectName("bannerBtn")
        self.btn_skip.setToolTip(
            "页面实际没有验证码时使用：跳过后立即继续抓取，"
            "且本任务内不再因验证暂停（重新开始任务会恢复检测）")
        self.btn_skip.clicked.connect(self.skip_clicked)

        self.btn_done = QPushButton("我已处理完成，继续抓取")
        self.btn_done.setObjectName("bannerBtn")
        self.btn_done.clicked.connect(self.done_clicked)

        lay.addWidget(self.label, 1)
        lay.addWidget(self.btn_skip)
        lay.addWidget(self.btn_done)

    # ------------------------------------------------------------------
    def show_for(self, level: str, reason: str):
        kind = {
            "CAPTCHA": "验证码",
            "HUMAN": "访问频控",
            "LOGIN": "登录墙",
        }.get(level, "验证")

        if "已确认为验证码" in reason or "已确认" in reason or "登录墙（已确认" in reason:
            tail = "程序会自动检测恢复，也可点击右侧按钮手动确认。"
        else:
            tail = ("程序会自动检测恢复；若判断有误，可点「跳过（误判）」直接继续。")

        self.label.setText(
            f"检测到{kind}：{reason}\n"
            f"已自动暂停，请直接在下方浏览器中手动完成验证。{tail}"
        )
        self.setVisible(True)

    def hide_banner(self):
        self.setVisible(False)
