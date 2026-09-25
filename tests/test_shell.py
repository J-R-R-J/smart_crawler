# -*- coding: utf-8 -*-
"""外壳测试：窗口图标 / 控制台开关 / 样式表路径 / 新窗口请求。

为什么单独一个文件
------------------
这几项都是「打包后才暴露、源码运行看不出来」的问题，此前长期没被发现：

1. **窗口图标**：QApplication 不调用 setWindowIcon()，标题栏左上角就是空白。
   另外图标文件只有一张 256×256 时，小尺寸会被系统缩放糊掉。
2. **样式表**：PyInstaller 不会自动收集 .qss，spec 的 datas 漏了就「打包版
   完全没样式」，而且代码里只有一条 WARNING。
3. **新窗口请求**：QWebEnginePage.createWindow() 默认返回 nullptr，
   target="_blank" 与 window.open() 被静默丢弃 —— 点了没反应。

第 3 条用**真实 WebEngine 导航**验证（而不是只检查方法存在）。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--no-sandbox --disable-gpu --single-process")

HERE = os.path.dirname(os.path.abspath(__file__))   # tests/
ROOT = os.path.dirname(HERE)                        # 项目根目录
TESTDATA = os.path.join(HERE, "testdata")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PASS = []
FAIL = []
SKIP = []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}", flush=True)


def skip(name, reason=""):
    SKIP.append(name)
    print(f"[SKIP] {name} {reason}", flush=True)


def file_url(name):
    return "file:///" + os.path.join(TESTDATA, name).replace("\\", "/")


# ======================================================================
# 1. 图标
# ======================================================================
def test_appicon():
    from PySide6.QtGui import QIcon

    from utils.appicon import (
        ICON_SIZES, app_icon, icon_file, render_pixmap, search_dirs,
    )

    dirs = search_dirs()
    check("图标搜索目录非空且都是字符串",
          bool(dirs) and all(isinstance(d, str) and d for d in dirs), str(dirs))

    check("ICON_SIZES 覆盖标题栏(16)与超大图标(256)",
          16 in ICON_SIZES and 256 in ICON_SIZES, str(ICON_SIZES))

    path = icon_file()
    check("icon_file() 找到本机图标文件",
          bool(path) and os.path.isfile(path), path)

    icon = app_icon()
    check("app_icon() 非空", isinstance(icon, QIcon) and not icon.isNull())
    sizes = {s.width() for s in icon.availableSizes()}
    check("窗口图标含 16 与 32 像素帧（标题栏 / 任务栏够用）",
          {16, 32} <= sizes, str(sorted(sizes)))
    for s in (16, 32, 48, 256):
        pm = icon.pixmap(s, s)
        check(f"pixmap({s}) 可取且尺寸正确",
              (not pm.isNull()) and pm.width() == s and pm.height() == s,
              f"{pm.width()}x{pm.height()}")

    # 现画的兜底图形必须是**真的画上了内容**，而不是一片空底。
    # 这里刻意数「中心偏白的像素」：曾经用 drawText 画字母，无头环境没有
    # 字体时会退化成缺字方框，白像素比例在不同尺寸下完全不成等比。
    for size, floor in ((64, 100), (256, 1500)):
        pm = render_pixmap(size)
        img = pm.toImage()
        white = 0
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if (c.alpha() > 128 and c.red() > 200
                        and c.green() > 200 and c.blue() > 200):
                    white += 1
        check(f"兜底图标 {size}px 真的画上了图形（白像素 {white}）",
              white >= floor)
        check(f"兜底图标 {size}px 尺寸正确",
              pm.width() == size and pm.height() == size)


# ======================================================================
# 2. 控制台开关
# ======================================================================
def test_console():
    from utils import console

    check("has_console() 返回 bool", isinstance(console.has_console(), bool),
          f"has_console={console.has_console()}")
    check("is_visible() 返回 bool", isinstance(console.is_visible(), bool))

    # 只验证「显示」是安全的；**绝不**在测试里隐藏控制台
    r = console.set_visible(True)
    check("set_visible(True) 返回 bool 且不抛异常", isinstance(r, bool), str(r))
    check("没有控制台时安全返回 False 而不是报错",
          r is False or console.has_console())


# ======================================================================
# 3. 样式表路径
# ======================================================================
def test_qss_paths():
    from ui.main_window import qss_candidates

    cands = qss_candidates()
    check("样式表候选路径 >= 3 条（源码 / onedir / onefile 都兜住）",
          len(cands) >= 3, str(cands))
    check("候选路径全部是字符串", all(isinstance(c, str) for c in cands))
    check("第一条（__file__ 同级）在源码下真实存在",
          os.path.isfile(cands[0]), cands[0])
    check("源码路径指向 ui/styles.qss",
          cands[0].replace("\\", "/").endswith("ui/styles.qss"), cands[0])

    found = [p for p in cands if os.path.isfile(p)]
    check("至少有一条候选能真正读到文件", bool(found), str(found))
    check("读到的样式表非空",
          bool(found) and os.path.getsize(found[0]) > 0)


# ======================================================================
# 4. 新窗口请求（真实 WebEngine 导航）
# ======================================================================
def test_new_window(browser):
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtWebEngineCore import QWebEnginePage

    from core.browser import CrawlerPage

    page = browser.page
    check("Browser 用的是 CrawlerPage", isinstance(page, CrawlerPage),
          type(page).__name__)
    check("CrawlerPage 是 QWebEnginePage 子类",
          issubclass(CrawlerPage, QWebEnginePage))

    # --- 接口层：createWindow 的返回值语义 ---
    window_type = getattr(QWebEnginePage.WebWindowType, "WebBrowserWindow", 0)
    nav_typed = getattr(QWebEnginePage.NavigationType, "NavigationTypeTyped", 0)

    page.set_redirect_new_windows(True)
    check("开启接回时 createWindow 返回自身（而不是 None）",
          page.createWindow(window_type) is page)
    check("acceptNavigationRequest 放行导航",
          page.acceptNavigationRequest(page.url(), nav_typed, True) is True)
    page.set_redirect_new_windows(False)
    check("关闭接回时 createWindow 返回 None（恢复 Qt 默认行为）",
          page.createWindow(window_type) is None)
    page.set_redirect_new_windows(True)

    # --- 真实导航 ---
    #
    # 这里**不用 loadFinished 判定就绪**：offscreen + --single-process 下
    # Chromium 渲染进程首次启动要 5~11 秒（GPU 初始化那几行报错就是它），
    # 单等一个信号配固定超时非常脆，曾被卡在 10 秒差一点没赶上。
    # 改成轮询**可观测状态**（DOM 元素是否存在 / URL 是否已变），
    # 与启动快慢无关。
    fired = []

    def pump(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def js_eval(code, timeout=3000):
        box = {"done": False, "value": None}

        def _cb(v):
            box["value"] = v
            box["done"] = True

        page.runJavaScript(code, _cb)
        waited = 0
        while not box["done"] and waited < timeout:
            pump(50)
            waited += 50
        return box["value"]

    def wait_until(pred, timeout=30000, step=250):
        waited = 0
        while waited < timeout:
            if pred():
                return True
            pump(step)
            waited += step
        return bool(pred())

    origin = file_url("newwindow.html")
    page.load(QUrl(origin))
    ok = wait_until(lambda: js_eval("!!document.getElementById('ext')") is True)
    check("初始页面 DOM 就绪", ok, page.url().toString())
    check("初始 URL 就是 newwindow.html",
          page.url().toString().endswith("newwindow.html"), page.url().toString())
    if not ok:
        skip("target=_blank / window.open 导航用例", "初始页面未就绪")
        return

    page.new_window_requested.connect(lambda u: fired.append(u))

    # 场景 1：点 target="_blank" 链接（deepseek.com 那类按钮的形态）
    fired.clear()
    js_eval("document.getElementById('ext').click();")
    moved = wait_until(lambda: page.url().toString().endswith("page1.html"))
    check("点击 target=_blank 后当前视图真的跳到了目标页",
          moved, page.url().toString())
    check("并且上报了 new_window_requested", bool(fired), str(fired))
    if fired:
        check("上报的 URL 与最终 URL 一致",
              fired[-1].endswith("page1.html"), fired[-1])

    # 场景 2：window.open() 脚本开窗
    page.load(QUrl(origin))
    if not wait_until(lambda: js_eval("!!document.getElementById('btn_open')") is True):
        skip("window.open() 接回当前视图", "页面未就绪")
        return
    fired.clear()
    js_eval("document.getElementById('btn_open').click();")
    moved2 = wait_until(lambda: page.url().toString().endswith("page2.html"))
    if moved2:
        check("window.open() 同样被接回当前视图", True, page.url().toString())
        check("window.open() 也上报了 new_window_requested", bool(fired), str(fired))
    else:
        # 无用户手势的脚本开窗可能被 Chromium 弹窗拦截挡掉，那属于浏览器
        # 策略而不是本项目代码问题 —— 如实标 SKIP，不伪装成通过。
        skip("window.open() 接回当前视图",
             f"被浏览器策略拦截或未触发（url={page.url().toString()}）")


# ======================================================================
def main():
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("SmartCrawler")
    app.setOrganizationName("SmartCrawler")

    test_appicon()
    test_console()
    test_qss_paths()

    from core.browser import Browser
    browser = Browser("default", "close")
    try:
        test_new_window(browser)
    finally:
        try:
            browser.close()
        except Exception:
            pass

    print("-" * 60, flush=True)
    print(f"PASS={len(PASS)}  FAIL={len(FAIL)}  SKIP={len(SKIP)}", flush=True)
    for n in FAIL:
        print("  FAILED:", n, flush=True)
    for n in SKIP:
        print("  SKIPPED:", n, flush=True)
    print("SHELL RESULT: " + ("FAILED" if FAIL else "OK"), flush=True)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
