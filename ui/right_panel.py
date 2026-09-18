# -*- coding: utf-8 -*-
"""右侧结果面板：数据 / JSON / Cookie / 日志 / 任务 五个 Tab。"""

import json
import os
import time
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QPlainTextEdit,
    QPushButton, QLabel, QFileDialog, QMessageBox,
)

from config.constants import EXPORT_DIR, LOG_DIR
from utils.exporters import export_csv, export_json

from .cookie_panel import CookiePanel


class RightPanel(QWidget):
    def __init__(self, prefs, parent=None):
        super().__init__(parent)
        self.prefs = prefs
        self.rows: List[Dict[str, Any]] = []
        self.columns: List[str] = []
        self._build()

    # ==================================================================
    # UI
    # ==================================================================
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 0, 0, 0)

        self.tabs = QTabWidget()

        # --- 1. 数据 ---
        self.table = QTableWidget(0, 0)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.tabs.addTab(self.table, "数据")

        # --- 2. JSON ---
        self.json_view = QPlainTextEdit()
        self.json_view.setReadOnly(True)
        self.json_view.setFont(QFont("Consolas", 9))
        self.tabs.addTab(self.json_view, "JSON")

        # --- 3. Cookie ---
        self.cookie_panel = CookiePanel(self.prefs)
        self.tabs.addTab(self.cookie_panel, "Cookie")

        # --- 4. 日志 ---
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 9))
        self.tabs.addTab(self.log_view, "日志")

        # --- 5. 任务 ---
        self.task_view = QPlainTextEdit()
        self.task_view.setReadOnly(True)
        self.task_view.setFont(QFont("Consolas", 9))
        self.tabs.addTab(self.task_view, "任务")

        lay.addWidget(self.tabs, 1)

        # ---------- 底部工具条 ----------
        self.export_dir_label = QLabel("")
        self.export_dir_label.setObjectName("hintLabel")
        lay.addWidget(self.export_dir_label)

        bottom = QHBoxLayout()

        self.count_label = QLabel("0 条")
        self.count_label.setObjectName("countLabel")

        self.btn_export_dir   = QPushButton("导出目录…")
        self.btn_clean_temp   = QPushButton("清理临时文件")
        self.btn_open_log_dir = QPushButton("打开日志目录")
        self.btn_clear        = QPushButton("清空结果")
        self.btn_export_csv   = QPushButton("导出 CSV")
        self.btn_export_json  = QPushButton("导出 JSON")

        bottom.addWidget(self.count_label, 1)
        bottom.addWidget(self.btn_export_dir)
        bottom.addWidget(self.btn_clean_temp)
        bottom.addWidget(self.btn_open_log_dir)
        bottom.addWidget(self.btn_clear)
        bottom.addWidget(self.btn_export_csv)
        bottom.addWidget(self.btn_export_json)
        lay.addLayout(bottom)

        # 信号
        self.btn_clear.clicked.connect(self.clear)
        self.btn_export_csv.clicked.connect(lambda: self.export("csv"))
        self.btn_export_json.clicked.connect(lambda: self.export("json"))
        self.btn_open_log_dir.clicked.connect(self._open_log_dir)
        self.btn_export_dir.clicked.connect(self._choose_export_dir)
        self.btn_clean_temp.clicked.connect(self._clean_temp)

        self._refresh_export_dir_label()

    # ==================================================================
    # 导出目录
    # ==================================================================
    def _current_export_dir(self) -> str:
        """优先使用用户自定义目录，否则用默认导出目录。"""
        custom = (self.prefs.export_dir or "").strip()
        if custom and os.path.isdir(custom):
            return custom
        return EXPORT_DIR

    def _refresh_export_dir_label(self):
        self.export_dir_label.setText(f"导出目录：{self._current_export_dir()}")
        self.btn_export_dir.setToolTip("设置结果导出的默认目录")

    def _choose_export_dir(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "选择结果导出目录", self._current_export_dir())
        if not chosen:
            # 允许用户清除自定义目录，回退到默认目录
            if (self.prefs.export_dir or "").strip():
                self.prefs.export_dir = ""
                self._refresh_export_dir_label()
                self.log("INFO", "已恢复默认导出目录")
            return
        self.prefs.export_dir = chosen
        self._refresh_export_dir_label()
        self.log("INFO", f"导出目录已设为：{chosen}")

    # ==================================================================
    # 清理临时文件
    # ==================================================================
    def _clean_temp(self):
        from utils import maintenance
        usage = maintenance.temp_usage()
        detail = "\n".join(
            f"  {k}：{maintenance.human_size(v)}" for k, v in usage.items())
        ret = QMessageBox.question(
            self, "清理临时文件",
            "将清理以下内容（不会删除 Profile 与 Cookie）：\n\n"
            f"{detail}\n\n"
            "• 浏览器引擎缓存\n• 项目内 __pycache__\n• 根目录临时日志/残留\n\n"
            "是否继续？")
        if ret != QMessageBox.StandardButton.Yes:
            return
        try:
            result = maintenance.clean_temp()
        except Exception as e:
            QMessageBox.critical(self, "清理失败", str(e))
            return
        msg = (f"已释放 {result['freed_text']}\n"
               f"删除 {len(result['removed'])} 项")
        if result["skipped"]:
            msg += f"\n\n{len(result['skipped'])} 项被占用未能删除（可稍后重试）"
        self.log("INFO", f"[clean] {msg}")
        QMessageBox.information(self, "清理完成", msg)

    # ==================================================================
    # 数据
    # ==================================================================
    def append_rows(self, rows: List[Dict[str, Any]]):
        if not rows:
            return

        new_cols = []
        for r in rows:
            for k in r.keys():
                if k not in self.columns and k not in new_cols:
                    new_cols.append(k)
        if new_cols:
            self.columns.extend(new_cols)
            self.table.setColumnCount(len(self.columns))
            self.table.setHorizontalHeaderLabels(self.columns)

        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            for c, col in enumerate(self.columns):
                v = r.get(col, "")
                if not isinstance(v, str):
                    try:
                        v = json.dumps(v, ensure_ascii=False)
                    except Exception:
                        v = str(v)
                self.table.setItem(i, c, QTableWidgetItem(v))

        self.rows.extend(rows)
        self.count_label.setText(f"{len(self.rows)} 条")

        # JSON 预览
        preview = self.rows[-200:]
        try:
            self.json_view.setPlainText(
                json.dumps(preview, ensure_ascii=False, indent=2))
        except Exception as e:
            self.json_view.setPlainText(f"(JSON 序列化失败：{e})")

        # 首次自动调整列宽
        if self.table.rowCount() == len(rows):
            self.table.resizeColumnsToContents()
            for c in range(self.table.columnCount()):
                if self.table.columnWidth(c) > 320:
                    self.table.setColumnWidth(c, 320)

    def clear(self):
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.columns = []
        self.rows = []
        self.json_view.clear()
        self.count_label.setText("0 条")

    # ==================================================================
    # 日志
    # ==================================================================
    def log(self, level: str, msg: str):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        self.log_view.appendPlainText(line)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_task_summary(self, text: str):
        self.task_view.setPlainText(text)

    # ==================================================================
    # 导出
    # ==================================================================
    def export(self, fmt: str):
        if not self.rows:
            QMessageBox.information(self, "提示", "当前没有可导出的数据。")
            return

        default = os.path.join(
            self._current_export_dir(),
            f"result_{time.strftime('%Y%m%d_%H%M%S')}.{fmt}")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出结果", default,
            "CSV 文件 (*.csv)" if fmt == "csv" else "JSON 文件 (*.json)")
        if not path:
            return
        try:
            if fmt == "csv":
                export_csv(self.rows, self.columns, path)
            else:
                export_json(self.rows, path)
            # 记住用户实际保存到的目录，下次默认用它
            saved_dir = os.path.dirname(os.path.abspath(path))
            if saved_dir and saved_dir != self.prefs.export_dir:
                self.prefs.export_dir = saved_dir
                self._refresh_export_dir_label()
            QMessageBox.information(self, "导出成功", f"已保存到：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    # ==================================================================
    # 打开日志目录
    # ==================================================================
    def _open_log_dir(self):
        try:
            if os.name == "nt":
                os.startfile(LOG_DIR)   # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.Popen(["xdg-open", LOG_DIR])
        except Exception as e:
            QMessageBox.warning(self, "无法打开", str(e))