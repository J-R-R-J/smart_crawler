# -*- coding: utf-8 -*-
"""core.cookie_manager —— Cookie 增删查、导入导出与变更通知。

- 首次 loadAllCookies()（异步）用 QEventLoop 阻塞等待完成；
- cookieAdded / cookieRemoved 触发缓存刷新并 emit cookies_changed(list_cookies())；
- 会话 cookie 判定：QNetworkCookie.isSessionCookie()；
- 多 Profile：把当前 cookie 集按 profile 名持久化到
  PROFILE_DIR/<name>/cookies.json，switch_profile 负责 保存→清空→载入。
"""

import os

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal
from PySide6.QtNetwork import QNetworkCookie

from config.constants import PROFILE_DIR
from utils.exporters import export_cookies, import_cookies
from utils.logger import log_info, log_warn


def _qba_to_str(value) -> str:
    """QByteArray → str（安全解码）。"""
    if value is None:
        return ""
    try:
        return bytes(value).decode("utf-8", "replace")
    except Exception:
        return ""


class CookieManager(QObject):
    cookies_changed = Signal(list)      # list[dict]

    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self._profile = profile
        self.store = profile.cookieStore()
        # 缓存：完整 QNetworkCookie 对象（供 deleteCookie 使用）
        self._raw = {}        # (name, domain, path) -> QNetworkCookie
        self._cookies = {}    # (name, domain, path) -> dict
        self._loaded = False
        self._profile_name = "default"

        self.store.cookieAdded.connect(lambda *a: self._on_cookie_added(a[0]))
        self.store.cookieRemoved.connect(lambda *a: self._on_cookie_removed(a[0]))

        # 变更后延迟持久化（去抖），保证切换/重启后 cookie 不丢
        self._persist_timer = QTimer(self)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.setInterval(600)
        self._persist_timer.timeout.connect(self._persist)

        self._load_initial()

    # --------------------------------------------------------------
    # 初始加载（阻塞，仅首次）
    # --------------------------------------------------------------
    def _load_initial(self) -> None:
        """QEventLoop 阻塞等待首次 loadAllCookies 的 cookieAdded 批次结束。"""
        if self._loaded:
            return
        self._loaded = True
        loop = QEventLoop(self)
        settle = QTimer(self)
        settle.setSingleShot(True)
        settle.setInterval(300)
        settle.timeout.connect(loop.quit)

        def _on_batch_cookie(_cookie):
            settle.start()   # 静默期重计：300ms 无新 cookie 即结束等待

        try:
            self.store.cookieAdded.connect(_on_batch_cookie)
            self.store.loadAllCookies()
            settle.start()
            loop.exec()
            self.store.cookieAdded.disconnect(_on_batch_cookie)
        except Exception as e:
            log_warn(f"[cookie] 初始加载异常：{e}")

    # --------------------------------------------------------------
    # 内部缓存维护
    # --------------------------------------------------------------
    def _key(self, cookie: QNetworkCookie):
        return (_qba_to_str(cookie.name()), cookie.domain(), cookie.path())

    def _on_cookie_added(self, cookie) -> None:
        try:
            key = self._key(cookie)
            self._raw[key] = QNetworkCookie(cookie)   # 拷贝，保持对象稳定
            self._cookies[key] = self._to_dict(cookie)
            self.cookies_changed.emit(self.list_cookies())
            self._schedule_persist()
        except RuntimeError:
            pass   # 关闭阶段对象已销毁，忽略

    def _on_cookie_removed(self, cookie) -> None:
        try:
            key = self._key(cookie)
            self._raw.pop(key, None)
            self._cookies.pop(key, None)
            self.cookies_changed.emit(self.list_cookies())
            self._schedule_persist()
        except RuntimeError:
            pass   # 关闭阶段对象已销毁，忽略

    @staticmethod
    def _to_dict(cookie: QNetworkCookie) -> dict:
        return {
            "name": _qba_to_str(cookie.name()),
            "value": _qba_to_str(cookie.value()),
            "domain": cookie.domain() or "",
            "path": cookie.path() or "/",
            "secure": bool(cookie.isSecure()),
            "http_only": bool(cookie.isHttpOnly()),
            "session": bool(cookie.isSessionCookie()),
        }

    # --------------------------------------------------------------
    # 查询
    # --------------------------------------------------------------
    def list_cookies(self) -> list:
        """返回 [{name,value,domain,path,secure,http_only,session}]，按 domain,path,name 排序。"""
        out = []
        for key in sorted(self._cookies, key=lambda k: (k[1], k[2], k[0])):
            out.append(dict(self._cookies[key]))
        return out

    # --------------------------------------------------------------
    # 增删
    # --------------------------------------------------------------
    def add_cookie(self, name, value, domain, path="/", secure=False,
                   http_only=False) -> bool:
        """组装 QNetworkCookie 写入 store；name/domain 为空返回 False。"""
        if not name or not domain:
            return False
        cookie = QNetworkCookie()
        cookie.setName(str(name).encode("utf-8", "replace"))
        cookie.setValue(str(value).encode("utf-8", "replace"))
        cookie.setDomain(str(domain))
        cookie.setPath(str(path) if path else "/")
        cookie.setSecure(bool(secure))
        cookie.setHttpOnly(bool(http_only))
        # 不设置过期时间 → 会话 cookie
        self.store.setCookie(cookie)
        return True

    def delete_cookie(self, name: str, domain: str, path: str = "/") -> bool:
        """用缓存中的完整 QNetworkCookie 对象删除；找不到返回 False。

        Qt 会把 domain 规范化为带前导点（example.com → .example.com），
        这里对带/不带前导点两种写法都做匹配，避免删不掉。
        """
        path = path or "/"
        cookie = self._raw.get((name, domain, path))
        if cookie is None and domain and not domain.startswith("."):
            cookie = self._raw.get((name, "." + domain, path))
        if cookie is None and domain and domain.startswith("."):
            cookie = self._raw.get((name, domain[1:], path))
        if cookie is None:
            return False
        self.store.deleteCookie(cookie)
        return True

    def clear_all(self) -> None:
        self.store.deleteAllCookies()
        self._raw.clear()
        self._cookies.clear()
        self.cookies_changed.emit(self.list_cookies())
        self._schedule_persist()

    # --------------------------------------------------------------
    # Profile=cookie 集持久化 / 切换
    # --------------------------------------------------------------
    def _cookies_path(self, name: str) -> str:
        return os.path.join(PROFILE_DIR, name, "cookies.json")

    def set_profile_name(self, name: str) -> None:
        self._profile_name = name or "default"

    def _schedule_persist(self) -> None:
        self._persist_timer.start()

    def _persist(self) -> None:
        self.save_to_profile(self._profile_name)

    def save_to_profile(self, name: str) -> int:
        """把当前 cookie 集写到 PROFILE_DIR/<name>/cookies.json，返回条数。"""
        name = name or "default"
        try:
            return export_cookies(self.list_cookies(), self._cookies_path(name))
        except Exception as e:
            log_warn(f"[cookie] 保存 profile '{name}' 失败：{e}")
            return 0

    def load_from_profile(self, name: str) -> int:
        """从 PROFILE_DIR/<name>/cookies.json 载入 cookie 集，返回条数。"""
        name = name or "default"
        path = self._cookies_path(name)
        if not os.path.isfile(path):
            return 0
        try:
            rows = import_cookies(path)
        except Exception as e:
            log_warn(f"[cookie] 载入 profile '{name}' 失败：{e}")
            return 0
        count = 0
        for row in rows:
            try:
                if self.add_cookie(
                        row.get("name", ""),
                        row.get("value", ""),
                        row.get("domain", ""),
                        row.get("path", "/"),
                        bool(row.get("secure", False)),
                        bool(row.get("http_only", False))):
                    count += 1
            except Exception as e:
                log_warn(f"[cookie] 载入 cookie 失败：{e}")
        return count

    def switch_profile(self, name: str) -> int:
        """切换 Profile：保存当前 → 清空 → 载入目标，返回载入条数。"""
        name = name or "default"
        if name == self._profile_name:
            return len(self.list_cookies())
        self.save_to_profile(self._profile_name)
        self.store.deleteAllCookies()
        self._raw.clear()
        self._cookies.clear()
        self._profile_name = name
        n = self.load_from_profile(name)
        self.cookies_changed.emit(self.list_cookies())
        log_info(f"[cookie] 已切换 profile 到 {name}（载入 {n} 条 cookie）")
        return n

    # --------------------------------------------------------------
    # 导入 / 导出
    # --------------------------------------------------------------
    def import_from_file(self, path: str) -> int:
        """utils.exporters.import_cookies + add_cookie 批量写入，返回成功条数。"""
        try:
            rows = import_cookies(path)
        except Exception as e:
            log_warn(f"[cookie] 导入失败：{e}")
            return 0
        count = 0
        for row in rows:
            try:
                if self.add_cookie(
                        row.get("name", ""),
                        row.get("value", ""),
                        row.get("domain", ""),
                        row.get("path", "/"),
                        bool(row.get("secure", False)),
                        bool(row.get("http_only", False))):
                    count += 1
            except Exception as e:
                log_warn(f"[cookie] 写入失败：{e}")
        return count

    def export_to_file(self, path: str) -> int:
        return export_cookies(self.list_cookies(), path)

    # --------------------------------------------------------------
    # 可选扩展：从 Set-Cookie 头写入
    # --------------------------------------------------------------
    def set_from_header(self, url: str, header: str) -> None:
        from PySide6.QtCore import QByteArray, QUrl
        try:
            for cookie in QNetworkCookie.parseCookies(
                    QByteArray(header.encode("utf-8"))):
                cookie.normalize(QUrl(url))
                self.store.setCookie(cookie)
        except Exception as e:
            log_warn(f"[cookie] set_from_header 失败：{e}")
