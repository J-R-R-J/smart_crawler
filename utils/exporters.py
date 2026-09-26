# -*- coding: utf-8 -*-
"""结果导出：CSV / TSV / JSON / JSONL / Excel / Markdown / HTML / TXT / XML / YAML / SQLite。

设计要点
--------
- **零第三方依赖**：Excel（.xlsx）不借助 openpyxl 也能写 —— xlsx 本质是一个
  装着若干 XML 的 zip，这里按 OOXML 最小子集自行拼装（字符串用 inlineStr，
  不需要 sharedStrings）；YAML 只覆盖本项目的数据形状（标量 / 列表 / 映射）。
  好处是打包体积不变、用户机器上也不用额外装东西。
- :data:`EXPORT_FORMATS` 是格式清单的**唯一真值来源**：界面菜单、文件对话框
  过滤器、单条导出都从它取，避免「加了新格式但某个入口漏了」。
- 所有写表函数签名统一为 ``(rows, columns, path)``，列清单缺省时按行内键
  自动推导（并集、保持首次出现顺序），因此单条导出可以直接传 ``[row]``。
"""

import csv
import json
import os
import re
import sqlite3
import unicodedata
import zipfile
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape as _xml_escape


def _ensure_parent(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)


# ======================================================================
# 格式清单（唯一真值来源）
# ======================================================================
#: (key, 中文名, 扩展名)
EXPORT_FORMATS: Tuple[Tuple[str, str, str], ...] = (
    ("csv",    "CSV 表格",       "csv"),
    ("tsv",    "TSV 表格",       "tsv"),
    ("json",   "JSON",           "json"),
    ("jsonl",  "JSON Lines",     "jsonl"),
    ("xlsx",   "Excel 工作簿",   "xlsx"),
    ("md",     "Markdown 表格",  "md"),
    ("html",   "HTML 网页表格",  "html"),
    ("txt",    "纯文本",         "txt"),
    ("xml",    "XML",            "xml"),
    ("yaml",   "YAML",           "yaml"),
    ("sqlite", "SQLite 数据库",  "db"),
)

EXPORT_FORMAT_KEYS: Tuple[str, ...] = tuple(k for k, _l, _e in EXPORT_FORMATS)
EXPORT_LABELS: Dict[str, str] = {k: l for k, l, _e in EXPORT_FORMATS}
EXPORT_EXTS: Dict[str, str] = {k: e for k, _l, e in EXPORT_FORMATS}
#: 扩展名 -> key（.yaml/.yml、.htm 等常见别名都认）
_EXT_ALIASES = {
    "csv": "csv", "tsv": "tsv", "tab": "tsv", "json": "json",
    "jsonl": "jsonl", "ndjson": "jsonl", "xlsx": "xlsx", "xlsm": "xlsx",
    "md": "md", "markdown": "md", "html": "html", "htm": "html",
    "txt": "txt", "log": "txt", "xml": "xml",
    "yaml": "yaml", "yml": "yaml",
    "db": "sqlite", "sqlite": "sqlite", "sqlite3": "sqlite",
}


def file_filter(key: str) -> str:
    """Qt 文件对话框过滤器，如 ``CSV 表格 (*.csv)``。"""
    key = normalize_format(key)
    return "%s (*.%s)" % (EXPORT_LABELS.get(key, key), EXPORT_EXTS.get(key, key))


def all_file_filter() -> str:
    parts = ["%s (*.%s)" % (l, e) for _k, l, e in EXPORT_FORMATS]
    return ";;".join(parts + ["所有文件 (*)"])


def normalize_format(fmt: str) -> str:
    """把用户/扩展名给的格式串归一成 EXPORT_FORMATS 里的 key。"""
    f = (fmt or "").strip().lower().lstrip(".")
    if f in EXPORT_LABELS:
        return f
    return _EXT_ALIASES.get(f, f)


def format_for_path(path: str) -> str:
    """按目标文件扩展名推断格式 key（推断不出抛 ValueError）。"""
    ext = os.path.splitext(path or "")[1].lstrip(".").lower()
    key = _EXT_ALIASES.get(ext, "")
    if not key:
        raise ValueError(
            "无法从扩展名推断导出格式：%s（可用：%s）"
            % (ext or "(无)", "、".join(EXPORT_FORMAT_KEYS)))
    return key


# ======================================================================
# 值 / 列 归一
# ======================================================================
def cell_text(v: Any) -> str:
    """单元格文本：字符串原样，其余 JSON 序列化（与 CSV 导出行为一致）。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, float) and v != v:          # NaN
        return ""
    try:
        return json.dumps(v, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(v)


def resolve_columns(rows: Sequence[dict], columns: Optional[Sequence[str]] = None,
                    first: Sequence[str] = ()) -> List[str]:
    """列清单：先用显式传入的，再按 ``first``，最后按行内键并集补全。"""
    cols: List[str] = []
    for c in list(first) + list(columns or []):
        c = str(c)
        if c not in cols:
            cols.append(c)
    for r in rows or []:
        if isinstance(r, dict):
            for k in r.keys():
                k = str(k)
                if k not in cols:
                    cols.append(k)
    return cols


def _sanitize_xml_text(s: str) -> str:
    """去掉 XML 1.0 不允许的控制字符，并修掉非法代理项。"""
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        s = s.encode("utf-8", "replace").decode("utf-8")
    return s


def _disp_width(s: str) -> int:
    """终端对齐用的显示宽度（CJK 全角算 2 格）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in s)


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _disp_width(s))


# ======================================================================
# 1. CSV / TSV
# ======================================================================
def export_csv(rows: List[dict], columns: Optional[List[str]], path: str,
               delimiter: str = ",") -> None:
    """写 CSV（utf-8-sig，Excel 友好；缺列填空串）。"""
    _ensure_parent(path)
    cols = resolve_columns(rows, columns)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=delimiter)
        writer.writerow(cols)
        for row in rows or []:
            writer.writerow([cell_text((row or {}).get(c, "")) for c in cols])


def export_tsv(rows: List[dict], columns: Optional[List[str]], path: str) -> None:
    """写 TSV（制表符分隔；换行/制表符在单元格内转成空格）。"""
    export_csv([{k: re.sub(r"[\t\r\n]+", " ", cell_text(v)) for k, v in (r or {}).items()}
                for r in (rows or [])], columns, path, delimiter="\t")


# ======================================================================
# 2. JSON / JSON Lines
# ======================================================================
def export_json(rows: Any, path: str) -> None:
    """写 JSON（indent=2, ensure_ascii=False）。"""
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)


def export_jsonl(rows: List[dict], columns: Optional[List[str]], path: str) -> None:
    """写 JSON Lines（每行一个对象；流式处理大数据集友好）。"""
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows or []:
            fh.write(json.dumps(row or {}, ensure_ascii=False, default=str))
            fh.write("\n")


# ======================================================================
# 3. Excel（.xlsx，零依赖：手写 OOXML 最小包）
# ======================================================================
def _col_letters(idx: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA。"""
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def _xlsx_cell(ref: str, v: Any) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return '<c r="%s" t="b"><v>%d</v></c>' % (ref, 1 if v else 0)
    if isinstance(v, (int, float)):
        return '<c r="%s"><v>%s</v></c>' % (ref, v)
    text = _xml_escape(_sanitize_xml_text(cell_text(v)))
    return ('<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
            % (ref, text))


def _sheet_name(name: str) -> str:
    """Excel 工作表名：去非法字符、限 31 字符、不能为空。"""
    n = re.sub(r"[\[\]:*?/\\]", "_", (name or "").strip())[:31]
    return n or "result"


def export_xlsx(rows: List[dict], columns: Optional[List[str]], path: str,
                sheet: str = "result") -> None:
    """写 xlsx（OOXML 最小包：字符串用 inlineStr，不写 sharedStrings）。

    同时冻结首行并加自动筛选 —— 导出后打开就能直接按列筛。
    """
    _ensure_parent(path)
    cols = resolve_columns(rows, columns)
    data = list(rows or [])

    body = []
    header = "".join(_xlsx_cell("%s1" % _col_letters(c), cols[c])
                     for c in range(len(cols)))
    body.append('<row r="1">%s</row>' % header)
    for i, row in enumerate(data):
        cells = "".join(
            _xlsx_cell("%s%d" % (_col_letters(c), i + 2), (row or {}).get(cols[c], ""))
            for c in range(len(cols)))
        body.append('<row r="%d">%s</row>' % (i + 2, cells))

    last = "%s%d" % (_col_letters(max(0, len(cols) - 1)), len(data) + 1)
    dim = "A1:%s" % last if cols else "A1"
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<dimension ref="%s"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        '<sheetData>%s</sheetData>'
        '%s'
        '</worksheet>'
        % (dim, "".join(body),
           '<autoFilter ref="A1:%s"/>' % last if cols else "")
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>' % _xml_escape(_sheet_name(sheet))
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1"'
        ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"'
        ' Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1"'
        ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
        ' Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels"'
        ' ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)


# ======================================================================
# 4. Markdown / HTML / 纯文本
# ======================================================================
def _md_cell(v: Any) -> str:
    return cell_text(v).replace("|", "\\|").replace("\r\n", " ").replace("\n", " ")


def export_markdown(rows: List[dict], columns: Optional[List[str]], path: str) -> None:
    """写 Markdown 表格（单元格内的竖线与换行会被转义）。"""
    _ensure_parent(path)
    cols = resolve_columns(rows, columns)
    data = list(rows or [])
    lines = ["# 抓取结果", "",
             f"- 条数：{len(data)}", f"- 字段：{'、'.join(cols) if cols else '(无)'}",
             ""]
    if cols:
        lines.append("| " + " | ".join(_md_cell(c) for c in cols) + " |")
        lines.append("| " + " | ".join("---" for _ in cols) + " |")
        for row in data:
            lines.append("| " + " | ".join(_md_cell((row or {}).get(c, ""))
                                           for c in cols) + " |")
    lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


_HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>抓取结果</title>
<style>
 body{font-family:"Microsoft YaHei",system-ui,sans-serif;margin:24px;color:#222}
 h1{font-size:18px;margin:0 0 8px}
 p.meta{color:#666;font-size:12px;margin:0 0 16px}
 table{border-collapse:collapse;font-size:13px;max-width:100%}
 th,td{border:1px solid #d0d7de;padding:4px 8px;text-align:left;
       vertical-align:top;max-width:520px;word-break:break-all}
 th{background:#f3f5f7;position:sticky;top:0}
 tr:nth-child(even) td{background:#fafbfc}
 a{color:#0b5cad}
</style>
</head>
<body>
"""


def export_html(rows: List[dict], columns: Optional[List[str]], path: str) -> None:
    """写自包含 HTML 表格（UTF-8 声明 + 内联样式，双击即可看）。"""
    _ensure_parent(path)
    cols = resolve_columns(rows, columns)
    data = list(rows or [])
    out = [_HTML_HEAD]
    out.append("<h1>抓取结果</h1>\n<p class=\"meta\">共 %d 条 · 字段 %d 个</p>\n"
               % (len(data), len(cols)))
    out.append("<table>\n<thead><tr>")
    for c in cols:
        out.append("<th>%s</th>" % _xml_escape(_sanitize_xml_text(c)))
    out.append("</tr></thead>\n<tbody>\n")
    for row in data:
        out.append("<tr>")
        for c in cols:
            txt = _sanitize_xml_text(cell_text((row or {}).get(c, "")))
            if re.match(r"^(https?|ftp)://\S+$", txt.strip()):
                out.append('<td><a href="%s" target="_blank" rel="noreferrer">%s</a></td>'
                           % (_xml_escape(txt.strip(), {'"': "&quot;"}), _xml_escape(txt)))
            else:
                out.append("<td>%s</td>" % _xml_escape(txt))
        out.append("</tr>\n")
    out.append("</tbody>\n</table>\n</body>\n</html>\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(out))


def export_txt(rows: List[dict], columns: Optional[List[str]], path: str) -> None:
    """写等宽对齐的纯文本表：单条时改用「字段：值」清单，更易读。"""
    _ensure_parent(path)
    cols = resolve_columns(rows, columns)
    data = list(rows or [])
    lines = []
    if len(data) == 1 and cols:
        lines.append("抓取结果（1 条）")
        lines.append("=" * 40)
        for c in cols:
            lines.append("%s：%s" % (c, cell_text((data[0] or {}).get(c, ""))))
    else:
        lines.append("抓取结果（%d 条）" % len(data))
        lines.append("=" * 40)
        if cols:
            # 表格模式必须单行化：值里带换行会把整张表的对齐冲垮
            def _one_line(v: Any) -> str:
                return re.sub(r"\s*[\r\n]+\s*", " ", cell_text(v)).strip()

            body = [[_one_line((r or {}).get(c, "")) for c in cols] for r in data]
            widths = [max([_disp_width(c)] + [_disp_width(r[i]) for r in body])
                      for i, c in enumerate(cols)]
            lines.append("  ".join(_pad(c, widths[i]) for i, c in enumerate(cols)))
            lines.append("-" * (sum(widths) + 2 * max(0, len(widths) - 1)))
            for r in body:
                lines.append("  ".join(_pad(r[i], widths[i]) for i in range(len(cols))))
    lines.append("=" * 40)
    lines.append("导出时间：%s" % _now())
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _now() -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ======================================================================
# 5. XML / YAML
# ======================================================================
_XML_NAME_BAD = re.compile(r"[^0-9A-Za-z_.\-\u00b7\u00c0-\uffff]")


def _xml_tag(name: str, index: int) -> str:
    """把任意列名变成合法 XML 标签名。"""
    t = _XML_NAME_BAD.sub("_", (name or "").strip())
    t = t.strip("_") or ("field_%d" % index)
    if not re.match(r"[A-Za-z_\u00c0-\uffff]", t):
        t = "f_" + t
    return t


def export_xml(rows: List[dict], columns: Optional[List[str]], path: str) -> None:
    """写 XML：``<results><row index="1"><字段>值</字段></row></results>``。"""
    _ensure_parent(path)
    cols = resolve_columns(rows, columns)
    tags = []
    used: Dict[str, int] = {}
    for i, c in enumerate(cols):
        t = _xml_tag(c, i)
        used[t] = used.get(t, 0) + 1
        if used[t] > 1:
            t = "%s_%d" % (t, used[t])
        tags.append(t)
    data = list(rows or [])
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<results count="%d" generator="SmartCrawler">' % len(data)]
    for i, row in enumerate(data):
        out.append('  <row index="%d">' % (i + 1))
        for c, t in zip(cols, tags):
            out.append("    <%s>%s</%s>"
                       % (t, _xml_escape(_sanitize_xml_text(cell_text((row or {}).get(c, "")))), t))
        out.append("  </row>")
    out.append("</results>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


_YAML_PLAIN_OK = re.compile(r"^[^\s#&*!|>'\"%@`{}\[\],:?\-][^#\r\n]*$")
_YAML_LOOKS_SPECIAL = re.compile(
    r"^(?:[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|true|false|null|yes|no|on|off|~)$",
    re.IGNORECASE)


def _yaml_scalar(v: Any, indent: int = 0) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (dict, list)):
        return _yaml_inline(v, indent)
    s = cell_text(v)
    if s == "":
        return '""'
    if ("\n" in s or "\r" in s or s != s.strip()
            or _YAML_LOOKS_SPECIAL.match(s)
            or not _YAML_PLAIN_OK.match(s)
            or s.endswith(":") or ": " in s):
        return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return s


def _yaml_inline(v: Any, indent: int = 0) -> str:
    if isinstance(v, dict):
        if not v:
            return "{}"
        return "{" + ", ".join("%s: %s" % (_yaml_scalar(k, indent),
                                           _yaml_scalar(x, indent))
                               for k, x in v.items()) + "}"
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[" + ", ".join(_yaml_scalar(x, indent) for x in v) + "]"
    return _yaml_scalar(v, indent)


def export_yaml(rows: List[dict], columns: Optional[List[str]], path: str) -> None:
    """写 YAML 列表（覆盖标量 / 嵌套映射 / 列表，够本项目的数据形状用）。"""
    _ensure_parent(path)
    cols = resolve_columns(rows, columns)
    data = list(rows or [])
    lines = ["# SmartCrawler 导出 · %d 条 · %s" % (len(data), _now())]
    for row in data:
        row = row or {}
        first = True
        for c in cols:
            v = row.get(c, None)
            prefix = "- " if first else "  "
            first = False
            if isinstance(v, (dict, list)) and v:
                lines.append("%s%s:" % (prefix, _yaml_scalar(c)))
                lines.append("    " + _yaml_inline(v))
            else:
                lines.append("%s%s: %s" % (prefix, _yaml_scalar(c), _yaml_scalar(v)))
        if first:                       # 空行（没有任何列）
            lines.append("- {}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ======================================================================
# 6. SQLite
# ======================================================================
_SQL_TYPE_INT = re.compile(r"^-?\d+$")
_SQL_TYPE_FLOAT = re.compile(r"^-?\d*\.\d+(?:[eE][-+]?\d+)?$")


def _sql_ident(name: str, index: int) -> str:
    n = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff]", "_", (name or "").strip())
    if not n or n[0].isdigit():
        n = "c_%d_%s" % (index, n) if n else "c_%d" % index
    return n


def _sql_type(values: List[Any]) -> str:
    """按列的值分布推断列类型。

    整数是实数的子集：``[1, 2.5]`` 必须是 REAL 而不是退回 TEXT —— 之前用
    「两个布尔量都翻过就算不出来」的写法，混合数字列会静默变成字符串列，
    之后在 SQLite 里排序 / 比较就都不对了。
    """
    all_int = all_num = False
    for v in values:
        if v is None or v == "":
            continue
        if isinstance(v, bool):
            kind = "int"
        elif isinstance(v, int):
            kind = "int"
        elif isinstance(v, float):
            kind = "float"
        else:
            s = cell_text(v)
            if _SQL_TYPE_INT.match(s):
                kind = "int"
            elif _SQL_TYPE_FLOAT.match(s):
                kind = "float"
            else:
                return "TEXT"
        if not all_num:
            all_num, all_int = True, True
        if kind == "float":
            all_int = False
    if not all_num:
        return "TEXT"
    return "INTEGER" if all_int else "REAL"


def export_sqlite(rows: List[dict], columns: Optional[List[str]], path: str,
                  table: str = "results") -> None:
    """写 SQLite 数据库（表名默认 results，列为 TEXT/INTEGER/REAL 自动推断）。"""
    _ensure_parent(path)
    cols = resolve_columns(rows, columns)
    data = list(rows or [])
    names, used = [], {}
    for i, c in enumerate(cols):
        n = _sql_ident(c, i)
        used[n] = used.get(n, 0) + 1
        if used[n] > 1:
            n = "%s_%d" % (n, used[n])
        names.append(n)
    types = [_sql_type([(r or {}).get(c) for r in data]) for c in cols]
    tbl = _sql_ident(table, 0)

    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute("DROP TABLE IF EXISTS %s" % tbl)
        if names:
            cols_sql = ", ".join('"%s" %s' % (n, t) for n, t in zip(names, types))
            conn.execute('CREATE TABLE "%s" (%s)' % (tbl, cols_sql))
            placeholders = ", ".join("?" for _ in names)
            conn.executemany(
                'INSERT INTO "%s" (%s) VALUES (%s)'
                % (tbl, ", ".join('"%s"' % n for n in names), placeholders),
                [tuple(_sql_value((r or {}).get(c)) for c in cols) for r in data])
            # 第一列建索引：按主字段查行是实际使用中最常见的操作
            # （注意 rowid 是隐式列，不能直接 CREATE INDEX ... (rowid)）
            conn.execute('CREATE INDEX "idx_%s_first" ON "%s" ("%s")'
                         % (tbl, tbl, names[0]))
        conn.commit()
    finally:
        conn.close()


def _sql_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float, str)):
        return v
    return cell_text(v)


# ======================================================================
# 统一入口
# ======================================================================
_TABLE_WRITERS = {
    "csv": export_csv,
    "tsv": export_tsv,
    "jsonl": export_jsonl,
    "xlsx": export_xlsx,
    "md": export_markdown,
    "html": export_html,
    "txt": export_txt,
    "xml": export_xml,
    "yaml": export_yaml,
    "sqlite": export_sqlite,
}


def export_any(rows: List[dict], columns: Optional[List[str]], path: str,
               fmt: Optional[str] = None) -> str:
    """按格式（或缺省按扩展名）导出，返回实际使用的格式 key。"""
    key = normalize_format(fmt) if fmt else format_for_path(path)
    if key == "json":
        export_json(list(rows or []), path)
        return key
    writer = _TABLE_WRITERS.get(key)
    if writer is None:
        raise ValueError("不支持的导出格式：%s（可用：%s）"
                         % (fmt or key, "、".join(EXPORT_FORMAT_KEYS)))
    writer(list(rows or []), columns, path)
    return key


def export_single(row: dict, path: str, fmt: Optional[str] = None,
                  columns: Optional[Sequence[str]] = None) -> str:
    """导出**单条**记录。

    - json / yaml：写成「一个对象」而不是单元素数组（单条导出要能直接读）；
    - 其余格式：写成只有一行的表（txt 自动变成「字段：值」清单）。
    """
    key = normalize_format(fmt) if fmt else format_for_path(path)
    r = row or {}
    cols = resolve_columns([r], columns)
    if key == "json":
        export_json(r, path)
        return key
    if key == "yaml":
        export_yaml([r], cols, path)
        return key
    writer = _TABLE_WRITERS.get(key)
    if writer is None:
        raise ValueError("不支持的导出格式：%s" % (fmt or key))
    writer([r], cols, path)
    return key


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


__all__ = [
    "EXPORT_FORMATS", "EXPORT_FORMAT_KEYS", "EXPORT_LABELS", "EXPORT_EXTS",
    "file_filter", "all_file_filter", "normalize_format", "format_for_path",
    "cell_text", "resolve_columns",
    "export_csv", "export_tsv", "export_json", "export_jsonl", "export_xlsx",
    "export_markdown", "export_html", "export_txt", "export_xml",
    "export_yaml", "export_sqlite",
    "export_any", "export_single", "export_cookies", "import_cookies",
]
