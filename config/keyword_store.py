# -*- coding: utf-8 -*-
"""检测关键词的可自定义存储。

- 默认值来自 `config.default_settings`；
- 用户在界面上的修改保存到 `crawler_data/keywords.json`（整体替换，便于精确控制）；
- `core.detector` 通过本模块读取，因此改词后立即生效，无需改代码或重启。

分组：
- ``captcha``：验证码 / 人机验证
- ``human``：访问频控 / 异常流量
- ``login``：登录墙
"""

import json
import os

from config.constants import DATA_DIR
from config.default_settings import (
    CAPTCHA_KEYWORDS,
    HUMAN_VERIFY_KEYWORDS,
    LOGIN_KEYWORDS,
)

STORE_PATH = os.path.join(DATA_DIR, "keywords.json")

GROUPS = ("captcha", "human", "login")

GROUP_LABELS = {
    "captcha": "验证码 / 人机验证",
    "human": "访问频控 / 异常流量",
    "login": "登录墙",
}

_DEFAULTS = {
    "captcha": list(CAPTCHA_KEYWORDS),
    "human": list(HUMAN_VERIFY_KEYWORDS),
    "login": list(LOGIN_KEYWORDS),
}

_cache = None


# ----------------------------------------------------------------------
# 内部
# ----------------------------------------------------------------------
def _normalize(words) -> list:
    """去空行、去首尾空白、去重（保持顺序）。"""
    out = []
    seen = set()
    for w in words or []:
        if w is None:
            continue
        s = str(w).strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _read_file() -> dict:
    if not os.path.isfile(STORE_PATH):
        return {}
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_file(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _ensure_cache() -> dict:
    global _cache
    if _cache is None:
        stored = _read_file()
        merged = {}
        for g in GROUPS:
            words = stored.get(g)
            merged[g] = _normalize(words) if isinstance(words, list) \
                else list(_DEFAULTS[g])
        _cache = merged
    return _cache


# ----------------------------------------------------------------------
# 公共 API
# ----------------------------------------------------------------------
def defaults(group: str) -> list:
    return list(_DEFAULTS.get(group, []))


def load(group: str) -> list:
    """返回某组当前生效的关键词。"""
    return list(_ensure_cache().get(group, []))


def load_all() -> dict:
    """返回三组关键词的当前值。"""
    cache = _ensure_cache()
    return {g: list(cache.get(g, [])) for g in GROUPS}


def save(group: str, words) -> None:
    """保存某一组关键词（整体替换默认值）。"""
    if group not in GROUPS:
        return
    global _cache
    cache = _ensure_cache()
    cache[group] = _normalize(words)
    _write_file({g: cache[g] for g in GROUPS})


def save_all(mapping: dict) -> None:
    global _cache
    cache = _ensure_cache()
    for g in GROUPS:
        if g in (mapping or {}):
            cache[g] = _normalize(mapping[g])
    _write_file({g: cache[g] for g in GROUPS})


def reset(group: str = None) -> None:
    """恢复默认值；group 为 None 时恢复全部。"""
    global _cache
    cache = _ensure_cache()
    targets = GROUPS if group is None else (group,)
    for g in targets:
        if g in _DEFAULTS:
            cache[g] = list(_DEFAULTS[g])
    _write_file({g: cache[g] for g in GROUPS})


def is_customized() -> bool:
    """是否存在与默认值不同的组。"""
    cache = _ensure_cache()
    for g in GROUPS:
        if _normalize(cache.get(g)) != _normalize(_DEFAULTS[g]):
            return True
    return False


def reload() -> None:
    """丢弃缓存，下次读取重新加载文件。"""
    global _cache
    _cache = None
