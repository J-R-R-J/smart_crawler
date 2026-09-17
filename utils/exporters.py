# -*- coding: utf-8 -*-
"""结果导出：CSV / JSON / Cookie。"""

import csv
import json
import os
from typing import Any, List


def _ensure_parent(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)


def export_csv(rows: List[dict], columns: List[str], path: str) -> None:
    """写 CSV（utf-8-sig，Excel 友好；缺列填空串）。"""
    _ensure_parent(path)
    cols = list(columns or [])
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(cols)
        for row in rows:
            line = []
            for c in cols:
                v = row.get(c, "")
                if not isinstance(v, str):
                    try:
                        v = json.dumps(v, ensure_ascii=False)
                    except Exception:
                        v = str(v)
                line.append(v)
            writer.writerow(line)


def export_json(rows: Any, path: str) -> None:
    """写 JSON（indent=2, ensure_ascii=False）。"""
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)


def export_cookies(cookies: List[dict], path: str) -> int:
    """写 Cookie JSON 数组，返回条数。"""
    _ensure_parent(path)
    data = cookies or []
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return len(data)


def import_cookies(path: str) -> List[dict]:
    """读取 Cookie JSON 数组，返回含 name/domain 的合法项。"""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("Cookie 文件必须是 JSON 数组")
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("name") and item.get("domain"):
            out.append(item)
    return out
