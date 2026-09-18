# -*- coding: utf-8 -*-
"""临时文件清理维护工具。

可清理项（默认只清理真正的「临时」内容，不动用户数据）：

- ``engine_cache``：浏览器引擎缓存（``crawler_data/engine/cache``）
- ``pycache``：项目内所有 ``__pycache__`` 目录
- ``temp_logs``：临时/测试日志（项目根目录下的 ``*.log``、``*.part``）
- ``app_logs``：应用日志（``crawler_data/logs``，可选）
- ``exports``：导出结果（``crawler_data/exports``，可选）
- ``downloads``：下载文件目录（``crawler_data/downloads``，可选）

**不会**触碰：``crawler_data/profiles``（Profile 与 Cookie 集）、程序源码、``.venv``。
"""

import os
import shutil

from config.constants import (
    BASE_DIR, DATA_DIR, DOWNLOAD_DIR, ENGINE_DIR, EXPORT_DIR, LOG_DIR,
)


def dir_size(path: str) -> int:
    """递归统计目录/文件占用字节数（忽略无法访问的项）。"""
    total = 0
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total


def human_size(num: int) -> str:
    """字节数转为易读字符串。"""
    n = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def _remove(path: str, freed: dict, removed: list, skipped: list) -> None:
    """删除文件或目录，并把释放大小累加进父级。"""
    if not os.path.exists(path):
        return
    size = dir_size(path)
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=False)
        else:
            os.remove(path)
        freed["parent"] += size
        removed.append(path)
    except OSError:
        skipped.append(path)


def find_pycache(root: str, max_depth: int = 6) -> list:
    """查找项目内的 __pycache__ 目录（限制深度，跳过 .venv）。"""
    found = []
    root = os.path.abspath(root)
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, _filenames in os.walk(root):
        if dirpath.count(os.sep) - base_depth >= max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                       if d not in (".venv", "venv", "node_modules")]
        if "__pycache__" in dirnames:
            found.append(os.path.join(dirpath, "__pycache__"))
    return found


def clean_temp(engine_cache: bool = True,
               pycache: bool = True,
               temp_logs: bool = True,
               app_logs: bool = False,
               exports: bool = False,
               downloads: bool = False) -> dict:
    """执行清理，返回统计信息。

    返回 dict:
        freed (int)     释放的字节数
        freed_text (str) 易读大小
        removed (list)  已删除的路径
        skipped (list)  因占用 / 权限未能删除的路径
    """
    freed = {"parent": 0}
    removed: list = []
    skipped: list = []

    if engine_cache:
        _remove(os.path.join(ENGINE_DIR, "cache"), freed, removed, skipped)
    if pycache:
        for path in find_pycache(BASE_DIR):
            _remove(path, freed, removed, skipped)
    if temp_logs:
        try:
            for name in os.listdir(BASE_DIR):
                if name.endswith((".log", ".part")):
                    _remove(os.path.join(BASE_DIR, name), freed,
                            removed, skipped)
        except OSError:
            pass
    if app_logs:
        _remove(LOG_DIR, freed, removed, skipped)
    if exports:
        _remove(EXPORT_DIR, freed, removed, skipped)
    if downloads:
        _remove(DOWNLOAD_DIR, freed, removed, skipped)

    total = freed["parent"]
    return {
        "freed": total,
        "freed_text": human_size(total),
        "removed": removed,
        "skipped": skipped,
    }


def temp_usage() -> dict:
    """统计各临时区域当前占用（用于界面展示）。"""
    return {
        "engine_cache": dir_size(os.path.join(ENGINE_DIR, "cache")),
        "logs": dir_size(LOG_DIR),
        "exports": dir_size(EXPORT_DIR),
        "downloads": dir_size(DOWNLOAD_DIR),
    }
