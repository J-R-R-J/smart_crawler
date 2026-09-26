# -*- coding: utf-8 -*-
"""设置对话框：依赖与「浏览器增强包」的安装指引。

为什么单独做一个对话框，而不是只写在 README 里：

  免安装版**不携带 README**（zip 里只有 exe 与 _internal），而要用
  隐身 / 动态引擎还得再凑齐两样东西 —— ``scrapling`` 包 + Playwright 浏览器。
  把指引只放在 README，对免安装版用户等于没有。所以做成界面里随时能点开的
  对话框，并附带「复制命令」「打开目录」两个动作，省掉手打一长串路径。

**文案里的路径、命令与版本号一律从 core.scrapling_engine 取，不在这里另写
一份**（``site_packages_dir()`` / ``browser_target_dir()`` / ``site_packages_hint()``
/ ``install_hint()`` / ``browser_tree_text()`` / ``dry_run_hint()`` / ``mirror_hint()``）。
写死的话，换打包解释器、换依赖版本或换落点就会两边漂移 ——
这类「文档里的路径和代码里的不一致」在本项目已经出过好几次。

界面不做实时刷新：这是用户主动打开的说明窗口，打开时取一次状态即可
（改完目录后自动刷新一次，因为那是本窗口自己做的改动）。
"""

import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from config.default_settings import ANTIBOT_ITEMS
from core import scrapling_engine as se
from utils.logger import log_info

#: 需求对照：哪个引擎需要什么。三列都写成「要 / 不要」，避免只写「要」时
#: 读者以为没写的就是必须。
NEEDS = (
    ("浏览器引擎（默认）", "不要", "不要"),
    ("HTTP 快速模式", "要", "不要"),
    ("自适应选择器", "要", "不要"),
    ("隐身引擎 StealthyFetcher", "要", "要"),
    ("动态引擎 DynamicFetcher", "要", "要"),
)

#: 「浏览器目录是谁定的」→ 给用户看的一句话
SOURCE_LABELS = {
    "env": "环境变量 PLAYWRIGHT_BROWSERS_PATH（优先级最高）",
    "custom": "本窗口里自定义的目录",
    "auto": "程序自动探测到的默认位置",
    "": "还没确定（下面任选一条路线装一次即可）",
}


def _mono(text: str) -> QPlainTextEdit:
    """只读的等宽文本框，用来展示要复制到终端的命令。"""
    box = QPlainTextEdit(text)
    box.setReadOnly(True)
    box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    box.setFixedHeight(min(150, 26 + 20 * (text.count("\n") + 1)))
    return box


class SettingsDialog(QDialog):
    """「设置」按钮打开的窗口：反检测强化 + 依赖与浏览器增强包说明。"""

    def __init__(self, parent=None, prefs=None, apply_cb=None):
        super().__init__(parent)
        self.setWindowTitle("设置 · 反检测与依赖")
        self.setMinimumSize(720, 640)
        self._command = ""
        # prefs / apply_cb 允许缺省：测试与临时调用可以只 new 一个窗口
        # 看文案，不需要真的接上偏好存储。
        if prefs is None:
            from core.user_prefs import UserPrefs
            prefs = UserPrefs()
        self._prefs = prefs
        self._apply_cb = apply_cb
        self._boxes = {}
        self._build()
        self.refresh()

    # ------------------------------------------------------------------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        title = QLabel("反检测强化 与「浏览器增强包」安装指引")
        title.setObjectName("countLabel")
        outer.addWidget(title)

        intro = QLabel(
            "默认的「浏览器引擎」不需要装任何东西。只有下面这四种引擎需要 "
            "Scrapling；其中隐身 / 动态两种还要额外一份 Playwright 浏览器"
            "（约 700 MB，解压后约 706 MB）。")
        intro.setObjectName("hintLabel")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        # ---- 可滚动区：反检测 + 状态 + 三条路线 ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(10)

        lay.addWidget(self._antibot_group())
        lay.addWidget(self._status_group())
        lay.addWidget(self._needs_group())
        lay.addWidget(self._paths_group())
        lay.addWidget(self._route1_group())
        lay.addWidget(self._route2_group())
        lay.addWidget(self._route3_group())
        lay.addWidget(self._notes_group())
        lay.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # ---- 底部按钮 ----
        row = QHBoxLayout()
        self.btn_open_browsers = QPushButton("打开浏览器目录")
        self.btn_open_browsers.setToolTip(
            "打开 ms-playwright 文件夹（自定义目录优先）；不存在时会先创建")
        self.btn_open_browsers.clicked.connect(
            lambda: self._open_dir(se.browser_target_dir()))

        self.btn_open_pkgs = QPushButton("打开外挂依赖目录")
        self.btn_open_pkgs.setToolTip(
            "把 scrapling 装到这里（pip --target 的目标目录）")
        self.btn_open_pkgs.clicked.connect(
            lambda: self._open_dir(se.site_packages_dir()))

        self.btn_copy = QPushButton("复制安装命令")
        self.btn_copy.setObjectName("primary")
        self.btn_copy.clicked.connect(self.copy_command)

        self.btn_refresh = QPushButton("刷新状态")
        self.btn_refresh.setToolTip("装完/解压完之后点一下，不用重启程序")
        self.btn_refresh.clicked.connect(self.refresh)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)

        row.addWidget(self.btn_open_browsers)
        row.addWidget(self.btn_open_pkgs)
        row.addWidget(self.btn_refresh)
        row.addStretch(1)
        row.addWidget(self.btn_copy)
        row.addWidget(box)
        outer.addLayout(row)

    # ------------------------------------------------------------------
    def _antibot_group(self) -> QGroupBox:
        """反检测强化：一个总开关 + 六个子项。

        文案与顺序取自 config.default_settings.ANTIBOT_ITEMS，
        **不在这里另写一份**（文案与实现漂移过一次就会有第二次）。
        """
        g = QGroupBox("① 反检测强化")
        lay = QVBoxLayout(g)

        self.chk_master = QCheckBox("启用反检测强化（总开关）")
        self.chk_master.setToolTip(
            "关掉它等于把下面六项全部关掉，用来排查「抓不到内容是不是伪装导致的」。\n"
            "重新勾上会回到原来的组合。")
        lay.addWidget(self.chk_master)

        for key, label, hint in ANTIBOT_ITEMS:
            box = QCheckBox(label)
            box.setToolTip(hint)
            self._boxes[key] = box
            lay.addWidget(box)

        self.chk_creatives = QCheckBox("同时拦截可见广告素材（可能触发反广告检测）")
        self.chk_creatives.setToolTip(
            "默认关闭。把 AdSense 这类可见广告位也拦掉，等于向站点的反广告脚本"
            "自首 —— 它们正是靠「广告元素有没有加载成功」来判断你装没装拦截器。")
        lay.addWidget(self.chk_creatives)

        tip = QLabel(
            "改动立即生效并写入 crawler_data\\settings.ini。"
            "其中 Canvas 指纹干扰 / WebRTC 泄露防护是注入到页面里的，"
            "**对已经打开的页面要刷新一次才生效**。")
        tip.setObjectName("hintLabel")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self.chk_master.toggled.connect(self._on_master_toggled)
        for key, box in self._boxes.items():
            box.toggled.connect(lambda _v, k=key: self._save(k))
        self.chk_creatives.toggled.connect(
            lambda _v: self._save("block_ad_creatives"))
        return g

    def _on_master_toggled(self, value: bool) -> None:
        self._prefs.antibot_enabled = bool(value)
        self._sync_enabled_state()
        self._notify()

    def _sync_enabled_state(self) -> None:
        on = self.chk_master.isChecked()
        for box in self._boxes.values():
            box.setEnabled(on)
        self.chk_creatives.setEnabled(on)

    def _save(self, key: str) -> None:
        """把某个子项写进偏好并通知外部应用。"""
        box = self._boxes.get(key) or self.chk_creatives
        try:
            setattr(self._prefs, key, bool(box.isChecked()))
        except Exception as exc:                       # pragma: no cover
            log_info("[settings] 保存 %s 失败：%s" % (key, exc))
            return
        self._notify()

    def _notify(self) -> None:
        if callable(self._apply_cb):
            try:
                self._apply_cb()
            except Exception as exc:                   # pragma: no cover
                log_info("[settings] 应用反检测设置失败：%s" % exc)

    def load_antibot(self) -> None:
        """把偏好回填到勾选框（不触发保存）。"""
        p = self._prefs
        widgets = [self.chk_master, self.chk_creatives] + list(self._boxes.values())
        for w in widgets:
            w.blockSignals(True)
        self.chk_master.setChecked(bool(getattr(p, "antibot_enabled", True)))
        for key, box in self._boxes.items():
            box.setChecked(bool(getattr(p, key, True)))
        self.chk_creatives.setChecked(
            bool(getattr(p, "block_ad_creatives", False)))
        for w in widgets:
            w.blockSignals(False)
        self._sync_enabled_state()

    def _status_group(self) -> QGroupBox:
        g = QGroupBox("② 当前状态")
        lay = QVBoxLayout(g)
        self.lbl_pkg = QLabel("")
        self.lbl_pkg.setWordWrap(True)
        self.lbl_dir = QLabel("")
        self.lbl_dir.setWordWrap(True)
        self.lbl_engine = QLabel("")
        self.lbl_engine.setWordWrap(True)
        for w in (self.lbl_pkg, self.lbl_dir, self.lbl_engine):
            lay.addWidget(w)
        return g

    # ------------------------------------------------------------------
    def _paths_group(self) -> QGroupBox:
        """④ 引擎文件位置：外挂依赖目录 / 浏览器目录都可以自定义。

        存在的意义：包与浏览器合计数百 MB，用户完全可能装在别的盘；
        而 playwright 联网下载默认落在 ``%LOCALAPPDATA%\\ms-playwright``——
        有了这一组，**不用搬文件**，把程序指过去就行。
        """
        g = QGroupBox("④ 引擎文件位置（可自定义，改完立即生效）")
        lay = QVBoxLayout(g)

        tip = QLabel(
            "留空 = 用默认位置。装到别的盘、或者让 playwright 下到了用户目录时，"
            "在这里指过去即可，不需要移动任何文件。")
        tip.setObjectName("hintLabel")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self.edit_pkgs = QLineEdit("")
        self.edit_browsers = QLineEdit("")
        for label, edit, btn_text, handler, reset in (
            ("外挂依赖目录（scrapling）", self.edit_pkgs, "选择…",
             lambda: self._pick_dir("pkgs"), lambda: self._set_path("pkgs", "")),
            ("浏览器目录（ms-playwright）", self.edit_browsers, "选择…",
             lambda: self._pick_dir("browsers"),
             lambda: self._set_path("browsers", "")),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            edit.setReadOnly(True)
            edit.setToolTip("留空 = 使用默认位置")
            row.addWidget(edit, 1)
            btn = QPushButton(btn_text)
            btn.clicked.connect(handler)
            row.addWidget(btn)
            btn_reset = QPushButton("恢复默认")
            btn_reset.clicked.connect(reset)
            row.addWidget(btn_reset)
            lay.addLayout(row)

        self.lbl_path_note = QLabel("")
        self.lbl_path_note.setObjectName("hintLabel")
        self.lbl_path_note.setWordWrap(True)
        lay.addWidget(self.lbl_path_note)
        return g

    def _pick_dir(self, which: str) -> None:
        """选目录 → 写偏好 → 同步到融合层 → 立刻刷新状态。"""
        current = (self.edit_pkgs.text() if which == "pkgs"
                   else self.edit_browsers.text())
        start = current or (se.site_packages_dir() if which == "pkgs"
                            else se.browser_target_dir())
        chosen = QFileDialog.getExistingDirectory(self, "选择目录", start)
        if not chosen:
            return
        self._set_path(which, chosen)

    def _set_path(self, which: str, value: str) -> None:
        if which == "pkgs":
            self.edit_pkgs.setText(value)
            try:
                self._prefs.site_packages_path = value
            except Exception as exc:                   # pragma: no cover
                log_info("[settings] 保存外挂目录失败：%s" % exc)
            se.set_custom_paths(site_packages=value)
        else:
            self.edit_browsers.setText(value)
            try:
                self._prefs.browsers_path = value
            except Exception as exc:                   # pragma: no cover
                log_info("[settings] 保存浏览器目录失败：%s" % exc)
            se.set_custom_paths(browsers=value)
        self._notify()
        self.refresh()

    def load_paths(self) -> None:
        """把偏好回填到两个路径框。"""
        for edit, val in ((self.edit_pkgs, getattr(self._prefs, "site_packages_path", "")),
                          (self.edit_browsers, getattr(self._prefs, "browsers_path", ""))):
            edit.blockSignals(True)
            edit.setText(str(val or ""))
            edit.blockSignals(False)

    def _needs_group(self) -> QGroupBox:
        g = QGroupBox("③ 哪个引擎需要什么")
        lay = QVBoxLayout(g)
        head = QLabel("<b>引擎</b> ｜ <b>要 scrapling 包</b> ｜ <b>要浏览器</b>")
        lay.addWidget(head)
        for name, pkg, br in NEEDS:
            lay.addWidget(QLabel("%s ｜ %s ｜ %s" % (name, pkg, br)))
        hint = QLabel(
            "也就是说：只装 scrapling 包，就已经能用上 HTTP 快速模式与"
            "自适应选择器，不需要再下任何东西。")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return g

    def _route1_group(self) -> QGroupBox:
        drop = se.browser_target_dir()
        g = QGroupBox("⑤ 路线 1（推荐）：解压「浏览器增强包」")
        lay = QVBoxLayout(g)
        txt = QLabel(
            "从 Release 附件下载 <b>SmartCrawler-v0.0.4-win64-browsers.zip</b>，"
            "把里面的 <b>ms-playwright</b> 文件夹解压到下面这个位置"
            "（和 SmartCrawler.exe 同一层）：")
        txt.setWordWrap(True)
        lay.addWidget(txt)
        lay.addWidget(_mono(drop))
        tip = QLabel("解压完成后，目录里应该是这个样子：")
        lay.addWidget(tip)
        tree = _mono(se.browser_tree_text(drop))
        tree.setFixedHeight(min(260, 26 + 20 * (se.browser_tree_text(drop).count("\n") + 1)))
        lay.addWidget(tree)
        tip2 = QLabel(
            "免安装版已经预留了这个空文件夹，直接解压覆盖进去即可，"
            "不需要设任何环境变量。\n"
            "⚠ 解压时**不要多套一层同名文件夹**（变成 ms-playwright\\ms-playwright\\ 就"
            "等于没装），也不要把 headless shell 的内容合并进 chrome-win64\\。")
        tip2.setObjectName("hintLabel")
        tip2.setWordWrap(True)
        lay.addWidget(tip2)
        return g

    def _route2_group(self) -> QGroupBox:
        g = QGroupBox("⑥ 路线 2：联网自行下载（playwright 官方源）")
        lay = QVBoxLayout(g)
        txt = QLabel(
            "先装包（把外挂依赖目录建出来），再下浏览器。"
            "命令里的路径都可以用上面两个「打开目录」按钮核对：")
        txt.setWordWrap(True)
        lay.addWidget(txt)
        self.box_route2 = _mono("")
        lay.addWidget(self.box_route2)

        where = QLabel(
            "⚠ 不指定目录时，浏览器会下到 <b>用户目录</b>，不是程序目录：<br>"
            f"&nbsp;&nbsp;<code>{se.default_download_dir()}</code><br>"
            "找不到浏览器时先来这里看；**不用搬文件** —— "
            "在上面的「④ 引擎文件位置」里把浏览器目录指过去即可。")
        where.setObjectName("hintLabel")
        where.setWordWrap(True)
        lay.addWidget(where)

        self.box_dryrun = _mono(se.dry_run_hint())
        lay.addWidget(self.box_dryrun)
        tip = QLabel(
            "浏览器不要去下 camoufox / Firefox —— 这里要的是 chromium。"
            "官方源慢或不通时走路线 1 或路线 3。")
        tip.setObjectName("hintLabel")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        return g

    def _route3_group(self) -> QGroupBox:
        g = QGroupBox("⑦ 路线 3：国内镜像手动下载（npmmirror）")
        lay = QVBoxLayout(g)
        txt = QLabel(
            "官方 CDN 在国内经常只有几十 KB/s。镜像里这两份 zip 与本程序需要的"
            "版本完全一致，下载后按下面的目录名摆好即可（含标记文件，"
            "否则 playwright 会把手动装的当成「没安装」重新下载）：")
        txt.setWordWrap(True)
        lay.addWidget(txt)
        self.box_route3 = _mono(se.mirror_hint())
        self.box_route3.setFixedHeight(
            min(420, 26 + 20 * (se.mirror_hint().count("\n") + 1)))
        lay.addWidget(self.box_route3)
        tip = QLabel(
            "为什么不直接设 PLAYWRIGHT_DOWNLOAD_HOST 让它自己走镜像："
            "playwright 1.58 起 Chromium 改用 Chrome for Testing，下载路径 "
            "builds/cft/… 是**硬编码**的，而那个环境变量只替换域名，"
            "拼到镜像上就是 404 —— 只能手动下。")
        tip.setObjectName("hintLabel")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        return g

    def _notes_group(self) -> QGroupBox:
        g = QGroupBox("⑧ 注意事项")
        lay = QVBoxLayout(g)
        for line in (
            "· pip 的 --python 必须写在 install 之前，否则报 "
            "\"The --python option must be placed before the pip subcommand name\"。",
            "· 免安装版装外挂依赖要用与内置运行时同一次版本的 Python"
            "（当前为 %s），否则 curl_cffi / greenlet 这类 C 扩展导入失败。" % se.python_tag(),
            "· 浏览器默认下到 %s，常被杀软拦成 "
            "EPERM: operation not permitted；换个目录并加白名单，"
            "再用「④ 引擎文件位置」指过去。" % se.default_download_dir(),
            "· 免安装版执行 scrapling.exe 前必须设 PYTHONPATH，否则它自己都"
            "导不进来（pip --target 装的脚本，sys.path[0] 是 Scripts\\ 那一层）。",
            "· 解压/摆放后的目录名要与上面完全一致；多套一层、或把 headless shell "
            "放进 chrome-win64\\，playwright 都会当作「没安装」而重新下载。",
            "· 手动装（路线 3）时记得建 INSTALLATION_COMPLETE 与 "
            "DEPENDENCIES_VALIDATED 两个空标记文件；后者过期（30 天）后"
            "playwright 会重跑依赖校验，那时需要 winldd-*\\PrintDeps.exe。",
            "· 直接用 python -m scrapling 会报 No module named scrapling.__main__"
            "（该包没有 __main__.py），要用 scrapling.exe 这个控制台脚本；"
            "playwright 不受此限，python -m playwright 是可用的。",
            "· 换过目录后点一下「刷新状态」。程序每次探测都会重新判断，"
            "不必重启；但已经在跑的抓取任务要重开才会用上新引擎。",
        ):
            w = QLabel(line)
            w.setWordWrap(True)
            lay.addWidget(w)
        return g

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """取一次状态，顺便决定哪个按钮/命令是当前该给用户的。"""
        self.load_antibot()
        self.load_paths()
        found = se.probe()
        ver = se.version() if found else ""
        ready = bool(found) and se.browsers_ready()
        source = se.browsers_dir_source()
        bdir = se.browsers_dir() or "（未确定）"

        self.lbl_pkg.setText(
            "Scrapling 包：<b>已安装 %s</b>（%s）" % (ver or "版本未知",
                                                se.site_packages_dir())
            if found else
            "Scrapling 包：<b>未安装</b>（可选依赖，不装也能用）"
            "，将搜索：%s" % se.site_packages_dir())
        self.lbl_dir.setText(
            "浏览器目录：<b>未确定</b> —— 按下面任一条路线装一次即可"
            if bdir == "（未确定）" else
            "浏览器目录：%s（%s）" % (bdir, SOURCE_LABELS.get(source, source)))
        if ready:
            self.lbl_engine.setText("隐身 / 动态引擎：<b>可用</b>")
        elif found:
            self.lbl_engine.setText(
                "隐身 / 动态引擎：<b>还缺浏览器</b> —— 按下面路线 1 / 2 / 3 装一次即可")
        else:
            self.lbl_engine.setText(
                "隐身 / 动态引擎：<b>不可用</b> —— 先装包，再按路线 1 / 2 / 3 装浏览器")

        note = ""
        if source:
            note = ("当前生效的浏览器目录由「%s」决定。"
                    % SOURCE_LABELS.get(source, source))
        if source == "env":
            note += ("\n环境变量优先级最高：即使这里填了自定义目录，"
                     "也请先清掉该环境变量（或让它指向同一个目录）。")
        self.lbl_path_note.setText(note)

        # 版本号/镜像地址随依赖版本变化，这里每次刷新重算一遍
        self.box_route3.setPlainText(se.mirror_hint())
        self.box_dryrun.setPlainText(se.dry_run_hint())

        # 复制按钮给「当前最该执行的那一段」，而不是把所有文本混在一起
        if not found:
            self._command = se.site_packages_hint()
        elif ready:
            self._command = ""
        else:
            self._command = se.install_hint()
        self.box_route2.setPlainText(
            se.site_packages_hint() + "\n\n" + se.install_hint())
        self.btn_copy.setEnabled(bool(self._command))
        self.btn_copy.setText("复制安装命令（已就绪）" if ready else "复制安装命令")

    # ------------------------------------------------------------------
    def copy_command(self) -> bool:
        """把当前该用的命令放进剪贴板。返回是否成功。"""
        if not self._command:
            return False
        try:
            QGuiApplication.clipboard().setText(self._command)
        except Exception as exc:                     # pragma: no cover - 取决于平台
            log_info("[settings] 写剪贴板失败：%s" % exc)
            return False
        self.btn_copy.setText("已复制")
        log_info("[settings] 安装命令已复制到剪贴板")
        return True

    def _open_dir(self, path: str) -> bool:
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
        return QDesktopServices.openUrl(QUrl.fromLocalFile(path))
