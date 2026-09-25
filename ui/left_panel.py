# -*- coding: utf-8 -*-
"""左侧抓取配置面板。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QListWidget, QListWidgetItem, QLineEdit, QPlainTextEdit,
    QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton, QLabel,
    QScrollArea, QFrame, QComboBox,
)

from config.default_settings import (
    SUPPORTED_FORMATS, FORMAT_LABELS, FORMAT_HINTS,
    NEEDS_SELECTOR, NEEDS_FIELDS, NEEDS_PATTERN,
    ENGINE_OPTIONS, DEFAULT_ENGINE, DEFAULT_ADAPTIVE,
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
    console_toggled  = Signal(bool)      # 显示 / 隐藏控制台窗口

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

        # ---------- ② 抓取引擎（反检测） ----------
        g_engine = QGroupBox("② 抓取引擎（反检测）")
        f_engine = QFormLayout(g_engine)

        self.engine_combo = QComboBox()
        for key, label, hint in ENGINE_OPTIONS:
            self.engine_combo.addItem(label, key)
            self.engine_combo.setItemData(
                self.engine_combo.count() - 1, hint,
                Qt.ItemDataRole.ToolTipRole)
        self.engine_combo.setToolTip(
            "决定页面 HTML 从哪里来。后三种由 Scrapling 提供，\n"
            "反检测作用在「请求阶段」；取回后仍走同一套检测 / 提取 / 翻页流程。\n"
            "未安装 Scrapling 时会自动回退为浏览器引擎。")
        f_engine.addRow("引擎：", self.engine_combo)

        self.adaptive_chk = QCheckBox("启用自适应选择器（网站改版自愈）")
        self.adaptive_chk.setToolTip(
            "常规选择器提取不到数据时，用 Scrapling 依据此前保存的元素特征\n"
            "重新定位元素。需先成功抓取过一次以保存特征。\n"
            "仅对「结构化记录」格式生效。")
        self.adaptive_chk.setChecked(bool(DEFAULT_ADAPTIVE))
        f_engine.addRow("", self.adaptive_chk)

        self.engine_hint = QLabel("")
        self.engine_hint.setObjectName("hintLabel")
        self.engine_hint.setWordWrap(True)
        f_engine.addRow("", self.engine_hint)

        lay.addWidget(g_engine)

        # ---------- ③ 翻页与节奏 ----------
        g2 = QGroupBox("③ 翻页与抓取节奏")
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

        # ---------- ④ 执行 ----------
        g3 = QGroupBox("④ 执行")
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

        # 控制台开关。正式版用 console 子系统打包（这样启动期崩溃、Qt/Chromium
        # 的 WARNING、--selftest 的输出都还看得到），默认显示；隐藏只是
        # ShowWindow(SW_HIDE)，进程与日志都不受影响，随时可以再打开。
        self.console_chk = QCheckBox("显示控制台窗口（排查用）")
        self.console_chk.setToolTip(
            "正式版保留控制台：启动期报错、Chromium 警告、自检输出都在这里。\n"
            "取消勾选只是隐藏窗口，程序与日志（crawler_data\\logs\\）不受影响，\n"
            "随时可以再勾回来。用 pythonw 启动源码、或打包时设了 SC_CONSOLE=0 时，\n"
            "没有控制台可显示，此项会自动置灰。")
        v3.addWidget(self.console_chk)

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
        self.engine_combo.currentIndexChanged.connect(
            lambda _i: self.refresh_engine_hint())
        self.adaptive_chk.toggled.connect(
            lambda _v: self.refresh_engine_hint())
        self.console_chk.toggled.connect(self.console_toggled)

        self.refresh_engine_hint()
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

    # ------------------------------------------------------------------
    # 抓取引擎 / 自适应
    # ------------------------------------------------------------------
    def engine(self) -> str:
        """当前选择的抓取引擎 key（browser / http / stealth / dynamic）。"""
        return str(self.engine_combo.currentData() or DEFAULT_ENGINE)

    def adaptive_enabled(self) -> bool:
        return self.adaptive_chk.isChecked()

    def set_engine(self, engine: str, adaptive: bool = False) -> None:
        """按 key 选中引擎并设置自适应开关（用于恢复偏好）。"""
        idx = self.engine_combo.findData(str(engine or DEFAULT_ENGINE))
        self.engine_combo.blockSignals(True)
        self.engine_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.engine_combo.blockSignals(False)
        self.adaptive_chk.setChecked(bool(adaptive))
        self.refresh_engine_hint()

    def refresh_engine_hint(self) -> None:
        """按 Scrapling 的可用程度提示引擎可用性。

        这里用 ``scrapling_engine.probe()``（内部 find_spec）而**不是**真正
        import：仅为了显示一行提示，没必要在启动阶段就把 scrapling
        （连带 playwright）加载进来。真正的导入发生在开始抓取时。

        probe() 会先把外挂依赖目录（crawler_data/site-packages）加进
        sys.path，因此「把 scrapling 装到外挂目录」这种用法也能被认出来。

        **三种状态要分开说，别合并**（合并就会说谎）：
          ① 包没装        -> 只有浏览器引擎可用；
          ② 包装了、浏览器没下 -> HTTP 快速模式与自适应可用，
                             隐身 / 动态引擎会失败（这里必须说清楚）；
          ③ 都齐了        -> 四种引擎均可用。
        曾经的写法是「probe() 为真 => 四种引擎均可用」，把 ② 也说成全可用，
        用户照着去用隐身引擎就会在抓取时失败。
        """
        from core import scrapling_engine as se

        found = se.probe()
        # 自适应选择器同样依赖 Scrapling；不可用时置灰，避免给出一个
        # 勾了也不生效的开关（与「控制台」勾选框的处理方式保持一致）。
        self.adaptive_chk.setEnabled(bool(found))
        if not found:
            self.adaptive_chk.setToolTip(
                "需要 Scrapling：未安装时自适应选择器不会生效。\n"
                f"请先安装到外挂目录（{se.python_tag()}）：\n"
                f"{se.site_packages_hint()}")

        if not found:
            if self.engine() == "browser":
                self.engine_hint.setText(
                    "未检测到 Scrapling；浏览器引擎不受影响。\n"
                    f"要用其它三种引擎，可安装到外挂目录（需与本程序同为 "
                    f"Python {se.python_tag()}）：\n"
                    f"{se.site_packages_hint()}\n"
                    "安装完成后重新打开本程序即可识别。")
            else:
                self.engine_hint.setText(
                    "未检测到 Scrapling，该引擎将在抓取时自动回退为浏览器引擎。\n"
                    f"安装到外挂目录即可（需与本程序同为 Python {se.python_tag()}）：\n"
                    f"{se.site_packages_hint()}\n"
                    "安装完成后重新打开本程序即可识别。")
        elif not se.browsers_ready():
            self.engine_hint.setText(
                "Scrapling 已就绪：HTTP 快速模式与自适应选择器可用。\n"
                + se.install_hint())
        else:
            self.engine_hint.setText("Scrapling 已就绪，四种引擎均可用。")

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

    # ------------------------------------------------------------------
    # 控制台窗口
    # ------------------------------------------------------------------
    def console_visible(self) -> bool:
        return bool(self.console_chk.isChecked())

    def set_console_visible(self, visible: bool, available: bool = True) -> None:
        """同步控制台勾选框（不触发 console_toggled）。

        ``available=False``（进程压根没有控制台，例如用 pythonw.exe 跑源码）
        时置灰并换一条说明，避免给出一个勾了也不生效的开关。
        """
        self.console_chk.blockSignals(True)
        self.console_chk.setChecked(bool(visible))
        self.console_chk.blockSignals(False)
        self.console_chk.setEnabled(bool(available))
        if not available:
            self.console_chk.setToolTip(
                "当前运行方式没有控制台窗口（例如用 pythonw.exe 启动源码）。\n"
                "打包版默认带控制台，此项可用。")

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
        self.set_engine(getattr(p, "last_engine", DEFAULT_ENGINE),
                        getattr(p, "last_adaptive", DEFAULT_ADAPTIVE))
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
            engine=self.engine(),
            adaptive=self.adaptive_enabled(),
        )

        # 记忆偏好
        p = self.prefs
        p.last_modes = modes
        p.last_mode = modes[0] if modes else ""   # 兼容旧字段
        p.last_delay = task.delay
        p.last_max_pages = task.max_pages
        p.last_autoscroll = task.autoscroll
        p.last_engine = task.engine
        p.last_adaptive = task.adaptive

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