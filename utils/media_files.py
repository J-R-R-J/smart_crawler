# -*- coding: utf-8 -*-
"""把结果里的媒体链接导出成**真实文件**。

数据区右键「导出此条的文件」和底部「导出文件…」都走这里。三条路径：

1. **本地已有** —— 浏览器抓取时下载到 ``crawler_data\\downloads``，直接复制过去
   （不重复消耗流量，也不怕链接过期）；
2. **本地没有** —— 用标准库 urllib 下载（带上与浏览器一致的请求头，
   见 core.headers），落盘时按响应 Content-Type 补扩展名；
3. **内联 data: URL** —— base64 直接解码写文件（有些站点的图片是内联的）。

``blob:`` / ``about:`` 这类只在页面内有效的地址导出不了，会被标成 skipped
并给出原因 —— 静默丢文件比报错更难查。
"""

import base64
import hashlib
import mimetypes
import os
import re
import shutil
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

from config.constants import DOWNLOAD_DIR
from config.default_settings import (
    ALL_MEDIA_EXTS, ARCHIVE_EXTS, AUDIO_EXTS, DOC_EXTS, IMAGE_EXTS, VIDEO_EXTS,
)

#: 「像文件」的扩展名：媒体 + 文档 + 压缩包。只有这些（或带媒体信息的列名、
#: 或 data: 内联数据）才算可导出的文件；普通网页链接（/note/123 这种）
#: 不在此列 —— 否则右键菜单会把每条记录都算成「有 1 个文件」。
FILE_EXTS = tuple(dict.fromkeys(ALL_MEDIA_EXTS + DOC_EXTS + tuple(ARCHIVE_EXTS)))

# ======================================================================
# 常量
# ======================================================================
_URL_RE = re.compile(r"^(?:https?:)?//", re.IGNORECASE)
_DATA_RE = re.compile(r"^data:", re.IGNORECASE)
_LOCAL_ONLY_RE = re.compile(r"^(?:blob|about|javascript|chrome|file):", re.IGNORECASE)

_KIND_BY_EXT: Dict[str, str] = {}
for _k, _exts in (("image", IMAGE_EXTS), ("video", VIDEO_EXTS), ("audio", AUDIO_EXTS)):
    for _e in _exts:
        _KIND_BY_EXT.setdefault(_e, _k)

#: 字段名里出现这些词时，即使 URL 没有扩展名也能判断类型
_KIND_HINTS = (
    ("image", ("image", "img", "pic", "photo", "poster", "thumb", "cover",
               "avatar", "logo", "icon", "banner", "图片", "头像", "封面", "缩略")),
    ("video", ("video", "movie", "film", "play", "m3u8", "mpd", "视频", "影片")),
    ("audio", ("audio", "music", "sound", "voice", "mp3", "音频", "音乐", "语音")),
)

_MIME_EXT = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
    "image/webp": ".webp", "image/avif": ".avif", "image/svg+xml": ".svg",
    "image/bmp": ".bmp", "image/x-icon": ".ico", "image/tiff": ".tiff",
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
    "video/x-matroska": ".mkv", "video/mpeg": ".mpeg", "video/x-msvideo": ".avi",
    "video/mp2t": ".ts", "application/vnd.apple.mpegurl": ".m3u8",
    "application/x-mpegurl": ".m3u8", "application/dash+xml": ".mpd",
    "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/aac": ".aac",
    "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/flac": ".flac",
    "audio/ogg": ".ogg", "audio/opus": ".opus", "audio/webm": ".weba",
    "application/pdf": ".pdf", "application/zip": ".zip",
    "application/json": ".json", "text/plain": ".txt",
    "application/octet-stream": "",
}

#: Windows 不允许出现在文件名里的字符（含控制字符）
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "com5",
             "com6", "com7", "com8", "com9", "lpt1", "lpt2", "lpt3", "lpt4",
             "lpt5", "lpt6", "lpt7", "lpt8", "lpt9"}
_MAX_NAME = 150
_CHUNK = 256 * 1024


class MediaRef(NamedTuple):
    """一条待导出的媒体：来自哪一列、原始 URL、类型、建议文件名。"""
    field: str
    url: str
    kind: str          # image / video / audio / file
    filename: str


# ======================================================================
# 识别
# ======================================================================
def _path_of(url: str) -> str:
    """取 URL 的路径部分（去掉查询串与锚点，data: 除外）。"""
    if _DATA_RE.match(url):
        return url
    p = urllib.parse.urlsplit(url if "://" in url else "https:" + url)
    return p.path or ""


def ext_of(url: str) -> str:
    """URL 的扩展名（小写、不含点）；没有则空串。"""
    if _DATA_RE.match(url):
        m = re.match(r"data:([\w.+-]+/[\w.+-]+)", url)
        if m:
            return _MIME_EXT.get(m.group(1).lower(), "").lstrip(".")
        return ""
    path = _path_of(url)
    base = os.path.basename(urllib.parse.unquote(path))
    ext = os.path.splitext(base)[1].lstrip(".").lower()
    return ext if re.match(r"^[a-z0-9]{1,8}$", ext or "") else ""


def kind_of(url: str, field: str = "") -> str:
    """判断媒体类型：优先扩展名，其次字段名提示，最后 file。"""
    ext = ext_of(url)
    if ext in _KIND_BY_EXT:
        return _KIND_BY_EXT[ext]
    low = (field or "").lower()
    for kind, words in _KIND_HINTS:
        if any(w in low for w in words):
            return kind
    if _DATA_RE.match(url):
        m = re.match(r"data:([\w.+-]+)/", url)
        if m:
            major = m.group(1).lower()
            if major in ("image", "video", "audio"):
                return major
    return "file"


def iter_urls(value: Any) -> Iterable[str]:
    """递归取出字符串 / 列表 / 字典里的 URL（内嵌 JSON 常把地址埋在数组里）。"""
    if isinstance(value, str):
        v = value.strip()
        if v and (_URL_RE.match(v) or _DATA_RE.match(v) or _LOCAL_ONLY_RE.match(v)):
            yield v
    elif isinstance(value, dict):
        for v in value.values():
            yield from iter_urls(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from iter_urls(v)


def row_files(row: dict) -> List[MediaRef]:
    """列出一行里所有可导出的文件（同 URL 去重，保留首次出现的列名）。"""
    if not isinstance(row, dict):
        return []
    out: List[MediaRef] = []
    seen = set()
    for field, value in row.items():
        field = str(field)
        if field.startswith("_"):          # _mode 之类的内部字段
            continue
        for url in iter_urls(value):
            key = url.strip()
            if key in seen or not is_exportable(key, field):
                continue
            seen.add(key)
            kind = kind_of(key, field)
            out.append(MediaRef(field=field, url=key,
                                kind=kind, filename=filename_for(key, kind)))
    return out


def has_files(row: dict) -> bool:
    return bool(row_files(row))


def is_exportable(url: str, field: str = "") -> bool:
    """是否算「可导出的文件」。

    判据（任一成立）：内联 data:；扩展名在媒体/文档/压缩包清单里；
    列名本身带媒体信息（``图片1`` / ``封面图`` / ``video_url`` 之类）。
    普通网页链接不算 —— 它们由「在浏览器中打开链接」负责。
    """
    if _DATA_RE.match(url):
        return True
    ext = ext_of(url)
    if ext and ext in FILE_EXTS:
        return True
    low = (field or "").lower()
    return any(w in low for _kind, words in _KIND_HINTS for w in words)


def first_openable(row: dict) -> Optional[MediaRef]:
    """挑一个「最适合直接打开」的引用（非 file 类型优先）。"""
    refs = row_files(row)
    for r in refs:
        if r.kind != "file":
            return r
    return refs[0] if refs else None


def row_links(row: dict) -> List[Tuple[str, str]]:
    """页面链接（列名, URL），供「在浏览器打开」用（协议相对地址补上 https:）。"""
    out = []
    if not isinstance(row, dict):
        return out
    for field, value in row.items():
        for url in iter_urls(value):
            if _URL_RE.match(url) and not _DATA_RE.match(url):
                out.append((str(field), normalize_url(url)))
    return out


def normalize_url(url: str) -> str:
    """``//host/path`` -> ``https://host/path``（浏览器能打开，urllib 也能下）。"""
    u = (url or "").strip()
    return "https:" + u if u.startswith("//") else u


# ======================================================================
# 文件名
# ======================================================================
def safe_name(name: str, fallback: str = "") -> str:
    """清洗成 Windows 合法文件名（非法字符替换、去尾点/空格、避开保留名）。"""
    n = _BAD_CHARS.sub("_", (name or "").strip())
    n = n.strip().rstrip(". ")
    if len(n) > _MAX_NAME:
        stem, ext = os.path.splitext(n)
        n = stem[:_MAX_NAME - len(ext)] + ext
    if not n:
        n = fallback
    if n and os.path.splitext(n)[0].lower() in _RESERVED:
        n = "_" + n
    return n


def filename_for(url: str, kind: str = "") -> str:
    """由 URL 推一个文件名；拿不到名字时用内容哈希兜底（同名不同文件不会互相覆盖）。"""
    if _DATA_RE.match(url):
        ext = ("." + ext_of(url)) if ext_of(url) else ""
        return "inline_%s%s" % (hashlib.sha1(url.encode("utf-8", "replace")).hexdigest()[:10], ext)
    if _LOCAL_ONLY_RE.match(url):
        return ""
    path = _path_of(url)
    base = os.path.basename(urllib.parse.unquote(path))
    base = safe_name(base)
    if base and base not in (".", ".."):
        return base
    digest = hashlib.sha1(url.encode("utf-8", "replace")).hexdigest()[:10]
    prefix = {"image": "image", "video": "video", "audio": "audio"}.get(kind, "file")
    return "%s_%s" % (prefix, digest)


def unique_path(dest_dir: str, name: str, taken: set) -> str:
    """在目标目录里找一个不冲突的文件名（同名加 -1 / -2…）。"""
    candidate = name
    stem, ext = os.path.splitext(name)
    i = 0
    while True:
        key = candidate.lower()
        if key not in taken and not os.path.exists(os.path.join(dest_dir, candidate)):
            taken.add(key)
            return os.path.join(dest_dir, candidate)
        i += 1
        candidate = "%s-%d%s" % (stem, i, ext)


# ======================================================================
# 本地查找
# ======================================================================
def _candidate_names(url: str) -> List[str]:
    name = filename_for(url)
    if not name:
        return []
    out = [name, urllib.parse.unquote(name), safe_name(urllib.parse.unquote(name))]
    stem, ext = os.path.splitext(name)
    out.append(stem.replace("_", " ") + ext)
    return list(dict.fromkeys(n for n in out if n))


def find_local(url: str, search_dirs: Sequence[str] = ()) -> Optional[str]:
    """在下载目录里找这个 URL 已经落盘的文件（浏览器下载的文件名可能与 URL 略有差异）。"""
    dirs = [d for d in list(search_dirs or []) + [DOWNLOAD_DIR] if d and os.path.isdir(d)]
    names = _candidate_names(url)
    if not names:
        return None
    wanted = {n.lower() for n in names}
    for d in dirs:
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for entry in entries:
            if entry.lower() in wanted:
                full = os.path.join(d, entry)
                if os.path.isfile(full):
                    return full
    return None


# ======================================================================
# 下载
# ======================================================================
def request_headers(url: str) -> Dict[str, str]:
    """带浏览器风格的请求头（复用 core.headers 的一致性规则）。"""
    try:
        from core.headers import build_headers
        return dict(build_headers(url, kind="document"))
    except Exception:
        ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
        return {"User-Agent": ua, "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}


def download_url(url: str, dest_path: str, timeout: float = 30.0,
                 should_stop: Optional[Callable[[], bool]] = None) -> Tuple[str, int]:
    """下载到 ``dest_path``，返回 ``(最终路径, 字节数)``。

    先写 ``.part`` 再改名：中途失败不会留下一个「看起来完整」的坏文件。
    文件名没有扩展名时按响应 Content-Type 补一个。
    """
    if _URL_RE.match(url) and url.startswith("//"):
        url = normalize_url(url)
    path_dir = os.path.dirname(os.path.abspath(dest_path))
    if path_dir:
        os.makedirs(path_dir, exist_ok=True)
    tmp = dest_path + ".part"
    req = urllib.request.Request(url, headers=request_headers(url))
    written = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310
        ctype = (resp.headers.get_content_type() or "").lower()
        with open(tmp, "wb") as fh:
            while True:
                if should_stop and should_stop():
                    raise InterruptedError("已取消")
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                written += len(chunk)
    final = dest_path
    if not os.path.splitext(final)[1]:
        ext = _MIME_EXT.get(ctype) or (mimetypes.guess_extension(ctype) or "")
        if ext:
            final = final + ext
    if os.path.exists(final):
        os.remove(final)
    os.replace(tmp, final)
    return final, written


def export_ref(ref: MediaRef, dest_dir: str, overwrite: bool = False,
               timeout: float = 30.0, taken: Optional[set] = None,
               search_dirs: Sequence[str] = (), dest_file: str = "",
               should_stop: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    """导出一个引用，返回 ``{url, path, status, size, reason}``。

    status: copied（从下载目录复制）/ downloaded / exists（已存在）/ skipped / failed

    ``dest_file`` 非空时按**指定路径**落盘（「另存为…」用），否则在 ``dest_dir``
    里按文件名去重生成。
    """
    out: Dict[str, Any] = {"url": ref.url, "field": ref.field, "kind": ref.kind,
                           "path": "", "status": "", "size": 0, "reason": ""}
    url = (ref.url or "").strip()
    os.makedirs(dest_dir, exist_ok=True)
    taken = taken if taken is not None else set()

    # ---- 页面内地址：导出不了 ----
    if _LOCAL_ONLY_RE.match(url) and not _DATA_RE.match(url):
        out.update(status="skipped",
                   reason="页面内临时地址（%s），无法在页面外导出"
                          % url.split(":", 1)[0])
        return out

    name = ref.filename or filename_for(url, ref.kind) or "file"

    def _target() -> str:
        if dest_file:
            parent = os.path.dirname(os.path.abspath(dest_file))
            if parent:
                os.makedirs(parent, exist_ok=True)
            return dest_file
        return unique_path(dest_dir, name, taken)

    # ---- 本地已有：直接复制 ----
    local = find_local(url, search_dirs)
    dest = _target()
    if local:
        if os.path.exists(dest) and not overwrite:
            out.update(status="exists", path=dest, size=os.path.getsize(dest))
            return out
        shutil.copy2(local, dest)
        out.update(status="copied", path=dest, size=os.path.getsize(dest))
        return out

    # ---- 内联 data: URL：解码写盘 ----
    if _DATA_RE.match(url):
        try:
            head, _, payload = url.partition(",")
            raw = (base64.b64decode(payload) if "base64" in head.lower()
                   else urllib.parse.unquote_to_bytes(payload))
            with open(dest, "wb") as fh:
                fh.write(raw)
            out.update(status="downloaded", path=dest, size=len(raw))
        except Exception as e:                       # noqa: BLE001
            out.update(status="failed", reason="内联数据解码失败：%s" % e)
        return out

    if not _URL_RE.match(url):
        out.update(status="skipped", reason="不是可下载的地址")
        return out

    # ---- 网络下载 ----
    try:
        final, size = download_url(url, dest, timeout=timeout, should_stop=should_stop)
        out.update(status="downloaded", path=final, size=size)
    except InterruptedError as e:
        out.update(status="skipped", reason=str(e))
        _cleanup_partials(dest)
    except Exception as e:                           # noqa: BLE001
        out.update(status="failed", reason="%s: %s" % (type(e).__name__, e))
        _cleanup_partials(dest)
    return out


def _cleanup_partials(dest: str) -> None:
    """删掉失败/取消时可能留下的半成品（.part 与目标文件）。"""
    for leftover in (dest, dest + ".part"):
        try:
            if os.path.exists(leftover):
                os.remove(leftover)
        except OSError:
            pass


# ======================================================================
# 批量导出
# ======================================================================
def collect_refs(rows: Sequence[dict], include_kinds: Sequence[str] = ()) -> List[MediaRef]:
    """把多行的文件引用汇总去重（同 URL 只导一次）。"""
    wanted = {k for k in include_kinds if k}
    out: List[MediaRef] = []
    seen = set()
    for row in rows or []:
        for ref in row_files(row):
            if wanted and ref.kind not in wanted:
                continue
            key = ref.url.strip()
            if key in seen:
                continue
            seen.add(key)
            out.append(ref)
    return out


def export_refs(refs: Sequence[MediaRef], dest_dir: str, overwrite: bool = False,
                timeout: float = 30.0, search_dirs: Sequence[str] = (),
                dest_file: str = "",
                on_progress: Optional[Callable[[int, int, MediaRef], None]] = None,
                should_stop: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    """批量导出，返回汇总报告（含逐项结果与失败原因）。

    ``dest_file`` 只对单项导出有意义（「另存为…」），多项时忽略。
    """
    refs = list(refs or [])
    os.makedirs(dest_dir, exist_ok=True)
    taken: set = set()
    items: List[Dict[str, Any]] = []
    total_bytes = 0
    for i, ref in enumerate(refs, 1):
        if on_progress:
            try:
                on_progress(i, len(refs), ref)
            except Exception:                        # noqa: BLE001
                pass
        if should_stop and should_stop():
            items.append({"url": ref.url, "field": ref.field, "kind": ref.kind,
                          "path": "", "status": "skipped", "size": 0,
                          "reason": "用户取消"})
            continue
        item = export_ref(ref, dest_dir, overwrite=overwrite, timeout=timeout,
                          taken=taken, search_dirs=search_dirs,
                          dest_file=dest_file if len(refs) == 1 else "",
                          should_stop=should_stop)
        total_bytes += int(item.get("size") or 0)
        items.append(item)
    return {"total": len(refs), "dest_dir": dest_dir, "items": items,
            "bytes": total_bytes,
            "copied": sum(1 for i in items if i["status"] == "copied"),
            "downloaded": sum(1 for i in items if i["status"] == "downloaded"),
            "exists": sum(1 for i in items if i["status"] == "exists"),
            "skipped": [i for i in items if i["status"] == "skipped"],
            "failed": [i for i in items if i["status"] == "failed"],
            "ok": sum(1 for i in items
                      if i["status"] in ("copied", "downloaded", "exists")),
            "time": time.strftime("%Y-%m-%d %H:%M:%S")}


def human_size(n: int) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.0f %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return "%.1f GB" % n


def summary_text(report: Dict[str, Any]) -> str:
    """报告摘要（界面与日志共用同一段文字，避免两处口径不一致）。"""
    lines = ["目标目录：%s" % report.get("dest_dir", ""),
             "共 %d 个文件：成功 %d（复制 %d / 下载 %d / 已存在 %d），"
             "跳过 %d，失败 %d，合计 %s"
             % (report.get("total", 0), report.get("ok", 0),
                report.get("copied", 0), report.get("downloaded", 0),
                report.get("exists", 0), len(report.get("skipped") or []),
                len(report.get("failed") or []),
                human_size(report.get("bytes", 0)))]
    for label, key in (("跳过", "skipped"), ("失败", "failed")):
        for item in (report.get(key) or [])[:10]:
            lines.append("  %s：%s —— %s"
                         % (label, item.get("url", "")[:120], item.get("reason", "")))
    return "\n".join(lines)


__all__ = [
    "MediaRef", "FILE_EXTS", "ext_of", "kind_of", "iter_urls", "is_exportable",
    "row_files", "has_files",
    "first_openable", "row_links", "normalize_url", "safe_name", "filename_for",
    "unique_path", "find_local", "request_headers", "download_url", "export_ref",
    "collect_refs", "export_refs", "human_size", "summary_text",
    "IMAGE_EXTS", "VIDEO_EXTS", "AUDIO_EXTS",
]
