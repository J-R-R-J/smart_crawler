# -*- coding: utf-8 -*-
"""utils.console —— Windows 控制台窗口的显示 / 隐藏。

为什么正式版要保留控制台
------------------------
发布版 exe 采用 **console 子系统**（而不是 GUI 子系统）：

- 启动期崩溃、Qt/Chromium 的 WARNING、解释器自己的 traceback 都还能打印出来。
  无控制台的版本在打包出错时是「双击没反应，什么都没有」，排查成本极高；
- `--selftest` / `--version` 这些命令行开关的输出必须能被看到。

但默认一直挂着一个黑色窗口对普通用户不友好，所以提供**运行期**开关：

- 默认值见 ``config.default_settings.DEFAULT_SHOW_CONSOLE``；
- 用户可在界面「④ 执行」里随时切换，偏好写入 crawler_data/settings.ini；
- 隐藏只是 ``ShowWindow(SW_HIDE)``：进程、stdin/stdout 都还在，
  日志照常写入 crawler_data/logs/，随时可以再显示回来，**不会丢日志**。

非 Windows、或进程本来就没有控制台（pythonw、GUI 子系统）时，
本模块所有函数安全降级为 no-op。
"""

import sys

_IS_WINDOWS = sys.platform.startswith("win")

# Win32 ShowWindow 命令
SW_HIDE = 0
SW_SHOW = 5


def _hwnd() -> int:
    """当前进程控制台窗口句柄；没有控制台时返回 0。"""
    if not _IS_WINDOWS:
        return 0
    try:
        import ctypes
        return int(ctypes.windll.kernel32.GetConsoleWindow() or 0)
    except Exception:
        return 0


def has_console() -> bool:
    """当前进程是否挂着一个控制台窗口。

    界面据此决定「显示控制台」勾选框是否可用：若为 False（例如用
    pythonw.exe 启动源码），勾了也没有意义，应置灰并给出说明。
    """
    return _hwnd() != 0


def set_visible(visible: bool) -> bool:
    """显示 / 隐藏控制台窗口；返回是否真的执行了操作。

    隐藏不会中断输出：被隐藏的控制台仍然接收 stdout，只是不可见。
    """
    hwnd = _hwnd()
    if not hwnd:
        return False
    try:
        import ctypes
        ctypes.windll.user32.ShowWindow(hwnd, SW_SHOW if visible else SW_HIDE)
        return True
    except Exception:
        return False


def is_visible() -> bool:
    """控制台窗口当前是否可见（无控制台时为 False）。"""
    hwnd = _hwnd()
    if not hwnd:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.user32.IsWindowVisible(hwnd))
    except Exception:
        return False
