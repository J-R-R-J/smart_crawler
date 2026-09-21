# -*- coding: utf-8 -*-
"""左侧抓取配置面板。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QListWidget, QListWidgetItem, QLineEdit, QPlainTextEdit,
    QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton, QLabel,
    QScrollArea, QFrame,
)

from config.default_settings import (
    SUPPORTED_FORMATS, FORMAT_LABELS, FORMAT_HINTS,
    NEEDS_SELECTOR, NEEDS_FIELDS, NEEDS_PATTERN,
)
from models.field import Field
from models.task  import Task
from core.user_prefs import UserPrefs


class LeftPanel(QWidget):
    start_clicked   = Signal()
    stop_clicked    = Signal()
    clear_clicked   = Signal()
    keywords_clicked = Signal()          # 打开「检测关键词设置」
    settings_changed = Signal()          # 反爬 / 下载上限发生变化

    def __init__(self, prefs: UserPrefs, parent=None):
        super().__init__(parent)
        self.prefs = prefs
        self._build()
        self._load_prefs()

    # ==================================================================
    # UI
    # ==================================================================
    def _build(self):
        # 外层只放一个滚动区：窗口再矮也能滚到全部配置，
        # 最大化时也不会再把控件挤压变形。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer.addWidget(self.scroll)

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(8)

        # ---------- ① 抓取格式（可多选） ----------
        g1 = QGroupBox("① 抓取目标格式（可多选）")
        v1 = QVBoxLayout(g1)

        self.mode_list = QListWidget()
        self.mode_list.setFixedHeight(150)
        self.mode_list.setToolTip("勾选一种或多种格式，将同时提取并合并结果")
        for key, label, hint in SUPPORTED_FORMATS:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setToolTip(hint)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.mode_list.addItem(item)
        self.mode_list.itemChanged.connect(self._update_hints)
        v1.addWidget(self.mode_list)

        row_sel = QHBoxLayout()
        self.btn_check_all = QPushButton("全选")
        self.btn_check_none = QPushButton("清空选择")
        row_sel.addWidget(self.btn_check_all)
        row_sel.addWidget(self.btn_check_none)
        row_sel.addStretch(1)
        v1.addLayout(row_sel)

        self.mode_hint = QLabel("")
        self.mode_hint.setObjectName("hintLabel")
        self.mode_hint.setWordWrap(True)
        v1.addWidget(self.mode_hint)

        f1 = QFormLayout()
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
        v1.addLayout(f1)

        self.btn_keywords = QPushButton("检测关键词设置…")
        self.btn_keywords.setToolTip(
            "自定义验证码 / 频控 / 登录墙的识别关键词")
        v1.addWidget(self.btn_keywords)

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

        self.stealth_chk = QCheckBox("启用反爬特征伪装（推荐）")
        self.stealth_chk.setToolTip(
            "隐藏自动化浏览器特征，并让每页延迟随机抖动，降低被风控拦截的概率")
        self.stealth_chk.setChecked(True)
        f2.addRow("", self.stealth_chk)

        self.download_spin = QSpinBox()
        self.download_spin.setRange(0, 102400)
        self.download_spin.setValue(50)
        self.download_spin.setSuffix(" MB")
        self.download_spin.setToolTip("单个文件下载大小上限，0 表示不限制")
        f2.addRow("下载上限：", self.download_spin)

        self.download_exts_edit = QLineEdit()
        self.download_exts_edit.setPlaceholderText("留空＝不限，如 pdf,csv,xlsx,zip")
        self.download_exts_edit.setToolTip(
            "只允许下载这些扩展名的文件（英文逗号分隔，不区分大小写）。\n"
            "留空表示允许全部。用于拦截站点的广告、安装包等非目标文件。")
        f2.addRow("下载格式：", self.download_exts_edit)

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

        # 把内容挂到滚动区（QScrollArea 接管所有权）
        self.scroll.setWidget(content)

        # 信号
        self.btn_start.clicked.connect(self.start_clicked)
        self.btn_stop.clicked.connect(self.stop_clicked)
        self.btn_clear.clicked.connect(self.clear_clicked)
        self.btn_keywords.clicked.connect(self.keywords_clicked)
        self.btn_check_all.clicked.connect(lambda: self._set_all_checked(True))
        self.btn_check_none.clicked.connect(lambda: self._set_all_checked(False))
        self.stealth_chk.toggled.connect(lambda _v: self.settings_changed.emit())
        self.download_spin.valueChanged.connect(
            lambda _v: self.settings_changed.emit())
        self.download_exts_edit.textChanged.connect(
            lambda _t: self.settings_changed.emit())

        self._update_hints()

    # ==================================================================
    # 运行设置（反爬 / 下载）
    # ==================================================================
    def stealth_enabled(self) -> bool:
        return self.stealth_chk.isChecked()

    def max_download_mb(self) -> int:
        return int(self.download_spin.value())

    def download_exts(self) -> str:
        return self.download_exts_edit.text().strip()

    def set_run_settings(self, stealth: bool, max_download_mb: int,
                         download_exts: str = "") -> None:
        widgets = (self.stealth_chk, self.download_spin,
                   self.download_exts_edit)
        for w in widgets:
            w.blockSignals(True)
        self.stealth_chk.setChecked(bool(stealth))
        self.download_spin.setValue(int(max_download_mb or 0))
        self.download_exts_edit.setText(str(download_exts or ""))
        for w in widgets:
            w.blockSignals(False)

    # ==================================================================
    # 格式多选
    # ==================================================================
    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.mode_list.blockSignals(True)
        for i in range(self.mode_list.count()):
            self.mode_list.item(i).setCheckState(state)
        self.mode_list.blockSignals(False)
        self._update_hints()

    def selected_modes(self) -> list:
        """当前勾选的格式 key 列表（按列表顺序）。"""
        out = []
        for i in range(self.mode_list.count()):
            item = self.mode_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def set_selected_modes(self, modes) -> None:
        wanted = set(modes or [])
        self.mode_list.blockSignals(True)
        for i in range(self.mode_list.count()):
            item = self.mode_list.item(i)
            key = item.data(Qt.ItemDataRole.UserRole)
            item.setCheckState(Qt.CheckState.Checked if key in wanted
                               else Qt.CheckState.Unchecked)
        self.mode_list.blockSignals(False)
        self._update_hints()

    def _update_hints(self, *_):
        modes = self.selected_modes()
        if not modes:
            self.mode_hint.setText("请至少勾选一种格式")
        else:
            labels = [FORMAT_LABELS.get(m, m) for m in modes]
            if len(labels) <= 3:
                names = "、".join(labels)
            else:
                names = "、".join(labels[:3]) + f" 等 {len(labels)} 种"
            self.mode_hint.setText(f"已选 {len(modes)} 种：{names}")

        # 按需启用输入框
        self.selector_edit.setEnabled(any(m in NEEDS_SELECTOR for m in modes))
        self.fields_edit.setEnabled(any(m in NEEDS_FIELDS for m in modes))
        self.pattern_edit.setEnabled(any(m in NEEDS_PATTERN for m in modes))

    # ------------------------------------------------------------------
    def _load_prefs(self):
        p = self.prefs
        modes = p.last_modes or ([p.last_mode] if p.last_mode else []) or ["records"]
        self.set_selected_modes(modes)
        self.delay_spin.setValue(p.last_delay)
        self.max_pages_spin.setValue(p.last_max_pages)
        self.autoscroll_chk.setChecked(p.last_autoscroll)
        self.set_run_settings(p.stealth_enabled, p.max_download_mb,
                              p.download_exts)

    # ------------------------------------------------------------------
    def collect_task(self) -> Task:
        """从 UI 收集当前配置，生成 Task 对象。"""
        modes = self.selected_modes()
        fields = Field.parse_block(self.fields_edit.toPlainText())

        task = Task(
            url="",  # URL 由 main_window 提供
            modes=modes,
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
        p.last_modes = modes
        p.last_mode = modes[0] if modes else ""   # 兼容旧字段
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