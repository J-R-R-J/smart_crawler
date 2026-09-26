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
                                         CAPTCHA_KEYWORDS, LOGIN_KEYWORDS,
                                         MEDIA_EXTS, ALL_MEDIA_EXTS,
                                         DOWNLOAD_PRESET_KEYS, preset_exts,
                                         ANTIBOT_ITEMS)
    check("20 formats", len(SUPPORTED_FORMATS) == 20, f"got {len(SUPPORTED_FORMATS)}")
    # 三种媒体格式必须在格式表里，否则界面上根本选不出来
    fmt_keys = [k for k, _l, _h in SUPPORTED_FORMATS]
    check("媒体格式齐全（images/video/audio/media）",
          all(k in fmt_keys for k in ("images", "video", "audio", "media")),
          str(fmt_keys))
    check("媒体扩展名表非空且三类都有",
          all(MEDIA_EXTS.get(k) for k in ("image", "video", "audio")),
          str({k: len(v) for k, v in MEDIA_EXTS.items()}))
    check("m3u8 / mpd 算视频（流媒体清单也要能抓）",
          "m3u8" in MEDIA_EXTS["video"] and "mpd" in MEDIA_EXTS["video"],
          str(MEDIA_EXTS["video"][-6:]))
    check("媒体预设展开成完整扩展名列表",
          len(preset_exts("media").split(",")) == len(ALL_MEDIA_EXTS),
          str(len(preset_exts("media").split(","))))
    check("预设 all 表示不限（空串）", preset_exts("all") == ""
          and preset_exts("") == "")
    check("下载预设表与展开函数一致",
          all(preset_exts(k) or k == "all" for k in DOWNLOAD_PRESET_KEYS),
          str(DOWNLOAD_PRESET_KEYS))
    check("反检测子项表非空", len(ANTIBOT_ITEMS) >= 6, str(len(ANTIBOT_ITEMS)))
    check("3 popup strategies", len(POPUP_STRATEGIES) == 3)
    check("keywords non-empty", bool(CAPTCHA_KEYWORDS) and bool(LOGIN_KEYWORDS))
    from config.js_scripts import (QWEBCHANNEL_JS, PICKER_JS, POPUP_SCAN_JS,
                                   build_extract_js, STEALTH_JS,
                                   build_stealth_js)
    check("QWEBCHANNEL_JS", "QWebChannel" in QWEBCHANNEL_JS)

    # ---- 1b. 反检测：请求头 / 拦截策略（纯 Python，不碰网络） ----
    from core import headers as H
    from core import antibot
    ua = H.desktop_ua(130)
    hdrs = H.build_headers("https://example.com/a", kind="document")
    check("UA 版本号可注入（与 Client Hints 同源）",
          "Chrome/130.0.0.0" in ua and '"Chromium";v="130"' in hdrs["sec-ch-ua"],
          ua)
    check("请求头自洽性自检通过", H.consistency_issues(ua, hdrs) == [],
          str(H.consistency_issues(ua, hdrs)))
    bad = dict(hdrs)
    bad["sec-ch-ua"] = '"Chromium";v="124"'
    check("自检能抓出 UA 与 sec-ch-ua 版本不一致",
          any("不一致" in x for x in H.consistency_issues(ua, bad)),
          str(H.consistency_issues(ua, bad)))
    check("按请求类型给出不同的 Sec-Fetch 三件套",
          H.build_headers("https://a.com/x", kind="xhr")["Sec-Fetch-Dest"] == "empty"
          and H.build_headers("https://a.com/x", kind="image")["Sec-Fetch-Dest"] == "image")
    check("Referer 会影响 Sec-Fetch-Site",
          H.fetch_site("https://a.com/x", "https://b.com/") == "cross-site"
          and H.fetch_site("https://a.com/x", "https://a.com/") == "same-origin",
          H.fetch_site("https://a.com/x", "https://b.com/"))
    check("追踪器按后缀匹配（不会误伤同名字符串）",
          antibot.should_block("https://www.google-analytics.com/x",
                               "https://mysite.com/", "xhr") is not None
          and antibot.should_block("https://notgoogle-analytics.com.evil.com/x",
                                   "https://mysite.com/", "xhr") is None,
          str(antibot.should_block("https://notgoogle-analytics.com.evil.com/x",
                                   "https://mysite.com/", "xhr")))
    check("主文档与第一方永不拦截",
          antibot.should_block("https://www.google-analytics.com/x",
                               "https://mysite.com/", "document") is None
          and antibot.should_block("https://mysite.com/ga.js",
                                   "https://mysite.com/", "script") is None)
    check("风控/校验服务在永不拦截名单里",
          antibot.is_never_blocked("challenges.cloudflare.com")
          and antibot.is_never_blocked("captcha.qq.com")
          and not antibot.is_never_blocked("www.google-analytics.com"))
    cf = antibot.is_cloudflare_challenge(
        "<html><head><title>Just a moment...</title>"
        "<script src='/cdn-cgi/challenge-platform/x.js'></script></head></html>")
    check("能识别 Cloudflare JS 挑战并可自动过",
          cf["challenge"] and cf["kind"] == "js" and cf["auto"], str(cf))
    cf2 = antibot.is_cloudflare_challenge(
        "<html><title>Verify</title><body><div class='cf-turnstile'></div>"
        "Please verify you are human</body></html>")
    check("交互式 Turnstile 判定为需人工", cf2["kind"] == "turnstile"
          and not cf2["auto"], str(cf2))
    check("普通页面不会被当成 CF 挑战",
          not antibot.is_cloudflare_challenge("<html><body>hello</body></html>",
                                              "首页")["challenge"])

    # ---- 1c. 伪装脚本的四个新开关 ----
    js_all = build_stealth_js(canvas=True, webrtc=True, adblock=True,
                              uach=True, major=130)
    js_off = build_stealth_js(canvas=False, webrtc=False, adblock=False,
                              uach=False, major=130)
    check("伪装脚本含 Canvas/WebRTC/反广告/UA-CH 四节",
          all(k in js_all for k in ("scDirty", "RTCPeerConnection", "adsbygoogle",
                                    "userAgentData")), str(len(js_all)))
    check("开关能真的关掉对应节（不是写了不生效）",
          '"canvas": true' in js_all and '"canvas": false' in js_off
          and '"webrtc": false' in js_off and '"adblock": false' in js_off,
          js_off[:120])
    check("STEALTH_JS 常量仍是可用的默认脚本",
          isinstance(STEALTH_JS, str) and "SC_FLAGS" not in STEALTH_JS
          and "@@" not in STEALTH_JS, str(len(STEALTH_JS)))

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
                 "jsonld", "meta", "forms", "video", "audio", "media",
                 "iframe", "rss", "sitemap",
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
    check("Extractor modes", len(ex.supported_modes()) == 20,
          str(len(ex.supported_modes())))
    check("picker/pager/popup",
          all(x is not None for x in (win.crawler.picker, win.crawler.pager,
                                      win.crawler.popup_handler)))
    check("Crawler picker", win.crawler.picker is not None)

    # ---- 5b. 反检测在真实 Browser 上的装配 ----
    st = browser.anti_detect_state()
    check("Browser 的 UA 与引擎真实版本一致",
          f"Chrome/{H.chrome_major()}.0.0.0" in st["user_agent"], st["user_agent"])
    check("Browser 设置了 Accept-Language（不再交给 Qt 默认 en-US）",
          st["accept_language"].startswith("zh"), st["accept_language"])
    check("追踪器拦截器已装上且默认开启",
          browser.tracker_policy is not None and browser.block_trackers is True)
    check("TLS 指纹档位已选出（curl_cffi 可用时）",
          st["tls"]["target"] == "" or st["tls"]["target"].startswith("chrome"),
          str(st["tls"]))
    check("伪装脚本开关可运行时切换（会重建并重注入）",
          browser.hide_canvas is True)
    browser.hide_canvas = False
    off_ok = (browser.hide_canvas is False
              and browser._find_script("sc_stealth") is not None)
    browser.hide_canvas = True
    check("关掉 Canvas 干扰后脚本仍在（只是那一节关了）",
          off_ok and browser.hide_canvas is True
          and browser._find_script("sc_stealth") is not None)
    check("Crawler 默认开启 Cloudflare 自动绕过",
          win.crawler.auto_cloudflare is True)

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
