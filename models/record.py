# -*- coding: utf-8 -*-
"""结果集：清洗 / 去重 / 列合并 / 导出。"""

import json
from typing import Any, List, Optional


def _clean_value(v: Any) -> Any:
    """清洗单个值：字符串去首尾空白；None/空 dict 返回 None。"""
    if isinstance(v, str):
        v = v.strip()
        return v or None
    if v is None:
        return None
    if isinstance(v, dict):
        return v if v else None
    # 其它类型（int/float/bool/list）保持不变
    return v


def _row_fingerprint(row: dict) -> Optional[tuple]:
    """生成整行指纹用于去重；值不可哈希时回退 None（不去重该行）。"""
    try:
        return tuple(sorted((k, json.dumps(v, ensure_ascii=False, sort_keys=True))
                            for k, v in row.items()))
    except (TypeError, ValueError):
        return None


class RecordSet:
    """收集抓取到的记录，支持清洗、去重、列合并与导出。"""

    def __init__(self):
        self.rows: List[dict] = []
        self.columns: List[str] = []
        self._seen: set = set()

    # ------------------------------------------------------------------
    def add_rows(self, rows) -> int:
        """加入一批行，返回实际新增条数。"""
        added = 0
        for raw in (rows or []):
            if not isinstance(raw, dict):
                continue
            # 清洗 + 剔除全空行
            row = {}
            for k, v in raw.items():
                cv = _clean_value(v)
                if cv is None:
                    continue
                row[str(k)] = cv
            if not row:
                continue
            fp = _row_fingerprint(row)
            if fp is not None:
                if fp in self._seen:
                    continue
                self._seen.add(fp)
            # 列合并（保持首次出现顺序）
            for k in row.keys():
                if k not in self.columns:
                    self.columns.append(k)
            self.rows.append(row)
            added += 1
        return added

    def extend(self, rows) -> int:
        return self.add_rows(rows)

    # ------------------------------------------------------------------
    def count(self) -> int:
        return len(self.rows)

    def clear(self) -> None:
        self.rows = []
        self.columns = []
        self._seen = set()

    def has(self, row: dict) -> bool:
        fp = _row_fingerprint(row)
        return fp in self._seen if fp is not None else False

    # ------------------------------------------------------------------
    def to_csv(self, path: str, columns=None) -> None:
        from utils.exporters import export_csv
        export_csv(self.rows, columns or self.columns, path)

    def to_json(self, path: str) -> None:
        from utils.exporters import export_json
        export_json(self.rows, path)

    def __len__(self):
        return len(self.rows)

    def __repr__(self):
        return f"RecordSet(rows={len(self.rows)}, columns={len(self.columns)})"
