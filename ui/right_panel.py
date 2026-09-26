# -*- coding: utf-8 -*-
"""右侧结果面板：数据 / JSON / Cookie / 日志 / 任务 五个 Tab。

数据区（第一个 Tab）支持：

- **右键菜单**：复制单元格 / 整行 / 整列 / JSON；导出**此一条**数据（11 种格式）；
  导出**此条的文件**（图片 / 视频 / 音频，本地已有直接复制、缺失的现下）；
  打开文件、在资源管理器定位、在浏览器打开原始链接、删除此条。
- **底部导出**：`导出为…`（11 种格式，全部结果）、`导出文件…`（把结果里引用的
  媒体全部导出成真实文件），外加原有的 CSV / JSON 快捷按钮。
"""

import json
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QPlainTextEdit,
    QPushButton, QToolButton, QMenu, QLabel, QFileDialog, QMessageBox,
)

from config.constants import EXPORT_DIR, LOG_DIR
from utils import media_files
from utils.exporters import (
    EXPORT_FORMATS, EXPORT_EXTS, export_csv, export_json, export_single,
    file_filter, normalize_format,
)

from .cookie_panel import CookiePanel
from .media_export import MediaExportDialog


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
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_menu)
        self.table.doubleClicked.connect(self._on_table_double_clicked)
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

        # 第一行：计数 + 导出入口
        top = QHBoxLayout()
        self.count_label = QLabel("0 条")
        self.count_label.setObjectName("countLabel")

        self.btn_export_menu = QToolButton()
        self.btn_export_menu.setText("导出为…")
        self.btn_export_menu.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_export_menu.setToolTip("把全部结果导出成表格 / 文档 / 数据库等格式")
        self.export_menu = QMenu(self)
        for key, label, ext in EXPORT_FORMATS:
            act = self.export_menu.addAction(f"{label}  (*.{ext})")
            act.setData(key)
            act.triggered.connect(lambda _checked=False, k=key: self.export(k))
        self.btn_export_menu.setMenu(self.export_menu)

        self.btn_export_files = QPushButton("导出文件…")
        self.btn_export_files.setToolTip(
            "把结果里引用的图片 / 视频 / 音频导出成真实文件\n"
            "（本地已下载的直接复制，缺失的现下）")

        top.addWidget(self.count_label, 1)
        top.addWidget(self.btn_export_menu)
        top.addWidget(self.btn_export_files)
        lay.addLayout(top)

        # 第二行：原有按钮
        bottom = QHBoxLayout()
        self.btn_export_csv   = QPushButton("导出 CSV")
        self.btn_export_json  = QPushButton("导出 JSON")
        self.btn_export_dir   = QPushButton("导出目录…")
        self.btn_clean_temp   = QPushButton("清理临时文件")
        self.btn_open_log_dir = QPushButton("打开日志目录")
        self.btn_clear        = QPushButton("清空结果")

        bottom.addWidget(self.btn_export_csv)
        bottom.addWidget(self.btn_export_json)
        bottom.addWidget(self.btn_export_dir)
        bottom.addWidget(self.btn_clean_temp)
        bottom.addWidget(self.btn_open_log_dir)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_clear)
        lay.addLayout(bottom)

        # 信号
        self.btn_clear.clicked.connect(self.clear)
        self.btn_export_csv.clicked.connect(lambda: self.export("csv"))
        self.btn_export_json.clicked.connect(lambda: self.export("json"))
        self.btn_export_files.clicked.connect(lambda: self.export_files_all())
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

    def _remember_dir(self, path: str):
        """记住用户实际保存到的目录，下次默认用它。"""
        saved_dir = os.path.dirname(os.path.abspath(path)) if path else ""
        if saved_dir and saved_dir != self.prefs.export_dir:
            self.prefs.export_dir = saved_dir
            self._refresh_export_dir_label()

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
                item = QTableWidgetItem(v)
                # 有可导出文件的行给个提示（右键能导出）
                if media_files.has_files(r):
                    item.setToolTip("此条包含可导出的文件：右键 → 导出此条的文件")
                self.table.setItem(i, c, item)

        self.rows.extend(rows)
        self.count_label.setText(f"{len(self.rows)} 条")

        self._refresh_json_preview()

        # 首次自动调整列宽
        if self.table.rowCount() == len(rows):
            self.table.resizeColumnsToContents()
            for c in range(self.table.columnCount()):
                if self.table.columnWidth(c) > 320:
                    self.table.setColumnWidth(c, 320)

    def _refresh_json_preview(self):
        preview = self.rows[-200:]
        try:
            self.json_view.setPlainText(
                json.dumps(preview, ensure_ascii=False, indent=2))
        except Exception as e:
            self.json_view.setPlainText(f"(JSON 序列化失败：{e})")

    def clear(self):
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.columns = []
        self.rows = []
        self.json_view.clear()
        self.count_label.setText("0 条")

    # ----------------------------------------------------------------
    def _row(self, index: int) -> Optional[dict]:
        if 0 <= index < len(self.rows):
            return self.rows[index]
        return None

    def _selected_rows(self) -> List[int]:
        sm = self.table.selectionModel()
        if sm is None:
            return []
        idx = sorted({i.row() for i in sm.selectedIndexes()})
        return [i for i in idx if 0 <= i < len(self.rows)]

    def _row_head(self, index: int) -> str:
        """行标题（前两个非空字段），用于提示文字。"""
        row = self._row(index) or {}
        parts = [f"{k}={str(v)[:40]}" for k, v in row.items()
                 if not str(k).startswith("_") and v not in ("", None)]
        return "，".join(parts[:2]) or f"第 {index + 1} 条"

    # ==================================================================
    # 数据区右键菜单
    # ==================================================================
    def _make_row_menu(self, row_idx: int, col_idx: int = 0) -> QMenu:
        """构造某一行（或选中多行）的右键菜单（不 exec，便于单独测试）。"""
        menu = QMenu(self)
        selected = self._selected_rows()
        multi = len(selected) > 1 and row_idx in selected
        row = self._row(row_idx)

        if row is None:
            act = menu.addAction("(没有数据)")
            act.setEnabled(False)
            return menu

        targets = selected if multi else [row_idx]

        # ---------- 复制 ----------
        if multi:
            menu.addAction(f"复制选中的 {len(targets)} 行为 JSON",
                           lambda: self._clipboard(
                               json.dumps([self.rows[i] for i in targets],
                                          ensure_ascii=False, indent=2)))
        else:
            menu.addAction("复制单元格",
                           lambda: self._clipboard(self._cell_text(row_idx, col_idx)))
            menu.addAction("复制整行（制表符分隔）",
                           lambda: self._clipboard(self._row_text(row_idx)))
            menu.addAction("复制整列",
                           lambda: self._clipboard(self._column_text(col_idx)))
            menu.addAction("复制为 JSON",
                           lambda: self._clipboard(
                               json.dumps(row, ensure_ascii=False, indent=2)))

        menu.addSeparator()

        # ---------- 导出数据 ----------
        data_menu = menu.addMenu(
            f"导出此 {len(targets)} 条数据…" if multi else "导出此条数据…")
        for key, label, ext in EXPORT_FORMATS:
            data_menu.addAction(
                f"{label}  (*.{ext})",
                lambda k=key, t=tuple(targets): self.export_selected(t, k))

        menu.addAction("快速导出为 JSON（不弹窗）",
                       lambda t=tuple(targets): self.export_quick(t, "json"))

        menu.addSeparator()

        # ---------- 导出文件 ----------
        refs = media_files.row_files(row)
        if multi:
            all_refs = media_files.collect_refs([self.rows[i] for i in targets])
            act = menu.addAction(f"导出选中行的 {len(all_refs)} 个文件…",
                                 lambda r=all_refs, i=tuple(targets):
                                 self._export_refs(r, note=f"选中 {len(i)} 条"))
            act.setEnabled(bool(all_refs))
        else:
            act = menu.addAction(f"导出此条的文件（{len(refs)} 个）…",
                                 lambda: self.export_row_files(row_idx))
            act.setEnabled(bool(refs))
            if len(refs) == 1:
                menu.addAction("该文件另存为…",
                               lambda: self.export_one_file(row_idx))
            if refs:
                open_act = menu.addAction("打开该文件（本地已有）",
                                          lambda: self.open_row_file(row_idx))
                open_act.setEnabled(any(media_files.find_local(r.url) for r in refs))

        links = media_files.row_links(row)
        if links:
            act = menu.addAction("在浏览器中打开链接",
                                 lambda: self._open_url(links[0][1]))
            act.setToolTip(links[0][1])

        menu.addSeparator()
        if multi:
            menu.addAction(f"删除选中的 {len(targets)} 行",
                           lambda t=tuple(targets): self.remove_rows(t))
        else:
            menu.addAction("删除此行", lambda: self.remove_rows((row_idx,)))
        return menu

    def _on_table_menu(self, pos):
        item = self.table.itemAt(pos)
        row_idx = item.row() if item is not None else self.table.currentRow()
        col_idx = item.column() if item is not None else self.table.currentColumn()
        if row_idx < 0:
            return
        menu = self._make_row_menu(row_idx, col_idx)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _on_table_double_clicked(self, index):
        row_idx = index.row()
        refs = media_files.row_files(self._row(row_idx) or {})
        if refs and any(media_files.find_local(r.url) for r in refs):
            self.open_row_file(row_idx)

    # ==================================================================
    # 复制
    # ==================================================================
    def _clipboard(self, text: str):
        try:
            QApplication.clipboard().setText(text or "")
            self.log("INFO", f"已复制到剪贴板（{len(text or '')} 字符）")
        except Exception as e:                       # noqa: BLE001
            self.log("WARN", f"复制失败：{e}")

    def _cell_text(self, row_idx: int, col_idx: int) -> str:
        item = self.table.item(row_idx, col_idx)
        return item.text() if item is not None else ""

    def _row_text(self, row_idx: int) -> str:
        row = self._row(row_idx) or {}
        return "\t".join(str(row.get(c, "")) for c in self.columns)

    def _column_text(self, col_idx: int) -> str:
        if not (0 <= col_idx < len(self.columns)):
            return ""
        return "\n".join(str((r or {}).get(self.columns[col_idx], ""))
                         for r in self.rows)

    # ==================================================================
    # 导出（数据）
    # ==================================================================
    def export(self, fmt: str, rows: Optional[List[dict]] = None):
        """导出全部结果（rows 为空时）。"""
        rows = self.rows if rows is None else rows
        if not rows:
            QMessageBox.information(self, "提示", "当前没有可导出的数据。")
            return
        fmt = normalize_format(fmt)
        ext = EXPORT_EXTS.get(fmt, fmt)
        default = os.path.join(
            self._current_export_dir(),
            f"result_{time.strftime('%Y%m%d_%H%M%S')}.{ext}")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出结果", default, file_filter(fmt))
        if not path:
            return
        try:
            if fmt == "csv":
                export_csv(rows, self.columns, path)
            elif fmt == "json":
                export_json(rows, path)
            else:
                from utils.exporters import export_any
                export_any(rows, self.columns, path, fmt)
            self._remember_dir(path)
            self.log("INFO", f"[export] {len(rows)} 条 → {path}")
            QMessageBox.information(self, "导出成功", f"已保存到：\n{path}")
        except Exception as e:                       # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(e))

    def export_selected(self, indices, fmt: str, path: str = ""):
        """导出选中的若干条（1 条时写成对象 / 单行表，多条写成表）。"""
        rows = [self.rows[i] for i in indices if 0 <= i < len(self.rows)]
        if not rows:
            return
        fmt = normalize_format(fmt)
        ext = EXPORT_EXTS.get(fmt, fmt)
        if not path:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            name = (f"row{indices[0] + 1}_{stamp}" if len(rows) == 1
                    else f"rows_{len(rows)}_{stamp}")
            path, _ = QFileDialog.getSaveFileName(
                self, "导出数据", os.path.join(self._current_export_dir(),
                                               f"{name}.{ext}"),
                file_filter(fmt))
        if not path:
            return
        try:
            if len(rows) == 1:
                export_single(rows[0], path, fmt)
            else:
                from utils.exporters import export_any
                export_any(rows, self.columns, path, fmt)
            self._remember_dir(path)
            self.log("INFO", f"[export] {len(rows)} 条 → {path}")
            QMessageBox.information(self, "导出成功", f"已保存到：\n{path}")
        except Exception as e:                       # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(e))

    def export_quick(self, indices, fmt: str = "json") -> str:
        """不弹窗，直接写到导出目录（右键「快速导出」用）。"""
        rows = [self.rows[i] for i in indices if 0 <= i < len(self.rows)]
        if not rows:
            return ""
        fmt = normalize_format(fmt)
        ext = EXPORT_EXTS.get(fmt, fmt)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        name = (f"row{indices[0] + 1}_{stamp}" if len(rows) == 1
                else f"rows_{len(rows)}_{stamp}")
        path = os.path.join(self._current_export_dir(), f"{name}.{ext}")
        try:
            if len(rows) == 1:
                export_single(rows[0], path, fmt)
            else:
                from utils.exporters import export_any
                export_any(rows, self.columns, path, fmt)
            self.log("INFO", f"[export] {len(rows)} 条 → {path}")
        except Exception as e:                       # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(e))
            return ""
        return path

    def remove_rows(self, indices):
        for i in sorted({int(x) for x in indices}, reverse=True):
            if 0 <= i < len(self.rows):
                self.table.removeRow(i)
                del self.rows[i]
        self.count_label.setText(f"{len(self.rows)} 条")
        self._refresh_json_preview()

    # ==================================================================
    # 导出（文件）
    # ==================================================================
    def export_row_files(self, row_idx: int, dest_dir: str = "", modal: bool = True):
        """导出某一行的文件（复制本地已有的 / 下载缺失的）。"""
        row = self._row(row_idx)
        if row is None:
            return None
        refs = media_files.row_files(row)
        if not refs:
            QMessageBox.information(
                self, "没有文件",
                f"此条数据里没有可导出的文件地址。\n\n{self._row_head(row_idx)}")
            return None
        return self._export_refs(refs, dest_dir, modal=modal,
                                 note=self._row_head(row_idx))

    def export_files_all(self, dest_dir: str = "", kinds=(), modal: bool = True,
                         rows: Optional[List[dict]] = None):
        """导出全部结果里引用的文件。"""
        rows = self.rows if rows is None else rows
        refs = media_files.collect_refs(rows, kinds)
        if not refs:
            QMessageBox.information(
                self, "没有文件",
                "当前结果里没有图片 / 视频 / 音频地址。\n"
                "（用「图片列表 / 视频地址 / 全部媒体」格式抓取后再试）")
            return None
        return self._export_refs(refs, dest_dir, modal=modal,
                                 note=f"全部 {len(rows)} 条结果")

    def _export_refs(self, refs, dest_dir: str = "", modal: bool = True,
                     note: str = "", dest_file: str = "", overwrite: bool = False):
        """弹出（或后台运行）文件导出对话框；返回对话框对象，报告在 .report。"""
        if not refs:
            QMessageBox.information(self, "没有文件", "没有可导出的文件。")
            return None
        if not dest_dir:
            dest_dir = QFileDialog.getExistingDirectory(
                self, "选择文件导出目录", self._current_export_dir())
            if not dest_dir:
                return None
        dlg = MediaExportDialog(refs, dest_dir, prefs=self.prefs, parent=self,
                                dest_file=dest_file, overwrite=overwrite)
        self.log("INFO", f"[export] 文件导出：{note} → {len(refs)} 个文件，"
                         f"目录 {dest_dir}")
        if modal:
            dlg.start()
            dlg.exec()
        else:
            dlg.show()
            dlg.start()
        return dlg

    def export_one_file(self, row_idx: int, ref_index: int = 0,
                        path: str = "", modal: bool = True):
        """把某一条里的一个文件「另存为…」（按用户输入的确切路径落盘）。"""
        row = self._row(row_idx)
        refs = media_files.row_files(row or {})
        if not refs:
            QMessageBox.information(self, "没有文件", "此条数据里没有可导出的文件地址。")
            return None
        ref = refs[min(ref_index, len(refs) - 1)]
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "导出文件",
                os.path.join(self._current_export_dir(),
                             ref.filename or "file.bin"))
        if not path:
            return None
        return self._export_refs([ref], os.path.dirname(os.path.abspath(path)),
                                 modal=modal, dest_file=path, overwrite=True,
                                 note=f"另存为 {os.path.basename(path)}")

    def _open_url(self, url: str):
        try:
            if os.name == "nt":
                os.startfile(url)                    # type: ignore[attr-defined]
            else:
                import webbrowser
                webbrowser.open(url)
        except Exception as e:                       # noqa: BLE001
            QMessageBox.warning(self, "无法打开", str(e))

    def open_row_file(self, row_idx: int, ref_index: int = 0):
        """用系统默认程序打开该行文件（需要已经下载到本地）。"""
        refs = media_files.row_files(self._row(row_idx) or {})
        if not refs:
            return
        ref = refs[min(ref_index, len(refs) - 1)]
        local = media_files.find_local(ref.url)
        if not local:
            QMessageBox.information(
                self, "文件还没下载",
                f"本地没有这个文件：\n{ref.url}\n\n"
                "请先用右键菜单「导出此条的文件…」把它导出到本地。")
            return
        try:
            if os.name == "nt":
                os.startfile(local)                  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", local])
        except Exception as e:                       # noqa: BLE001
            QMessageBox.warning(self, "无法打开", str(e))

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
