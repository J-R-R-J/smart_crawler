# -*- coding: utf-8 -*-
"""离屏渲染主窗口截图（供 README 使用），并分析渲染质量。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--no-sandbox --disable-gpu --single-process")

HERE = os.path.dirname(os.path.abspath(__file__))   # tools/
ROOT = os.path.dirname(HERE)                        # 项目根目录
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT_DIR = os.path.join(ROOT, "docs")
os.makedirs(OUT_DIR, exist_ok=True)
OUT = os.path.join(OUT_DIR, "screenshot.png")


def spin(ms):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def analyze(pix, label, x0, y0, x1, y1):
    """统计区域内的颜色种类，判断该区域是否渲染出了内容。"""
    img = pix.toImage()
    colors = set()
    for y in range(y0, y1, 4):
        for x in range(x0, x1, 4):
            colors.add(img.pixel(x, y))
            if len(colors) > 400:
                break
        if len(colors) > 400:
            break
    print(f"  {label}: {len(colors)} distinct colors (region {x1-x0}x{y1-y0})", flush=True)
    return len(colors)


def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase

    app = QApplication(sys.argv)
    app.setApplicationName("SmartCrawler")
    app.setOrganizationName("SmartCrawler")

    # ------------------------------------------------------------------
    # 没有字体就**不要生成**。
    #
    # 离屏环境（尤其是容器 / CI / AI 沙箱）常常没有可用字体，
    # QFontDatabase.families() 会返回空列表。此时 Qt 仍会「画」出界面，
    # 但所有文字都是空白 —— 截出来的图看着有窗口、有控件，就是没有字，
    # 而且**像素统计也未必能发现**（大片网页底色会把指标撑得很好看）。
    # 这种图贴到 README 上等于「没有内容」，还会把别人桌面环境下生成的
    # 好图覆盖掉。所以宁可失败退出，也不写文件。
    # ------------------------------------------------------------------
    if not QFontDatabase.families():
        print("FATAL: 当前环境没有可用字体（QFontDatabase.families() 为空）。",
              flush=True)
        print("       离屏渲染的文字会全部缺失，生成的截图不能用于 README。",
              flush=True)
        print("       请在**有桌面环境的机器**上运行本脚本；"
              "已存在的 docs/screenshot.png 未被改动。", flush=True)
        return 2

    from ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1560, 940)
    win.show()
    spin(3000)

    win.right_panel.append_rows([
        {"标题": "示例条目 A", "链接": "https://example.com/a", "价格": "10"},
        {"标题": "示例条目 B", "链接": "https://example.com/b", "价格": "20"},
        {"标题": "示例条目 C", "链接": "https://example.com/c", "价格": "30"},
    ])
    win.right_panel.log("INFO", "示例日志：任务已完成，共 3 条记录。")
    spin(800)

    pix = win.grab()
    w, h = pix.width(), pix.height()
    print("window:", w, "x", h, flush=True)
    c = analyze(pix, "left panel  ", 10, 120, 330, h - 20)
    m = analyze(pix, "center panel", 340, 120, w - 500, h - 20)
    r = analyze(pix, "right panel ", w - 480, 120, w - 10, h - 20)

    ok = pix.save(OUT, "PNG")
    print("saved:", OUT, "ok=", ok, flush=True)
    print("verdict: center rendered =", m > 5, flush=True)

    win.close()
    spin(300)
    app.quit()


if __name__ == "__main__":
    sys.exit(main())
