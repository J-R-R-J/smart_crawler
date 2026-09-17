# -*- coding: utf-8 -*-
"""功能覆盖测试：18 种提取格式 + 弹窗三策略 + 验证码检测 + Cookie 导入导出 + 多 Profile。"""
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


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}", flush=True)


def spin(ms, app):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    from core.browser import Browser, list_profiles
    from core.crawler import Crawler
    from core.extractor import Extractor
    from core.popup_handler import PopupHandler
    from core.detector import Detector
    from core.cookie_manager import CookieManager
    from models.task import Task
    from models.field import Field

    browser = Browser("default", "close")
    extractor = Extractor(browser.js)
    popup = PopupHandler(browser.page, browser.js, "close")

    def load_and_wait(url):
        loop = QEventLoop()
        t = QTimer(); t.setSingleShot(True)
        t.timeout.connect(loop.quit)
        browser.page.loadFinished.connect(lambda ok: loop.quit())
        browser.page.load(url)
        t.start(10000)
        loop.exec()
        t.stop()
        spin(200, app)

    rich = "file:///" + os.path.join(TESTDATA, "rich.html").replace("\\", "/")
    load_and_wait(rich)

    def extract(mode, selector="", fields=None, pattern=""):
        task = Task(url=rich, mode=mode, selector=selector, fields=fields or [],
                    pattern=pattern, flags="g")
        return extractor.extract(browser.page, task)

    # ============ 18 种提取格式 ============
    rows = extract("records", ".item", Field.parse_block("标题|.title|text|\n价格|.price|text|"))
    check("records", len(rows) == 2 and rows[0]["标题"] == "Item One", str(rows))

    rows = extract("list", ".list")
    check("list", len(rows) == 3 and rows[0]["text"] == "alpha", str(rows))

    rows = extract("table")
    check("table", len(rows) == 2 and rows[0].get("Name") == "Apple", str(rows[:1]))

    rows = extract("links")
    check("links", any(r.get("href", "").endswith("/ext") for r in rows), f"n={len(rows)}")

    rows = extract("images")
    check("images", len(rows) >= 2 and all(r.get("src") for r in rows), f"n={len(rows)}")

    rows = extract("text")
    check("text", len(rows) == 1 and "Welcome" in rows[0]["text"])

    rows = extract("html")
    check("html", len(rows) == 1 and "<html" in rows[0]["html"].lower())

    rows = extract("regex", pattern=r"(Item\s+\w+)")
    check("regex", any("Item" in r.get("match", "") for r in rows), str(rows))

    rows = extract("jsonld")
    check("jsonld", any(r.get("@type") == "Product" for r in rows), str(rows))

    rows = extract("meta")
    check("meta", any(r.get("name") == "description" for r in rows), f"n={len(rows)}")

    rows = extract("forms")
    check("forms", len(rows) == 1 and len(rows[0]["fields"]) == 3, str(rows))

    rows = extract("video")
    check("video", len(rows) == 1 and rows[0]["src"].endswith("movie.mp4"), str(rows))

    rows = extract("iframe")
    check("iframe", len(rows) == 1 and rows[0]["src"].endswith("frame.html"), str(rows))

    rows = extract("rss")
    check("rss", len(rows) == 1 and rows[0]["href"].endswith("feed.xml"), str(rows))

    rows = extract("sitemap")
    check("sitemap", len(rows) >= 1, str(rows))

    rows = extract("contacts")
    emails = [r["value"] for r in rows if r.get("type") == "email"]
    check("contacts", "support@example.com" in emails, str(emails))

    rows = extract("embedded_json")
    check("embedded_json", any(r.get("appConfig") for r in rows), str(rows))

    rows = extract("page_cookies")
    check("page_cookies", len(rows) == 1 and "cookies" in rows[0], str(rows))

    # ============ 弹窗三策略 ============
    found, handled = popup.handle()
    check("popup close", found >= 1 and handled >= 1, f"found={found} handled={handled}")

    # 重新加载以恢复 modal，测试 remove 策略
    load_and_wait(rich)
    popup_remove = PopupHandler(browser.page, browser.js, "remove")
    found2, handled2 = popup_remove.handle()
    check("popup remove", found2 >= 1 and handled2 >= 1, f"found={found2} handled={handled2}")

    # notify 策略只报告不处理
    load_and_wait(rich)
    popup_notify = PopupHandler(browser.page, browser.js, "notify")
    found3, handled3 = popup_notify.handle()
    check("popup notify", found3 >= 1 and handled3 == 0, f"found={found3} handled={handled3}")

    # ============ 验证码检测 ============
    captcha_url = "file:///" + os.path.join(TESTDATA, "captcha.html").replace("\\", "/")
    load_and_wait(captcha_url)
    det = Detector()
    html = browser.js.run_sync("document.documentElement.outerHTML", 5000)
    level, _reason = det.classify(html or "", "Verify")
    check("captcha detect", level == "CAPTCHA", level)

    # ============ Cookie 导入导出 ============
    from config.constants import COOKIE_DIR, PROFILE_DIR
    cm = CookieManager(browser.profile, browser)
    export_path = os.path.join(COOKIE_DIR, "_feat_export.json")
    n = cm.export_to_file(export_path)
    check("cookie export", n == len(cm.list_cookies()), f"n={n}")
    import_path = os.path.join(COOKIE_DIR, "_feat_import.json")
    import json as _json
    with open(import_path, "w", encoding="utf-8") as fh:
        _json.dump([{"name": "sess", "value": "xyz", "domain": "example.com", "path": "/"}], fh)
    added = cm.import_from_file(import_path)
    spin(800, app)
    check("cookie import", added == 1 and "sess" in [c["name"] for c in cm.list_cookies()],
          f"added={added}")

    # ============ 多 Profile（cookie 集切换） ============
    from core.browser import profile_dir
    profile_dir("work")   # 创建 work profile 目录
    # 当前 profile=default，写入一条 cookie 后切到 work（应被保存到 default）
    cm.add_cookie(name="def_ck", value="d1", domain="example.com", path="/")
    spin(900, app)
    n_default_before = len(cm.list_cookies())
    check("default has cookie", "def_ck" in [c["name"] for c in cm.list_cookies()],
          str([c["name"] for c in cm.list_cookies()]))

    browser.switch_profile("work", "close")
    cm.switch_profile("work")
    cm.set_profile_name("work")
    spin(500, app)
    check("profile switch label", browser.profile_name == "work", browser.profile_name)
    check("work empty after switch", "def_ck" not in [c["name"] for c in cm.list_cookies()],
          str([c["name"] for c in cm.list_cookies()]))
    # default 的 cookie 已落盘
    default_json = os.path.join(PROFILE_DIR, "default", "cookies.json")
    check("default cookies persisted", os.path.isfile(default_json), default_json)

    # 切回 default，cookie 应恢复
    browser.switch_profile("default", "close")
    cm.switch_profile("default")
    cm.set_profile_name("default")
    spin(500, app)
    check("default restored", "def_ck" in [c["name"] for c in cm.list_cookies()],
          str([c["name"] for c in cm.list_cookies()]))

    browser.close()
    app.quit()

    print(f"\n===== FEATURE RESULT: {len(PASS)} passed, {len(FAIL)} failed =====", flush=True)
    if FAIL:
        print("FAILED:", FAIL, flush=True)
        sys.exit(1)
    print("ALL OK", flush=True)


if __name__ == "__main__":
    main()
