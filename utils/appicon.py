# -*- coding: utf-8 -*-
"""utils.appicon —— 应用 / 窗口图标。

两条互不相干的路径，别混淆
--------------------------
1. **exe 文件图标**（资源管理器里看到的那个）：由打包时 spec 的
   ``icon=appicon.ico`` 写进 PE 资源，运行期代码管不着；
2. **窗口图标**（标题栏左上角、Alt+Tab、任务栏按钮）：必须由程序主动调用
   ``QApplication.setWindowIcon()``。**不调用就是空白** —— Qt 不会替你猜，
   也不会自动继承 exe 资源里的图标。

本模块负责第 2 条。图标来源优先用现成的 .ico（打包时随 datas 分发，
源码运行时取本机 packaging/ 下的那份），找不到就用 QPainter **现画**一个，
保证源码运行、CI、无图标文件的克隆体上左上角都不会是空白。
"""

import os
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPixmap

# 现画图标补齐的尺寸：
#   16 标题栏 / 小图标视图，24 有些 shell 会要，32 任务栏与 Alt+Tab，
#   48 中等图标，64 大图标，128/256 资源管理器超大图标与 ICO 备用帧。
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

# 与 ui/styles.qss 的主色保持一致（#2f6feb 系）
_BG_TOP = "#3f7ff0"
_BG_BOTTOM = "#1b4fa8"

# 图形是**纯矢量**，刻意不用文字：
# 无头环境（CI、容器、offscreen 平台）里 Qt 可能一个字体都没有，
# drawText 会退化成「缺字方框」——画出来是个空框，而且小尺寸下糊成一团。
# 三条长度不一的白条不会遇到这个问题，16px 下也认得出来。
_BARS = (          # (y 起点, 宽度, 不透明度)，均为尺寸的比例
    (0.280, 0.56, 1.00),
    (0.445, 0.38, 0.80),
    (0.610, 0.48, 0.90),
)
_BAR_X0 = 0.22
_BAR_H = 0.11


def search_dirs() -> list:
    """按优先级返回可能存放图标文件的目录列表。"""
    dirs = []

    # 打包后：datas 落在 _internal\（onedir 时 _MEIPASS 即 _internal）
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        dirs.append(meipass)

    # 源码根目录（utils/ 的上一级）
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dirs.append(root)
    dirs.append(os.path.join(root, "assets"))
    # packaging/ 是本机打包工具链（不入库），开发机上图标就在这里
    dirs.append(os.path.join(root, "packaging"))

    # 冻结后：exe 同级目录（用户手动放一个图标也能生效）
    try:
        from config.constants import BASE_DIR
        if BASE_DIR not in dirs:
            dirs.append(BASE_DIR)
    except Exception:
        pass

    return dirs


def icon_file() -> str:
    """返回第一个存在的图标文件路径；都没有则返回空串。"""
    for d in search_dirs():
        for name in ("appicon.ico", "appicon.png"):
            path = os.path.join(d, name)
            if os.path.isfile(path):
                return path
    return ""


def render_pixmap(size: int) -> QPixmap:
    """画一张 size×size 的图标（圆角渐变底 + 三条数据条）。

    需要已经创建 QGuiApplication（QPixmap 依赖 GUI 环境）；本函数只在
    main() 里 QApplication 之后调用，以及打包脚本 / tests 的 offscreen
    环境中调用。**不依赖任何字体**，因此无头环境下结果一致。
    """
    size = max(8, int(size))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pm)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        # ---- 底：圆角 + 斜向渐变 ----
        grad = QLinearGradient(0, 0, size, size)
        grad.setColorAt(0.0, QColor(_BG_TOP))
        grad.setColorAt(1.0, QColor(_BG_BOTTOM))
        painter.setBrush(grad)
        radius = size * 0.18
        painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

        # ---- 三条数据条 ----
        bar_h = size * _BAR_H
        bar_r = bar_h / 2.0
        x0 = size * _BAR_X0
        for y_ratio, w_ratio, alpha in _BARS:
            color = QColor("#ffffff")
            color.setAlphaF(alpha)
            painter.setBrush(color)
            painter.drawRoundedRect(
                QRectF(x0, size * y_ratio, size * w_ratio, bar_h),
                bar_r, bar_r)
    finally:
        painter.end()

    return pm


def fallback_icon() -> QIcon:
    """现画的多尺寸兜底图标。"""
    icon = QIcon()
    for s in ICON_SIZES:
        icon.addPixmap(render_pixmap(s))
    return icon


def app_icon() -> QIcon:
    """窗口图标：优先用图标文件，退化到现画。永不返回空 QIcon。"""
    path = icon_file()
    if path:
        icon = QIcon(path)
        if not icon.isNull() and not icon.pixmap(16, 16).isNull():
            return icon
    return fallback_icon()
