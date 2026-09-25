# -*- coding: utf-8 -*-
"""打包相关的一致性校验（防漂移）。

`packaging/` 是本机维护、不入库的打包工具链，因此：

- 文件不存在时**直接跳过**（在 CI 或协作者的机器上不会因此失败）；
- 文件存在时把「以后容易改歪」的地方全部钉死：
    1. 属性文件能被 PyInstaller 的读法（eval + VSVersionInfo 等替身类）解析
    2. FileVersion / ProductVersion 与 config.APP_VERSION 一致（四段式）
    3. filevers / prodvers 数字版本与字符串版本一致
    4. OriginalFilename / InternalName 与 spec 里的 APP_NAME 一致
    5. LegalCopyright 与 LICENSE 对得上
    6. Comments 里的仓库地址与 README 中的地址一致
    7. 中英文两张字符串表的字段名必须一致（漏翻字段会被抓出来）
"""

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))   # tests/
ROOT = os.path.dirname(HERE)                        # 项目根目录
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SPEC_PATH = os.path.join(ROOT, "packaging", "SmartCrawler.spec")
VERSION_INFO_PATH = os.path.join(ROOT, "packaging", "version_info.txt")
LICENSE_PATH = os.path.join(ROOT, "LICENSE")
README_PATH = os.path.join(ROOT, "README.md")

REQUIRED_FIELDS = (
    "CompanyName", "FileDescription", "FileVersion", "InternalName",
    "LegalCopyright", "OriginalFilename", "ProductName",
    "ProductVersion", "Comments",
)


# ----------------------------------------------------------------------
# 替身类：PyInstaller 读取 --version-file 时就是提供这些名字后 exec 文件内容
# ----------------------------------------------------------------------
class _Stub(object):
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


_STUB_NS = {
    "VSVersionInfo": _Stub,
    "FixedFileInfo": _Stub,
    "StringFileInfo": _Stub,
    "StringTable": _Stub,
    "StringStruct": _Stub,
    "VarFileInfo": _Stub,
    "VarStruct": _Stub,
}


def load_version_info(path):
    """解析 version_info.txt，返回 (fixed_file_info, {表键: {字段: 值}})。

    注意用 eval 而不是 exec：该文件是一个**裸表达式**（VSVersionInfo(...)），
    exec 会把结果丢掉。PyInstaller 读 --version-file 也正是 eval 语义。
    """
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    ns = dict(_STUB_NS)
    info = eval(compile(source, path, "eval"), ns)   # noqa: S307 - 本机自有文件

    ffi = info.kwargs.get("ffi")
    kids = info.kwargs.get("kids") or []
    string_file_info = kids[0]
    tables = {}
    for table in string_file_info.args[0]:
        key = table.args[0]
        tables[key] = {s.args[0]: s.args[1] for s in table.args[1]}
    return ffi, tables


def read_spec_app_name(path):
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r'^APP_NAME\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else None


def read_repo_url():
    """从 README 里取仓库地址（工作区没有 .git，不能用 git remote）。"""
    if not os.path.isfile(README_PATH):
        return None
    with open(README_PATH, "r", encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"https://github\.com/[\w.\-]+/[\w.\-]+", text)
    return m.group(0).rstrip(".") if m else None


def read_license_copyright():
    if not os.path.isfile(LICENSE_PATH):
        return None
    with open(LICENSE_PATH, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.lower().startswith("copyright"):
                return line.strip()
    return None


class PackagingTests(unittest.TestCase):

    def setUp(self):
        if not os.path.isfile(VERSION_INFO_PATH):
            self.skipTest("packaging/version_info.txt 不存在（本机维护文件，不入库）")
        self.ffi, self.tables = load_version_info(VERSION_INFO_PATH)
        self.app_version = self._app_version()

    @staticmethod
    def _app_version():
        from config.constants import APP_VERSION
        return APP_VERSION

    # ------------------------------------------------------------------
    def test_parses_with_pyinstaller_stub(self):
        """能被 PyInstaller 的读法解析（字段名写错会在这里炸）。"""
        self.assertTrue(self.tables, "没有解析出任何字符串表")
        self.assertIn("080404B0", self.tables, "缺少中文（简体）字符串表")
        self.assertIn("040904B0", self.tables, "缺少英文（美国）字符串表")

    def test_version_matches_app_version(self):
        """FileVersion / ProductVersion 前三段与 config.APP_VERSION 一致。"""
        for key in ("080404B0", "040904B0"):
            table = self.tables[key]
            for field in ("FileVersion", "ProductVersion"):
                value = table[field]
                self.assertTrue(
                    value.startswith(self.app_version + "."),
                    f"{key} 的 {field}={value!r} 与 APP_VERSION="
                    f"{self.app_version!r} 不一致")

    def test_numeric_version_matches_string_version(self):
        """filevers / prodvers 数字版本必须与字符串版本一致。"""
        parts = tuple(int(x) for x in (self.app_version + ".0").split(".")[:4])
        self.assertEqual(tuple(self.ffi.kwargs["filevers"]), parts)
        self.assertEqual(tuple(self.ffi.kwargs["prodvers"]), parts)
        for key in ("080404B0", "040904B0"):
            expect = ".".join(str(p) for p in parts)
            self.assertEqual(self.tables[key]["FileVersion"], expect)
            self.assertEqual(self.tables[key]["ProductVersion"], expect)

    def test_file_names_match_spec(self):
        """OriginalFilename / InternalName 必须与 spec 里的 APP_NAME 一致。"""
        if not os.path.isfile(SPEC_PATH):
            self.skipTest("packaging/SmartCrawler.spec 不存在")
        app_name = read_spec_app_name(SPEC_PATH)
        self.assertIsNotNone(app_name, "未能从 spec 中解析出 APP_NAME")
        for key in ("080404B0", "040904B0"):
            table = self.tables[key]
            self.assertEqual(table["InternalName"], app_name)
            self.assertEqual(table["OriginalFilename"], app_name + ".exe")

    def test_copyright_matches_license(self):
        """LegalCopyright 必须与 LICENSE 对得上。"""
        lic = read_license_copyright()
        if not lic:
            self.skipTest("LICENSE 中未找到 Copyright 行")
        for key in ("080404B0", "040904B0"):
            self.assertEqual(self.tables[key]["LegalCopyright"], lic)

    def test_comments_points_to_repo(self):
        """Comments 里的仓库地址必须与 README 中的一致。"""
        url = read_repo_url()
        if not url:
            self.skipTest("未能从 README 中解析出仓库地址")
        for key in ("080404B0", "040904B0"):
            self.assertIn(url, self.tables[key]["Comments"])

    def test_all_required_fields_present(self):
        """必需字段齐全，且中英文两张表字段名完全一致。"""
        for key in ("080404B0", "040904B0"):
            missing = [f for f in REQUIRED_FIELDS if f not in self.tables[key]]
            self.assertEqual(missing, [], f"{key} 缺少字段：{missing}")
        self.assertEqual(set(self.tables["080404B0"]),
                         set(self.tables["040904B0"]),
                         "中英文两张表的字段名不一致")

    def test_spec_excludes_unused_qt_modules(self):
        """spec 必须保留项目真正用到的 7 个 Qt 模块，并排除其余模块。"""
        if not os.path.isfile(SPEC_PATH):
            self.skipTest("spec 不存在")
        with open(SPEC_PATH, "r", encoding="utf-8") as fh:
            text = fh.read()
        for mod in ("QtCore", "QtGui", "QtWidgets", "QtNetwork",
                    "QtWebChannel", "QtWebEngineCore", "QtWebEngineWidgets"):
            self.assertIn(f'"{mod}"', text, f"spec 里未声明保留 {mod}")
        # 排除逻辑必须是「动态扫描 + 白名单」而不是硬编码全部模块名
        self.assertIn("KEEP_QT", text)
        self.assertIn("glob.glob", text)


# ----------------------------------------------------------------------
#  执行 spec，验证过滤逻辑本身（这是最容易写错、又最难在打包时发现的地方）
# ----------------------------------------------------------------------
class _SpecStub(object):
    """替身：让 spec 里 Analysis / PYZ / EXE / COLLECT 的调用能跑完。"""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.datas = []
        self.binaries = []
        self.scripts = []
        self.pure = []
        self.zipfiles = []
        self.zipped_data = []

    def __getattr__(self, name):          # 其它属性一律当空列表
        return []


def load_spec(path):
    """执行 spec 文件，返回它命名空间里的符号（含 _drop_data / _drop_binary）。"""
    ns = {
        "SPEC": path,
        "__file__": path,
        "__name__": "smartcrawler_spec",
        "Analysis": _SpecStub,
        "PYZ": _SpecStub,
        "EXE": _SpecStub,
        "COLLECT": _SpecStub,
        "BUNDLE": _SpecStub,
    }
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    exec(compile(source, path, "exec"), ns)   # noqa: S102 - 本机自有文件
    return ns


class SpecFilterTests(unittest.TestCase):
    """验证「排除无关库」的判定逻辑，避免误删必需资源或漏删大文件。"""

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(SPEC_PATH):
            raise unittest.SkipTest("packaging/SmartCrawler.spec 不存在")
        try:
            cls.ns = load_spec(SPEC_PATH)
        except ImportError as e:          # 未安装 PySide6 时跳过
            raise unittest.SkipTest(f"无法执行 spec：{e}")

    # ---- 数据文件 ----
    def test_drops_debug_resources(self):
        drop = self.ns["_drop_data"]
        for name in ("PySide6/resources/qtwebengine_devtools_resources.debug.pak",
                     "PySide6/resources/qtwebengine_resources.debug.pak",
                     "PySide6/resources/v8_context_snapshot.debug.bin"):
            self.assertTrue(drop((name, name, "DATA")), f"应剔除：{name}")

    def test_keeps_webengine_runtime_resources(self):
        drop = self.ns["_drop_data"]
        for name in ("PySide6/resources/qtwebengine_resources.pak",
                     "PySide6/resources/icudtl.dat",
                     "PySide6/resources/v8_context_snapshot.bin",
                     "PySide6/resources/qtwebengine_resources_100p.pak"):
            self.assertFalse(drop((name, name, "DATA")),
                             f"必须保留（缺了浏览器起不来）：{name}")

    def test_drops_development_dirs(self):
        drop = self.ns["_drop_data"]
        for name in ("PySide6/metatypes/pyside6_metatypes.json",
                     "PySide6/include/QtCore/qcoreapplication.h",
                     "PySide6/typesystems/typesystem_core.xml",
                     "PySide6/qml/QtQuick/Controls/qmldir"):
            self.assertTrue(drop((name, name, "DATA")), f"应剔除：{name}")

    def test_locale_filter_keeps_chinese_and_english(self):
        drop = self.ns["_drop_data"]
        for name in ("PySide6/translations/qtwebengine_locales/zh-CN.pak",
                     "PySide6/translations/qtwebengine_locales/en-US.pak",
                     "PySide6/translations/qt_zh_CN.qm",
                     "PySide6/translations/qt_en.qm"):
            self.assertFalse(drop((name, name, "DATA")),
                             f"中英翻译必须保留：{name}")

    def test_locale_filter_drops_others(self):
        """关键回归：路径里的 qtwebengine 含 'en'，不能因此把所有语言都留下。"""
        drop = self.ns["_drop_data"]
        for name in ("PySide6/translations/qtwebengine_locales/fr.pak",
                     "PySide6/translations/qtwebengine_locales/de.pak",
                     "PySide6/translations/qtwebengine_locales/ja.pak",
                     "PySide6/translations/qt_fr.qm"):
            self.assertTrue(drop((name, name, "DATA")), f"应剔除：{name}")

    # ---- 二进制 / 插件 ----
    def test_keeps_required_plugins(self):
        drop = self.ns["_drop_binary"]
        for name in ("PySide6/plugins/platforms/qwindows.dll",
                     "PySide6/plugins/tls/qopensslbackend.dll",
                     "PySide6/plugins/imageformats/qjpeg.dll",
                     "PySide6/Qt6WebEngineCore.dll",
                     "PySide6/Qt6Core.dll",
                     "PySide6/Qt6Widgets.dll"):
            self.assertFalse(drop((name, name, "BINARY")),
                             f"必须保留：{name}")

    def test_drops_unused_plugins_and_tools(self):
        drop = self.ns["_drop_binary"]
        for name in ("PySide6/plugins/sqldrivers/qsqlite.dll",
                     "PySide6/plugins/sceneparsers/gltf.dll",
                     "PySide6/plugins/designer/qquickwidget.dll",
                     "PySide6/qmlls.exe",
                     "PySide6/designer.exe"):
            self.assertTrue(drop((name, name, "BINARY")), f"应剔除：{name}")

    # ---- 模块排除清单 ----
    def test_excludes_cover_unused_qt_modules(self):
        excludes = self.ns["EXCLUDES"]
        for mod in ("PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtSql",
                    "PySide6.QtDesigner", "PySide6.QtMultimedia",
                    "PySide6.Qt3DCore", "PySide6.QtPdf", "PySide6.QtCharts"):
            self.assertIn(mod, excludes, f"应排除 {mod}")

    def test_excludes_keep_required_qt_modules(self):
        excludes = self.ns["EXCLUDES"]
        for mod in ("PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
                    "PySide6.QtNetwork", "PySide6.QtWebChannel",
                    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"):
            self.assertNotIn(mod, excludes, f"不能排除 {mod}")

    def test_excludes_cover_unused_third_party(self):
        excludes = self.ns["EXCLUDES"]
        for mod in ("tkinter", "setuptools", "numpy", "PIL"):
            self.assertIn(mod, excludes, f"应排除 {mod}")

    # ----------------------------------------------------------------
    # Scrapling 融合层：有意不打进包，必须整条依赖链都排除
    # ----------------------------------------------------------------
    #  如果只排 scrapling 而漏掉它的依赖，PyInstaller 仍可能把
    #  playwright / curl_cffi 之类的重依赖拖进产物；
    #  反过来若漏排 scrapling 本身，产物会暴涨数百 MB。
    def test_excludes_scrapling_stack(self):
        excludes = self.ns["EXCLUDES"]
        required = (
            "scrapling",                     # 顶层
            "curl_cffi",                     # HTTP 引擎
            "playwright", "patchright", "camoufox",   # 浏览器引擎
            "browserforge", "apify_fingerprint_datapoints",
            "greenlet", "pyee",              # playwright 运行时依赖
            "cssselect", "w3lib", "tld", "orjson", "msgspec",
            "protego", "anyio",
            "markdownify", "mcp", "IPython",  # [all] 额外带入
        )
        for mod in required:
            self.assertIn(mod, excludes, f"应排除 {mod}")

    # ---- 随包分发的数据文件 ----
    def test_bundles_stylesheet_in_datas(self):
        """spec 必须把 ui/styles.qss 收进 datas，并真的交给 Analysis。

        PyInstaller **不会**自动收集 .qss 这类非 .py 文件；漏掉的后果是
        「打包版一点样式都没有」，而代码里只有一条 WARNING，界面照样显示，
        所以这个错误极容易被忽略 —— 本项目就真的漏掉过（v0.0.2 ~ v0.0.4
        的包全都没有样式）。这条测试专门钉住它。

        这里不看源码字符串，而是**执行 spec** 后直接检查传进 Analysis 的
        参数，因此「声明了 DATAS 却忘了传给 Analysis」也会被抓出来。
        """
        datas = self.ns["DATAS"]
        dests = [str(d[0]).replace("\\", "/") for d in datas]
        targets = [str(d[1]).replace("\\", "/") for d in datas]
        self.assertTrue(
            any(p.lower().endswith("ui/styles.qss") for p in dests),
            f"DATAS 应包含 ui/styles.qss，实际：{dests}")
        self.assertIn("ui", targets, f"styles.qss 的目标目录应为 ui/，实际：{targets}")

        passed = self.ns["a"].kwargs.get("datas")
        self.assertIs(passed, datas, "DATAS 必须传给 Analysis(datas=...)")

    def test_bundled_data_survives_drop_filter(self):
        """刚加进 datas 的数据文件不能被 _drop_data 又筛掉。

        过滤规则里有一堆「包含 /scripts/、/doc/ 就丢」的判定，数据文件
        一旦踩到就会静默消失 —— 必须验证它们活着通过过滤器。
        """
        drop = self.ns["_drop_data"]
        toc = [("ui/styles.qss", "ui/styles.qss", "DATA")]
        for entry in toc:
            self.assertFalse(drop(entry), f"被误删：{entry[0]}")
        # 图标若存在也应能通过
        for name in ("appicon.ico", "appicon.png"):
            self.assertFalse(drop((name, name, "DATA")), f"被误删：{name}")

    def test_release_keeps_console_by_default(self):
        """正式版默认**保留**控制台；只有 SC_CONSOLE=0 才去掉。

        保留控制台是为了让启动期崩溃、Qt/Chromium 的 WARNING 和 --selftest
        的输出还能被看到（GUI 子系统出错时是「双击没反应，什么都没有」）。
        运行期想隐藏它，由界面的「显示控制台窗口」开关负责，不需要重新打包。
        """
        self.assertTrue(self.ns["CONSOLE"], "默认应保留控制台")
        self.assertTrue(self.ns["exe"].kwargs.get("console"),
                        "EXE(console=...) 应为 True")

        saved = os.environ.get("SC_CONSOLE")
        try:
            os.environ["SC_CONSOLE"] = "0"
            ns2 = load_spec(SPEC_PATH)
            self.assertFalse(ns2["CONSOLE"], "SC_CONSOLE=0 应去掉控制台")
            os.environ["SC_CONSOLE"] = "1"
            ns3 = load_spec(SPEC_PATH)
            self.assertTrue(ns3["CONSOLE"], "SC_CONSOLE=1 应保留控制台")
        finally:
            if saved is None:
                os.environ.pop("SC_CONSOLE", None)
            else:
                os.environ["SC_CONSOLE"] = saved

    def test_scrapling_absent_from_bundle_is_safe(self):
        """包里没有 scrapling 时，引擎必须能安全降级而不是崩。

        直接检查源码：core/scrapling_engine.py 的导入点必须包在
        try/except 里，available() 才能在 ImportError 时返回 False。
        """
        engine = os.path.join(ROOT, "core", "scrapling_engine.py")
        if not os.path.isfile(engine):
            self.skipTest("core/scrapling_engine.py 不存在")
        with open(engine, "r", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("def available", src)
        self.assertIn("def unavailable_reason", src)

        # 惰性导入必须被 try/except 包住。
        # 注意 1：模块文档字符串里也出现过 `import scrapling` 字样，
        #         所以必须先定位到 _load() 函数，再在它之后找导入语句。
        # 注意 2：取**整个函数体**（到下一个顶格 def / class 为止），
        #         不能用固定长度窗口 —— 函数一变长就会把 except 挤出窗口，
        #         从而误报「没有 except 兜底」（真的这样误报过一次）。
        fn = src.find("def _load")
        self.assertGreater(fn, 0, "应有 _load() 惰性导入函数")
        end = len(src)
        for marker in ("\ndef ", "\nclass "):
            pos = src.find(marker, fn + 1)
            if pos != -1:
                end = min(end, pos)
        body = src[fn:end]

        imp = body.find("import scrapling")
        self.assertGreater(imp, 0, "应在 _load() 内找到 import scrapling")
        self.assertIn("try:", body, "scrapling 导入必须在 try 中")
        self.assertIn("except", body, "scrapling 导入必须有 except 兜底")

        # 降级返回空结果而不是抛异常
        self.assertIn("return []", src)
        self.assertIn("FetchResult(ok=False", src)
        # 外挂依赖目录：冻结版要能把用户 pip --target 装进去的 scrapling 找出来
        self.assertIn("def site_packages_dir", src)
        self.assertIn("sys.path.append", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
