# -*- coding: utf-8 -*-
"""任务数据类：一次抓取的完整配置。"""

from dataclasses import dataclass, field, asdict
from typing import Any, List

from .field import Field


@dataclass
class Task:
    url: str = ""
    mode: str = "records"                       # SUPPORTED_FORMATS 的 key
    selector: str = ""
    fields: List[Field] = field(default_factory=list)
    pattern: str = ""
    flags: str = "g"
    next_selector: str = ""
    max_pages: int = 1
    delay: float = 1.5
    autoscroll: bool = True

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fields"] = [f.to_dict() for f in self.fields]
        return d

    def validate(self) -> List[str]:
        """返回错误信息列表；空列表表示合法。"""
        errors: List[str] = []
        if not self.url:
            errors.append("URL 不能为空")
        if self.mode == "records" and not self.selector:
            errors.append("结构化记录需要「容器选择器」")
        if self.mode == "records" and not self.fields:
            errors.append("结构化记录需要至少一个「字段映射」")
        if self.mode == "regex" and not self.pattern:
            errors.append("正则模式需要填写「正则表达式」")
        if self.max_pages < 1:
            errors.append("最大页数必须 ≥ 1")
        if self.delay < 0:
            errors.append("每页延迟不能为负")
        return errors

    def __repr__(self):
        return (f"Task(url={self.url!r}, mode={self.mode!r}, "
                f"pages={self.max_pages}, fields={len(self.fields)})")
