#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 MHTML（浏览器「另存为单个网页」）导出为纯文本。

用途：用户经常把与 AI 的对话记录存成 ``.mhtml`` 发过来（例如那份
「pip 选项位置错误」的排障记录）。这类文件要读的是**正文**，
而它外面裹着 MIME + quoted-printable + HTML 标签，直接打开是乱码，
所以留一个小工具做提取。

用法::

    .venv\\Scripts\\python.exe tools\\mhtml_to_text.py <输入.mhtml> <输出.txt>

MHTML 就是把多个 MIME part 拼在一个文件里，HTML part 常见是
quoted-printable + gbk/utf-8。这里用 email 模块拆 part，再用正则去标签。
提取结果里还会有大量导航栏噪声（对话列表等），自己挑需要的段落看。
"""
import email
import html
import quopri
import re
import sys


def decode_part(part):
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    for enc in (charset, "utf-8", "gbk", "latin-1"):
        try:
            return payload.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return payload.decode("utf-8", "replace")


def html_to_text(src):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", src)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|pre|blockquote)>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "- ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = s.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def main():
    raw = open(sys.argv[1], "rb").read()
    msg = email.message_from_bytes(raw)
    chunks = []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/html", "text/plain"):
            continue
        text = decode_part(part)
        if ctype == "text/html":
            text = html_to_text(text)
        text = quopri.decodestring(text.encode("latin-1", "ignore")).decode(
            "utf-8", "ignore") if "=E" in text[:4000] else text
        if text.strip():
            chunks.append(text)
    out = "\n\n" + ("=" * 70 + "\n").join(chunks)
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        fh.write(out)
    print("parts=%d chars=%d -> %s" % (len(chunks), len(out), sys.argv[2]))


if __name__ == "__main__":
    main()
