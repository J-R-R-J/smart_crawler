# -*- coding: utf-8 -*-
"""日志落盘：按天生成文件 + 5MB 轮转，同时输出到 stdout。"""

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler

from config.constants import LOG_DIR

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_lock = threading.Lock()
_logger = logging.getLogger("smartcrawler")
_logger.setLevel(logging.DEBUG)
_logger.propagate = False

# 当前日志文件绝对路径（无日期后缀，供外部引用展示）
current_log_file = ""
_current_handler = None
_current_day = ""


def _file_path_for_day(day: str) -> str:
    return os.path.join(LOG_DIR, f"smartcrawler_{day}.log")


def _ensure_handler() -> None:
    """保证 file handler 指向当天的日志文件（跨天自动切换）。"""
    global _current_handler, _current_day, current_log_file
    import time
    day = time.strftime("%Y%m%d")
    if _current_day == day and _current_handler is not None:
        return
    if _current_handler is not None:
        _logger.removeHandler(_current_handler)
        try:
            _current_handler.close()
        except Exception:
            pass
        _current_handler = None

    path = _file_path_for_day(day)
    handler = RotatingFileHandler(
        path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    handler.setLevel(logging.DEBUG)
    _logger.addHandler(handler)
    _current_handler = handler
    _current_day = day
    current_log_file = path


def _emit(level: int, msg: str) -> None:
    with _lock:
        _ensure_handler()
        _logger.log(level, msg)


def log_info(msg: str) -> None:
    _emit(logging.INFO, msg)


def log_warn(msg: str) -> None:
    _emit(logging.WARNING, msg)


def log_error(msg: str) -> None:
    _emit(logging.ERROR, msg)


def log_debug(msg: str) -> None:
    _emit(logging.DEBUG, msg)


# ---- stdout handler（始终存在） ----
_stdout = logging.StreamHandler(sys.stdout)
_stdout.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
_stdout.setLevel(logging.INFO)
_logger.addHandler(_stdout)
