# -*- coding: utf-8 -*-
"""验证反爬特征伪装脚本是否生效。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--no-sandbox --disable-gpu --single-process")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def spin(ms):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    from core.browser import Browser

    browser = Browser("default", "close", stealth_enabled=True, max_download_mb=30)
    page = browser.page
    url = "file:///" + os.path.join(ROOT, "tests", "testdata", "page1.html").replace("\\", "/")

    loop = QEventLoop()
    t = QTimer(); t.setSingleShot(True); t.timeout.connect(loop.quit)
    page.loadFinished.connect(lambda ok: loop.quit())
    page.load(__import__("PySide6.QtCore", fromlist=["QUrl"]).QUrl(url))
    t.start(10000)
    loop.exec(); t.stop(); spin(400)

    probes = {
        "webdriver": "String(navigator.webdriver)",
        "languages": "navigator.languages.join(',')",
        "platform": "navigator.platform",
        "plugins": "navigator.plugins.length",
        "chrome": "typeof window.chrome",
        "hw": "navigator.hardwareConcurrency",
        "webgl_vendor": "(function(){try{var c=document.createElement('canvas');"
                        "var g=c.getContext('webgl');"
                        "return g?g.getParameter(37445):'no-webgl';}catch(e){return 'err';}})()",
    }
    for name, js in probes.items():
        val = browser.js.run_sync(js, 5000)
        print(f"  {name:14s} = {val!r}", flush=True)

    print("max_download_mb =", browser.max_download_mb, flush=True)
    browser.close()
    app.quit()
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
