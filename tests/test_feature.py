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

    # ============ 验证码检测（关键词） ============
    captcha_url = "file:///" + os.path.join(TESTDATA, "captcha.html").replace("\\", "/")
    load_and_wait(captcha_url)
    det = Detector()
    html = browser.js.run_sync("document.documentElement.outerHTML", 5000)
    level, _reason = det.classify(html or "", "Verify")
    check("captcha detect", level == "CAPTCHA", level)

    # ============ 结构化确认：验证码表单 ============
    from config.js_scripts import CAPTCHA_PROBE_JS, LOGIN_PROBE_JS

    def probe(js):
        raw = browser.js.run_sync(js, 6000)
        import json as _j
        return _j.loads(raw) if isinstance(raw, str) and raw.strip() else {}

    # 1) 真正的验证码表单：应被结构确认
    cap_form_url = "file:///" + os.path.join(TESTDATA, "captcha_form.html").replace("\\", "/")
    load_and_wait(cap_form_url)
    info = probe(CAPTCHA_PROBE_JS)
    check("captcha probe finds input form",
          bool(info.get("found")) and "input" in (info.get("kinds") or []),
          str(info))

    html2 = browser.js.run_sync("document.documentElement.outerHTML", 5000) or ""
    text2 = browser.js.run_sync("document.body.innerText", 5000) or ""
    level, reason = det.classify(html2, "Verify", cap_form_url, text2,
                                 captcha_forms=info)
    check("captcha confirmed by form", level == "CAPTCHA" and "已确认" in reason,
          f"{level} {reason}")

    # 2) 结构确认优先于关键词：无关键词但有验证组件也应识别
    level, reason = det.classify("<html><body></body></html>", "", "", "",
                                 captcha_forms={"found": True, "kinds": ["iframe"],
                                                "details": ["iframe: recaptcha"]})
    check("structure alone triggers captcha", level == "CAPTCHA",
          f"{level} {reason}")

    # 3) 仅命中关键词、无组件 → 疑似，并提示可跳过
    load_and_wait(captcha_url)
    info_kw = probe(CAPTCHA_PROBE_JS)
    check("keyword-only page has no captcha structure",
          not info_kw.get("found"), str(info_kw))
    html3 = browser.js.run_sync("document.documentElement.outerHTML", 5000) or ""
    text3 = browser.js.run_sync("document.body.innerText", 5000) or ""
    level, reason = det.classify(html3, "Verify", captcha_url, text3,
                                 captcha_forms=info_kw)
    check("keyword-only becomes suspected",
          level == "CAPTCHA" and "疑似" in reason and "跳过" in reason,
          f"{level} {reason}")

    # 4) 普通页面不应误判
    load_and_wait(rich)
    info_rich = probe(CAPTCHA_PROBE_JS)
    check("rich page: no captcha structure", not info_rich.get("found"), str(info_rich))
    html4 = browser.js.run_sync("document.documentElement.outerHTML", 5000) or ""
    text4 = browser.js.run_sync("document.body.innerText", 5000) or ""
    level, _ = det.classify(html4, "", rich, text4, captcha_forms=info_rich)
    check("rich page not flagged", level in ("NONE", "LOGIN"), level)

    # 5) 登录表单结构确认
    login_url = "file:///" + os.path.join(TESTDATA, "login_form.html").replace("\\", "/")
    load_and_wait(login_url)
    linfo = probe(LOGIN_PROBE_JS)
    check("login probe finds password field",
          bool(linfo.get("found")) and linfo.get("password", 0) >= 1, str(linfo))
    html5 = browser.js.run_sync("document.documentElement.outerHTML", 5000) or ""
    text5 = browser.js.run_sync("document.body.innerText", 5000) or ""
    level, reason = det.classify(html5, "Login", login_url, text5,
                                 login_form=linfo)
    check("login confirmed by form", level == "LOGIN" and "已确认" in reason,
          f"{level} {reason}")

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

    # ============ 检测增强：渲染文本 + 混淆关键词 ============
    det2 = Detector()

    # 1) 关键词只出现在渲染后的可见文本里（HTML 源码中没有明文）
    level, reason = det2.classify(
        "<html><body><canvas id='c'></canvas></body></html>", "",
        "https://example.com", "请完成安全验证后继续")
    check("detect keyword only in rendered text", level == "CAPTCHA", f"{level} {reason}")

    # 2) 零宽字符插入的伪装
    obf = "验\u200b证\u200b码"
    level, _ = det2.classify(f"<html><body><p>{obf}</p></body></html>", "")
    check("detect zero-width obfuscated keyword", level == "CAPTCHA", level)

    # 3) 字符间隔写法
    level, _ = det2.classify("<html><body><p>验 证 码</p></body></html>", "")
    check("detect spaced keyword", level == "CAPTCHA", level)

    # 4) 纯文本里的频控关键词
    level, _ = det2.classify("<html></html>", "", "", "访问过于频繁，请稍后再试")
    check("detect human keyword from text", level == "HUMAN", level)

    # 5) 正常页面不应误判
    level, _ = det2.classify("<html><body><h1>新闻标题</h1><p>正文内容</p></body></html>",
                             "首页", "https://news.example.com", "新闻标题 正文内容")
    check("no false positive", level == "NONE", level)

    # ============ 自定义关键词 ============
    from config import keyword_store
    original = keyword_store.load("captcha")
    keyword_store.save("captcha", ["自定义拦截词"])
    check("keyword saved",
          keyword_store.load("captcha") == ["自定义拦截词"],
          str(keyword_store.load("captcha")))
    check("keyword file written", os.path.isfile(keyword_store.STORE_PATH),
          keyword_store.STORE_PATH)

    level, reason = det2.classify("<html><body>自定义拦截词</body></html>", "")
    check("custom keyword works", level == "CAPTCHA" and "自定义拦截词" in reason,
          f"{level} {reason}")

    level, _ = det2.classify("<html><body>验证码</body></html>", "")
    check("old keyword replaced", level == "NONE", level)

    keyword_store.reset("captcha")
    check("keyword reset to default",
          keyword_store.load("captcha") == original,
          str(keyword_store.load("captcha")[:2]))
    check("is_customized False after reset", keyword_store.is_customized() is False)

    # ============ 临时文件清理 ============
    from utils import maintenance
    usage = maintenance.temp_usage()
    check("temp_usage returns dict",
          isinstance(usage, dict) and "engine_cache" in usage, str(list(usage)))
    check("human_size", maintenance.human_size(1536) == "1.5 KB",
          maintenance.human_size(1536))

    # 造一个可清理的临时文件
    junk_dir = os.path.join(HERE, "..", "__pycache__")
    junk_dir = os.path.abspath(junk_dir)
    os.makedirs(junk_dir, exist_ok=True)
    with open(os.path.join(junk_dir, "junk.pyc"), "wb") as fh:
        fh.write(b"x" * 2048)
    result = maintenance.clean_temp(engine_cache=False, temp_logs=False)
    check("clean_temp removed pycache", not os.path.isdir(junk_dir), junk_dir)
    check("clean_temp reports freed bytes", result["freed"] > 0,
          f"freed={result['freed_text']} removed={len(result['removed'])}")
    check("clean keeps profiles",
          os.path.isdir(PROFILE_DIR), PROFILE_DIR)

    browser.close()
    app.quit()

    print(f"\n===== FEATURE RESULT: {len(PASS)} passed, {len(FAIL)} failed =====", flush=True)
    if FAIL:
        print("FAILED:", FAIL, flush=True)
        sys.exit(1)
    print("ALL OK", flush=True)


if __name__ == "__main__":
    main()
