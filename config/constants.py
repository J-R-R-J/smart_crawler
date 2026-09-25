# -*- coding: utf-8 -*-
"""全局路径常量与应用元信息。

所有路径常量均为 str（os.path.join 风格），供 ui/ 层直接拼接使用
（如 os.path.join(COOKIE_DIR, "cookies.json")、os.startfile(LOG_DIR)）。
导入本模块时自动创建运行时数据目录。

打包（PyInstaller）后的数据位置：
    冻结状态下数据放在 **exe 同级目录** 的 crawler_data\\ ，
    而不是 PyInstaller 的运行时目录 _internal\\ —— 后者在升级程序时
    会被整体替换，用户也找不到自己的 Profile 与导出结果。
"""
import os
import sys

if getattr(sys, "frozen", False):
    # PyInstaller 打包后：sys.executable 是 exe 的绝对路径
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(BASE_DIR, "crawler_data")
PROFILE_DIR = os.path.join(DATA_DIR, "profiles")
LOG_DIR = os.path.join(DATA_DIR, "logs")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")
COOKIE_DIR = os.path.join(DATA_DIR, "cookies")
DOWNLOAD_DIR = os.path.join(DATA_DIR, "downloads")
ENGINE_DIR = os.path.join(DATA_DIR, "engine")

# 外挂依赖目录（可选）。
#
# 正式版 exe 有意不打包 Scrapling 及其浏览器依赖（见 packaging/SmartCrawler.spec：
# playwright / patchright / curl_cffi 的 wheel 加上浏览器合计数百 MB，
# 与「解压即用」的免安装包定位冲突）。但用户仍可能想用非浏览器引擎，
# 因此留一个外挂目录：用 pip --target 把 scrapling 装到这里，
# 程序会把它追加到 sys.path。
# 放在 crawler_data\ 下而不是 exe 同级，是为了跟随运行时数据一起被忽略/清理，
# 也不会和程序文件混在一起。
SITE_PACKAGES_DIR = os.path.join(DATA_DIR, "site-packages")

APP_TITLE = "SmartCrawler · 智能可视化爬虫"
APP_VERSION = "0.0.4"
DEFAULT_PROFILE = "default"

__all__ = [
    "BASE_DIR", "DATA_DIR", "PROFILE_DIR", "LOG_DIR", "EXPORT_DIR", "COOKIE_DIR",
    "DOWNLOAD_DIR", "ENGINE_DIR", "SITE_PACKAGES_DIR",
    "APP_TITLE", "APP_VERSION", "DEFAULT_PROFILE", "ensure_dirs",
]


def ensure_dirs() -> None:
    """创建运行时数据目录（幂等）。"""
    for path in (DATA_DIR, PROFILE_DIR, LOG_DIR, EXPORT_DIR, COOKIE_DIR,
                 DOWNLOAD_DIR, ENGINE_DIR, SITE_PACKAGES_DIR):
        os.makedirs(path, exist_ok=True)


ensure_dirs()
