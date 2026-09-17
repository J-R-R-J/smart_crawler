# -*- coding: utf-8 -*-
"""core.extractor —— 数据提取与规范化。

- extract() 用 build_extract_js 生成脚本，js.run_sync 同步执行并解析 JSON
  （兼容返回 str 与 list/dict 对象两种情况）；
- _normalize 统一为 list[dict]，每条补 "_mode"；
- 所有值强制可 JSON 序列化。
"""

import json

from PySide6.QtCore import QObject, Signal

from config.default_settings import SUPPORTED_FORMATS
from config.js_scripts import build_extract_js
from utils.logger import log_warn


class Extractor(QObject):
    extracted = Signal(list)               # list[dict]（规范化后）

    # str 数据时按 mode 使用的字段名
    _STR_FIELD = {
        "list": "text",
        "links": "text",
        "images": "src",
        "text": "text",
        "html": "html",
        "regex": "match",
    }

    def __init__(self, js, parent=None):
        super().__init__(parent)
        self._js = js

    def extract(self, page, task) -> list:
        """执行提取脚本并返回规范化后的 list[dict]。"""
        try:
            js_code = build_extract_js(task.mode, task.selector, task.fields,
                                       task.pattern, task.flags)
            raw = self._js.run_sync(js_code)
            if raw is None:
                log_warn(f"[extract] 脚本无返回（mode={task.mode}）")
                return []
            data = self._parse(raw)
            rows = self._normalize(task.mode, data)
            self.extracted.emit(rows)
            return rows
        except Exception as e:
            log_warn(f"[extract] 提取失败：{e}")
            return []

    @staticmethod
    def _parse(raw):
        """JSON 字符串 → 对象；list/dict 直接使用；其余原样返回。"""
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return None
            try:
                return json.loads(s)
            except (ValueError, TypeError):
                return s
        return raw

    def _normalize(self, mode: str, data) -> list:
        """统一为 list[dict]：list 逐项保留、dict 包装、str 换字段名，
        每条补 "_mode"，所有值保证可 JSON 序列化。"""
        if data is None:
            return []
        if isinstance(data, list):
            items = list(data)
        elif isinstance(data, dict):
            items = [data]
        elif isinstance(data, str):
            items = [{self._STR_FIELD.get(mode, "text"): data}]
        else:
            items = [{"value": data}]

        out = []
        for item in items:
            if isinstance(item, dict):
                row = {}
                for k, v in item.items():
                    row[str(k)] = self._json_safe(v)
            elif isinstance(item, str):
                row = {self._STR_FIELD.get(mode, "text"): item}
            else:
                row = {"value": self._json_safe(item)}
            row["_mode"] = mode
            out.append(row)
        return out

    @staticmethod
    def _json_safe(v):
        """保证值可 JSON 序列化；复杂对象序列化成字符串。"""
        if v is None or isinstance(v, (bool, int, float, str)):
            return v
        try:
            json.dumps(v)
            return v
        except (TypeError, ValueError):
            try:
                return json.dumps(v, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                return str(v)

    def supported_modes(self) -> list:
        """SUPPORTED_FORMATS 的 18 个 key。"""
        return [key for key, _label, _hint in SUPPORTED_FORMATS]
