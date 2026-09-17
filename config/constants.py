# -*- coding: utf-8 -*-
"""全局路径常量与应用元信息。

所有路径常量均为 str（os.path.join 风格），供 ui/ 层直接拼接使用
（如 os.path.join(COOKIE_DIR, "cookies.json")、os.startfile(LOG_DIR)）。
导入本模块时自动创建运行时数据目录。
"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "crawler_data")
PROFILE_DIR = os.path.join(DATA_DIR, "profiles")
LOG_DIR = os.path.join(DATA_DIR, "logs")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")
COOKIE_DIR = os.path.join(DATA_DIR, "cookies")

APP_TITLE = "SmartCrawler · 智能可视化爬虫"
APP_VERSION = "1.0.0"
DEFAULT_PROFILE = "default"

__all__ = [
    "BASE_DIR", "DATA_DIR", "PROFILE_DIR", "LOG_DIR", "EXPORT_DIR", "COOKIE_DIR",
    "APP_TITLE", "APP_VERSION", "DEFAULT_PROFILE", "ensure_dirs",
]


def ensure_dirs() -> None:
    """创建运行时数据目录（幂等）。"""
    for path in (DATA_DIR, PROFILE_DIR, LOG_DIR, EXPORT_DIR, COOKIE_DIR):
        os.makedirs(path, exist_ok=True)


ensure_dirs()
