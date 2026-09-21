# -*- coding: utf-8 -*-
"""反爬特征自检：打印关键指纹，确认伪装是否生效、现代 JS API 是否完整。

用法（在项目根目录执行）：
    .venv\\Scripts\\python.exe tools\\probe_stealth.py

说明：在无头 / offscreen 环境下 WebGL 相关项会显示 no-webgl（没有 GPU 上下文），
属于环境限制，不代表伪装失效；真实桌面环境下会返回伪装值。
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--no-sandbox --disable-gpu --single-process "
                      "--disable-blink-features=AutomationControlled")

HERE = os.path.dirname(os.path.abspath(__file__))   # tools/
ROOT = os.path.dirname(HERE)                        # 项目根目录
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def spin(ms):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


# (分组, 名称, JS 表达式, 期望值；None 表示仅展示不判定)
CHECKS = [
    ("自动化标志", "navigator.webdriver",
     "String(navigator.webdriver)", "undefined"),
    ("自动化标志", "webdriver 是否为自有属性",
     "String(Object.prototype.hasOwnProperty.call(navigator, 'webdriver'))",
     "false"),
    ("自动化标志", "'webdriver' in navigator",
     "String('webdriver' in navigator)", None),
    ("自动化标志", "window.chrome 类型",
     "typeof window.chrome", "object"),
    ("自动化标志", "chrome.runtime 类型",
     "typeof (window.chrome && window.chrome.runtime)", "object"),

    ("残留标记", "Selenium/WebDriver 标记数",
     "(function(){var m=['__webdriver_evaluate','__selenium_evaluate',"
     "'__driver_evaluate','__fxdriver_evaluate','_Selenium_IDE_Recorder',"
     "'_selenium','calledSelenium','__nightmare','callPhantom','domAutomation',"
     "'domAutomationController','__playwright','__puppeteer'];"
     "var n=0;for(var i=0;i<m.length;i++){if(m[i] in window){n++;}}"
     "return String(n);})()",
     "0"),
    ("残留标记", "cdc_/wdc_ 属性数",
     "(function(){var n=0;var re=/^\\$?(cdc_|wdc_)/i;"
     "var ks=Object.getOwnPropertyNames(window);"
     "for(var i=0;i<ks.length;i++){if(re.test(ks[i])){n++;}}"
     "ks=Object.getOwnPropertyNames(document);"
     "for(var j=0;j<ks.length;j++){if(re.test(ks[j])){n++;}}"
     "return String(n);})()",
     "0"),

    ("语言区域", "navigator.language", "navigator.language", "zh-CN"),
    ("语言区域", "navigator.languages", "navigator.languages.join(',')",
     "zh-CN,zh,en-US,en"),
    ("语言区域", "时区",
     "Intl.DateTimeFormat().resolvedOptions().timeZone", None),

    ("硬件平台", "navigator.platform", "navigator.platform", "Win32"),
    ("硬件平台", "hardwareConcurrency",
     "String(navigator.hardwareConcurrency)", "8"),
    ("硬件平台", "deviceMemory", "String(navigator.deviceMemory)", "8"),
    ("硬件平台", "maxTouchPoints", "String(navigator.maxTouchPoints)", "0"),
    ("硬件平台", "vendor", "navigator.vendor", "Google Inc."),
    ("硬件平台", "plugins 数量",
     "String(navigator.plugins ? navigator.plugins.length : -1)", None),
    ("硬件平台", "mimeTypes 数量",
     "String(navigator.mimeTypes ? navigator.mimeTypes.length : -1)", None),

    ("渲染特征", "WebGL 厂商",
     "(function(){try{var c=document.createElement('canvas');"
     "var g=c.getContext('webgl')||c.getContext('experimental-webgl');"
     "return g?String(g.getParameter(37445)):'no-webgl';}"
     "catch(e){return 'error';}})()", None),
    ("渲染特征", "WebGL 渲染器",
     "(function(){try{var c=document.createElement('canvas');"
     "var g=c.getContext('webgl')||c.getContext('experimental-webgl');"
     "return g?String(g.getParameter(37446)):'no-webgl';}"
     "catch(e){return 'error';}})()", None),
    ("渲染特征", "UA 含 Headless",
     "String(/Headless/i.test(navigator.userAgent))", "false"),
    ("渲染特征", "UA", "navigator.userAgent", None),

    ("无头特征", "outerWidth", "String(window.outerWidth)", None),
    ("无头特征", "outerHeight", "String(window.outerHeight)", None),
    ("无头特征", "innerWidth", "String(window.innerWidth)", None),
    ("无头特征", "document.hasFocus()", "String(document.hasFocus())", None),
    ("无头特征", "connection.effectiveType",
     "String(navigator.connection ? navigator.connection.effectiveType : 'missing')",
     None),
]

API_PROBES = [
    "fetch", "Promise", "Intl", "Intl.DateTimeFormat", "Intl.NumberFormat",
    "Proxy", "Reflect", "Symbol", "TextEncoder", "TextDecoder",
    "URLSearchParams", "AbortController", "ResizeObserver",
    "IntersectionObserver", "MutationObserver", "queueMicrotask",
    "structuredClone", "requestAnimationFrame",
]


def main():
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    from core.browser import Browser

    browser = Browser("default", "close", stealth_enabled=True,
                      max_download_mb=50, allowed_download_exts="pdf,csv,xlsx")
    page = browser.page

    url = "file:///" + os.path.join(ROOT, "tests", "testdata",
                                    "page1.html").replace("\\", "/")
    loop = QEventLoop()
    t = QTimer(); t.setSingleShot(True); t.timeout.connect(loop.quit)
    page.loadFinished.connect(lambda ok: loop.quit())
    page.load(QUrl(url))
    t.start(10000)
    loop.exec(); t.stop(); spin(400)

    bad = []
    group = None
    for grp, name, js, expect in CHECKS:
        if grp != group:
            print(f"\n=== {grp} ===", flush=True)
            group = grp
        try:
            val = browser.js.run_sync(js, 5000)
        except Exception as e:
            val = f"<异常: {e}>"
        if expect is None:
            mark, verdict = " -", ""
        elif str(val) == expect:
            mark, verdict = "OK", ""
        else:
            mark, verdict = "!!", f"   <- 期望 {expect}"
            bad.append((name, val, expect))
        print(f"  [{mark}] {name:26s} = {val!r}{verdict}", flush=True)

    print("\n=== 现代 JS API 完整性 ===", flush=True)
    for api in API_PROBES:
        js = (f"(function(){{try{{var o=window;var p='{api}'.split('.');"
              f"for(var i=0;i<p.length;i++){{o=o[p[i]];if(o==null)return 'MISSING';}}"
              f"return typeof o;}}catch(e){{return 'MISSING';}}}})()")
        try:
            val = browser.js.run_sync(js, 5000)
        except Exception as e:
            val = f"<异常: {e}>"
        mark = "OK" if str(val) not in ("MISSING", "undefined") else "!!"
        if mark == "!!":
            bad.append((api, val, "非 undefined"))
        print(f"  [{mark}] {api:26s} = {val!r}", flush=True)

    print("\n=== 下载配置 ===", flush=True)
    print(f"  大小上限   = {browser.max_download_mb} MB", flush=True)
    print(f"  格式白名单 = {sorted(browser.allowed_download_exts) or '（不限）'}",
          flush=True)
    print(f"  允许 pdf -> {browser._ext_allowed('a.pdf')}", flush=True)
    print(f"  允许 exe -> {browser._ext_allowed('a.exe')}", flush=True)

    print("\n" + "=" * 58, flush=True)
    if bad:
        print(f"存在 {len(bad)} 项异常：", flush=True)
        for name, val, expect in bad:
            print(f"  - {name}: {val!r}（期望 {expect}）", flush=True)
    else:
        print("全部检查项通过。", flush=True)
    print("=" * 58, flush=True)

    browser.close()
    spin(200)
    app.quit()


if __name__ == "__main__":
    main()
