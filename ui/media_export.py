# -*- coding: utf-8 -*-
"""导出爬取到的**文件**：工作线程 + 进度对话框。

为什么单独一个线程：一个页面动辄几十个视频 / 几十 MB，放在 UI 线程里下载
界面会整个卡住（用户以为程序死了，然后强杀进程 —— 这正是「下载完成但文件
不完整」的经典来源）。这里用 QThread + 进度条，并且可随时停止。
"""

import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from utils import media_files
from utils.logger import log_info, log_warn

KIND_LABELS = {"image": "图片", "video": "视频", "audio": "音频", "file": "文件"}
STATUS_LABELS = {
    "pending": "等待中", "working": "处理中", "copied": "已复制",
    "downloaded": "已下载", "exists": "已存在", "skipped": "已跳过",
    "failed": "失败", "": "",
}


class MediaExportWorker(QThread):
    """后台批量导出（复制本地已有 / 下载缺失的）。"""

    progress = Signal(int, int, str)       # 已完成数, 总数, 当前文件名
    done = Signal(dict)                    # 汇总报告

    def __init__(self, refs, dest_dir, overwrite=False, timeout=30.0,
                 dest_file="", parent=None):
        super().__init__(parent)
        self._refs = list(refs or [])
        self._dest_dir = dest_dir
        self._overwrite = bool(overwrite)
        self._timeout = float(timeout)
        self._dest_file = dest_file
        self._stop = False

    def stop(self):
        self._stop = True

    @property
    def stopped(self) -> bool:
        return self._stop

    def run(self):                                     # noqa: D102
        try:
            report = media_files.export_refs(
                self._refs, self._dest_dir, overwrite=self._overwrite,
                timeout=self._timeout, dest_file=self._dest_file,
                on_progress=lambda i, n, ref: self.progress.emit(i, n, ref.filename),
                should_stop=lambda: self._stop)
        except Exception as e:                          # noqa: BLE001
            log_warn(f"[export] 文件导出线程异常：{e}")
            report = {"total": len(self._refs), "dest_dir": self._dest_dir,
                      "items": [], "bytes": 0, "copied": 0, "downloaded": 0,
                      "exists": 0, "skipped": [], "failed": [],
                      "ok": 0, "error": str(e)}
        self.done.emit(report)


class MediaExportDialog(QDialog):
    """展示待导出清单、进度与结果；父窗口通过 :attr:`report` 取汇总。"""

    def __init__(self, refs, dest_dir, prefs=None, parent=None,
                 overwrite=False, timeout=30.0, dest_file=""):
        super().__init__(parent)
        self.setWindowTitle("导出文件")
        self.resize(720, 460)
        self.refs = list(refs or [])
        self.dest_dir = dest_dir
        self.dest_file = dest_file
        self.prefs = prefs
        self.report = None
        self.worker = None
        self._build()
        self._fill_table()

    # ------------------------------------------------------------------
    def _build(self):
        lay = QVBoxLayout(self)

        self.info_label = QLabel(
            f"共 {len(self.refs)} 个文件 → "
            f"{self.dest_file or self.dest_dir}\n"
            "本地已下载的直接复制，缺失的用浏览器同款请求头下载。")
        self.info_label.setWordWrap(True)
        lay.addWidget(self.info_label)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["文件名", "类型", "来源列", "状态"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(
                c, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.table, 1)

        self.bar = QProgressBar()
        self.bar.setRange(0, max(1, len(self.refs)))
        self.bar.setValue(0)
        lay.addWidget(self.bar)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFixedHeight(90)
        lay.addWidget(self.detail)

        row = QHBoxLayout()
        self.btn_start = QPushButton("开始导出")
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)
        self.btn_open = QPushButton("打开目录")
        self.btn_close = QPushButton("关闭")
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_stop)
        row.addStretch(1)
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_open.clicked.connect(self._open_dir)
        self.btn_close.clicked.connect(self.reject)

    def _fill_table(self):
        self.table.setRowCount(len(self.refs))
        for i, ref in enumerate(self.refs):
            for c, text in enumerate((ref.filename, KIND_LABELS.get(ref.kind, ref.kind),
                                      ref.field, STATUS_LABELS["pending"])):
                self.table.setItem(i, c, QTableWidgetItem(text))

    def _set_status(self, index: int, status: str):
        item = self.table.item(index, 3)
        if item is not None:
            item.setText(STATUS_LABELS.get(status, status))

    # ------------------------------------------------------------------
    def start(self):
        if not self.refs:
            self.detail.setPlainText("没有可导出的文件。")
            return
        if self.worker is not None and self.worker.isRunning():
            return
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.bar.setValue(0)
        self.worker = MediaExportWorker(
            self.refs, self.dest_dir, timeout=30.0, dest_file=self.dest_file,
            parent=self)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def stop(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.detail.appendPlainText("已请求停止：当前文件结束后中断。")

    def _on_progress(self, done: int, total: int, name: str):
        self.bar.setRange(0, max(1, total))
        self.bar.setValue(done)
        if 0 < done <= self.table.rowCount():
            self._set_status(done - 1, "working")

    def _on_done(self, report: dict):
        self.report = report
        # 用逐项结果回填状态（比进度回调里的猜测准确）
        for i, item in enumerate(report.get("items") or []):
            if i < self.table.rowCount():
                self._set_status(i, item.get("status", ""))
        self.bar.setValue(self.bar.maximum())
        text = media_files.summary_text(report)
        self.detail.setPlainText(text)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        log_info("[export] 文件导出完成：%s"
                 % text.replace("\n", " | ")[:400])
        if self.prefs is not None:
            try:
                self.prefs.export_dir = self.dest_dir
            except Exception:                           # noqa: BLE001
                pass

    def _open_dir(self):
        try:
            if os.name == "nt":
                os.startfile(self.dest_dir)             # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.Popen(["xdg-open", self.dest_dir])
        except Exception as e:                          # noqa: BLE001
            QMessageBox.warning(self, "无法打开", str(e))

    def closeEvent(self, event):                        # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        super().closeEvent(event)


__all__ = ["MediaExportWorker", "MediaExportDialog", "KIND_LABELS", "STATUS_LABELS"]
