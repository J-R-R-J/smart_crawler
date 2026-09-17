# -*- coding: utf-8 -*-
"""左侧抓取配置面板。"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QComboBox, QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
    QCheckBox, QPushButton, QLabel,
)

from config.default_settings import SUPPORTED_FORMATS
from models.field import Field
from models.task  import Task
from core.user_prefs import UserPrefs


class LeftPanel(QWidget):
    start_clicked = Signal()
    stop_clicked  = Signal()
    clear_clicked = Signal()

    def __init__(self, prefs: UserPrefs, parent=None):
        super().__init__(parent)
        self.prefs = prefs
        self._build()
        self._load_prefs()

    # ==================================================================
    # UI
    # ==================================================================
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(8)

        # ---------- ① 抓取格式 ----------
        g1 = QGroupBox("① 抓取目标格式")
        f1 = QFormLayout(g1)

        self.mode_combo = QComboBox()
        for key, label, hint in SUPPORTED_FORMATS:
            self.mode_combo.addItem(f"{label}", key)
            self.mode_combo.setItemData(
                self.mode_combo.count() - 1, hint, 3)  # ToolTip
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        f1.addRow("格式：", self.mode_combo)

        self.mode_hint = QLabel("")
        self.mode_hint.setObjectName("hintLabel")
        f1.addRow("", self.mode_hint)

        self.selector_edit = QLineEdit()
        self.selector_edit.setPlaceholderText("容器选择器，如 .item 或 #list > li")
        f1.addRow("容器选择器：", self.selector_edit)

        self.fields_edit = QPlainTextEdit()
        self.fields_edit.setPlaceholderText(
            "字段映射，每行一条：\n"
            "名称 | 子选择器 | 类型 | 属性\n"
            "--------------------------------\n"
            "标题 | h3 > a   | text |\n"
            "链接 | h3 > a   | href |\n"
            "价格 | .price   | text |\n"
            "图片 | img      | src  |\n"
            "类型：text / href / src / html / attr"
        )
        self.fields_edit.setFixedHeight(140)
        f1.addRow("字段映射：", self.fields_edit)

        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText(
            r"正则表达式（regex 模式），如 (\d{4}-\d{2}-\d{2})")
        f1.addRow("正则：", self.pattern_edit)

        lay.addWidget(g1)

        # ---------- ② 翻页与节奏 ----------
        g2 = QGroupBox("② 翻页与抓取节奏")
        f2 = QFormLayout(g2)

        self.next_edit = QLineEdit()
        self.next_edit.setPlaceholderText("下一页按钮选择器，如 a.next")
        f2.addRow("下一页选择器：", self.next_edit)

        self.max_pages_spin = QSpinBox()
        self.max_pages_spin.setRange(1, 9999)
        self.max_pages_spin.setValue(1)
        f2.addRow("最大页数：", self.max_pages_spin)

        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 60.0)
        self.delay_spin.setSingleStep(0.5)
        self.delay_spin.setValue(1.5)
        self.delay_spin.setSuffix(" 秒")
        f2.addRow("每页延迟：", self.delay_spin)

        self.autoscroll_chk = QCheckBox("自动滚动触发懒加载")
        self.autoscroll_chk.setChecked(True)
        f2.addRow("", self.autoscroll_chk)

        lay.addWidget(g2)

        # ---------- ③ 执行 ----------
        g3 = QGroupBox("③ 执行")
        v3 = QVBoxLayout(g3)

        self.btn_start = QPushButton("开始抓取")
        self.btn_start.setObjectName("primary")
        self.btn_start.setFixedHeight(38)

        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)

        self.btn_clear = QPushButton("清空结果")

        v3.addWidget(self.btn_start)
        row = QHBoxLayout()
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_clear)
        v3.addLayout(row)

        lay.addWidget(g3)
        lay.addStretch(1)

        # 信号
        self.btn_start.clicked.connect(self.start_clicked)
        self.btn_stop.clicked.connect(self.stop_clicked)
        self.btn_clear.clicked.connect(self.clear_clicked)

        self._on_mode_changed(0)

    # ==================================================================
    # 逻辑
    # ==================================================================
    def _on_mode_changed(self, idx: int):
        key = self.mode_combo.itemData(idx) or "records"
        hint = self.mode_combo.itemData(idx, 3) or ""
        self.mode_hint.setText(hint)
        # 简单显隐控制
        need_selector = key in ("records", "list")
        need_fields   = key == "records"
        need_pattern  = key == "regex"
        self.selector_edit.setEnabled(need_selector or key in ("records", "list"))
        self.fields_edit.setEnabled(need_fields)
        self.pattern_edit.setEnabled(need_pattern)

    # ------------------------------------------------------------------
    def _load_prefs(self):
        p = self.prefs
        # mode
        for i in range(self.mode_combo.count()):
            if self.mode_combo.itemData(i) == p.last_mode:
                self.mode_combo.setCurrentIndex(i)
                break
        self.delay_spin.setValue(p.last_delay)
        self.max_pages_spin.setValue(p.last_max_pages)
        self.autoscroll_chk.setChecked(p.last_autoscroll)

    # ------------------------------------------------------------------
    def collect_task(self) -> Task:
        """从 UI 收集当前配置，生成 Task 对象。"""
        mode = self.mode_combo.currentData() or "records"
        fields = Field.parse_block(self.fields_edit.toPlainText())

        task = Task(
            url="",  # URL 由 main_window 提供
            mode=mode,
            selector=self.selector_edit.text().strip(),
            fields=fields,
            pattern=self.pattern_edit.text().strip(),
            flags="g",
            next_selector=self.next_edit.text().strip(),
            max_pages=self.max_pages_spin.value(),
            delay=self.delay_spin.value(),
            autoscroll=self.autoscroll_chk.isChecked(),
        )

        # 记忆偏好
        p = self.prefs
        p.last_mode = mode
        p.last_delay = task.delay
        p.last_max_pages = task.max_pages
        p.last_autoscroll = task.autoscroll

        return task

    # ------------------------------------------------------------------
    def set_running(self, running: bool):
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    # ------------------------------------------------------------------
    def apply_picked_selector(self, selector: str, text: str, tag: str):
        """元素拾取回调：智能填充。"""
        cur = self.selector_edit.text().strip()
        if not cur:
            self.selector_edit.setText(selector)
        if not self.fields_edit.toPlainText().strip():
            name = (text[:8] or tag.lower() or "字段1").replace("|", "")
            self.fields_edit.setPlainText(f"{name} | {selector} | text |")