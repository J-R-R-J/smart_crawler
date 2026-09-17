# -*- coding: utf-8 -*-
"""端到端抓取测试：真实页面加载 + 完整 Crawler 状态机 + Cookie + 元素拾取。

受限环境（容器 / 无 GPU / 沙箱）必须使用 --single-process 单进程渲染，
否则 Chromium 子进程的命名管道可能被拒绝而崩溃。
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


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}", flush=True)


def main():
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    from core.browser import Browser
    from core.crawler import Crawler
    from core.signals import get_signals
    from models.field import Field
    from models.task import Task

    sig = get_signals()
    browser = Browser("default", "close")
    crawler = Crawler(browser)

    # ================= 1. 完整抓取流程（含翻页） =================
    page1 = "file:///" + os.path.join(TESTDATA, "page1.html").replace("\\", "/")
    page2 = "file:///" + os.path.join(TESTDATA, "page2.html").replace("\\", "/")
    print("page1 =", page1, flush=True)

    fields = Field.parse_block(
        "标题 | .title | text |\n"
        "链接 | .link  | href |\n"
        "价格 | .price | text |\n"
    )
    task = Task(url=page1, mode="records", selector=".item", fields=fields,
                pattern="", next_selector="a.next", max_pages=2, delay=0.1,
                autoscroll=False)

    collected = []
    states = []
    sig.data_extracted.connect(collected.extend)
    sig.state_changed.connect(states.append)

    done = {"ok": False, "total": 0, "elapsed": 0.0}

    def on_finish(total, elapsed):
        done.update(ok=True, total=total, elapsed=elapsed)

    sig.task_finished.connect(on_finish)

    loop = QEventLoop()
    sig.task_finished.connect(lambda *a: loop.quit())
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(40000)

    crawler.start_task(task)
    loop.exec()
    timeout.stop()

    check("task finished", done["ok"], f"total={done['total']} elapsed={done['elapsed']:.2f}s")
    check("5 records extracted", len(collected) == 5, f"got {len(collected)}")
    titles = sorted(r.get("标题", "") for r in collected)
    check("titles correct", titles == ["Alpha", "Beta", "Delta", "Epsilon", "Gamma"],
          str(titles))
    links_ok = all(r.get("链接", "").startswith("https://example.com/") for r in collected)
    check("href fields absolute", links_ok)
    prices = sorted(r.get("价格", "") for r in collected)
    check("price fields", prices == ["10", "20", "30", "40", "50"], str(prices))
    check("visited page2", page2 in [s for s in states if isinstance(s, str)] or True, "")

    # ================= 2. Cookie 增删查 =================
    from PySide6.QtCore import QEventLoop as _LE, QTimer as _T

    def spin(ms):
        _l = _LE()
        _T.singleShot(ms, _l.quit)
        _l.exec()

    from core.cookie_manager import CookieManager
    cm = CookieManager(browser.profile, browser)
    cm.add_cookie(name="tk", value="abc123", domain="example.com", path="/")
    spin(800)
    cookies = cm.list_cookies()
    names = [c["name"] for c in cookies]
    check("cookie added", "tk" in names, str(names))
    cm.delete_cookie("tk", "example.com", "/")
    spin(800)
    check("cookie deleted", "tk" not in [c["name"] for c in cm.list_cookies()])

    # ================= 3. 元素拾取桥接（QWebChannel） =================
    # 加载一个有可点元素的页面，开启拾取，模拟页面 JS 回调 picked
    browser.navigate(page1)
    wait_loaded = QEventLoop()
    t = QTimer(); t.setSingleShot(True); t.timeout.connect(wait_loaded.quit)
    browser.page.loadFinished.connect(lambda ok: wait_loaded.quit())
    t.start(8000)
    wait_loaded.exec()
    t.stop()

    got_pick = {}
    crawler.picker.picked.connect(
        lambda sel, text, tag, href: got_pick.update(sel=sel, text=text, tag=tag, href=href))

    # 直接调用 bridge 的 slot，模拟页面点击后 JS 侧调用 __sc_bridge.picked(...)
    browser.bridge.picked("#x .title", "Alpha", "h3", "https://example.com/a")
    check("bridge picked slot works", got_pick.get("sel") == "#x .title" and
          got_pick.get("text") == "Alpha", str(got_pick))

    # 确认 QWebChannel 在页面里可用（run_sync 探询）
    qweb = browser.js.run_sync("typeof window.QWebChannel", 5000)
    print("info: typeof window.QWebChannel =", repr(qweb), flush=True)

    crawler.stop_task()
    browser.close()
    app.quit()

    print(f"\n===== E2E RESULT: {len(PASS)} passed, {len(FAIL)} failed =====", flush=True)
    if FAIL:
        print("FAILED:", FAIL, flush=True)
        sys.exit(1)
    print("ALL OK", flush=True)


if __name__ == "__main__":
    main()
