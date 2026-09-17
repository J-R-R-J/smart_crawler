# -*- coding: utf-8 -*-
"""Cookie 面板：Profile 切换 + Cookie 表格 + 增删改 + 导入导出。"""

import os
from typing import Any, Dict, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFileDialog, QMessageBox, QInputDialog,
    QDialog, QDialogButtonBox, QMenu,
)

from config.constants import COOKIE_DIR
from utils.exporters import export_cookies
from utils.logger import log_info

from core.browser import list_profiles, delete_profile
from core.user_prefs import UserPrefs


# ======================================================================
# 添加/编辑 Cookie 对话框
# ======================================================================
class CookieEditDialog(QDialog):
    def __init__(self, parent=None, initial: Dict[str, Any] = None):
        super().__init__(parent)
        self.setWindowTitle("编辑 Cookie")
        self.setMinimumWidth(420)

        from PySide6.QtWidgets import QFormLayout, QLineEdit, QCheckBox
        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit    = QLineEdit()
        self.value_edit   = QLineEdit()
        self.domain_edit  = QLineEdit()
        self.path_edit    = QLineEdit("/")
        self.secure_chk   = QCheckBox("Secure")
        self.http_chk     = QCheckBox("HttpOnly")

        form.addRow("Name:",     self.name_edit)
        form.addRow("Value:",    self.value_edit)
        form.addRow("Domain:",   self.domain_edit)
        form.addRow("Path:",     self.path_edit)
        form.addRow("",          self.secure_chk)
        form.addRow("",          self.http_chk)

        lay.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        if initial:
            self.name_edit.setText(initial.get("name", ""))
            self.value_edit.setText(initial.get("value", ""))
            self.domain_edit.setText(initial.get("domain", ""))
            self.path_edit.setText(initial.get("path", "/"))
            self.secure_chk.setChecked(bool(initial.get("secure", False)))
            self.http_chk.setChecked(bool(initial.get("http_only", False)))

    def get_data(self) -> Dict[str, Any]:
        return {
            "name": self.name_edit.text().strip(),
            "value": self.value_edit.text(),
            "domain": self.domain_edit.text().strip(),
            "path": self.path_edit.text().strip() or "/",
            "secure": self.secure_chk.isChecked(),
            "http_only": self.http_chk.isChecked(),
        }


# ======================================================================
# Cookie 面板
# ======================================================================
class CookiePanel(QWidget):
    profile_switch_requested = Signal(str)   # 请求主窗口切换 profile

    COLS = ["Name", "Value", "Domain", "Path", "Secure", "HttpOnly", "Session"]

    def __init__(self, prefs: UserPrefs, parent=None):
        super().__init__(parent)
        self.prefs = prefs
        self.cookie_manager = None       # 由 main_window 挂载
        self._cookies: List[Dict] = []
        self._build()
        self._refresh_profiles()

    # ==================================================================
    # UI
    # ==================================================================
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        # ---------- Profile 切换区 ----------
        top = QHBoxLayout()

        top.addWidget(QLabel("Profile："))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(160)
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        top.addWidget(self.profile_combo)

        self.btn_set_default = QPushButton("设为默认")
        self.btn_set_default.setToolTip("设为每次启动时默认使用的 Profile")
        self.btn_set_default.clicked.connect(self._on_set_default)

        self.btn_new_profile = QPushButton("新建")
        self.btn_new_profile.clicked.connect(self._on_new_profile)

        self.btn_del_profile = QPushButton("删除")
        self.btn_del_profile.clicked.connect(self._on_delete_profile)

        top.addWidget(self.btn_set_default)
        top.addWidget(self.btn_new_profile)
        top.addWidget(self.btn_del_profile)
        top.addStretch(1)

        lay.addLayout(top)

        # ---------- Cookie 操作区 ----------
        bar = QHBoxLayout()

        self.count_label = QLabel("0 条")
        self.count_label.setObjectName("countLabel")

        self.btn_refresh   = QPushButton("刷新")
        self.btn_add       = QPushButton("添加")
        self.btn_edit      = QPushButton("编辑")
        self.btn_delete    = QPushButton("删除")
        self.btn_clear     = QPushButton("清空全部")
        self.btn_clear.setObjectName("danger")
        self.btn_import    = QPushButton("导入…")
        self.btn_export    = QPushButton("导出…")

        bar.addWidget(self.count_label)
        bar.addStretch(1)
        bar.addWidget(self.btn_refresh)
        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_edit)
        bar.addWidget(self.btn_delete)
        bar.addWidget(self.btn_import)
        bar.addWidget(self.btn_export)
        bar.addWidget(self.btn_clear)

        lay.addLayout(bar)

        # ---------- 表格 ----------
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.doubleClicked.connect(lambda _: self._on_edit())
        lay.addWidget(self.table, 1)

        # ---------- 信号 ----------
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_add.clicked.connect(self._on_add)
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_clear.clicked.connect(self._on_clear_all)
        self.btn_import.clicked.connect(self._on_import)
        self.btn_export.clicked.connect(self._on_export)

    # ==================================================================
    # 外部接口
    # ==================================================================
    def attach_cookie_manager(self, cm):
        """由 main_window 在 profile 就绪后调用。"""
        if self.cookie_manager is not None:
            try:
                self.cookie_manager.cookies_changed.disconnect(self._on_cookies_changed)
            except Exception:
                pass

        self.cookie_manager = cm
        cm.cookies_changed.connect(self._on_cookies_changed)
        # 拉一次当前快照
        self._on_cookies_changed(cm.list_cookies())

    def set_current_profile(self, name: str):
        idx = self.profile_combo.findText(name)
        if idx >= 0:
            self.profile_combo.blockSignals(True)
            self.profile_combo.setCurrentIndex(idx)
            self.profile_combo.blockSignals(False)
        self._update_profile_buttons()

    # ==================================================================
    # Profile 操作
    # ==================================================================
    def _refresh_profiles(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for name in list_profiles():
            self.profile_combo.addItem(name)
        self.profile_combo.blockSignals(False)
        self._update_profile_buttons()

    def _on_profile_changed(self, name: str):
        if not name:
            return
        log_info(f"[cookie-ui] 请求切换 profile 到 {name}")
        self.prefs.last_profile = name
        self.profile_switch_requested.emit(name)
        self._update_profile_buttons()

    def _on_set_default(self):
        name = self.profile_combo.currentText()
        if not name:
            return
        self.prefs.default_profile = name
        QMessageBox.information(self, "已设置",
                                f"已将 '{name}' 设为默认 Profile。")
        log_info(f"[cookie-ui] 默认 profile 已设为 {name}")

    def _on_new_profile(self):
        name, ok = QInputDialog.getText(self, "新建 Profile",
                                        "请输入 Profile 名称（英文/数字）：")
        if not ok or not name.strip():
            return
        name = name.strip()
        if not name.replace("_", "").replace("-", "").isalnum():
            QMessageBox.warning(self, "名称非法",
                                "只能包含字母、数字、下划线、连字符。")
            return
        # 触发创建（list_profiles 会自动补目录）
        from core.browser import profile_dir
        profile_dir(name)
        self._refresh_profiles()
        self.profile_combo.setCurrentText(name)
        log_info(f"[cookie-ui] 已创建 profile：{name}")

    def _on_delete_profile(self):
        name = self.profile_combo.currentText()
        if not name:
            return
        if name == "default":
            QMessageBox.warning(self, "不能删除", "默认 Profile 不允许删除。")
            return
        ret = QMessageBox.question(
            self, "确认删除",
            f"确定要删除 Profile '{name}' 及其全部 Cookie / 缓存吗？")
        if ret != QMessageBox.StandardButton.Yes:
            return

        # 若当前使用就是它，先切回 default
        if self.prefs.last_profile == name:
            self.profile_switch_requested.emit("default")

        if delete_profile(name):
            log_info(f"[cookie-ui] 已删除 profile：{name}")
            self._refresh_profiles()

    def _update_profile_buttons(self):
        cur = self.profile_combo.currentText()
        is_default = (cur == "default")
        self.btn_del_profile.setEnabled(not is_default)
        self.btn_set_default.setEnabled(cur != self.prefs.default_profile)

    # ==================================================================
    # Cookie 表格
    # ==================================================================
    def _on_cookies_changed(self, cookies: List[Dict]):
        self._cookies = cookies or []
        self._render_table()
        self.count_label.setText(f"{len(self._cookies)} 条")

    def _render_table(self):
        self.table.setRowCount(0)
        for c in self._cookies:
            i = self.table.rowCount()
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem(c.get("name", "")))
            self.table.setItem(i, 1, QTableWidgetItem(c.get("value", "")))
            self.table.setItem(i, 2, QTableWidgetItem(c.get("domain", "")))
            self.table.setItem(i, 3, QTableWidgetItem(c.get("path", "")))
            self.table.setItem(i, 4, QTableWidgetItem("是" if c.get("secure") else ""))
            self.table.setItem(i, 5, QTableWidgetItem("是" if c.get("http_only") else ""))
            self.table.setItem(i, 6, QTableWidgetItem("是" if c.get("session") else ""))
        self.table.resizeColumnsToContents()
        for col in range(self.table.columnCount()):
            if self.table.columnWidth(col) > 360:
                self.table.setColumnWidth(col, 360)

    def refresh(self):
        if self.cookie_manager:
            self._on_cookies_changed(self.cookie_manager.list_cookies())

    # ==================================================================
    # 增删改
    # ==================================================================
    def _selected_rows(self) -> List[int]:
        rows = set()
        for item in self.table.selectedItems():
            rows.add(item.row())
        return sorted(rows)

    def _on_add(self):
        if not self.cookie_manager:
            QMessageBox.warning(self, "未就绪", "Cookie 管理器尚未挂载。")
            return
        dlg = CookieEditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.get_data()
            if not d["name"] or not d["domain"]:
                QMessageBox.warning(self, "字段缺失", "Name 和 Domain 必填。")
                return
            ok = self.cookie_manager.add_cookie(
                name=d["name"], value=d["value"], domain=d["domain"],
                path=d["path"], secure=d["secure"], http_only=d["http_only"])
            if ok:
                log_info(f"[cookie-ui] 已添加：{d['name']} @ {d['domain']}")

    def _on_edit(self):
        rows = self._selected_rows()
        if not rows:
            return
        i = rows[0]
        c = self._cookies[i]
        dlg = CookieEditDialog(self, initial=c)
        if dlg.exec() == QDialog.DialogCode.Accepted and self.cookie_manager:
            d = dlg.get_data()
            # 删除旧的，写入新的
            self.cookie_manager.delete_cookie(c["name"], c["domain"], c.get("path", "/"))
            self.cookie_manager.add_cookie(
                name=d["name"], value=d["value"], domain=d["domain"],
                path=d["path"], secure=d["secure"], http_only=d["http_only"])
            log_info(f"[cookie-ui] 已编辑：{c['name']} 改为 {d['name']}")

    def _on_delete(self):
        rows = self._selected_rows()
        if not rows or not self.cookie_manager:
            return
        for i in rows:
            c = self._cookies[i]
            self.cookie_manager.delete_cookie(
                c["name"], c["domain"], c.get("path", "/"))
        log_info(f"[cookie-ui] 已删除 {len(rows)} 条 cookie")

    def _on_clear_all(self):
        if not self.cookie_manager:
            return
        ret = QMessageBox.question(
            self, "确认清空", "确定要删除当前 Profile 的全部 Cookie 吗？")
        if ret == QMessageBox.StandardButton.Yes:
            self.cookie_manager.clear_all()

    # ==================================================================
    # 导入导出
    # ==================================================================
    def _on_import(self):
        if not self.cookie_manager:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Cookie 文件", COOKIE_DIR,
            "JSON 文件 (*.json);;所有文件 (*)")
        if not path:
            return
        try:
            n = self.cookie_manager.import_from_file(path)
            QMessageBox.information(self, "导入完成", f"成功导入 {n} 条 Cookie。")
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    def _on_export(self):
        if not self.cookie_manager:
            return
        if not self._cookies:
            QMessageBox.information(self, "无数据", "当前没有可导出的 Cookie。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 Cookie", os.path.join(COOKIE_DIR, "cookies.json"),
            "JSON 文件 (*.json)")
        if not path:
            return
        try:
            n = self.cookie_manager.export_to_file(path)
            QMessageBox.information(self, "导出成功",
                                    f"已导出 {n} 条到：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    # ==================================================================
    # 右键菜单
    # ==================================================================
    def _on_context_menu(self, pos):
        menu = QMenu(self)
        a1 = QAction("复制 Value", self)
        a2 = QAction("编辑", self)
        a3 = QAction("删除", self)
        a1.triggered.connect(self._copy_selected_value)
        a2.triggered.connect(self._on_edit)
        a3.triggered.connect(self._on_delete)
        menu.addAction(a1)
        menu.addSeparator()
        menu.addAction(a2)
        menu.addAction(a3)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _copy_selected_value(self):
        from PySide6.QtWidgets import QApplication
        rows = self._selected_rows()
        if not rows:
            return
        vals = [self._cookies[i].get("value", "") for i in rows]
        QApplication.clipboard().setText("\n".join(vals))
        log_info(f"[cookie-ui] 已复制 {len(vals)} 条 value")