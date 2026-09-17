# -*- coding: utf-8 -*-
"""字段映射：把「名称 | 子选择器 | 类型 | 属性」解析为 Field 对象。"""

VALID_TYPES = ("text", "href", "src", "html", "attr")


class Field:
    """结构化记录中的一个字段映射。"""

    def __init__(self, name: str, selector: str, ftype: str = "text", attr: str = ""):
        self.name = (name or "").strip()
        self.selector = (selector or "").strip()
        self.type = ftype.strip().lower() if ftype else "text"
        if self.type not in VALID_TYPES:
            self.type = "text"
        self.attr = (attr or "").strip()

    @property
    def ftype(self) -> str:
        return self.type

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "selector": self.selector,
            "type": self.type,
            "attr": self.attr,
        }

    @staticmethod
    def parse_line(line: str):
        """解析一行 ``名称 | 子选择器 | 类型 | 属性``；非法行返回 None。"""
        if not line:
            return None
        s = line.strip()
        if not s or s.startswith("#"):
            return None
        parts = [p.strip() for p in s.split("|")]
        # 至少需要 名称 / 选择器 / 类型 三段
        if len(parts) < 3:
            return None
        name, selector, ftype = parts[0], parts[1], parts[2]
        if not name or not selector:
            return None
        attr = parts[3] if len(parts) > 3 else ""
        return Field(name, selector, ftype, attr)

    @staticmethod
    def parse_block(text: str):
        """逐行解析字段映射文本块，返回 Field 列表。"""
        fields = []
        for line in (text or "").splitlines():
            f = Field.parse_line(line)
            if f is not None:
                fields.append(f)
        return fields

    def __repr__(self):
        return (f"Field(name={self.name!r}, selector={self.selector!r}, "
                f"type={self.type!r}, attr={self.attr!r})")
