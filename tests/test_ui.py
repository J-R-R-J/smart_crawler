# -*- coding: utf-8 -*-
"""UI 交互测试：按钮点击、导航历史、各面板操作、全局信号槽（无头模式）。

覆盖 test_smoke / test_e2e / test_feature 未触及的界面动作路径，
例如「后退 / 前进 / 刷新」这类直接映射到 Qt API 的按钮。
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


def spin(ms):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def file_url(name):
    return "file:///" + os.path.join(TESTDATA, name).replace("\\", "/")


def main():
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QInputDialog, QDialog

    app = QApplication(sys.argv)
    app.setApplicationName("SmartCrawler")
    app.setOrganizationName("SmartCrawler")

    # ---------- 屏蔽所有阻塞式对话框 ----------
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QInputDialog.getText = staticmethod(lambda *a, **k: ("uitest", True))

    save_paths = {"csv": os.path.join(ROOT, "crawler_data", "exports", "_ui_test.csv"),
                  "json": os.path.join(ROOT, "crawler_data", "exports", "_ui_test.json")}
    cookie_io = {"export": os.path.join(ROOT, "crawler_data", "cookies", "_ui_export.json"),
                 "import": os.path.join(ROOT, "crawler_data", "cookies", "_ui_import.json")}

    # 对话框返回值由测试控制（None 表示沿用调用方给的默认路径）
    dialog = {"save": None, "open": None}
    QFileDialog.getSaveFileName = staticmethod(
        lambda parent=None, title="", d="", filt="": (dialog["save"] or d, filt))
    QFileDialog.getOpenFileName = staticmethod(
        lambda parent=None, title="", d="", filt="": (dialog["open"] or d, filt))

    # 替换「编辑 Cookie」对话框，避免 exec() 阻塞
    import ui.cookie_panel as cp

    class FakeCookieDialog:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def get_data(self):
            return {"name": "ui_ck", "value": "uival", "domain": "example.com",
                    "path": "/", "secure": False, "http_only": False}

    cp.CookieEditDialog = FakeCookieDialog

    from ui.main_window import MainWindow
    from models.field import Field

    win = MainWindow()
    browser = win.browser
    win.show()
    spin(1500)

    # ================= 1. 顶栏与导航 =================
    tb = win.top_bar
    tb.set_url("https://example.com/x")
    check("top_bar.set_url", tb.url_edit.text() == "https://example.com/x")

    tb.set_popup_strategy("remove")
    check("top_bar.set_popup_strategy", tb.popup_combo.currentData() == "remove")

    tb.set_pick_active(True)
    check("top_bar.set_pick_active", tb.btn_pick.isChecked())

    # 真实导航历史：page1 -> page2 -> back -> forward -> reload
    def load_and_wait(url):
        loop = QEventLoop()
        t = QTimer(); t.setSingleShot(True)
        t.timeout.connect(loop.quit)
        browser.page.loadFinished.connect(lambda ok: loop.quit())
        browser.navigate(url)
        t.start(10000)
        loop.exec()
        t.stop()
        spin(150)

    load_and_wait(file_url("page1.html"))
    check("navigate page1", browser.url().endswith("page1.html"), browser.url())
    load_and_wait(file_url("page2.html"))
    check("navigate page2", browser.url().endswith("page2.html"), browser.url())

    check("can_go_back", browser.can_go_back() is True)
    tb.btn_back.click()
    spin(1200)
    check("btn_back clicked", browser.url().endswith("page1.html"), browser.url())

    check("can_go_forward", browser.can_go_forward() is True)
    tb.btn_fwd.click()
    spin(1200)
    check("btn_fwd clicked", browser.url().endswith("page2.html"), browser.url())

    tb.btn_reload.click()
    spin(1200)
    check("btn_reload clicked", browser.url().endswith("page2.html"), browser.url())

    tb.url_edit.setText(file_url("rich.html"))
    got_go = []
    tb.go_requested.connect(got_go.append)
    tb.btn_go.click()
    spin(1500)
    check("btn_go emits go_requested", got_go and got_go[-1].endswith("rich.html"),
          str(got_go))
    check("btn_go navigates", browser.url().endswith("rich.html"), browser.url())

    # ================= 2. 拾取开关 =================
    tb.btn_pick.setChecked(True)
    win._on_pick_toggled(True)
    check("picker enabled", win.crawler.picker.is_active() is True)
    win._on_pick_toggled(False)
    check("picker disabled", win.crawler.picker.is_active() is False)

    # 拾取回调（模拟页面回传）
    win._on_picked(".title", "Item One", "h3", "")
    check("picked applied to selector",
          ".title" in win.left_panel.selector_edit.text(),
          win.left_panel.selector_edit.text())

    # ================= 3. 左侧面板 =================
    lp = win.left_panel

    # 滚动区：窗口再矮也能看到全部配置
    check("left panel is scrollable",
          lp.scroll is not None and lp.scroll.widget() is not None,
          type(lp.scroll).__name__)
    check("left panel widgetResizable", lp.scroll.widgetResizable() is True)
    # 最小尺寸限制，避免控件被挤压
    check("window minimum size set",
          win.minimumWidth() >= 1000 and win.minimumHeight() >= 620,
          f"{win.minimumWidth()}x{win.minimumHeight()}")
    check("initial size fits screen",
          win.width() >= 1000 and win.height() >= 620,
          f"{win.width()}x{win.height()}")

    lp.fields_edit.setPlainText("标题 | .title | text |\n价格 | .price | text |")
    lp.selector_edit.setText(".item")
    lp.set_selected_modes(["records"])           # 单格式
    task = lp.collect_task()
    check("collect_task single mode",
          task.mode == "records" and task.modes == ["records"]
          and len(task.fields) == 2,
          f"modes={task.modes} fields={len(task.fields)}")

    # 多格式复选
    lp.set_selected_modes(["records", "links", "meta"])
    task_multi = lp.collect_task()
    check("collect_task multi modes",
          task_multi.modes == ["records", "links", "meta"]
          and task_multi.mode == "records",
          str(task_multi.modes))
    check("multi modes persisted to prefs",
          win.prefs.last_modes == ["records", "links", "meta"],
          str(win.prefs.last_modes))
    lp.set_selected_modes(["records"])

    # 全选 / 清空选择
    lp.btn_check_all.click()
    check("check all formats", len(lp.selected_modes()) == 20,
          str(len(lp.selected_modes())))
    lp.btn_check_none.click()
    check("clear format selection", lp.selected_modes() == [])
    lp.set_selected_modes(["records"])

    # 反爬 / 下载设置
    lp.stealth_chk.setChecked(False)
    lp.download_spin.setValue(12)
    lp.download_exts_edit.setText("pdf,csv")
    win._on_run_settings()
    check("run settings applied",
          win.browser.stealth_enabled is False
          and win.browser.max_download_mb == 12
          and win.prefs.max_download_mb == 12,
          f"stealth={win.browser.stealth_enabled} limit={win.browser.max_download_mb}")
    check("download exts applied",
          win.browser.allowed_download_exts == {"pdf", "csv"}
          and win.prefs.download_exts == "pdf,csv",
          f"{sorted(win.browser.allowed_download_exts)} / {win.prefs.download_exts!r}")
    check("手改扩展名后预设自动切到「自定义」",
          lp.download_preset() == "custom", lp.download_preset())
    lp.stealth_chk.setChecked(True)
    lp.download_spin.setValue(50)
    win._on_run_settings()
    check("run settings restored",
          win.browser.stealth_enabled is True and win.browser.max_download_mb == 50)

    # ---- 下载格式预设 ----
    lp.set_download_preset("image")
    img_exts = lp.download_exts()
    check("选「仅图片」后扩展名列表被展开",
          "jpg" in img_exts and "png" in img_exts and "mp4" not in img_exts,
          img_exts[:60])
    lp.set_download_preset("video")
    check("选「仅视频」时含流媒体清单 m3u8",
          "m3u8" in lp.download_exts() and "jpg" not in lp.download_exts(),
          lp.download_exts()[:60])
    lp.set_download_preset("media")
    media_exts = lp.download_exts()
    check("选「仅媒体」时三类都在",
          all(e in media_exts for e in ("jpg", "mp4", "mp3", "m3u8")),
          str(len(media_exts.split(","))))
    lp.set_download_preset("all")
    check("选「不限格式」时空串（=允许全部）", lp.download_exts() == "",
          repr(lp.download_exts()))
    # 预设会写进偏好，重开面板能恢复
    lp.set_download_preset("audio")
    lp.collect_task()
    check("下载预设已持久化", win.prefs.download_preset == "audio",
          win.prefs.download_preset)
    lp.set_download_preset("all")

    # ---- 反检测强化总开关 ----
    check("左面板有反检测总开关且默认开", lp.antibot_enabled() is True)
    lp.antibot_chk.setChecked(False)
    win._on_run_settings()
    check("关掉总开关后六项全部失效",
          win.browser.block_trackers is False
          and win.browser.auto_headers is False
          and win.browser.hide_canvas is False
          and win.browser.block_webrtc is False
          and win.crawler.auto_cloudflare is False,
          str(win._antibot_flags()))
    from core import scrapling_engine as _se
    check("总开关也会同步到 Scrapling 层（TLS / 请求头）",
          _se.runtime_options() == {"auto_headers": False, "tls_spoof": False},
          str(_se.runtime_options()))
    lp.antibot_chk.setChecked(True)
    win._on_run_settings()
    check("重新打开总开关后恢复（子项勾选状态没有被抹掉）",
          win.browser.block_trackers is True
          and win.browser.hide_canvas is True
          and _se.runtime_options() == {"auto_headers": True, "tls_spoof": True},
          str(win._antibot_flags()))

    lp.set_running(True)
    check("set_running(True)", not lp.btn_start.isEnabled() and lp.btn_stop.isEnabled())
    lp.set_running(False)
    check("set_running(False)", lp.btn_start.isEnabled())

    lp.btn_stop.click()          # 停止按钮 -> crawler.stop_task()
    lp.btn_clear.click()         # 清空按钮 -> right_panel.clear()
    check("stop/clear buttons ok", True)

    # 未填 URL 时点开始：应弹出提示而不崩溃
    tb.url_edit.setText("")
    lp.btn_start.click()
    check("start without url is safe", True)

    # ---- 停止按钮必须让「开始抓取」重新可用（回归 #7）----
    from models.task import Task
    lp.set_selected_modes(["records"])
    lp.fields_edit.setPlainText("标题 | .title | text |")
    lp.selector_edit.setText(".item")
    stop_task = Task(url=file_url("page1.html"), modes=["records"],
                     selector=".item",
                     fields=Field.parse_block("标题 | .title | text |"),
                     max_pages=1, delay=0.1, autoscroll=False)
    win.crawler.start_task(stop_task)
    spin(200)
    check("start disabled while running",
          not lp.btn_start.isEnabled() and lp.btn_stop.isEnabled(),
          f"start={lp.btn_start.isEnabled()} stop={lp.btn_stop.isEnabled()}")
    win.crawler.stop_task()
    spin(400)
    check("start re-enabled after stop",
          lp.btn_start.isEnabled() and not lp.btn_stop.isEnabled(),
          f"start={lp.btn_start.isEnabled()} stop={lp.btn_stop.isEnabled()}")

    # ================= 4. 右侧面板 =================
    rp = win.right_panel
    rp.append_rows([
        {"标题": "A", "链接": "https://e.com/a", "价格": "1"},
        {"标题": "B", "链接": "https://e.com/b", "价格": "2"},
    ])
    check("append_rows", rp.table.rowCount() == 2, f"rows={rp.table.rowCount()}")

    dialog["save"] = save_paths["csv"]
    rp.export("csv")
    check("export csv", os.path.isfile(save_paths["csv"]), save_paths["csv"])
    dialog["save"] = save_paths["json"]
    rp.export("json")
    check("export json", os.path.isfile(save_paths["json"]), save_paths["json"])
    dialog["save"] = None

    # ---------------- 多格式导出（11 种）----------------
    from utils.exporters import EXPORT_FORMATS

    fmt_paths = {}
    for key, _label, ext in EXPORT_FORMATS:
        p = os.path.join(ROOT, "crawler_data", "exports", f"_ui_fmt.{ext}")
        fmt_paths[key] = p
        rp.export_selected([0, 1], key, path=p)
    check("11 种格式都能从界面导出",
          len(fmt_paths) == 11
          and all(os.path.getsize(p) > 20 for p in fmt_paths.values()),
          ", ".join(sorted(os.path.basename(p) for p in fmt_paths.values())))
    with open(fmt_paths["md"], encoding="utf-8") as fh:
        check("导出的 Markdown 里含数据", "标题" in fh.read())
    quick = rp.export_quick((0,), "jsonl")
    check("快速导出（不弹窗）落到导出目录",
          os.path.isfile(quick) and quick.endswith(".jsonl")
          and open(quick, encoding="utf-8").read().strip().startswith("{"),
          os.path.basename(quick))

    # ---------------- 数据区右键菜单 ----------------
    rp.append_rows([{"标题": "C", "链接": "https://e.com/c",
                     "图片1": "https://cdn.x.com/a/p.jpg"},
                    {"标题": "D", "内联图片": "data:image/png;base64,aGVsbG8="}])
    check("append_rows 带媒体链接的行", rp.table.rowCount() == 4,
          f"rows={rp.table.rowCount()}")

    menu = rp._make_row_menu(0, 0)
    texts = [a.text() for a in menu.actions()]
    sub_actions = [a for a in menu.actions() if a.menu() is not None]
    sub_texts = ([a.text() for a in sub_actions[0].menu().actions()]
                 if sub_actions else [])
    check("右键菜单：复制项齐全",
          any("复制单元格" in t for t in texts)
          and any("复制整行" in t for t in texts)
          and any("复制整列" in t for t in texts)
          and any("复制为 JSON" in t for t in texts), str(texts))
    check("右键菜单：导出此条数据下 11 种格式",
          len(sub_texts) == 11 and any("(*.xlsx)" in t for t in sub_texts),
          str(sub_texts[:3]))
    check("右键菜单：无媒体链接时「导出此条的文件」置灰",
          any("导出此条的文件" in t and not a.isEnabled()
              for a, t in zip(menu.actions(), texts)), str(texts))

    menu2 = rp._make_row_menu(2, 0)
    texts2 = [a.text() for a in menu2.actions()]
    check("右键菜单：有媒体链接时出现「导出此条的文件（1 个）」",
          any("导出此条的文件（1 个）" in t for t in texts2), str(texts2))
    check("右键菜单：单个文件时出现「该文件另存为…」",
          any("另存为" in t for t in texts2), str(texts2))
    check("右键菜单：有链接时提供「在浏览器中打开链接」",
          any("在浏览器中打开链接" in t for t in texts2), str(texts2))
    check("右键菜单：删除此条", any("删除此行" in t for t in texts2), str(texts2))
    rp.table.selectAll()
    menu3 = rp._make_row_menu(0, 0)
    texts3 = [a.text() for a in menu3.actions()]
    check("右键菜单：多选时出现「导出选中行的 N 个文件…」",
          any("导出选中行的" in t for t in texts3)
          and any("删除选中的 4 行" in t for t in texts3), str(texts3))
    rp.table.clearSelection()

    check("单元格/整行/整列取文本",
          rp._cell_text(0, 0) == "A"
          and "A" in rp._row_text(0) and "A" in rp._column_text(0),
          rp._row_text(0)[:40])
    try:
        rp._clipboard("ui clipboard")
        copied = True
    except Exception as e:                                # noqa: BLE001
        copied = False
        print("clipboard:", e, flush=True)
    check("复制到剪贴板不抛异常", copied)

    # ---------------- 导出此条的文件（内联 data: URL，不联网）----------------
    import shutil as _shutil
    file_dir = os.path.join(ROOT, "crawler_data", "exports", "_ui_files")
    _shutil.rmtree(file_dir, ignore_errors=True)
    os.makedirs(file_dir, exist_ok=True)

    def wait_for(pred, ms=5000, step=100):
        waited = 0
        while waited < ms and not pred():
            spin(step)
            waited += step
        return pred()

    old_export_dir = rp.prefs.export_dir
    dlg = rp.export_row_files(3, dest_dir=file_dir, modal=False)
    ok = wait_for(lambda: dlg is not None and dlg.report is not None)
    rep = (dlg.report or {}) if dlg else {}
    import glob as _glob
    inline_files = _glob.glob(os.path.join(file_dir, "inline_*.png"))
    check("数据区导出此条的文件（本地解码，不联网）",
          ok and rep.get("ok") == 1 and len(inline_files) == 1
          and open(inline_files[0], "rb").read() == b"hello",
          str(rep.get("items")))
    check("文件导出对话框回填状态与摘要",
          dlg is not None and dlg.table.item(0, 3).text() == "已下载"
          and "成功 1" in dlg.detail.toPlainText(),
          dlg.detail.toPlainText().splitlines()[1] if dlg else "")

    dlg2 = rp.export_files_all(dest_dir=file_dir, modal=False,
                               rows=[{"内联图片": "data:image/png;base64,aGVsbG8="}])
    wait_for(lambda: dlg2 is not None and dlg2.report is not None)
    check("底部「导出文件…」批量导出",
          dlg2 is not None and (dlg2.report or {}).get("ok") == 1,
          str((dlg2.report or {}).get("items")))

    save_as = os.path.join(file_dir, "saveas.png")
    dlg3 = rp.export_one_file(3, path=save_as, modal=False)
    wait_for(lambda: dlg3 is not None and dlg3.report is not None)
    check("「另存为」按确切路径落盘",
          dlg3 is not None and os.path.isfile(save_as)
          and (dlg3.report or {}).get("items", [{}])[0].get("path") == save_as,
          str((dlg3.report or {}).get("items")))

    rp.prefs.export_dir = old_export_dir
    rp.remove_rows((3,))
    check("删除此行后行数与提示同步", rp.table.rowCount() == 3,
          f"rows={rp.table.rowCount()}")
    rp.remove_rows((2,))

    rp.log("INFO", "ui test log line")
    check("panel log", "ui test log line" in rp.log_view.toPlainText())

    rp.set_task_summary("任务完成 2 条")
    check("task summary", "2 条" in rp.task_view.toPlainText())

    rp.clear()
    check("panel clear", rp.table.rowCount() == 0)

    # ================= 5. Cookie / Profile 面板 =================
    cpanel = rp.cookie_panel
    cm = win.cookie_manager

    cpanel.refresh()
    check("cookie refresh", True)

    cpanel.table.setRowCount(0)
    cpanel._on_add()                       # 使用 FakeCookieDialog
    spin(700)
    names = [c["name"] for c in cm.list_cookies()]
    check("cookie add via UI", "ui_ck" in names, str(names))

    # 选中第一行 -> 编辑 / 删除
    if cpanel.table.rowCount() > 0:
        cpanel.table.selectRow(0)
        cpanel._on_edit()
        spin(500)
    check("cookie edit via UI", "ui_ck" in [c["name"] for c in cm.list_cookies()])

    dialog["save"] = cookie_io["export"]
    cpanel._on_export()
    dialog["save"] = None
    check("cookie export via UI", os.path.isfile(cookie_io["export"]), cookie_io["export"])

    # 准备导入文件
    import json as _json
    with open(cookie_io["import"], "w", encoding="utf-8") as fh:
        _json.dump([{"name": "imp_ck", "value": "v", "domain": "imp.com", "path": "/"}], fh)
    dialog["open"] = cookie_io["import"]
    cpanel._on_import()
    dialog["open"] = None
    spin(700)
    check("cookie import via UI", "imp_ck" in [c["name"] for c in cm.list_cookies()],
          str([c["name"] for c in cm.list_cookies()]))

    if cpanel.table.rowCount() > 0:
        cpanel.table.selectRow(0)
        cpanel._on_delete()
        spin(500)
    check("cookie delete via UI", True)

    cpanel._on_new_profile()               # FakeInputDialog -> "uitest"
    spin(300)
    from core.browser import list_profiles
    check("new profile via UI", "uitest" in list_profiles(), str(list_profiles()))

    # 切换 Profile（走 cookie 集切换）
    cpanel._on_profile_changed("uitest")
    spin(600)
    check("switch profile via UI", browser.profile_name == "uitest", browser.profile_name)
    cpanel._on_profile_changed("default")
    spin(600)
    check("switch back to default", browser.profile_name == "default", browser.profile_name)

    # 设为默认 Profile（需先在组合框中选中目标项）
    idx = cpanel.profile_combo.findText("uitest")
    if idx >= 0:
        cpanel.profile_combo.setCurrentIndex(idx)
    combo_before = cpanel.profile_combo.currentText()
    cpanel._on_set_default()
    items = [cpanel.profile_combo.itemText(i)
             for i in range(cpanel.profile_combo.count())]
    check("set default profile", win.prefs.default_profile == "uitest",
          f"combo_before={combo_before!r} items={items} "
          f"after={win.prefs.default_profile!r} shared={cpanel.prefs is win.prefs}")

    # 删除 Profile（同样先选中）
    idx = cpanel.profile_combo.findText("uitest")
    if idx >= 0:
        cpanel.profile_combo.setCurrentIndex(idx)
    cpanel._on_delete_profile()            # FakeQuestion -> Yes
    spin(300)
    check("delete profile via UI", "uitest" not in list_profiles(), str(list_profiles()))
    win.prefs.default_profile = "default"  # 复位，避免影响后续运行

    cpanel._on_clear_all()
    spin(500)
    check("clear all cookies via UI", cm.list_cookies() == [],
          str(cm.list_cookies()))

    # 清空之后迟到的 cookieAdded（清空前排队的事件）不能把 cookie 复活 ——
    # 这是实测踩到的竞态：切换 Profile 载入一批 cookie 紧接着点清空时，
    # 排队的添加事件会在清空之后送达，界面上表现为「清了又回来」。
    from PySide6.QtCore import QByteArray as _QBA
    from PySide6.QtNetwork import QNetworkCookie as _QNC
    late = _QNC()
    late.setName(_QBA(b"late_ck"))
    late.setValue(_QBA(b"x"))
    late.setDomain(".example.com")
    late.setPath("/")
    cm.clear_all()                     # 明确地在静默窗口内送一次迟到事件
    check("清空后进入静默窗口（清空前排队的添加会被拦住）",
          cm._clearing_now() is True, str(cm._cleared_at))
    cm._on_cookie_added(late)
    check("清空后迟到的 cookieAdded 被忽略（不会复活）",
          cm.list_cookies() == [], str(cm.list_cookies()))

    # ================= 6. 横幅（确认 / 跳过）与全局信号 =================
    banner = win.banner
    banner.show_for("CAPTCHA", "检测到验证码输入框，已确认为验证码")
    check("banner shown", banner.isVisible() and "验证码" in banner.label.text())
    check("banner has skip button", banner.btn_skip is not None
          and banner.btn_skip.text() != "")
    check("confirmed reason hides skip hint", "跳过" not in banner.label.text(),
          banner.label.text()[:60])

    # 疑似场景：横幅应提示可以跳过
    banner.show_for("CAPTCHA", "疑似验证码：命中关键词「验证码」，但未检测到验证码组件。"
                              "若为误判可点击横幅上的「跳过」继续。")
    check("suspected reason hints skip", "跳过" in banner.label.text(),
          banner.label.text()[:80])
    banner.hide_banner()

    # 跳过按钮 -> crawler.skip_human()：立即恢复且本任务内不再因验证暂停
    from models.task import Task as _Task
    win.crawler._task = _Task(url=file_url("rich.html"), modes=["meta"], max_pages=1)
    win.crawler._cancel = False          # 模拟任务正在运行
    win.crawler._set_state("HUMAN_WAIT")
    win.crawler._skip_detection = False
    banner.btn_skip.click()
    spin(300)
    check("skip resumes immediately", win.crawler._state != "HUMAN_WAIT",
          win.crawler._state)
    check("skip disables detection for task",
          win.crawler._skip_detection is True, str(win.crawler._skip_detection))
    check("skip hides banner", not banner.isVisible())
    win.crawler.stop_task()
    spin(200)

    # 新任务应重新启用检测
    win.crawler.start_task(_Task(url=file_url("rich.html"), modes=["meta"], max_pages=1))
    check("new task re-enables detection",
          win.crawler._skip_detection is False, str(win.crawler._skip_detection))
    win.crawler.stop_task()
    spin(300)

    banner.show_for("LOGIN", "登录墙")
    banner.done_clicked.emit()             # -> crawler.on_human_done()
    spin(200)
    banner.hide_banner()
    check("banner hidden", not banner.isVisible())

    s = win.signals
    s.log.emit("INFO", "signal log")
    s.state_changed.emit("EXTRACTING")
    s.page_loaded.emit(True)
    s.human_required.emit("LOGIN", "检测到登录墙")
    check("human_required shows banner", banner.isVisible())
    s.human_cleared.emit()
    s.data_extracted.emit([{"标题": "sig"}])
    s.task_started.emit()
    s.task_finished.emit(5, 1.23)
    s.picked.emit(".sig", "SigText", "div", "https://e.com/s")
    s.popup_found.emit([{"id": "m1", "cls": "modal"}])
    s.popup_closed.emit([{"id": "m1"}])
    s.profile_changed.emit("default")
    spin(300)
    check("global signals handled", True)
    check("status bar updated",
          win.status.currentMessage() != "" if hasattr(win, "status") else True,
          win.status.currentMessage())

    # ================= 7. 中间面板换页 =================
    win.center_panel.set_page(browser.page)
    check("center_panel.set_page", win.center_panel.view.page() is browser.page)

    # ================= 8. 关闭 =================
    win.close()
    spin(300)

    print(f"\n===== UI RESULT: {len(PASS)} passed, {len(FAIL)} failed =====", flush=True)
    if FAIL:
        print("FAILED:", FAIL, flush=True)
        sys.exit(1)
    print("ALL OK", flush=True)


if __name__ == "__main__":
    main()
