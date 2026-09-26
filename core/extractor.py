# -*- coding: utf-8 -*-
"""core.extractor —— 数据提取与规范化。

- extract() 按 task.modes（可多选）依次生成并执行提取脚本，结果合并返回；
  用 js.run_sync 同步执行并解析 JSON（兼容返回 str 与 list/dict 两种情况）；
- _normalize 统一为 list[dict]，每条补 "_mode"；
- 所有值强制可 JSON 序列化。
"""

import json

from PySide6.QtCore import QObject, Signal

from config.default_settings import SUPPORTED_FORMATS
from config.js_scripts import build_extract_js
from utils.logger import log_info, log_warn


class Extractor(QObject):
    extracted = Signal(list)               # list[dict]（规范化后）

    # str 数据时按 mode 使用的字段名
    _STR_FIELD = {
        "list": "text",
        "links": "text",
        "images": "src",
        "video": "src",
        "audio": "src",
        "media": "src",
        "text": "text",
        "html": "html",
        "regex": "match",
    }

    def __init__(self, js, parent=None):
        super().__init__(parent)
        self._js = js
        #: 上一次过滤掉的站点素材图数量（0 表示没过滤或没命中）
        self.last_filtered = 0

    def extract(self, page, task) -> list:
        """按 task.modes 依次执行提取，返回合并后的 list[dict]。

        支持多格式复选：每种格式独立跑一遍提取脚本，结果按序拼接；
        每条记录都带 `_mode` 字段，便于在结果表中区分来源格式。
        """
        modes = [m for m in (getattr(task, "modes", None) or [task.mode]) if m]
        if not modes:
            return []

        all_rows = []
        for mode in modes:
            try:
                js_code = build_extract_js(mode, task.selector, task.fields,
                                           task.pattern, task.flags)
                raw = self._js.run_sync(js_code)
                if raw is None:
                    log_warn(f"[extract] 脚本无返回（mode={mode}）")
                    continue
                data = self._parse(raw)
                rows = self._normalize(mode, data)
                rows = self._filter_assets(
                    rows, bool(getattr(task, "filter_site_assets", False)))
                all_rows.extend(rows)
                log_info(f"[extract] {mode}：{len(rows)} 条")
            except Exception as e:
                log_warn(f"[extract] {mode} 提取失败：{e}")

        if all_rows:
            self.extracted.emit(all_rows)
        return all_rows

    def _filter_assets(self, rows: list, enabled: bool = False) -> list:
        """按开关丢弃站点自己的 UI 素材图（图标 / 表情 / 头像 / 皮肤资源）。

        为什么要做：抓媒体时**绝大多数行都是站点 UI 图**（实测某视频站一页
        181 条里大部分是图标与表情），真正的正文图被淹没，用户会以为
        「只能抓到站点的素材图」。JS 侧已给每条打上 ``asset=1``，
        这里只在用户勾选时丢弃，并明确写一条日志说明丢了多少 ——
        静默丢数据比留着更糟。
        """
        self.last_filtered = 0
        if not rows or not enabled:
            return rows
        keep, dropped = [], 0
        for r in rows:
            if isinstance(r, dict) and r.get("asset"):
                dropped += 1
                continue
            keep.append(r)
        if dropped:
            self.last_filtered = dropped
            log_info(f"[extract] 已过滤 {dropped} 条站点素材图"
                     f"（图标/表情/头像/UI 资源），保留 {len(keep)} 条")
        return keep

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
        """SUPPORTED_FORMATS 的 20 个 key。"""
        return [key for key, _label, _hint in SUPPORTED_FORMATS]
