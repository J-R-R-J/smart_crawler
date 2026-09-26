# -*- coding: utf-8 -*-
"""Scrapling 融合层测试（core/scrapling_engine.py）。

特点：
  · 解析类能力**完全离线**，不需要网络、不需要 Qt；
  · scrapling 未安装时自动跳过需要它的用例，并额外验证「降级路径」；
  · 唯一联网用例（http_get 真实请求）失败时标记 SKIP 而非 FAIL，
    避免离线环境把测试跑红。

用法（在项目根目录执行）：
    .venv\\Scripts\\python.exe tests\\test_scrapling.py
"""
import logging
import os
import re
import sys
import shutil
import tempfile

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
SKIP = []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")


def skip(name, why=""):
    SKIP.append(name)
    print(f"[SKIP] {name} {why}")


TEST_DB = os.path.join(ROOT, "crawler_data", "test_scrapling_adaptive.db")

HTML_OLD = (
    "<html><head><title>Demo</title></head><body>"
    "<div class='old-card'><h2>Alpha</h2><a href='/a'>la</a>"
    "<img src='/i.png' alt='ia'></div>"
    "<div class='old-card'><h2>Beta</h2><a href='/b'>lb</a>"
    "<img src='/j.png' alt='ib'></div>"
    "</body></html>"
)
# 模拟网站改版：容器 class 完全变了
HTML_NEW = (
    "<html><head><title>Demo</title></head><body>"
    "<div class='brand-new-card'><h2>Alpha</h2><a href='/a'>la</a>"
    "<img src='/i.png' alt='ia'></div>"
    "<div class='brand-new-card'><h2>Beta</h2><a href='/b'>lb</a>"
    "<img src='/j.png' alt='ib'></div>"
    "</body></html>"
)


def _clean_db():
    for suffix in ("", "-wal", "-shm"):
        p = TEST_DB + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


def integration():
    """接入层：Task 字段、引擎选项、左侧面板、偏好记忆、HTML 注入。"""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)

    from config.default_settings import (ENGINE_OPTIONS, ENGINE_LABELS,
                                         DEFAULT_ENGINE, DEFAULT_ADAPTIVE)
    check("ENGINE_OPTIONS 共 4 种引擎", len(ENGINE_OPTIONS) == 4,
          str(len(ENGINE_OPTIONS)))
    check("默认引擎为 browser", DEFAULT_ENGINE == "browser")
    check("默认不开启自适应", DEFAULT_ADAPTIVE is False)
    check("四种引擎标签齐全",
          all(k in ENGINE_LABELS
              for k in ("browser", "http", "stealth", "dynamic")))
    check("首个引擎是 browser", ENGINE_OPTIONS[0][0] == "browser")

    from models.task import Task
    t = Task(url="https://e.com", modes=["text"])
    check("Task 默认 engine=browser", t.engine == "browser", t.engine)
    check("Task 默认 adaptive=False", t.adaptive is False)
    check("Task 默认 engine_timeout=30", float(t.engine_timeout) == 30.0)
    check("合法引擎通过校验",
          Task(url="u", modes=["text"], engine="http").validate() == [])
    errs = Task(url="u", modes=["text"], engine="bogus").validate()
    check("非法引擎被校验拦下", any("引擎" in e for e in errs), str(errs))

    from core.browser import _inject_base
    out_head = _inject_base(
        "<html><head><title>T</title></head><body>x</body></html>",
        "https://e.com")
    check("<base> 注入到 head 之后",
          out_head.startswith('<html><head><base href="https://e.com">'),
          out_head[:60])
    out_nohead = _inject_base("<html><body>x</body></html>", "https://e.com")
    check("<base> 无 head 时自建 head",
          '<head><base href="https://e.com"></head>' in out_nohead,
          out_nohead[:80])
    check("<base> 无 html 时前置",
          _inject_base("plain", "https://e.com")
          .startswith('<base href="https://e.com">'))

    from core.user_prefs import UserPrefs
    from ui.left_panel import LeftPanel
    prefs = UserPrefs()
    saved = (prefs.last_engine, prefs.last_adaptive)
    try:
        prefs.last_engine = "browser"
        prefs.last_adaptive = False
        lp = LeftPanel(prefs)
        check("引擎下拉共 4 项", lp.engine_combo.count() == 4,
              str(lp.engine_combo.count()))
        check("下拉默认选中 browser", lp.engine() == "browser", lp.engine())
        check("默认未勾选自适应", lp.adaptive_enabled() is False)

        lp.set_engine("stealth", True)
        check("set_engine 往返 stealth", lp.engine() == "stealth",
              lp.engine())
        check("set_engine 同步自适应", lp.adaptive_enabled() is True)

        lp.set_engine("http", False)
        check("set_engine 切回 http", lp.engine() == "http", lp.engine())

        task = lp.collect_task()
        check("collect_task 带上 engine", task.engine == "http", task.engine)
        check("collect_task 带上 adaptive", task.adaptive is False)
        check("引擎选择已记忆到偏好", prefs.last_engine == "http",
              prefs.last_engine)
        check("引擎提示文案非空", bool(lp.engine_hint.text()),
              lp.engine_hint.text())
        lp.deleteLater()
    finally:
        prefs.last_engine, prefs.last_adaptive = saved

    prefs.last_engine = "dynamic"
    prefs.last_adaptive = True
    check("偏好 last_engine 往返", prefs.last_engine == "dynamic")
    check("偏好 last_adaptive 往返", prefs.last_adaptive is True)
    prefs.last_engine = "不存在的引擎"
    check("非法引擎值被规整为 browser", prefs.last_engine == "browser",
          prefs.last_engine)
    prefs.last_engine, prefs.last_adaptive = saved

    from PySide6.QtCore import QThread
    from core.crawler import Crawler, _EngineFetcher, _BROWSER_ENGINES
    check("_BROWSER_ENGINES 只含浏览器直连路径",
          set(_BROWSER_ENGINES) == {"browser", ""}, str(_BROWSER_ENGINES))
    check("_EngineFetcher 是 QThread 子类",
          issubclass(_EngineFetcher, QThread))
    for name in ("_start_engine_fetch", "_on_engine_fetched",
                 "_adaptive_extract"):
        check(f"Crawler 具备 {name}", hasattr(Crawler, name))

    from core import scrapling_engine as _se
    saved_state = (_se._tried, _se._module, _se._error)
    try:
        _se._tried, _se._module, _se._error = True, None, "模拟不可用"
        import importlib
        crawler_mod = importlib.import_module("core.crawler")
        check("降级时 Crawler 模块仍可正常引用引擎",
              crawler_mod.scrapling_engine.available() is False)
    finally:
        _se._tried, _se._module, _se._error = saved_state


def run_without_scrapling(se):
    """把引擎按到「scrapling 未安装」状态，验证降级路径。"""
    saved = (se._tried, se._module, se._error)
    try:
        se._tried = True
        se._module = None
        se._error = "模拟：未安装 scrapling"

        check("降级 available() 为 False", se.available() is False)
        check("降级 version() 为空串", se.version() == "")
        check("降级 unavailable_reason 有内容",
              "未安装" in se.unavailable_reason(), se.unavailable_reason())
        check("降级 make_selector 返回 None",
              se.make_selector("<html/>") is None)

        rows = se.extract_records(HTML_OLD, "https://e.com", ".old-card",
                                  _fields())
        check("降级 extract_records 返回空 list", rows == [], str(rows))

        r = se.http_get("https://example.com")
        check("降级 http_get ok=False", r.ok is False)
        check("降级 http_get error 说明原因",
              "不可用" in r.error, r.error)

        r2 = se.stealth_get("https://example.com")
        check("降级 stealth_get ok=False", r2.ok is False)

        check("降级 find_similar 返回空 list",
              se.find_similar(HTML_OLD, "https://e.com", ".old-card") == [])
    finally:
        se._tried, se._module, se._error = saved


def _fields():
    from models.field import Field
    return [
        Field("title", "h2", "text"),
        Field("link", "a", "href"),
        Field("img", "img", "src"),
        Field("alt", "img", "attr", "alt"),
        Field("all", "", "text"),
    ]


def test_no_shadowed_top_level_defs(se):
    """模块顶层不允许出现重名函数（防静默遮蔽）。

    真的踩过：``install_hint`` 被定义了两次，后一个静默覆盖前一个，
    于是新写的「装到外挂目录」提示**永远不会显示**；而当时的测试恰好查的是
    被保留下来的旧函数，所以整个问题表现为「测试全绿、功能没生效」。

    Python 对重名函数既不报错也不警告，只能靠这种守卫拦住。
    """
    import ast

    path = getattr(se, "__file__", "")
    if not path or not os.path.isfile(path):
        skip("顶层重名守卫", "拿不到模块源文件路径")
        return
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)
    names = [n.name for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    dupes = sorted({n for n in names if names.count(n) > 1})
    check("顶层没有重名函数（防止静默遮蔽）", not dupes, str(dupes))


def test_extra_site_packages(se):
    """外挂依赖目录：冻结版靠它加载用户 ``pip --target`` 装进去的包。

    这是「免安装版能不能用非浏览器引擎」的全部依据，所以不只检查函数存在，
    而是**真的往目录里放一个模块，验证它确实能被 import 到** ——
    否则「加了路径」和「路径真的生效」是两回事。

    另外验证文档承诺过的两件事：
      · 外挂目录不存在时无副作用（本测试里它会被自动创建）；
      · 用户已经设了 ``PLAYWRIGHT_BROWSERS_PATH`` 时程序**不覆盖**它。
    """
    import importlib

    d = se.site_packages_dir()
    check("site_packages_dir() 落在 crawler_data 下",
          os.path.basename(os.path.dirname(d)) == "crawler_data", d)
    check("外挂目录已被创建", os.path.isdir(d), d)

    hint = se.site_packages_hint()
    check("site_packages_hint() 用 --target 指向该目录",
          "--target" in hint and d in hint, hint)
    check("site_packages_hint() 与 install_hint() 是两件不同的事",
          se.site_packages_hint() != se.install_hint(),
          "包未装 vs 浏览器未下载")
    # 只装 fetchers：all = ai,shell 会额外拉 mcp / IPython / markdownify
    # （连依赖树约 56 MB），而本项目只用四个引擎，用不到 shell 与 MCP 服务。
    check("site_packages_hint() 装的是 [fetchers] 而不是 [all]",
          "[fetchers]" in hint and "[all]" not in hint, hint)
    check("SCRAPLING_EXTRA 常量就是 fetchers",
          getattr(se, "SCRAPLING_EXTRA", "") == "fetchers",
          repr(getattr(se, "SCRAPLING_EXTRA", None)))

    # 界面提示必须引用「装包」那条。用源码断言是有意的：
    # 调用错函数不会报错，只会显示一段看起来合理、实际误导的提示，
    # 而本测试文件的 integration() 在 scrapling 可用时也不会走到那个分支。
    lp = os.path.join(ROOT, "ui", "left_panel.py")
    if os.path.isfile(lp):
        with open(lp, "r", encoding="utf-8") as fh:
            ui_src = fh.read()
        check("左面板提示用的是 site_packages_hint()（装包那条）",
              "site_packages_hint()" in ui_src)
        check("左面板也用 install_hint()（浏览器未下载那条）",
              "se.install_hint()" in ui_src)
        # 关键不变式：讲「下载浏览器」的 install_hint() **只能**出现在
        # 「包已装好但浏览器没下」那条分支里。它若出现在 browsers_ready()
        # 判断之前，说明又退回到「包都没装却让用户去下载浏览器」的误导文案。
        if "se.install_hint()" in ui_src and "browsers_ready()" in ui_src:
            check("install_hint() 只出现在 browsers_ready() 分支之后",
                  ui_src.index("browsers_ready()") < ui_src.index("se.install_hint()"))
        else:
            check("左面板区分了 browsers_ready() 分支", False,
                  "缺少 browsers_ready() 或 install_hint()")
        check("三种状态分开说明（包未装 / 浏览器未下 / 全就绪）",
              "未检测到 Scrapling" in ui_src
              and "四种引擎均可用" in ui_src
              and "browsers_ready()" in ui_src)

    # **整个界面层**都不许写死 Python 版本号。
    # 上一轮只查了 left_panel.py 里一个具体字符串（"同为 Python 3.13"），
    # 换成别的写法（"Python 3.13"、"3.13），"）就漏掉了 —— 改成扫全部 ui\*.py
    # 的自由文本，任何形如 3.1x 的版本字面量都算违规（版本号只能来自
    # scrapling_engine.python_tag()）。
    ui_dir = os.path.join(ROOT, "ui")
    offenders = []
    if os.path.isdir(ui_dir):
        for fn in sorted(os.listdir(ui_dir)):
            if not fn.endswith(".py"):
                continue
            with open(os.path.join(ui_dir, fn), "r", encoding="utf-8") as fh:
                for no, line in enumerate(fh, 1):
                    if re.search(r"\b3\.1[0-9]\b", line):
                        offenders.append(f"{fn}:{no}: {line.strip()}")
    check("界面层没有写死 Python 版本号（版本一律取自 python_tag()）",
          not offenders, " | ".join(offenders))

    mod_name = "_sc_ext_probe"
    probe = os.path.join(d, mod_name + ".py")
    saved_path = list(sys.path)
    saved_ready = se._path_ready
    saved_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    try:
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("VALUE = 'from-extra-site-packages'\n")
        importlib.invalidate_caches()

        se._path_ready = False            # 允许重新执行一次路径准备
        sys.modules.pop(mod_name, None)
        se._prepare_import_path()

        check("外挂目录已进入 sys.path", d in sys.path)
        module = importlib.import_module(mod_name)
        check("外挂目录里的模块可以真的 import",
              getattr(module, "VALUE", "") == "from-extra-site-packages",
              repr(getattr(module, "VALUE", None)))

        # 已设置的浏览器目录不能被覆盖
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = r"X:\keep-me"
        se._path_ready = False
        se._prepare_import_path()
        check("已设置的 PLAYWRIGHT_BROWSERS_PATH 不被覆盖",
              os.environ.get("PLAYWRIGHT_BROWSERS_PATH") == r"X:\keep-me",
              str(os.environ.get("PLAYWRIGHT_BROWSERS_PATH")))
    finally:
        sys.path[:] = saved_path
        se._path_ready = saved_ready
        sys.modules.pop(mod_name, None)
        if saved_env is None:
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
        else:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = saved_env
        try:
            os.remove(probe)
        except OSError:
            pass
        cache = os.path.join(d, "__pycache__")
        if os.path.isdir(cache):
            for fname in os.listdir(cache):
                if fname.startswith(mod_name + "."):
                    try:
                        os.remove(os.path.join(cache, fname))
                    except OSError:
                        pass


def test_extra_dir_appears_later(se):
    """外挂目录**在程序运行之后**才出现时，也必须被认出来。

    这是真实踩到的缺陷：``_prepare_import_path()`` 原本在第一次调用时无条件
    把 ``_path_ready`` 置真并提前返回。如果那一刻目录还不存在，之后永远
    不会再检查 —— 用户照着界面提示把 scrapling 装进去，程序却一直显示
    「未检测到 Scrapling」，只有重启才行。

    现在改成每次都重新确认目录是否已在 sys.path 里，本用例守住这个行为。
    """
    import shutil
    import tempfile

    saved_ready = se._path_ready
    saved_dir = se.SITE_PACKAGES_DIR
    saved_path = list(sys.path)

    d = os.path.join(tempfile.gettempdir(), "_sc_late_dir")
    try:
        if os.path.isdir(d):
            shutil.rmtree(d)

        # 第一次检查时目录还不存在
        se.SITE_PACKAGES_DIR = d
        se._path_ready = False
        se._prepare_import_path()
        check("目录尚未出现时不加入 sys.path", d not in sys.path)

        # 用户在程序运行期间把它建出来（照提示安装）
        os.makedirs(d, exist_ok=True)

        se._prepare_import_path()
        check("目录后出现后能被加入 sys.path（不再被记忆值卡住）",
              d in sys.path, f"dir_exists={os.path.isdir(d)} in_path={d in sys.path}")
    finally:
        sys.path[:] = saved_path
        se._path_ready = saved_ready
        se.SITE_PACKAGES_DIR = saved_dir
        try:
            shutil.rmtree(d)
        except OSError:
            pass


def test_version_and_browsers(se):
    """版本号与浏览器就绪判断：都必须**从运行环境推导**，不能写死。"""
    tag = se.python_tag()
    check("python_tag() 与当前解释器一致",
          tag == f"{sys.version_info.major}.{sys.version_info.minor}", tag)
    check("python_tag() 形如 X.Y",
          tag.count(".") == 1 and tag.split(".")[0].isdigit(), tag)

    # browsers_ready() 不能抛异常，且与 browsers_dir() 一致
    try:
        ready = se.browsers_ready()
        check("browsers_ready() 返回布尔值", isinstance(ready, bool), repr(ready))
    except Exception as exc:                       # pragma: no cover
        check("browsers_ready() 不抛异常", False, f"{type(exc).__name__}: {exc}")

    # 两个落点：外挂目录下、exe（源码运行即项目根）同级下，都叫 ms-playwright
    dirs = se.browser_drop_dirs()
    check("browser_drop_dirs() 给出两个落点",
          len(dirs) == 2, str(dirs))
    check("两个落点都叫 ms-playwright",
          all(os.path.basename(p) == "ms-playwright" for p in dirs), str(dirs))
    check("第二个落点与 BASE_DIR 同级（免安装版 = exe 同级）",
          os.path.dirname(dirs[1]) == se.BASE_DIR, dirs[1])
    check("第一个落点在外挂依赖目录下",
          os.path.dirname(dirs[0]) == se.SITE_PACKAGES_DIR, dirs[0])

    # install_hint() 必须把「解压浏览器增强包」这条路指出来，
    # 否则免安装版用户只能看到「联网下载 700 MB」这一条路。
    _ih2 = se.install_hint()
    check("install_hint 给出可解压的落点目录",
          "ms-playwright" in _ih2, _ih2.replace("\n", " | "))
    check("install_hint 同时给出 scrapling install 这条路",
          "install" in _ih2, _ih2.replace("\n", " | "))
    check("install_hint 里的落点就是 browser_drop_dirs() 的推荐落点",
          se.browser_drop_dirs()[1] in _ih2, _ih2.replace("\n", " | "))

    # 「联网下载」那条路在**冻结版**必须带 PYTHONPATH。
    # pip install --target 会把控制台脚本放进 <外挂目录>\Scripts\，
    # 脚本启动时 sys.path[0] 是 Scripts\ 那一层，**不含外挂目录**，
    # 于是 from scrapling.cli import main 直接 ModuleNotFoundError ——
    # 程序自己的 sys.path 里有外挂目录，但那是本进程的事，
    # 管不到用户在命令行里新起的进程。上一轮漏了这一条，写成了裸命令。
    saved_frozen = getattr(sys, "frozen", None)
    try:
        sys.frozen = True                       # 伪装成 PyInstaller 冻结版
        frozen_hint = se.install_hint()
        flat = frozen_hint.replace("\n", " | ")
        check("冻结版提示带 PYTHONPATH", "PYTHONPATH" in frozen_hint, flat)
        check("冻结版提示的 PYTHONPATH 指向外挂依赖目录",
              se.site_packages_dir() in frozen_hint, flat)
        check("冻结版提示带 PLAYWRIGHT_BROWSERS_PATH",
              "PLAYWRIGHT_BROWSERS_PATH" in frozen_hint, flat)
        check("冻结版提示里两条 $env: 都在 install 之前出现",
              frozen_hint.index("$env:PYTHONPATH")
              < frozen_hint.index("install"), flat)

        del sys.frozen
        source_hint = se.install_hint()
        check("源码运行的提示不需要 PYTHONPATH",
              "PYTHONPATH" not in source_hint,
              source_hint.replace("\n", " | "))
    finally:
        if saved_frozen is None:
            if hasattr(sys, "frozen"):
                del sys.frozen
        else:
            sys.frozen = saved_frozen

    saved_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    d = os.path.join(tempfile.gettempdir(), "_sc_browsers_probe")
    try:
        # 指向一个不存在的目录 -> 必须判为未就绪
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(d, "nope")
        check("目录不存在时 browsers_ready() 为假", se.browsers_ready() is False)

        # 指向一个空目录 -> 仍然是未就绪（空目录等于没下载）
        os.makedirs(d, exist_ok=True)
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = d
        check("空目录时 browsers_ready() 为假", se.browsers_ready() is False)

        # 目录里只有说明文件（免安装版预置的 ms-playwright 文件夹被丢进一个 txt）
        # -> 仍必须是未就绪。「目录非空即就绪」的旧判定法在这里会谎报
        #    「四种引擎均可用」，正是本用例要守住的那条线。
        with open(os.path.join(d, "把浏览器解压到这里.txt"),
                  "w", encoding="utf-8") as fh:
            fh.write("x")
        check("目录里只有说明文件时 browsers_ready() 为假",
              se.browsers_ready() is False)

        # 只有 chromium 目录、但解压不完整（没有可执行文件）-> 仍是未就绪
        chrome_dir = os.path.join(d, "chromium-1243", "chrome-win64")
        os.makedirs(chrome_dir, exist_ok=True)
        check("只有 chromium 目录、没有 chrome.exe 时仍为假",
              se.browsers_ready() is False)

        # 出现可执行文件 -> 就绪（路径依据 playwright/patchright 1.63.0 的
        # registry 表：chromium-<rev>\\chrome-win64\\chrome.exe）
        with open(os.path.join(chrome_dir, "chrome.exe"),
                  "w", encoding="utf-8") as fh:
            fh.write("x")
        check("chromium 的 chrome.exe 存在时 browsers_ready() 为真",
              se.browsers_ready() is True)

        # headless shell 单独存在也要算就绪（两个浏览器目录任一即可：
        # StealthyFetcher 默认 headless=True，走的就是 headless shell）
        shutil.rmtree(os.path.join(d, "chromium-1243"))
        shell_dir = os.path.join(d, "chromium_headless_shell-1243",
                                 "chrome-headless-shell-win64")
        os.makedirs(shell_dir, exist_ok=True)
        with open(os.path.join(shell_dir, "chrome-headless-shell.exe"),
                  "w", encoding="utf-8") as fh:
            fh.write("x")
        check("headless shell 单独存在时也算就绪", se.browsers_ready() is True)

        # 非 chromium 名字的目录不算（例如 ffmpeg-1011 / winldd-1007）
        shutil.rmtree(os.path.join(d, "chromium_headless_shell-1243"))
        os.makedirs(os.path.join(d, "ffmpeg-1011"), exist_ok=True)
        with open(os.path.join(d, "ffmpeg-1011", "ffmpeg-win64.exe"),
                  "w", encoding="utf-8") as fh:
            fh.write("x")
        check("只有 ffmpeg 之类非浏览器目录时仍为假",
              se.browsers_ready() is False)
        shutil.rmtree(os.path.join(d, "ffmpeg-1011"))
    finally:
        if saved_env is None:
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
        else:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = saved_env
        try:
            shutil.rmtree(d)
        except OSError:
            pass


def test_custom_paths(se):
    """外挂包目录 / 浏览器目录可以被用户自定义（界面上的「④ 引擎文件位置」）。

    为什么必须有：包 + 浏览器合计数百 MB，用户完全可能装在别的盘；
    而 playwright 联网下载默认落在 %LOCALAPPDATA%\\ms-playwright ——
    与其让他搬几百 MB 的文件，不如让程序指过去。这里守住四条：
      1. 设了就生效（目录 / 提示文案 / 落点全都跟着变）；
      2. 恢复默认后一切回到原样，且**旧的 sys.path 条目要撤掉**
         （否则换目录后仍从旧目录导入 —— 这类问题最难查）；
      3. 用户设的环境变量优先级最高（既有不变式，不能因为加了自定义就破坏）；
      4. 浏览器版本表能读到真实依赖的 browsers.json（决定镜像地址与目录名）。
    """
    import shutil
    import tempfile

    saved_path = list(sys.path)
    saved_custom = se.custom_paths()
    saved_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    d = os.path.join(tempfile.gettempdir(), "_sc_custom_paths")
    try:
        os.makedirs(d, exist_ok=True)
        # ---- 1. 设置 ----
        out = se.set_custom_paths(site_packages=d, browsers=d)
        check("set_custom_paths() 回显设置后的快照",
              out.get("site_packages") == d and out.get("browsers") == d, str(out))
        check("site_packages_dir() 用上了自定义目录",
              se.site_packages_dir() == d, se.site_packages_dir())
        check("自定义目录被真的加进 sys.path（不只是记下来）",
              d in sys.path, str([p for p in sys.path if p == d]))
        check("site_packages_hint() 里的路径跟着变",
              d in se.site_packages_hint(), se.site_packages_hint())
        check("浏览器落点跟着自定义目录走",
              se.browser_target_dir() == d, se.browser_target_dir())
        check("浏览器目录来源标记为 custom",
              se.browsers_dir_source() == "custom", se.browsers_dir_source())
        check("browser_drop_dirs() 仍是两个默认落点（不含自定义）",
              len(se.browser_drop_dirs()) == 2
              and se.browser_drop_dirs()[1] != d, str(se.browser_drop_dirs()))

        # ---- 2. 环境变量仍然优先 ----
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = r"X:\env-wins"
        se.set_custom_paths(browsers=d)          # 重新准备一次
        check("用户设的环境变量优先于界面自定义",
              se.browsers_dir() == r"X:\env-wins"
              and se.browsers_dir_source() == "env",
              f"{se.browsers_dir()} / {se.browsers_dir_source()}")
        os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)

        # ---- 3. 恢复默认 ----
        se.set_custom_paths(site_packages="", browsers="")
        check("恢复默认后目录回到内置值",
              se.site_packages_dir() == se.SITE_PACKAGES_DIR,
              se.site_packages_dir())
        check("恢复默认后旧目录已从 sys.path 撤掉",
              d not in sys.path, str([p for p in sys.path if p == d]))
        check("恢复默认后的来源不再是 custom",
              se.browsers_dir_source() != "custom", se.browsers_dir_source())

        # ---- 4. 版本表（镜像地址与目录名都靠它）----
        reg = se.browser_registry()
        check("browser_registry() 给出 chromium 的 revision 与版本号",
              reg["chromium_rev"].isdigit() and reg["chromium_version"].count(".") >= 2,
              str(reg))
        check("版本表优先读真实依赖的 browsers.json（不是只写死常量）",
              reg["source"] != "" and ("browsers.json" in reg["source"]
                                       or "常量" in reg["source"]),
              reg["source"])
        tree = se.browser_tree_text()
        check("目录树里带上了真实 revision 与两个必需 exe",
              f"chromium-{reg['chromium_rev']}" in tree
              and "chrome.exe" in tree and "chrome-headless-shell.exe" in tree,
              tree.splitlines()[1] if len(tree.splitlines()) > 1 else tree)
        check("目录树标明 winldd（依赖校验要用）",
              f"winldd-{reg['winldd_rev']}" in tree, tree)

        # ---- 5. 镜像指引（路线 3）----
        mirror = se.mirror_hint()
        check("镜像指引用的是真实版本号拼出来的地址",
              reg["chromium_version"] in mirror
              and "registry.npmmirror.com/binary.html?path=playwright/builds/cft/"
              in mirror, mirror.splitlines()[2] if len(mirror.splitlines()) > 2 else mirror)
        check("镜像指引给出两个必需的 zip 名",
              "chrome-win64.zip" in mirror
              and "chrome-headless-shell-win64.zip" in mirror)
        check("镜像指引要求建两个标记文件（否则会被当成没装）",
              "INSTALLATION_COMPLETE" in mirror
              and "DEPENDENCIES_VALIDATED" in mirror)
        check("镜像指引提醒 winldd（30 天后依赖校验要用）",
              "winldd" in mirror and "PrintDeps.exe" in mirror)

        dry = se.dry_run_hint()
        check("dry-run 指引含查看命令与默认落点",
              "playwright install --dry-run" in dry
              and se.default_download_dir() in dry, dry.splitlines()[1])
        check("默认落点是 %LOCALAPPDATA%\\ms-playwright",
              se.default_download_dir().replace("\\", "/").endswith("/ms-playwright")
              and "AppData" in se.default_download_dir(),
              se.default_download_dir())
    finally:
        se.set_custom_paths(site_packages=saved_custom.get("site_packages", ""),
                            browsers=saved_custom.get("browsers", ""))
        sys.path[:] = saved_path
        if saved_env is None:
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
        else:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = saved_env
        try:
            shutil.rmtree(d)
        except OSError:
            pass


def test_engine_setup_ui(se):
    """「装依赖 / 装浏览器」的界面指引：复制按钮、设置对话框、用户指南。

    这几处是**同一个契约的四个副本**：左侧提示、复制按钮复制的文本、
    设置对话框里的说明、以及随包分发的《浏览器增强包安装指南》。
    它们讲的必须是同一套路径与命令 —— 以前出过「文档里的路径和代码里的
    不一致」，所以这里把关键字都断言一遍，任一处漂移就会红。
    """
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import (
        QApplication, QGroupBox, QLabel, QPlainTextEdit,
    )

    QApplication.instance() or QApplication(sys.argv)

    from core.user_prefs import UserPrefs
    from ui.left_panel import LeftPanel
    from ui.settings_dialog import SettingsDialog
    from ui.top_bar import TopBar

    # ---- 左侧「复制安装命令」 ----
    lp = LeftPanel(UserPrefs())
    check("左面板有「复制安装命令」按钮",
          lp.copy_hint_btn is not None and lp.copy_hint_btn.text() != "")
    check("复制按钮文案属于三种预期状态之一",
          lp.copy_hint_btn.text() in ("复制安装命令", "无需安装", "已复制"),
          lp.copy_hint_btn.text())
    check("复制内容随三态决定（有 payload 或明确为空）",
          isinstance(lp._copy_payload, str))
    got = lp.copy_engine_command()
    if lp._copy_payload:
        check("点复制后剪贴板拿到同一段命令",
              got is True
              and QGuiApplication.clipboard().text() == lp._copy_payload,
              QGuiApplication.clipboard().text()[:60])
        check("复制后按钮给出反馈",
              lp.copy_hint_btn.text() == "已复制", lp.copy_hint_btn.text())
    else:
        check("无需安装时点复制不做任何事", got is False)
    lp.deleteLater()

    # ---- 左上角「设置」按钮 ----
    tb = TopBar()
    check("顶栏有「设置」按钮", tb.btn_settings is not None)
    check("设置按钮在整条顶栏的最左边（左上角）",
          tb.layout().indexOf(tb.btn_settings) == 0,
          str(tb.layout().indexOf(tb.btn_settings)))
    fired = []
    tb.settings_clicked.connect(lambda: fired.append(1))
    tb.btn_settings.click()
    check("点设置会发 settings_clicked", bool(fired))
    tb.deleteLater()

    # ---- 设置对话框 ----
    dlg = SettingsDialog()
    check("设置对话框标题含「设置」", "设置" in dlg.windowTitle(),
          dlg.windowTitle())
    titles = [g.title() for g in dlg.findChildren(QGroupBox)]
    check("对话框同时给出两条安装路线",
          any("路线 1" in t for t in titles) and any("路线 2" in t for t in titles),
          str(titles))
    text = "\n".join(w.text() for w in dlg.findChildren(QLabel))
    text += "\n" + "\n".join(b.toPlainText() for b in dlg.findChildren(QPlainTextEdit))
    text += "\n" + "\n".join(titles)
    for key in ("chromium-1243", "chrome-headless-shell.exe",
                "判据", "PYTHONPATH", "注意事项", "INSTALLATION_COMPLETE",
                "153.0.8010.12", "npmmirror"):
        check(f"对话框写明 {key}", key in text)
    check("对话框给出三条安装路线（含国内镜像）",
          any("路线 1" in t for t in titles) and any("路线 2" in t for t in titles)
          and any("路线 3" in t for t in titles), str(titles))
    check("对话框有「引擎文件位置」分组（可自定义两个目录）",
          any("引擎文件位置" in t for t in titles), str(titles))
    check("对话框写明联网下载的默认落点是用户目录（不用搬文件）",
          se.default_download_dir() in "\n".join(
              w.text() for w in dlg.findChildren(QLabel)))
    check("命令框含 dry-run 查看命令（版本号与落点都从它来）",
          "--dry-run" in dlg.box_dryrun.toPlainText())
    check("路线 3 文本给出镜像地址与版本号",
          "registry.npmmirror.com" in dlg.box_route3.toPlainText()
          and se.browser_registry()["chromium_version"]
          in dlg.box_route3.toPlainText())
    check("对话框的命令框含 pip --target 命令",
          "--target" in dlg.box_route2.toPlainText())
    check("对话框给出复制命令的动作", dlg.copy_command() is True)
    check("复制的是当前该用的那段命令",
          QGuiApplication.clipboard().text() == dlg._command)
    check("对话框有「打开浏览器目录」「打开外挂依赖目录」两个动作",
          dlg.btn_open_browsers.isEnabled() and dlg.btn_open_pkgs.isEnabled())
    dlg.deleteLater()

    # ---- 设置窗口里的「反检测强化」分组 ----
    prefs2 = UserPrefs()
    calls = []
    dlg2 = SettingsDialog(prefs=prefs2, apply_cb=lambda: calls.append(1))
    titles2 = [g.title() for g in dlg2.findChildren(QGroupBox)]
    check("设置窗口第一组是「反检测强化」",
          any("反检测强化" in t for t in titles2), str(titles2))
    from config.default_settings import ANTIBOT_ITEMS
    check("六个子项全部出现在窗口里",
          all(key in dlg2._boxes for key, _l, _h in ANTIBOT_ITEMS),
          str(sorted(dlg2._boxes)))
    check("每个子项都有说明（不是光秃秃一个勾选框）",
          all(box.toolTip() for box in dlg2._boxes.values()))
    check("还有「拦截可见广告素材」这一项（默认关）",
          dlg2.chk_creatives is not None
          and prefs2.block_ad_creatives is False)
    # 改一项：要写进偏好并回调外部应用
    old = prefs2.hide_canvas
    dlg2._boxes["hide_canvas"].setChecked(not old)
    check("改子项会写偏好并触发应用回调",
          prefs2.hide_canvas is (not old) and bool(calls),
          f"prefs={prefs2.hide_canvas} calls={len(calls)}")
    prefs2.hide_canvas = old
    # 总开关关掉后子项置灰（避免给出「勾了也不生效」的开关）
    dlg2.chk_master.setChecked(False)
    check("总开关关掉后子项全部置灰",
          all(not b.isEnabled() for b in dlg2._boxes.values())
          and not dlg2.chk_creatives.isEnabled())
    dlg2.chk_master.setChecked(True)
    check("总开关重新打开后子项恢复可用",
          all(b.isEnabled() for b in dlg2._boxes.values()))
    check("总开关状态也持久化", prefs2.antibot_enabled is True)

    # ---- 设置窗口里的「引擎文件位置」：真的会写偏好 + 同步到融合层 ----
    check("路径框存在且默认留空（= 用默认位置）",
          dlg2.edit_pkgs.text() == "" and dlg2.edit_browsers.text() == "")
    import shutil as _sh
    import tempfile as _tf
    tmp_dir = os.path.join(_tf.gettempdir(), "_sc_ui_paths")
    _sh.rmtree(tmp_dir, ignore_errors=True)
    os.makedirs(tmp_dir, exist_ok=True)
    try:
        dlg2._set_path("pkgs", tmp_dir)
        check("选完目录：写进偏好",
              prefs2.site_packages_path == tmp_dir, prefs2.site_packages_path)
        check("选完目录：融合层立即生效（不用重启）",
              se.site_packages_dir() == tmp_dir, se.site_packages_dir())
        check("选完目录：路径框回填",
              dlg2.edit_pkgs.text() == tmp_dir, dlg2.edit_pkgs.text())
        dlg2._set_path("browsers", tmp_dir)
        check("浏览器目录同理",
              prefs2.browsers_path == tmp_dir
              and se.browser_target_dir() == tmp_dir,
              f"{prefs2.browsers_path} / {se.browser_target_dir()}")
        check("浏览器目录生效后状态区说明来源（自定义）",
              "自定义" in dlg2.lbl_path_note.text()
              or "自定义" in dlg2.lbl_dir.text(),
              dlg2.lbl_path_note.text() or dlg2.lbl_dir.text())
        dlg2._set_path("pkgs", "")
        dlg2._set_path("browsers", "")
        check("「恢复默认」清空偏好并回到内置目录",
              prefs2.site_packages_path == ""
              and prefs2.browsers_path == ""
              and se.site_packages_dir() == se.SITE_PACKAGES_DIR,
              f"{prefs2.site_packages_path!r} / {se.site_packages_dir()}")
    finally:
        _sh.rmtree(tmp_dir, ignore_errors=True)
    dlg2.deleteLater()

    # ---- 左面板：反检测总开关 + 下载格式预设 ----
    check("左面板有反检测总开关", lp.antibot_chk is not None
          and lp.antibot_enabled() in (True, False))
    check("左面板有「反检测详细设置」入口",
          lp.btn_antibot is not None and lp.btn_antibot.text() != "")
    fired2 = []
    lp.antibot_settings_clicked.connect(lambda: fired2.append(1))
    lp.btn_antibot.click()
    check("点它会请求打开设置窗口", bool(fired2))
    check("左面板有下载格式预设下拉", lp.preset_combo is not None
          and lp.preset_combo.count() >= 6, str(lp.preset_combo.count()))
    lp.set_download_preset("media")
    check("预设展开成完整媒体扩展名（含 m3u8）",
          "m3u8" in lp.download_exts() and "mp3" in lp.download_exts(),
          lp.download_exts()[:50])
    lp.set_download_preset("all")

    # ---- 随包分发的用户指南 ----
    guide = os.path.join(ROOT, "浏览器增强包安装指南.md")
    check("用户指南在仓库根目录", os.path.isfile(guide), guide)
    if os.path.isfile(guide):
        with open(guide, "r", encoding="utf-8") as fh:
            doc = fh.read()
        for key in ("chromium-1243", "chrome-headless-shell-win64",
                    "INSTALLATION_COMPLETE", "PYTHONPATH",
                    "scrapling[fetchers]", "--python", "winldd-1007"):
            check(f"指南含关键点 {key}", key in doc)
        check("指南里没有 scrapling[all] 的安装指引",
              "scrapling[all]" not in doc)
        check("指南说明了 3.13 是免安装版的 ABI 约束",
              "3.13" in doc and "ABI" in doc)


def main():
    from core import scrapling_engine as se

    # ---- 1. 模块自身（不依赖 scrapling 是否安装）----
    check("模块可导入", se is not None)
    check("ADAPTIVE_DB 落在 crawler_data 下",
          os.path.basename(os.path.dirname(se.ADAPTIVE_DB)) == "crawler_data",
          se.ADAPTIVE_DB)
    check("默认相似度阈值为 40", se.DEFAULT_PERCENTAGE == 40)
    check("FetchResult 默认值",
          se.FetchResult().ok is False and se.FetchResult().length == 0)
    check("FetchResult.length 反映 html 长度",
          se.FetchResult(html="abc").length == 3)
    _ih = se.install_hint()
    check("install_hint 指向 scrapling 的 install 子命令",
          "install" in _ih and "scrapling" in _ih.lower(), _ih.replace("\n", " | "))
    # scrapling 包里没有 __main__.py，`python -m scrapling install` 会直接报
    # "No module named scrapling.__main__"（实测）。这条守住别退回去。
    check("install_hint 不教用户用 python -m scrapling",
          "-m scrapling" not in _ih)

    # 顶层重名守卫 + 外挂依赖目录（都不依赖 scrapling 是否安装）
    test_no_shadowed_top_level_defs(se)
    test_extra_site_packages(se)
    test_extra_dir_appears_later(se)
    test_version_and_browsers(se)
    test_custom_paths(se)

    # ---- 超时单位（浏览器引擎是毫秒，HTTP 是秒）----
    check("seconds_to_ms: 90 → 90000", se.seconds_to_ms(90) == 90000,
          str(se.seconds_to_ms(90)))
    check("seconds_to_ms: 60 → 60000", se.seconds_to_ms(60) == 60000)
    check("seconds_to_ms 下限 30s", se.seconds_to_ms(1) == 30000,
          str(se.seconds_to_ms(1)))
    check("seconds_to_ms: 0 → 下限", se.seconds_to_ms(0) == 30000)
    check("seconds_to_ms: 负数 → 下限", se.seconds_to_ms(-5) == 30000)
    check("seconds_to_ms: 非法值 → 下限", se.seconds_to_ms("abc") == 30000)
    check("seconds_to_ms: None → 下限", se.seconds_to_ms(None) == 30000)
    check("seconds_to_ms 可自定义下限",
          se.seconds_to_ms(0.5, floor_s=0.1) == 500,
          str(se.seconds_to_ms(0.5, floor_s=0.1)))

    fr = se.FetchResult(ok=True, url="u", status=200, html="<html/>",
                        text="t", title="T", engine="http")
    check("FetchResult 字段完整",
          fr.ok and fr.status == 200 and fr.engine == "http" and fr.title == "T")

    # ---- 2. 未安装时的降级路径（先测，与是否真装无关）----
    run_without_scrapling(se)

    # ---- 3. 接入层（Task / 左面板 / 偏好 / HTML 注入）----
    integration()

    # ---- 3b. 安装指引的界面部分与用户指南 ----
    test_engine_setup_ui(se)

    # ---- 4. 需要 scrapling 的用例 ----
    if not se.available():
        skip("scrapling 解析用例", f"原因：{se.unavailable_reason()}")
        _summary()
        return

    check("available() 为 True", se.available() is True)
    check("version() 非空", bool(se.version()), se.version())

    from models.field import Field

    # make_selector
    page = se.make_selector(HTML_OLD, "https://e.com")
    check("make_selector 可用", page is not None)
    check("make_selector 能取标题",
          page.css("title::text").get() == "Demo")

    # 基础提取：text / href / src / attr / 全文本
    rows = se.extract_records(HTML_OLD, "https://e.com", ".old-card", _fields())
    check("extract_records 命中 2 条", len(rows) == 2, str(rows))
    if len(rows) == 2:
        r0 = rows[0]
        check("字段 text（h2）", r0.get("title") == "Alpha", repr(r0.get("title")))
        check("字段 href", r0.get("link") == "/a", repr(r0.get("link")))
        check("字段 src", r0.get("img") == "/i.png", repr(r0.get("img")))
        check("字段 attr（alt）", r0.get("alt") == "ia", repr(r0.get("alt")))
        check("空选择器 → 整块文本",
              "Alpha" in str(r0.get("all", "")), repr(r0.get("all")))
        check("第二条正确", rows[1].get("title") == "Beta")

    # 高级选择器语法
    check("::text 语法",
          se.make_selector(HTML_OLD).css("h2::text").getall() == ["Alpha", "Beta"])
    check("::attr 语法",
          se.make_selector(HTML_OLD).css("a::attr(href)").getall() == ["/a", "/b"])
    adv = [Field("t", "h2::text", "text")]
    rows_adv = se.extract_records(HTML_OLD, "https://e.com", ".old-card", adv)
    check("字段选择器直接用 ::text",
          [r["t"] for r in rows_adv] == ["Alpha", "Beta"], str(rows_adv))

    # html 类型字段
    rows_html = se.extract_records(HTML_OLD, "https://e.com", ".old-card",
                                   [Field("raw", "h2", "html")])
    check("html 类型字段含标签",
          "<h2>" in rows_html[0]["raw"], repr(rows_html[0]["raw"])[:60])

    # ---- 4. 自适应 / 网站改版自愈（核心卖点）----
    _clean_db()
    try:
        saved_rows = se.extract_records(HTML_OLD, "https://e.com", ".old-card",
                                        _fields(), adaptive=True,
                                        auto_save=True, db_path=TEST_DB)
        check("自适应：首次 auto_save 命中 2 条",
              len(saved_rows) == 2, str(saved_rows))
        check("自适应：特征库已落盘", os.path.exists(TEST_DB), TEST_DB)

        gone = se.extract_records(HTML_NEW, "https://e.com", ".old-card",
                                  _fields(), db_path=TEST_DB)
        check("改版后：不开 adaptive 找不到（0 条）", gone == [], str(gone))

        healed = se.extract_records(HTML_NEW, "https://e.com", ".old-card",
                                    _fields(), adaptive=True, db_path=TEST_DB,
                                    identifier=".old-card")
        check("改版后：adaptive 自愈找回 2 条",
              len(healed) == 2, str(healed))
        if len(healed) == 2:
            check("自愈后数据正确",
                  healed[0].get("title") == "Alpha"
                  and healed[1].get("title") == "Beta", str(healed))
    finally:
        _clean_db()

    # ---- 5. find_similar ----
    sim = se.find_similar(HTML_OLD, "https://e.com", ".old-card")
    check("find_similar 返回选择器列表",
          isinstance(sim, list) and len(sim) >= 1, str(sim))
    check("find_similar 结果非空串",
          all(isinstance(x, str) and x for x in sim), str(sim))

    # ---- 6. 异常输入不应抛 ----
    check("空容器选择器 → 空 list",
          se.extract_records(HTML_OLD, "https://e.com", "", _fields()) == [])
    check("空 HTML → 空 list",
          se.extract_records("", "https://e.com", ".old-card", _fields()) == [])
    check("死选择器 → 空 list",
          se.extract_records(HTML_OLD, "https://e.com", ".nope", _fields()) == [])
    check("fields 为空 → 返回空 dict 行",
          se.extract_records(HTML_OLD, "https://e.com", ".old-card", [])
          == [{}, {}])
    check("字段选择器无效不抛异常",
          se.extract_records(HTML_OLD, "https://e.com", ".old-card",
                             [Field("bad", ">>>", "text")]) is not None)

    # ---- 7. 运行期开关：真实请求头 / TLS 指纹档案 ----
    from core import headers as H

    check("运行期开关默认全开",
          se.runtime_options() == {"auto_headers": True, "tls_spoof": True},
          str(se.runtime_options()))
    gen = se.headers_for("https://example.com/a", referer="https://www.google.com/")
    check("headers_for 给出整套自洽请求头",
          bool(gen) and H.consistency_issues(gen.get("User-Agent", ""), gen) == [],
          str(sorted(gen))[:120])
    check("Referer 与 Sec-Fetch-Site 对得上（不会一个说来自 Google、一个说 none）",
          gen.get("Sec-Fetch-Site") == "cross-site" and gen.get("Referer"),
          str(gen.get("Sec-Fetch-Site")))
    check("无 Referer 时 Sec-Fetch-Site=none",
          se.headers_for("https://example.com/a").get("Sec-Fetch-Site") == "none")
    se.set_runtime_options(auto_headers=False)
    check("关掉真实请求头后 headers_for 返回空（不半途而废）",
          se.headers_for("https://example.com/a") == {}
          and se.browser_identity() == {}, str(se.headers_for("https://e.com")))
    se.set_runtime_options(auto_headers=True)

    ident = se.browser_identity()
    check("浏览器引擎的地区身份成对给出（locale + 时区）",
          ident.get("locale") == H.locale()
          and ident.get("timezone_id") == H.timezone_id(),
          str(ident))
    check("locale 与 Accept-Language 同源（不会一个中文一个英文）",
          H.accept_language().startswith(H.locale().split("-")[0]),
          f"{H.locale()} / {H.accept_language()}")
    check("时区与 locale 匹配（中文环境不是 UTC）",
          H.timezone_id() == "Asia/Shanghai" or os.environ.get(
              "SMARTCRAWLER_TIMEZONE"), H.timezone_id())

    tls = H.tls_profile()
    if tls["available"]:
        check("TLS 档位与 UA 版本接近（不是随手挑一个）",
              tls["target"].startswith("chrome")
              and abs(int("".join(c for c in tls["target"] if c.isdigit()))
                      - H.chrome_major()) <= 8,
              str(tls))
        check("TLS 档位来自 curl_cffi 的真实可选列表（没有写死）",
              tls["target"] in H.impersonate_targets(), str(tls))
    else:
        skip("TLS 档位检查", "curl_cffi 不可用")

    # ---- 8. Scrapling 噪声日志被压掉 ----
    check("噪声过滤器已安装（'No Cloudflare challenge found.' 不再当 ERROR）",
          any(isinstance(f, se._ScraplingNoiseFilter)
              for f in logging.getLogger("scrapling").filters),
          str(logging.getLogger("scrapling").filters))
    check("cloudflare_noise_count 可读", isinstance(se.cloudflare_noise_count(), int))

    # ---- 9. 联网用例（失败记 SKIP，不算 FAIL）----
    try:
        res = se.http_get("https://example.com", timeout=25)
        if not res.ok:
            skip("http_get 真实请求", f"原因：{res.error[:80]}")
        else:
            check("http_get 状态 200", res.status == 200, str(res.status))
            check("http_get 有 HTML", res.length > 100, str(res.length))
            check("http_get 能解析标题",
                  "Example" in (res.title or ""), repr(res.title))
            check("http_get 返回纯文本", bool(res.text), repr(res.text[:40]))
            check("http_get engine 标记为 http", res.engine == "http")

        bad = se.http_get("https://this-domain-does-not-exist-xyz.invalid/",
                          timeout=8)
        check("无效域名 → ok=False 且带 error",
              bad.ok is False and bool(bad.error), bad.error[:80])
    except Exception as e:                               # pragma: no cover
        skip("http_get 真实请求", f"异常：{type(e).__name__}: {e}")

    _summary()


def _summary():
    total = len(PASS) + len(FAIL)
    print()
    print("=" * 58)
    print(f"test_scrapling: {len(PASS)} passed, {len(FAIL)} failed, "
          f"{len(SKIP)} skipped  (共 {total} 项断言)")
    if FAIL:
        print("失败项：")
        for name in FAIL:
            print(f"  · {name}")
    print("=" * 58)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
