# -*- coding: utf-8 -*-
"""功能覆盖测试：20 种提取格式 + 弹窗三策略 + 验证码检测 + Cookie 导入导出 + 多 Profile +
多格式导出（11 种）与爬取文件导出。"""
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

    # ============ 20 种提取格式 ============
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
    # 先完整备份三组关键词，测试结束后原样还原：
    # 既避免污染用户配置，也让断言不依赖上一次运行残留的状态。
    from config import keyword_store
    backup = keyword_store.load_all()
    try:
        keyword_store.reset()          # 从默认值起步，保证断言可预期
        original = keyword_store.load("captcha")

        keyword_store.save("captcha", ["自定义拦截词"])
        check("keyword saved",
              keyword_store.load("captcha") == ["自定义拦截词"],
              str(keyword_store.load("captcha")))
        check("keyword file written", os.path.isfile(keyword_store.STORE_PATH),
              keyword_store.STORE_PATH)

        level, reason = det2.classify("<html><body>自定义拦截词</body></html>", "")
        check("custom keyword works",
              level == "CAPTCHA" and "自定义拦截词" in reason, f"{level} {reason}")

        level, _ = det2.classify("<html><body>验证码</body></html>", "")
        check("old keyword replaced", level == "NONE", level)

        keyword_store.reset("captcha")
        check("keyword reset to default",
              keyword_store.load("captcha") == original,
              str(keyword_store.load("captcha")[:2]))

        keyword_store.reset()          # 三组全部恢复默认
        check("is_customized False after full reset",
              keyword_store.is_customized() is False)
    finally:
        keyword_store.save_all(backup)
    check("keyword config restored",
          keyword_store.load_all() == backup, "已还原测试前的关键词配置")

    # ============ 下载格式白名单 ============
    browser.allowed_download_exts = "pdf, .CSV ,xlsx"
    check("download exts parsed",
          browser.allowed_download_exts == {"pdf", "csv", "xlsx"},
          str(sorted(browser.allowed_download_exts)))
    check("ext allowed (lower)", browser._ext_allowed("report.pdf") is True)
    check("ext allowed (upper)", browser._ext_allowed("DATA.CSV") is True)
    check("ext rejected (exe)", browser._ext_allowed("setup.exe") is False)
    check("ext rejected (no ext)", browser._ext_allowed("README") is False)
    check("ext rejected (double ext)",
          browser._ext_allowed("evil.pdf.exe") is False)

    browser.allowed_download_exts = ""
    check("empty whitelist allows all",
          browser._ext_allowed("anything.exe") is True)
    check("empty whitelist set", browser.allowed_download_exts == set())

    # 全角逗号也应能解析
    browser.allowed_download_exts = "pdf，docx"
    check("fullwidth comma parsed",
          browser.allowed_download_exts == {"pdf", "docx"},
          str(sorted(browser.allowed_download_exts)))
    browser.allowed_download_exts = ""

    # ============ 媒体全格式提取（图片 / 视频 / 音频） ============
    media_url = "file:///" + os.path.join(TESTDATA, "media.html").replace("\\", "/")
    load_and_wait(media_url)

    def media_rows(mode):
        rows = extract(mode)
        return rows, {r.get("src", "") for r in rows}

    rows, urls = media_rows("images")
    check("images: 普通图", any(u.endswith("/img/plain.jpg") for u in urls), str(len(urls)))
    check("images: 懒加载 data-src（src 是 base64 占位图时不能只看 src）",
          any(u.endswith("/img/lazy-real.png") for u in urls))
    check("images: srcset 取最大候选（1280w），浏览器选中的记在 current 列",
          any(u.endswith("/img/s-1280.webp") for u in urls)
          and not any(u.endswith("/img/s-320.webp") for u in urls)
          and any(str(r.get("current", "")).endswith("/img/s-320.webp")
                  for r in rows),
          str([(r.get("src", "")[-18:], str(r.get("current", ""))[-18:])
               for r in rows if "s-1280" in r.get("src", "")]))
    check("images: <picture><source srcset>",
          any(u.endswith("/img/pic.avif") or u.endswith("/img/pic.webp")
              for u in urls))
    check("images: 内联样式背景图",
          any(u.endswith("/img/inline-bg.gif") for u in urls))
    check("images: CSS 规则里的背景图（读 CSSOM）",
          any(u.endswith("/assets/cssbg.jpg") for u in urls)
          and any(u.endswith("/assets/cssbg2.webp") for u in urls),
          str([u for u in urls if "cssbg" in u]))
    check("images: svg <image href>",
          any(u.endswith("/img/svg-inline.png") for u in urls))
    check("images: link rel=preload / icon",
          any(u.endswith("/pre/preload.jpg") for u in urls)
          and any(u.endswith("favicon.ico") for u in urls))
    check("images: og:image",
          any(u.endswith("/og/cover.png") for u in urls))
    check("images: 视频封面 poster 也算图片",
          any(u.endswith("/img/poster.webp") for u in urls)
          and any(u.endswith("/img/poster2.jpg") for u in urls))
    check("images: 内嵌 JSON 里转义斜杠的图片直链",
          any(u.endswith("/img/json-cover.jpeg") for u in urls),
          str([u for u in urls if "json-cover" in u]))
    check("images: 每行带 kind/format/source 列",
          all(r.get("kind") == "image" for r in rows)
          and any(r.get("format") == "jpg" for r in rows)
          and any(r.get("source") == "img" for r in rows),
          str(rows[0] if rows else {}))

    # ---- 内容图 vs 站点素材图（用户实测"只抓到站点素材图"的那条线）----
    check("images: 百分号编码的内嵌 JSON 也能抓到（抖音 RENDER_DATA 那类）",
          any("tos-cn-i-0813" in u for u in urls),
          str([u for u in urls if "douyinpic" in u]))
    check("images: 没有常规扩展名的正文图按内容标记识别（biz_tag=aweme_images）",
          any("biz_tag=aweme_images" in u for u in urls))
    check("images: 站点 UI 素材被标记 asset=1（图标 / 表情 / 头像）",
          sum(1 for r in rows if r.get("asset")) >= 3
          and any(not r.get("asset") for r in rows),
          str([(str(r.get("src"))[-26:], r.get("asset"))
               for r in rows if r.get("asset")][:3]))
    check("images: 正文图不带素材标记",
          all(not r.get("asset") for r in rows
              if "tos-cn-i-0813" in str(r.get("src"))))

    # 过滤开关：默认关（保留全部，不改变既有行为）；勾上后按 asset 丢弃
    _all_rows = extract("images")
    _filtered_rows = extractor.extract(
        browser.page, Task(url=media_url, mode="images", flags="g",
                           filter_site_assets=True))
    check("过滤站点素材图：默认不过滤", len(_all_rows) >= len(_filtered_rows))
    check("过滤站点素材图：勾选后丢掉 UI 素材并给出条数",
          len(_all_rows) - len(_filtered_rows) == extractor.last_filtered >= 3
          and all(not r.get("asset") for r in _filtered_rows),
          f"all={len(_all_rows)} kept={len(_filtered_rows)} "
          f"filtered={extractor.last_filtered}")
    check("过滤站点素材图：正文图仍在（不是把整页都丢了）",
          any("tos-cn-i-0813" in str(r.get("src")) for r in _filtered_rows)
          and any(str(r.get("src")).endswith("/img/plain.jpg")
                  for r in _filtered_rows))

    rows, urls = media_rows("video")
    check("video: <video src>", any(u.endswith("/media/movie.mp4") for u in urls))
    check("video: <video><source>", any(u.endswith("/media/movie.webm") for u in urls)
          and any(u.endswith("/media/movie.m4v") for u in urls))
    check("video: 独立 <source type=video/*>",
          any(u.endswith("/media/standalone.mp4") for u in urls))
    check("video: link rel=preload as=video",
          any(u.endswith("/pre/preload.mp4") for u in urls))
    check("video: og:video", any(u.endswith("/og/trailer.mp4") for u in urls))
    check("video: HLS(m3u8) / DASH(mpd) 清单",
          any(u.endswith("master.m3u8") for u in urls)
          and any(u.endswith("manifest.mpd") for u in urls),
          str([u for u in urls if "m3u8" in u or "mpd" in u]))
    check("video: 内嵌 JSON 里转义的直链（抖音那类写法）",
          any(u.endswith("/v/real-video.mp4") for u in urls),
          str([u for u in urls if "real-video" in u]))
    check("video: 视频平台 iframe 被收录",
          any("player.bilibili.com" in u for u in urls)
          and not any("example.com/frame.html" in u for u in urls))
    check("video: poster 单独成列",
          any(r.get("poster", "").endswith("/img/poster.webp") for r in rows),
          str([r.get("poster") for r in rows if r.get("poster")][:2]))

    rows, urls = media_rows("audio")
    check("audio: <audio src>", any(u.endswith("/audio/song.mp3") for u in urls))
    check("audio: <audio><source>", any(u.endswith("/audio/song.ogg") for u in urls)
          and any(u.endswith("/audio/song.flac") for u in urls))
    check("audio: og:audio", any(u.endswith("/og/theme.mp3") for u in urls))
    check("audio: 内嵌 JSON 里的音频（转义 + 未转义 + 百分号编码都要认）",
          any(u.endswith("/a/bgm.m4a") for u in urls)
          and any(u.endswith("/a/inline-song.mp3") for u in urls)
          and any(u.endswith("/a/enc-song.mp3") for u in urls),
          str([u for u in urls if "/a/" in u]))
    check("audio: 每行 kind=audio", all(r.get("kind") == "audio" for r in rows))

    rows, urls = media_rows("media")
    kinds = {r.get("kind") for r in rows}
    check("media: 一次抓齐图片/视频/音频三类",
          {"image", "video", "audio"} <= kinds, str(sorted(kinds)))
    check("media: 三类之间去重（同一地址只出现一次）",
          len(urls) == len(rows), f"rows={len(rows)} uniq={len(urls)}")
    check("media: 条数明显多于单一 images（说明真的合并了三路）",
          len(rows) > 25, str(len(rows)))
    rows_img, urls_img = media_rows("images")
    check("media 的图片条数 >= images 单跑（且没有丢图）",
          len({u for u in urls if u.endswith((".jpg", ".png", ".webp", ".gif",
                                              ".jpeg", ".avif", ".ico"))})
          >= len({u for u in urls_img if u.endswith((".jpg", ".png", ".webp",
                                                     ".gif", ".jpeg", ".avif",
                                                     ".ico"))}))

    # ============ 验证码误判：源码里有字样、可见区域没有 ============
    long_text = "正文内容" * 400
    noisy_html = ("<html><head><script>var t=\"captcha\";</script></head>"
                  "<body><p>%s</p></body></html>" % long_text)
    level, reason = det2.classify(noisy_html, "抖音笔记",
                                  "https://www.douyin.com/note/1", long_text)
    check("源码里的 captcha 字样不再拦截任务（实测踩过的误判）",
          level == "NONE", f"{level} {reason}")
    check("但会留下一条可排查的说明", "误报" in det2.last_note, det2.last_note)
    level, _ = det2.classify(noisy_html, "抖音笔记",
                             "https://www.douyin.com/note/1", "正在验证")
    check("渲染文本过短时仍走宽松判定（挑战页宁拦不漏）",
          level == "CAPTCHA", level)

    # ============ 弹窗处理：没有进展就不要再空转 ============
    from core.popup_handler import PopupHandler
    pop2 = PopupHandler(browser.page, browser.js, "remove")
    rounds = []
    orig_next = pop2._next_round

    def counting_next():
        rounds.append(pop2._round)
        return orig_next()

    pop2._next_round = counting_next
    pop2.handle_all()
    spin(1500, app)
    check("弹窗无进展时不再空转（最多 3 轮 -> 实际更少）",
          len(rounds) <= 3, f"rounds={rounds}")

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

    # ==================== 多格式导出 + 爬取文件导出 ====================
    import csv as _csv
    import json
    import sqlite3
    import xml.etree.ElementTree as _ET
    import zipfile

    from utils import exporters as EX
    from utils import media_files as MF

    out_dir = os.path.join(ROOT, "crawler_data", "exports", "_feat_formats")
    os.makedirs(out_dir, exist_ok=True)
    ex_rows = [{"标题": "A|B", "链接": "https://e.com/a", "价格": 1,
                "ok": True, "tags": ["x", "y"], "n": None},
               {"标题": "中文标题", "链接": "https://e.com/b", "价格": 2.5,
                "ok": False, "tags": [], "n": "多行\n值"}]
    ex_cols = ["标题", "链接", "价格", "ok", "tags", "n"]

    written = {}
    for _key, _label, _ext in EX.EXPORT_FORMATS:
        _p = os.path.join(out_dir, "out." + _ext)
        EX.export_any(ex_rows, ex_cols, _p, _key)
        written[_key] = _p
    check("11 种导出格式都能落盘且非空",
          len(written) == 11 and all(os.path.getsize(p) > 20 for p in written.values()),
          ", ".join(sorted(written)))

    with open(written["csv"], encoding="utf-8-sig", newline="") as fh:
        _csv_rows = list(_csv.reader(fh))
    check("CSV 表头 + 2 行", _csv_rows[0] == ex_cols and len(_csv_rows) == 3,
          str(_csv_rows[:1]))

    with open(written["tsv"], encoding="utf-8-sig", newline="") as fh:
        _tsv_rows = list(_csv.reader(fh, delimiter="\t"))
    check("TSV 制表符分隔且单元格内换行被压平",
          _tsv_rows[0] == ex_cols and "\n" not in _tsv_rows[2][5], str(_tsv_rows[2]))

    with open(written["jsonl"], encoding="utf-8") as fh:
        _lines = [l for l in fh.read().splitlines() if l.strip()]
    check("JSONL 每行一个对象", len(_lines) == 2 and json.loads(_lines[0])["标题"] == "A|B")

    _zf = zipfile.ZipFile(written["xlsx"])
    _parts = set(_zf.namelist())
    check("xlsx 是合法的 OOXML 包（零依赖手写）",
          {"[Content_Types].xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml"} <= _parts,
          str(sorted(_parts)))
    _sheet = _zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    _ET.fromstring(_sheet)                       # 不是合法 XML 这里就会抛
    check("xlsx 表格 XML 合法且带冻结首行 / 自动筛选",
          'state="frozen"' in _sheet and "<autoFilter" in _sheet
          and 't="inlineStr"' in _sheet)
    check("xlsx 里中文字段名原样保留", "标题" in _sheet)

    _root = _ET.parse(written["xml"]).getroot()
    check("XML 可被解析且结构正确",
          _root.tag == "results" and _root.get("count") == "2" and len(_root) == 2,
          _root.tag)

    _conn = sqlite3.connect(written["sqlite"])
    _got = _conn.execute("select 标题, 价格, ok from results").fetchall()
    _types = {r[1]: r[2] for r in
              _conn.execute("pragma table_info(results)").fetchall()}
    _conn.close()
    check("SQLite 数据正确", _got[0][0] == "A|B" and len(_got) == 2, str(_got))
    check("SQLite 列类型推断：混合数字列 REAL、布尔列 INTEGER、文本列 TEXT",
          _types.get("价格") == "REAL" and _types.get("ok") == "INTEGER"
          and _types.get("标题") == "TEXT", str(_types))

    with open(written["md"], encoding="utf-8") as fh:
        _md = fh.read()
    check("Markdown 表格转义竖线", "\\|" in _md and _md.count("| --- |") + _md.count("| --- ") >= 1,
          _md.splitlines()[5][:40] if len(_md.splitlines()) > 5 else _md[:40])

    with open(written["html"], encoding="utf-8") as fh:
        _html = fh.read()
    check("HTML 自包含表格 + 链接可点",
          "<table>" in _html and '<a href="https://e.com/a"' in _html
          and 'charset="utf-8"' in _html)

    with open(written["txt"], encoding="utf-8") as fh:
        _txt = fh.read()
    check("TXT 表格按显示宽度对齐（中文列不歪）",
          "标题" in _txt and "多行 值" in _txt and _txt.count("\n") >= 6)

    with open(written["yaml"], encoding="utf-8") as fh:
        _yaml = fh.read()
    check("YAML 列表 + 标量引号规则",
          _yaml.count("- 标题:") == 2 and '"多行\\n值"' in _yaml,
          _yaml.splitlines()[-1])

    check("按扩展名推断格式",
          EX.format_for_path("a/b.XLSX") == "xlsx"
          and EX.format_for_path("x.yaml") == "yaml"
          and EX.format_for_path("x.db") == "sqlite")
    try:
        EX.export_any(ex_rows, ex_cols, os.path.join(out_dir, "x.unknown"), None)
        _bad = False
    except ValueError:
        _bad = True
    check("未知扩展名明确报错（不静默写成空文件）", _bad)

    _one = os.path.join(out_dir, "one.json")
    EX.export_single(ex_rows[0], _one, "json")
    with open(_one, encoding="utf-8") as fh:
        _one_data = json.load(fh)
    check("单条导出 json 是对象而不是数组",
          isinstance(_one_data, dict) and _one_data["标题"] == "A|B")

    # ---------- 行内媒体链接识别 ----------
    m_row = {"图片1": "https://cdn.x.com/a/b/photo.jpg?w=100",
             "视频": "//v.x.com/x/clip.MP4",
             "内联": "data:image/png;base64,aGVsbG8=",
             "临时视频": "blob:https://x.com/123",
             "src": "https://cdn.x.com/clip.mp4",
             "封面图": "https://cdn.x.com/img/abc123",
             "链接": "https://e.com/note/123"}
    _refs = MF.row_files(m_row)
    _by_field = {r.field: r for r in _refs}
    check("行内媒体识别：图片（带查询串）",
          _by_field["图片1"].filename == "photo.jpg"
          and _by_field["图片1"].kind == "image")
    check("行内媒体识别：协议相对 URL + 大写扩展名",
          _by_field["视频"].kind == "video"
          and _by_field["视频"].filename == "clip.MP4")
    check("行内媒体识别：内联 data: URL 生成带扩展名的哈希名",
          _by_field["内联"].kind == "image"
          and _by_field["内联"].filename.startswith("inline_")
          and _by_field["内联"].filename.endswith(".png"))
    check("行内媒体识别：无扩展名时按列名判断类型",
          _by_field["封面图"].kind == "image"
          and _by_field["封面图"].filename == "abc123")
    check("行内媒体识别：blob: 也被列出（导出时才会说明原因）",
          _by_field["临时视频"].kind == "video" and _by_field["临时视频"].filename == "")
    check("普通网页链接不当成「文件」",
          "链接" not in _by_field
          and MF.row_files({"链接": "https://e.com/a"}) == []
          and MF.row_files({"_mode": "https://a/b.jpg"}) == [])
    check("网页链接仍可由「在浏览器打开」取到",
          any(u == "https://e.com/note/123" for _f, u in MF.row_links(m_row)))
    check("文件名清洗掉 Windows 非法字符 / 保留名",
          MF.safe_name("a<b>:c|d?.jpg") == "a_b__c_d_.jpg"
          and MF.safe_name("con.png") == "_con.png")

    # ---------- 本地已有：复制；内联：解码；临时地址：跳过 ----------
    fake_dl = os.path.join(out_dir, "fake_downloads")
    os.makedirs(fake_dl, exist_ok=True)
    with open(os.path.join(fake_dl, "feat_photo.jpg"), "wb") as fh:
        fh.write(b"\xff\xd8\xff\xe0JPEGDATA")
    dest_dir = os.path.join(out_dir, "files")
    _rep = MF.export_refs(
        [MF.MediaRef("图片1", "https://cdn.x.com/a/b/feat_photo.jpg?w=100", "image",
                     "feat_photo.jpg"),
         MF.MediaRef("内联", "data:image/png;base64,aGVsbG8=", "image", "inline.png"),
         MF.MediaRef("临时", "blob:https://x.com/123", "file", ""),
         MF.MediaRef("坏", "http://127.0.0.1:9/none.jpg", "image", "none.jpg")],
        dest_dir, timeout=3, search_dirs=(fake_dl,))
    _st = [i["status"] for i in _rep["items"]]
    check("文件导出：本地已下载的直接复制（不重新下载）",
          _st[0] == "copied"
          and os.path.getsize(os.path.join(dest_dir, "feat_photo.jpg")) == 12,
          str(_st))
    check("文件导出：内联 data: URL 解码落盘",
          _st[1] == "downloaded"
          and open(os.path.join(dest_dir, "inline.png"), "rb").read() == b"hello")
    check("文件导出：页面内 blob: 地址标为跳过并给出原因",
          _st[2] == "skipped" and "临时地址" in _rep["items"][2]["reason"],
          _rep["items"][2]["reason"])
    check("文件导出：连接失败标为失败且不留残缺文件",
          _st[3] == "failed" and not os.path.exists(os.path.join(dest_dir, "none.jpg")),
          _rep["items"][3]["reason"][:60])
    check("文件导出报告摘要含成功/跳过/失败计数",
          "成功 2" in MF.summary_text(_rep) and "失败 1" in MF.summary_text(_rep),
          MF.summary_text(_rep).splitlines()[1])

    _rep2 = MF.export_refs(
        [MF.MediaRef("图片1", "https://cdn.x.com/a/b/feat_photo.jpg?w=100", "image",
                     "feat_photo.jpg")], dest_dir, search_dirs=(fake_dl,))
    check("重复导出不覆盖已有文件（自动改名 -1）",
          _rep2["items"][0]["status"] == "copied"
          and os.path.isfile(os.path.join(dest_dir, "feat_photo-1.jpg"))
          and os.path.isfile(os.path.join(dest_dir, "feat_photo.jpg")),
          _rep2["items"][0]["path"])

    _rep3 = MF.export_refs(
        [MF.MediaRef("图片1", "https://cdn.x.com/a/b/feat_photo.jpg?w=100", "image",
                     "feat_photo.jpg")], dest_dir, search_dirs=(fake_dl,),
        dest_file=os.path.join(dest_dir, "feat_photo.jpg"))
    check("「另存为」指定确切路径：已存在且不允许覆盖时判为已存在（不误删用户文件）",
          _rep3["items"][0]["status"] == "exists"
          and os.path.getsize(os.path.join(dest_dir, "feat_photo.jpg")) == 12,
          _rep3["items"][0]["status"])
    _rep4 = MF.export_refs(
        [MF.MediaRef("图片1", "https://cdn.x.com/a/b/feat_photo.jpg?w=100", "image",
                     "feat_photo.jpg")], dest_dir, search_dirs=(fake_dl,),
        overwrite=True, dest_file=os.path.join(dest_dir, "feat_photo.jpg"))
    check("「另存为」允许覆盖时按确切路径写入",
          _rep4["items"][0]["status"] == "copied"
          and os.path.getsize(os.path.join(dest_dir, "feat_photo.jpg")) == 12,
          _rep4["items"][0]["status"])

    # ---------- 下载路径：用假响应验证「先 .part 再改名」与 Content-Type 补扩展名 ----------
    class _FakeHeaders:
        def __init__(self, ctype):
            self._ctype = ctype

        def get_content_type(self):
            return self._ctype

    class _FakeResp:
        def __init__(self, data, ctype):
            self._data = data
            self.headers = _FakeHeaders(ctype)

        def read(self, n=-1):
            if n is None or n < 0:
                n = len(self._data)
            chunk, self._data = self._data[:n], self._data[n:]
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    _seen_req = {}

    def _fake_urlopen(req, timeout=None):        # noqa: ANN001
        _seen_req["url"] = getattr(req, "full_url", str(req))
        _seen_req["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _FakeResp(b"VIDEOBYTES", "video/mp4")

    _orig_urlopen = MF.urllib.request.urlopen
    MF.urllib.request.urlopen = _fake_urlopen
    try:
        _dl_dest = os.path.join(out_dir, "nodot", "streamfile")
        os.makedirs(os.path.dirname(_dl_dest), exist_ok=True)
        _final, _size = MF.download_url("https://v.x.com/s/streamfile", _dl_dest,
                                       timeout=5)
        _ok_dl = (os.path.isfile(_final) and _size == 10
                  and _final.endswith(".mp4")
                  and open(_final, "rb").read() == b"VIDEOBYTES"
                  and not os.path.exists(_dl_dest + ".part"))
        check("下载：无扩展名时按 Content-Type 补 .mp4 且不留 .part 残留文件", _ok_dl, _final)
        check("下载：带上浏览器同款请求头（UA / Accept-Language）",
              "user-agent" in _seen_req.get("headers", {})
              and "accept-language" in _seen_req.get("headers", {}),
              str(list(_seen_req.get("headers", {})))[:120])

        _stop_ref = MF.MediaRef("v", "https://v.x.com/s/x.mp4", "video", "x.mp4")
        _stop_rep = MF.export_ref(_stop_ref, dest_dir, timeout=5,
                                  should_stop=lambda: True)
        check("下载：可中途取消且不留残缺文件",
              _stop_rep["status"] == "skipped"
              and not os.path.exists(os.path.join(dest_dir, "x.mp4")),
              _stop_rep["reason"])
    finally:
        MF.urllib.request.urlopen = _orig_urlopen

    check("collect_refs 跨行去重",
          len(MF.collect_refs([m_row, m_row])) == len(MF.row_files(m_row)))
    check("row_links 只挑出真正的页面链接",
          all(u.startswith("http") for _f, u in MF.row_links(m_row))
          and len(MF.row_links(m_row)) >= 3, str(MF.row_links(m_row))[:120])

    # ============ 非浏览器引擎：注入页面的加载失败不能终止任务 ============
    # 用户实测：隐身 / 动态引擎都取回了 1.5 MB 的抖音 HTML，紧接着
    # 「页面加载失败，任务终止 / 共 0 条」—— 于是结论变成"这两个引擎用不了"。
    # 真因是注入之后页面脚本自己跳转，Qt 把那次加载判为 aborted(False)。
    import time as _time
    _crawler = Crawler(browser)
    _crawler._task = Task(url=rich, mode="text")
    _crawler._state = "WAIT_LOAD"
    _crawler._cancel = False
    _crawler._injected_until = _time.time() + 30.0
    fin = []
    _crawler._signals.task_finished.connect(lambda *a: fin.append(1))
    _crawler._on_load_finished(False)
    check("注入 HTML 的加载被判失败时不终止任务（隐身/动态引擎 0 条的真因）",
          not fin, f"finished={len(fin)} state={_crawler._state}")
    _crawler._cancel = True          # 让随后那次 _after_load 直接返回，别干扰后续用例

    _crawler2 = Crawler(browser)
    _crawler2._task = Task(url=rich, mode="text")
    _crawler2._state = "WAIT_LOAD"
    _crawler2._cancel = False
    _crawler2._injected_until = 0.0  # 浏览器自己导航：失败仍然是致命的
    fin2 = []
    _crawler2._signals.task_finished.connect(lambda *a: fin2.append(1))
    _crawler2._on_load_finished(False)
    check("浏览器自己导航时加载失败仍按原样终止（没有放宽过头）",
          bool(fin2), f"finished={len(fin2)}")
    _crawler.deleteLater()
    _crawler2.deleteLater()

    browser.close()
    app.quit()

    print(f"\n===== FEATURE RESULT: {len(PASS)} passed, {len(FAIL)} failed =====", flush=True)
    if FAIL:
        print("FAILED:", FAIL, flush=True)
        sys.exit(1)
    print("ALL OK", flush=True)


if __name__ == "__main__":
    main()
