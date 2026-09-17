# -*- coding: utf-8 -*-
"""浏览器视图容器。"""

from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtWebEngineWidgets import QWebEngineView


class CenterPanel(QWidget):
    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.view = QWebEngineView()
        self.view.setPage(page)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)

    # ------------------------------------------------------------------
    def set_page(self, page):
        """Profile 切换后调用。"""
        self.view.setPage(page)