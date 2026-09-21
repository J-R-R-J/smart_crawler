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

APP_TITLE = "SmartCrawler · 智能可视化爬虫"
APP_VERSION = "0.0.3"
DEFAULT_PROFILE = "default"

__all__ = [
    "BASE_DIR", "DATA_DIR", "PROFILE_DIR", "LOG_DIR", "EXPORT_DIR", "COOKIE_DIR",
    "DOWNLOAD_DIR", "ENGINE_DIR",
    "APP_TITLE", "APP_VERSION", "DEFAULT_PROFILE", "ensure_dirs",
]


def ensure_dirs() -> None:
    """创建运行时数据目录（幂等）。"""
    for path in (DATA_DIR, PROFILE_DIR, LOG_DIR, EXPORT_DIR, COOKIE_DIR,
                 DOWNLOAD_DIR, ENGINE_DIR):
        os.makedirs(path, exist_ok=True)


ensure_dirs()
