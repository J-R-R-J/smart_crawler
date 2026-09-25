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
    python main.py              启动界面
    python main.py --version    只打印版本号后退出（不启动界面）
    python main.py --selftest   导入全部模块并自检后退出（用于验证打包完整性）
"""

import os
import sys
import traceback


# ---- 确保当前目录可导入（双击运行 / PyCharm 直接运行都正常） ----
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _safe_print(msg: str) -> None:
    """控制台输出永不因代码页问题而崩溃。

    Windows 控制台可能既不是 UTF-8 也不是 GBK（英文系统为 cp1252），
    直接 print 中文会抛 UnicodeEncodeError。打印日志永远不能毁掉结论。
    """
    try:
        print(msg)
    except UnicodeEncodeError:
        try:
            enc = sys.stdout.encoding or "ascii"
            sys.stdout.write(msg.encode(enc, "backslashreplace").decode(enc, "replace") + "\n")
        except Exception:
            pass
    except Exception:
        pass


# 打包完整性自检要导入的模块（与代码真实层级一一对应）
_SELFTEST_MODULES = (
    "config.constants", "config.default_settings", "config.js_scripts",
    "config.keyword_store", "config.welcome",
    "models.field", "models.task", "models.record",
    "core.signals", "core.user_prefs", "core.browser", "core.cookie_manager",
    "core.detector", "core.extractor", "core.picker", "core.pager",
    "core.popup_handler", "core.scrapling_engine", "core.crawler",
    "utils.logger", "utils.exporters", "utils.js_runner", "utils.maintenance",
    "utils.console", "utils.appicon",
    "ui.top_bar", "ui.banner", "ui.left_panel", "ui.center_panel",
    "ui.right_panel", "ui.cookie_panel", "ui.keyword_dialog", "ui.main_window",
)


def run_selftest() -> int:
    """导入全部模块，验证打包产物是否完整（不启动界面）。

    结果同时写到控制台与日志文件：发布版是无控制台窗口的 exe，
    双击运行时看不到控制台输出，此时请看 crawler_data\\logs\\ 下的日志。
    """
    from config.constants import APP_VERSION, BASE_DIR, DATA_DIR
    from utils.logger import log_info, log_error

    lines = []

    def emit(msg):
        lines.append(msg)
        _safe_print(msg)

    emit(f"SmartCrawler selftest  version={APP_VERSION}")
    emit(f"frozen={getattr(sys, 'frozen', False)}  base_dir={BASE_DIR}")
    emit(f"data_dir={DATA_DIR}")

    ok, failed = 0, []
    for name in _SELFTEST_MODULES:
        try:
            __import__(name)
            ok += 1
        except Exception as e:
            failed.append((name, repr(e)))

    # 关键二进制是否可用
    try:
        import PySide6
        from PySide6 import QtWebEngineWidgets  # noqa: F401
        from PySide6 import QtWebEngineCore     # noqa: F401
        from PySide6 import QtWebChannel        # noqa: F401
        from PySide6 import QtPrintSupport      # noqa: F401
        emit(f"PySide6 {PySide6.__version__}  "
             f"QtWebEngine/QtWebChannel/QtPrintSupport OK")
    except Exception as e:
        failed.append(("PySide6 imports", repr(e)))

    # 运行时目录
    if not os.path.isdir(DATA_DIR):
        failed.append(("crawler_data", "目录不存在"))

    # 可选依赖：Scrapling 融合层。
    # 打包产物**有意不包含**它，因此这里显示「未安装」属于正常现象，
    # 不是错误：非浏览器引擎会在抓取时自动回退为浏览器引擎。
    try:
        from core import scrapling_engine as _se
        if _se.available():
            emit(f"scrapling: {_se.version()} 已就绪"
                 f"（HTTP 快速模式 / 隐身引擎 / 动态引擎 / 自适应选择器可用）")
        else:
            reason = _se.unavailable_reason() or "未安装"
            emit(f"scrapling: 不可用（{reason}）"
                 f" —— 非浏览器引擎将回退为浏览器引擎，其余功能不受影响")
            emit(f"          可安装到外挂目录：{_se.site_packages_dir()}")
            emit(f"          {_se.site_packages_hint()}")
    except Exception as e:
        emit(f"scrapling: 状态检测跳过（{type(e).__name__}: {e}）")

    # 窗口图标 / 控制台：这两个是「界面外壳」问题，打包后最容易只剩空白，
    # 因此自检里直接报出实际取值，省得靠肉眼判断。
    try:
        from utils.appicon import icon_file
        emit(f"window_icon: {icon_file() or '未找到图标文件，将用内置绘制图标'}")
    except Exception as e:
        emit(f"window_icon: 检测失败（{type(e).__name__}: {e}）")

    try:
        from utils import console
        emit(f"console: {'有控制台窗口（可显示/隐藏）' if console.has_console() else '无控制台窗口'}"
             f"  visible={console.is_visible()}")
    except Exception as e:
        emit(f"console: 检测失败（{type(e).__name__}: {e}）")

    emit(f"modules: {ok} ok, {len(failed)} failed")
    for name, err in failed:
        emit(f"  FAILED {name}: {err}")
    emit("SELFTEST RESULT: " + ("FAILED" if failed else "OK"))

    try:
        for line in lines:
            (log_error if failed else log_info)("[selftest] " + line)
    except Exception:
        pass

    return 1 if failed else 0


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


def _apply_window_icon(app) -> None:
    """设置窗口图标（标题栏左上角 / 任务栏 / Alt+Tab）。

    这件事**必须显式做**：QApplication 不会自动继承 exe 资源里的图标，
    不调用 ``setWindowIcon()`` 窗口左上角就是空白 —— 这正是「打包版没有
    图标」的原因。图标优先取 appicon.ico（打包时随 datas 分发），
    找不到就用 utils.appicon 现画一个，保证任何运行方式下都不空白。
    """
    from utils.logger import log_info, log_warn
    try:
        from utils.appicon import app_icon, icon_file, search_dirs
        app.setWindowIcon(app_icon())
        path = icon_file()
        if path:
            log_info(f"[ui] 窗口图标：{path}")
        else:
            log_info(f"[ui] 窗口图标：内置绘制（未找到图标文件，已搜索 "
                     f"{len(search_dirs())} 个目录）")
    except Exception as e:
        log_warn(f"[ui] 窗口图标设置失败：{e}")


def main():
    # ---- 命令行开关（不启动界面，便于验证安装/打包完整性）----
    argv = [a.lower() for a in sys.argv[1:]]
    if "--version" in argv or "-v" in argv:
        from config.constants import APP_TITLE, APP_VERSION
        _safe_print(f"{APP_TITLE}  v{APP_VERSION}")
        return
    if "--selftest" in argv:
        sys.exit(run_selftest())

    # ---- 环境准备 ----
    # 单进程渲染 + 软渲染：在受限/无 GPU 环境（沙箱、CI、容器、远程桌面）下
    # 也能稳定加载页面；普通桌面用户可用环境变量覆盖。
    #
    # --disable-blink-features=AutomationControlled 让 Chromium 从源头不设置
    # navigator.webdriver，比事后用 JS 覆盖更彻底（不留 own property 痕迹）。
    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--no-sandbox --disable-gpu --single-process "
        "--disable-gpu-driver-bug-workarounds "
        "--disable-blink-features=AutomationControlled")

    # ---- Qt 相关 ----
    from PySide6.QtCore import Qt, QCoreApplication
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    app.setApplicationName("SmartCrawler")
    app.setOrganizationName("SmartCrawler")
    app.setFont(QFont("Microsoft YaHei UI", 9))

    # ---- 窗口图标（标题栏左上角；不设置就是空白） ----
    _apply_window_icon(app)

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