# -*- coding: utf-8 -*-
"""
SmartCrawler · 智能可视化爬虫
====================================================================
入口文件。
启动顺序：
  1. 创建 QApplication
  2. 安装全局异常钩子（防止崩溃直接退出）
  3. 实例化 MainWindow（内部创建 core / ui 全部组件）
  4. 显示窗口，进入事件循环

用法：
    python main.py
"""

import os
import sys
import traceback


# ---- 确保当前目录可导入（双击运行 / PyCharm 直接运行都正常） ----
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _install_excepthook():
    """未捕获异常写日志，不让程序静默死掉。"""
    from utils.logger import log_error

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log_error("未捕获异常：\n" + msg)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook


def main():
    # ---- 环境准备 ----
    # 单进程渲染 + 软渲染：在受限/无 GPU 环境（沙箱、CI、容器、远程桌面）下
    # 也能稳定加载页面；普通桌面用户可用环境变量覆盖。
    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--no-sandbox --disable-gpu --single-process "
        "--disable-gpu-driver-bug-workarounds")

    # ---- Qt 相关 ----
    from PySide6.QtCore import Qt, QCoreApplication
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    app.setApplicationName("SmartCrawler")
    app.setOrganizationName("SmartCrawler")
    app.setFont(QFont("Microsoft YaHei UI", 9))

    # ---- 全局异常钩子（日志已就绪后生效） ----
    _install_excepthook()

    # ---- 启动主窗口 ----
    from ui.main_window import MainWindow

    win = MainWindow()
    win.show()

    # ---- 退出时确保按顺序销毁引擎（page 先于 profile） ----
    def _cleanup():
        try:
            win.close()
        except Exception:
            pass

    app.aboutToQuit.connect(_cleanup)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()