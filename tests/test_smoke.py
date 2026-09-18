# -*- coding: utf-8 -*-
"""SmartCrawler 冒烟测试：模块导入、配置、UI 与 core 组装（无头模式）。

用法（在项目根目录执行）：
    .venv\\Scripts\\python.exe tests\\test_smoke.py
或系统 Python 已装 PySide6：
    python tests/test_smoke.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--no-sandbox --disable-gpu --single-process "
                      "--disable-gpu-compositing")

HERE = os.path.dirname(os.path.abspath(__file__))   # tests/
ROOT = os.path.dirname(HERE)                        # 项目根目录
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PASS = []
FAIL = []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")


def main():
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)

    # ---- 1. config ----
    from config import constants as C
    check("constants dirs exist",
          all(os.path.isdir(d) for d in (C.PROFILE_DIR, C.LOG_DIR, C.EXPORT_DIR, C.COOKIE_DIR)),
          str([C.PROFILE_DIR, C.LOG_DIR, C.EXPORT_DIR, C.COOKIE_DIR]))
    from config.default_settings import (SUPPORTED_FORMATS, POPUP_STRATEGIES,
                                         CAPTCHA_KEYWORDS, LOGIN_KEYWORDS)
    check("18 formats", len(SUPPORTED_FORMATS) == 18, f"got {len(SUPPORTED_FORMATS)}")
    check("3 popup strategies", len(POPUP_STRATEGIES) == 3)
    check("keywords non-empty", bool(CAPTCHA_KEYWORDS) and bool(LOGIN_KEYWORDS))
    from config.js_scripts import (QWEBCHANNEL_JS, PICKER_JS, POPUP_SCAN_JS,
                                   build_extract_js)
    check("QWEBCHANNEL_JS", "QWebChannel" in QWEBCHANNEL_JS)

    # ---- 2. models ----
    from models.field import Field
    fields = Field.parse_block("标题 | h3 > a | text |\n链接 | h3 > a | href |\n坏行\n价格 | .p | text |")
    check("Field.parse_block", len(fields) == 3, str([f.name for f in fields]))
    from models.task import Task
    t = Task(url="https://example.com", mode="records", selector=".item",
             fields=fields, pattern="", next_selector="a.next", max_pages=2)
    check("Task build", t.url and t.max_pages == 2 and len(t.fields) == 3)
    from models.record import RecordSet
    rs = RecordSet()
    n1 = rs.add_rows([{"a": " 1 "}, {"a": "1"}, {}, None, "bad"])
    check("RecordSet clean/dedup", n1 == 1 and rs.count() == 1, f"n1={n1}")

    # ---- 3. utils ----
    import utils.logger as _logmod
    from utils.logger import log_info, log_warn, log_error
    log_info("smoke: logger ok")
    check("logger file", os.path.isfile(_logmod.current_log_file),
          _logmod.current_log_file)
    from utils.exporters import export_csv, export_json
    tmp_csv = os.path.join(C.EXPORT_DIR, "_smoke.csv")
    export_csv([{"a": "1", "b": "2"}], ["a", "b"], tmp_csv)
    check("export_csv", os.path.isfile(tmp_csv))
    from utils.js_runner import JsRunner
    check("JsRunner import", JsRunner is not None)

    # ---- 4. build_extract_js sanity (JS syntax by node not available; structural check) ----
    js = build_extract_js("records", ".item", fields, "", "g")
    check("build_extract_js records", "JSON.stringify" in js and "querySelectorAll" in js,
          f"len={len(js)}")
    for mode in ("list", "table", "links", "images", "text", "html", "regex",
                 "jsonld", "meta", "forms", "video", "iframe", "rss", "sitemap",
                 "contacts", "embedded_json", "page_cookies"):
        j2 = build_extract_js(mode, ".x", fields, r"\d+", "g")
        check(f"build_extract_js {mode}", isinstance(j2, str) and len(j2) > 100, f"len={len(j2)}")

    # ---- 5. core + ui（复用 MainWindow 内的唯一 Browser/引擎） ----
    # 注意：单进程渲染下只能存在一个 QWebEngineProfile，因此全程只创建一个
    # MainWindow（内部只建一个 Browser），避免第二个 profile 触发崩溃。
    from core.signals import get_signals
    sig = get_signals()
    check("signals singleton", get_signals() is sig)

    from core.user_prefs import UserPrefs, SETTINGS_PATH
    p = UserPrefs()
    check("user_prefs api", isinstance(p.last_modes, list)
          and isinstance(p.last_delay, float)
          and p.popup_strategy in ("notify", "close", "remove")
          and isinstance(p.max_download_mb, int)
          and isinstance(p.stealth_enabled, bool)
          and isinstance(p.export_dir, str),
          f"modes={p.last_modes} delay={p.last_delay} "
          f"limit={p.max_download_mb} stealth={p.stealth_enabled}")
    check("user_prefs uses ini file", SETTINGS_PATH.endswith("settings.ini"),
          SETTINGS_PATH)
    p.stealth_enabled = True
    p.max_download_mb = 50
    check("user_prefs write/read",
          p.stealth_enabled is True and p.max_download_mb == 50,
          f"stealth={p.stealth_enabled} limit={p.max_download_mb}")

    from core.browser import list_profiles, profile_dir
    check("list_profiles", "default" in list_profiles(), str(list_profiles()))
    check("profile_dir", os.path.isdir(profile_dir("default")))

    from ui.main_window import MainWindow
    win = MainWindow()
    browser = win.browser
    check("MainWindow built", win.top_bar is not None and win.right_panel is not None)
    check("banner hidden", not win.banner.isVisible())
    check("Browser page", browser.page is not None)
    check("Browser js", browser.js is not None)
    check("Browser url empty", browser.url() in ("", "about:blank"), browser.url())

    cookies = win.cookie_manager.list_cookies()
    check("CookieManager list", isinstance(cookies, list), f"n={len(cookies)}")

    from core.detector import Detector
    det = Detector()
    level, reason = det.classify("<html>please complete the captcha 验证码</html>", "")
    check("Detector captcha", level == "CAPTCHA", f"{level} {reason}")
    level2, _ = det.classify("<html><p>hello</p></html>", "News")
    check("Detector none", level2 == "NONE", level2)

    ex = win.crawler.extractor
    check("Extractor modes", len(ex.supported_modes()) == 18)
    check("picker/pager/popup",
          all(x is not None for x in (win.crawler.picker, win.crawler.pager,
                                      win.crawler.popup_handler)))
    check("Crawler picker", win.crawler.picker is not None)

    # ---- 6. stop 接口 + 关闭 ----
    win.crawler.stop_task()
    win.close()
    win.cookie_manager.list_cookies()  # 触发一次刷新

    print()
    print(f"===== SMOKE RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
