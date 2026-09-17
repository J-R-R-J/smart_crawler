# -*- coding: utf-8 -*-
"""core.signals —— 全局信号总线（模块级惰性单例）。

Signal 名称与参数个数必须保持稳定：ui 层通过 get_signals() 获取总线并连接。
"""

from PySide6.QtCore import QObject, Signal


class Signals(QObject):
    log            = Signal(str, str)            # level, msg
    state_changed  = Signal(str)                 # 状态机状态
    page_loaded    = Signal(bool)                # ok
    human_required = Signal(str, str)            # level(CAPTCHA/HUMAN/LOGIN), reason
    human_cleared  = Signal()                    # 人类验证已通过
    data_extracted = Signal(list)                # 新增 rows(list[dict])
    task_started   = Signal()
    task_finished  = Signal(int, float)          # total, elapsed
    picked         = Signal(str, str, str, str)  # selector, text, tag, href
    popup_found    = Signal(list)                # 弹窗描述列表
    popup_closed   = Signal(list)                # 已处理弹窗列表
    profile_changed = Signal(str)                # profile name


_signals: Signals = None


def get_signals() -> Signals:
    """返回全局信号总线单例（首次调用时惰性创建）。"""
    global _signals
    if _signals is None:
        _signals = Signals()
    return _signals
