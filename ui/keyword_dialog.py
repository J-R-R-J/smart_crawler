# -*- coding: utf-8 -*-
"""检测关键词设置对话框。

三个分组各自一行一个关键词；保存后写入 `crawler_data/keywords.json`，
`core.detector` 立即生效，无需重启。
"""

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout,
)

from config import keyword_store


class KeywordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("检测关键词设置")
        self.setMinimumSize(560, 460)
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        lay = QVBoxLayout(self)

        tip = QLabel(
            "每行一个关键词，不区分大小写。\n"
            "检测时会同时扫描 HTML 源码、页面标题、URL 与渲染后的可见文本，"
            "并自动忽略零宽字符与空格干扰。"
        )
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self.tabs = QTabWidget()
        self.editors = {}
        for group in keyword_store.GROUPS:
            editor = QPlainTextEdit()
            editor.setPlaceholderText("每行一个关键词")
            editor.setPlainText("\n".join(keyword_store.load(group)))
            self.tabs.addTab(editor, keyword_store.GROUP_LABELS.get(group, group))
            self.editors[group] = editor
        lay.addWidget(self.tabs, 1)

        row = QHBoxLayout()
        self.btn_reset_group = QPushButton("恢复本组默认")
        self.btn_reset_all = QPushButton("恢复全部默认")
        row.addWidget(self.btn_reset_group)
        row.addWidget(self.btn_reset_all)
        row.addStretch(1)
        lay.addLayout(row)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        self.btn_reset_group.clicked.connect(self._on_reset_group)
        self.btn_reset_all.clicked.connect(self._on_reset_all)

    # ------------------------------------------------------------------
    def _current_group(self) -> str:
        idx = self.tabs.currentIndex()
        return keyword_store.GROUPS[idx] if 0 <= idx < len(keyword_store.GROUPS) else ""

    def _fill(self, group: str, words) -> None:
        editor = self.editors.get(group)
        if editor is not None:
            editor.setPlainText("\n".join(words))

    def _on_reset_group(self):
        group = self._current_group()
        if not group:
            return
        self._fill(group, keyword_store.defaults(group))

    def _on_reset_all(self):
        for group in keyword_store.GROUPS:
            self._fill(group, keyword_store.defaults(group))

    def _on_save(self):
        data = {g: self.editors[g].toPlainText().splitlines()
                for g in keyword_store.GROUPS}
        if not any(v for v in data.values()):
            QMessageBox.warning(self, "无法保存", "至少需要保留一个关键词。")
            return
        try:
            keyword_store.save_all(data)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
            return
        self.accept()
