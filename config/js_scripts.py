# -*- coding: utf-8 -*-
"""内置 JS 脚本与提取 JS 生成器。

全部为模块级字符串常量（纯 JS，r 三引号，避免与 Python 转义冲突）。
- QWEBCHANNEL_JS / PICKER_JS / PICKER_TEARDOWN_JS：桥接与元素拾取
- POPUP_SCAN_JS / POPUP_CLOSE_JS / POPUP_REMOVE_JS：弹窗扫描/关闭/移除
- SCROLL_JS / GET_HTML_JS / GET_TEXT_JS / GET_TITLE_JS：页面工具
- STEALTH_JS：自动化浏览器特征伪装
- build_extract_js()：生成 IIFE 提取脚本，立即执行并返回 JSON 字符串

关键词表 / 关闭选择器表从 config.default_settings 注入（json.dumps），
模板占位符 @@XXX@@ 用一次性正则替换，避免 JS 花括号与 .format 冲突。
"""
import json
import re

from config.default_settings import POPUP_CLOSE_SELECTORS, POPUP_HINT_KEYWORDS

__all__ = [
    "QWEBCHANNEL_JS", "PICKER_JS", "PICKER_TEARDOWN_JS",
    "POPUP_SCAN_JS", "POPUP_CLOSE_JS", "POPUP_REMOVE_JS",
    "SCROLL_JS", "GET_HTML_JS", "GET_TEXT_JS", "GET_TITLE_JS",
    "STEALTH_JS", "CAPTCHA_PROBE_JS", "LOGIN_PROBE_JS",
    "build_extract_js",
]

_PLACEHOLDER_RE = re.compile(
    r"@@(FIELDS|SELECTOR|PATTERN|FLAGS|MODE|POPUP_HINT_KEYWORDS|POPUP_CLOSE_SELECTORS)@@"
)

_BASE_INJECT = {
    "POPUP_HINT_KEYWORDS": json.dumps(POPUP_HINT_KEYWORDS),
    "POPUP_CLOSE_SELECTORS": json.dumps(POPUP_CLOSE_SELECTORS),
}


def _inject(template: str, **values) -> str:
    """一次性替换模板中的 @@TOKEN@@ 占位符（注入值不会被二次扫描）。"""
    merged = dict(_BASE_INJECT)
    merged.update(values)
    return _PLACEHOLDER_RE.sub(lambda m: merged[m.group(1)], template).strip()


# ---------------------------------------------------------------------------
# 反爬特征伪装（DocumentCreation 注入，早于页面脚本执行）
#
# 目的：消除「自动化浏览器」的明显指纹，降低被风控直接拦截的概率。
# 仅做常规浏览器特征对齐，**不包含**验证码识别或绕过逻辑——
# 遇到验证码仍交由人工处理（见 core/crawler 的人机协作流程）。
# ---------------------------------------------------------------------------
STEALTH_JS = r"""
(function(){
    try {
        Object.defineProperty(navigator, 'webdriver', { get: function(){ return undefined; } });
    } catch (e) {}

    try {
        Object.defineProperty(navigator, 'languages', {
            get: function(){ return ['zh-CN', 'zh', 'en-US', 'en']; }
        });
        Object.defineProperty(navigator, 'language', {
            get: function(){ return 'zh-CN'; }
        });
    } catch (e) {}

    try {
        Object.defineProperty(navigator, 'platform', { get: function(){ return 'Win32'; } });
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: function(){ return 8; } });
        Object.defineProperty(navigator, 'deviceMemory', { get: function(){ return 8; } });
        Object.defineProperty(navigator, 'maxTouchPoints', { get: function(){ return 0; } });
    } catch (e) {}

    try {
        if (!navigator.plugins || navigator.plugins.length === 0) {
            var fakePlugins = [
                { name: 'PDF Viewer', filename: 'internal-pdf-viewer' },
                { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer' },
                { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer' }
            ];
            fakePlugins.item = function(i){ return this[i]; };
            fakePlugins.namedItem = function(n){
                for (var i = 0; i < this.length; i++) {
                    if (this[i].name === n) { return this[i]; }
                }
                return null;
            };
            Object.defineProperty(navigator, 'plugins', { get: function(){ return fakePlugins; } });
        }
    } catch (e) {}

    try {
        if (!window.chrome) { window.chrome = {}; }
        if (!window.chrome.runtime) { window.chrome.runtime = {}; }
    } catch (e) {}

    try {
        if (navigator.permissions && navigator.permissions.query) {
            var origQuery = navigator.permissions.query.bind(navigator.permissions);
            navigator.permissions.query = function(params){
                if (params && params.name === 'notifications') {
                    return Promise.resolve({ state: Notification.permission });
                }
                return origQuery(params);
            };
        }
    } catch (e) {}

    try {
        var getParam = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(p){
            if (p === 37445) { return 'Intel Inc.'; }
            if (p === 37446) { return 'Intel Iris OpenGL Engine'; }
            return getParam.apply(this, arguments);
        };
    } catch (e) {}
})();
"""


# ---------------------------------------------------------------------------
# 结构化探测：页面里是否真的存在验证码 / 登录表单
#
# 关键词匹配容易误判（帮助页、说明文字、短信验证码标签都会命中），
# 因此命中关键词后再用本脚本做结构确认：
#   - 验证码输入框（name/id/placeholder 命中 captcha / verify / 验证码 …）
#   - 第三方验证组件 iframe（reCAPTCHA / hCaptcha / Turnstile / Geetest / 网易易盾 …）
#   - 已知的验证组件容器（.g-recaptcha、#challenge-form、.nc-container …）
#   - 滑块类验证元素
# 只统计**可见**元素，避免命中隐藏模板。
#
# 返回 JSON 字符串：{"found": true, "kinds": [...], "details": ["...", ...]}
# ---------------------------------------------------------------------------
CAPTCHA_PROBE_JS = r"""
(function(){
    function visible(el){
        if (!el || el.nodeType !== 1) { return false; }
        var st = window.getComputedStyle(el);
        if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') {
            return false;
        }
        var r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) { return false; }
        return true;
    }

    function qsa(sel){
        try { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
        catch (e) { return []; }
    }

    var kinds = [], details = [];

    function hit(kind, detail){
        if (kinds.indexOf(kind) < 0) { kinds.push(kind); }
        if (details.length < 5 && details.indexOf(detail) < 0) { details.push(detail); }
    }

    // 1) 验证码输入框
    var inputSelectors = [
        'input[name*="captcha" i]', 'input[id*="captcha" i]',
        'input[name*="verify" i]', 'input[id*="verify" i]',
        'input[name*="checkcode" i]', 'input[id*="checkcode" i]',
        'input[name*="vcode" i]', 'input[id*="vcode" i]',
        'input[name*="authcode" i]', 'input[id*="authcode" i]',
        'input[placeholder*="验证码"]', 'input[placeholder*="校验码"]',
        'input[placeholder*="图形码"]', 'input[aria-label*="验证码"]',
        'input[title*="验证码"]'
    ];
    for (var i = 0; i < inputSelectors.length; i++) {
        var els = qsa(inputSelectors[i]);
        for (var j = 0; j < els.length; j++) {
            if (visible(els[j])) {
                hit('input', 'input: ' + inputSelectors[i]);
                break;
            }
        }
    }

    // 2) 第三方验证组件 iframe
    var frameRe = /(recaptcha|hcaptcha|turnstile|geetest|yidun|dingxiang|nc\.js|captcha|challenge|verify)/i;
    var frames = qsa('iframe');
    for (var k = 0; k < frames.length; k++) {
        var src = frames[k].src || frames[k].getAttribute('src') || '';
        if (src && frameRe.test(src) && visible(frames[k])) {
            hit('iframe', 'iframe: ' + src.slice(0, 100));
        }
    }

    // 3) 已知验证组件容器 / 云盾挑战
    var containerSelectors = [
        '.g-recaptcha', '.h-captcha', '.cf-turnstile',
        '#challenge-form', '#challenge-running', '#cf-challenge-running',
        '.geetest_holder', '.geetest_panel', '.geetest_widget',
        '.nc_wrapper', '.nc-container', '#nc_1_wrapper',
        '.yidun_panel', '.yidun_intellisense',
        '[class*="captcha" i]', '[id*="captcha" i]',
        '[class*="verify-box" i]', '[class*="verifybox" i]',
        '[id*="verify-box" i]', '[class*="slide-verify" i]',
        '[class*="slider-verify" i]', '[class*="drag-verify" i]'
    ];
    for (var m = 0; m < containerSelectors.length; m++) {
        var cs = qsa(containerSelectors[m]);
        for (var n = 0; n < cs.length; n++) {
            if (visible(cs[n])) {
                hit('container', 'element: ' + containerSelectors[m]);
                break;
            }
        }
    }

    // 4) 图片验证码：尺寸较小且在疑似验证区域内的 img / canvas
    var imgs = qsa('img');
    for (var p = 0; p < imgs.length; p++) {
        var im = imgs[p];
        if (!visible(im)) { continue; }
        var r = im.getBoundingClientRect();
        var mark = ((im.id || '') + ' ' + (im.className || '') + ' ' +
                    (im.getAttribute('src') || '') + ' ' +
                    (im.getAttribute('alt') || '')).toLowerCase();
        var small = r.width <= 220 && r.height <= 90 && r.width >= 30 && r.height >= 20;
        if (small && /(captcha|verify|code|yzm|checkcode|vcode)/.test(mark)) {
            hit('image', 'img: ' + (im.id || im.className || 'captcha-like'));
            break;
        }
    }

    return JSON.stringify({
        found: kinds.length > 0,
        kinds: kinds,
        details: details
    });
})();
"""


# ---------------------------------------------------------------------------
# 结构化探测：是否存在登录表单（用于确认登录墙）
# 返回 JSON 字符串：{"found": bool, "password": int, "user": int}
# ---------------------------------------------------------------------------
LOGIN_PROBE_JS = r"""
(function(){
    function count(sel){
        try { return document.querySelectorAll(sel).length; } catch (e) { return 0; }
    }
    var pwd = count('input[type="password"]');
    var user = count('input[type="text"][name*="user" i],' +
                     'input[type="email"],' +
                     'input[name*="account" i],' +
                     'input[name*="phone" i],' +
                     'input[name*="mobile" i]');
    return JSON.stringify({ found: pwd > 0, password: pwd, user: user });
})();
"""


# ---------------------------------------------------------------------------
# QWebChannel 桥接（幂等：window.__sc_bridge 已存在则不重复连接）
# ---------------------------------------------------------------------------
QWEBCHANNEL_JS = r"""
(function(){
    if (window.QWebChannel && !window.__sc_bridge) {
        try {
            new QWebChannel(qt.webChannelTransport, function(ch){
                window.__sc_bridge = ch.objects.bridge;
            });
        } catch(e) {}
    }
})();
"""

# ---------------------------------------------------------------------------
# 元素拾取：捕获阶段 click/mouseover 高亮 + CSS 选择器生成，Esc 解除
# ---------------------------------------------------------------------------
PICKER_JS = r"""
(function(){
    if (window.__sc_pickActive) { return; }
    window.__sc_pickActive = true;

    var hl = document.createElement('div');
    hl.id = '__sc_picker_hl';
    hl.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;outline:3px solid #ff4d4f;background:rgba(255,77,79,0.08);display:none;';
    (document.body || document.documentElement).appendChild(hl);

    function esc(s){
        try { return window.CSS && CSS.escape ? CSS.escape(s) : s; }
        catch(e){ return s; }
    }

    function uniqueSelector(el){
        if (!el || el.nodeType !== 1) { return ''; }
        if (el.id) { return '#' + esc(el.id); }
        var parts = [];
        var cur = el;
        while (cur && cur.nodeType === 1 && cur !== document.body && cur !== document.documentElement) {
            if (cur.id) { parts.unshift('#' + esc(cur.id)); break; }
            var part = cur.tagName.toLowerCase();
            if (cur.classList && cur.classList.length) {
                var cls = [];
                for (var i = 0; i < cur.classList.length && cls.length < 2; i++) {
                    var c = cur.classList[i];
                    if (c && !/^\d/.test(c)) { cls.push(c); }
                }
                if (cls.length) { part += '.' + cls.join('.'); }
            }
            if (cur.parentElement && cur.parentElement.children) {
                var sibs = cur.parentElement.children;
                var sameTag = 0, myIdx = 0;
                for (var j = 0; j < sibs.length; j++) {
                    if (sibs[j].tagName === cur.tagName) {
                        sameTag++;
                        if (sibs[j] === cur) { myIdx = sameTag; }
                    }
                }
                if (sameTag > 1) { part += ':nth-of-type(' + myIdx + ')'; }
            }
            parts.unshift(part);
            try {
                if (document.querySelectorAll(parts.join(' > ')).length === 1) { break; }
            } catch(e) { break; }
            cur = cur.parentElement;
        }
        return parts.join(' > ');
    }

    function onOver(e){
        var t = e.target;
        if (!t || t.nodeType !== 1) { return; }
        var r = t.getBoundingClientRect();
        hl.style.display = 'block';
        hl.style.left = r.left + 'px';
        hl.style.top = r.top + 'px';
        hl.style.width = r.width + 'px';
        hl.style.height = r.height + 'px';
    }

    function onClick(e){
        e.preventDefault();
        e.stopPropagation();
        var t = e.target;
        if (!t || t.nodeType !== 1) { return; }
        var sel = uniqueSelector(t);
        var text = (t.innerText || t.textContent || '').trim().slice(0, 200);
        var tag = t.tagName.toLowerCase();
        var href = t.getAttribute ? (t.getAttribute('href') || '') : '';
        try {
            if (window.__sc_bridge && window.__sc_bridge.picked) {
                window.__sc_bridge.picked(sel, text, tag, href);
            }
        } catch(e) {}
        teardown();
    }

    function onKey(e){
        if (e.key === 'Escape' || e.key === 'Esc') {
            e.preventDefault();
            teardown();
        }
    }

    function teardown(){
        window.__sc_pickActive = false;
        var h = window.__sc_pickHandlers;
        if (h) {
            document.removeEventListener('mouseover', h.over, true);
            document.removeEventListener('click', h.click, true);
            document.removeEventListener('keydown', h.key, true);
            window.__sc_pickHandlers = null;
        }
        if (hl && hl.parentNode) { hl.parentNode.removeChild(hl); }
    }

    window.__sc_pickHandlers = {over: onOver, click: onClick, key: onKey};
    document.addEventListener('mouseover', onOver, true);
    document.addEventListener('click', onClick, true);
    document.addEventListener('keydown', onKey, true);
})();
"""

PICKER_TEARDOWN_JS = r"""
(function(){
    window.__sc_pickActive = false;
    var h = window.__sc_pickHandlers;
    if (h) {
        document.removeEventListener('mouseover', h.over, true);
        document.removeEventListener('click', h.click, true);
        document.removeEventListener('keydown', h.key, true);
        window.__sc_pickHandlers = null;
    }
    var hl = document.getElementById('__sc_picker_hl');
    if (hl && hl.parentNode) { hl.parentNode.removeChild(hl); }
})();
"""

# ---------------------------------------------------------------------------
# 弹窗扫描 / 关闭 / 移除
# ---------------------------------------------------------------------------
POPUP_SCAN_JS = _inject(r"""
(function(){
    var KWS = @@POPUP_HINT_KEYWORDS@@;
    function isVisible(el){
        if (!el || el.nodeType !== 1) { return false; }
        var st = window.getComputedStyle(el);
        if (st.display === 'none' || st.visibility === 'hidden') { return false; }
        var op = parseFloat(st.opacity);
        if (!(op > 0)) { return false; }
        var r = el.getBoundingClientRect();
        if (r.width < 4 || r.height < 4) { return false; }
        return true;
    }
    var out = [];
    var all = document.querySelectorAll('body *');
    for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (el.id === '__sc_picker_hl') { continue; }
        var id = (el.id || '').toLowerCase();
        var cls = ((typeof el.className === 'string' ? el.className : '') + ' ' +
                   (el.getAttribute('class') || '')).toLowerCase();
        var hit = false;
        for (var j = 0; j < KWS.length; j++) {
            var k = KWS[j].toLowerCase();
            if (id.indexOf(k) >= 0 || cls.indexOf(k) >= 0 ||
                el.tagName.toLowerCase().indexOf(k) >= 0) {
                hit = true;
                break;
            }
        }
        if (!hit) {
            var st = window.getComputedStyle(el);
            var zi = parseInt(st.zIndex, 10) || 0;
            if (!(st.position === 'fixed' && zi >= 50)) { continue; }
        }
        if (!isVisible(el)) { continue; }
        out.push({
            id: el.id || '',
            cls: typeof el.className === 'string' ? el.className : '',
            tag: el.tagName.toLowerCase(),
            text: (el.innerText || el.textContent || '').trim().slice(0, 60),
            visible: true
        });
    }
    return JSON.stringify(out);
})();
""")

POPUP_CLOSE_JS = _inject(r"""
(function(){
    var SELS = @@POPUP_CLOSE_SELECTORS@@;
    function isVisible(el){
        if (!el) { return false; }
        var st = window.getComputedStyle(el);
        if (st.display === 'none' || st.visibility === 'hidden') { return false; }
        var r = el.getBoundingClientRect();
        return r.width >= 4 && r.height >= 4;
    }
    for (var i = 0; i < SELS.length; i++) {
        var els = [];
        try { els = document.querySelectorAll(SELS[i]); } catch(e) { continue; }
        for (var j = 0; j < els.length; j++) {
            var el = els[j];
            if (!isVisible(el)) { continue; }
            try {
                el.scrollIntoView({block: 'center'});
                el.click();
            } catch(e) {}
            return 1;
        }
    }
    return 0;
})();
""")

POPUP_REMOVE_JS = _inject(r"""
(function(){
    var KWS = @@POPUP_HINT_KEYWORDS@@;
    var removed = 0;
    function isVisible(el){
        if (!el || el.nodeType !== 1) { return false; }
        var st = window.getComputedStyle(el);
        if (st.display === 'none' || st.visibility === 'hidden') { return false; }
        var r = el.getBoundingClientRect();
        return r.width >= 4 && r.height >= 4;
    }
    var all = document.querySelectorAll('body *');
    for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.parentNode) { continue; }
        var id = (el.id || '').toLowerCase();
        var cls = ((typeof el.className === 'string' ? el.className : '') + ' ' +
                   (el.getAttribute('class') || '')).toLowerCase();
        var hit = false;
        for (var j = 0; j < KWS.length; j++) {
            var k = KWS[j].toLowerCase();
            if (id.indexOf(k) >= 0 || cls.indexOf(k) >= 0) { hit = true; break; }
        }
        if (hit && isVisible(el)) {
            try { el.remove(); removed++; } catch(e) {}
        }
    }
    return removed;
})();
""")

# ---------------------------------------------------------------------------
# 懒加载滚动（返回 Promise，Python 端等待结果）
# ---------------------------------------------------------------------------
SCROLL_JS = r"""
(function(){
    return new Promise(function(resolve){
        var step = Math.max(1, Math.floor(window.innerHeight * 0.6));
        var timer = window.setInterval(function(){
            var before = window.scrollY;
            window.scrollBy(0, step);
            var doc = document.documentElement;
            if (window.scrollY >= doc.scrollHeight - window.innerHeight ||
                window.scrollY === before) {
                window.clearInterval(timer);
                window.scrollTo(0, 0);
                resolve(true);
            }
        }, 120);
    });
})();
"""

GET_HTML_JS = r"""
(function(){ return document.documentElement ? document.documentElement.outerHTML : ''; })();
"""

GET_TEXT_JS = r"""
(function(){ return document.body ? document.body.innerText : ''; })();
"""

GET_TITLE_JS = r"""
(function(){ return document.title || ''; })();
"""

# ---------------------------------------------------------------------------
# 提取 JS 模板（18 个 mode 函数，@@TOKEN@@ 一次性替换后可直接 runJavaScript）
# ---------------------------------------------------------------------------
_EXTRACT_TEMPLATE = r"""
(function(){
    function QSA(s){ if(!s){ return []; } try { return Array.prototype.slice.call(document.querySelectorAll(s)); } catch(e){ return []; } }
    function ABS(u){ if(!u){ return u; } try { return new URL(u, location.href).href; } catch(e){ return u; } }
    function TXT(e){ if(!e){ return ''; } var t = e.innerText || e.textContent || ''; return (t === null || t === undefined) ? '' : String(t).trim(); }
    var out = [];
    var F = @@FIELDS@@;
    function fieldValue(el, f){
        if(!el){ return ''; }
        if(f.type === 'href'){ return el.getAttribute ? (el.getAttribute('href') || '') : ''; }
        if(f.type === 'src'){ return el.src || (el.getAttribute ? (el.getAttribute('src') || '') : ''); }
        if(f.type === 'html'){ return el.innerHTML || ''; }
        if(f.type === 'attr'){ return el.getAttribute ? (el.getAttribute(f.attr) || '') : ''; }
        return TXT(el);
    }
    function rowFields(container, fields){
        var row = {};
        for(var i=0;i<fields.length;i++){
            var f = fields[i];
            var el = f.selector ? container.querySelector(f.selector) : container;
            row[f.name] = fieldValue(el, f);
        }
        return row;
    }
    var H = {
        records: function(){
            var conts = @@SELECTOR@@ ? QSA(@@SELECTOR@@) : [document];
            for(var i=0;i<conts.length;i++){
                if(F.length){ out.push(rowFields(conts[i], F)); }
            }
        },
        list: function(){
            var conts = @@SELECTOR@@ ? QSA(@@SELECTOR@@) : [document];
            for(var i=0;i<conts.length;i++){
                var els = conts[i].querySelectorAll('*');
                for(var j=0;j<els.length;j++){
                    var t = TXT(els[j]);
                    if(t){ out.push({text: t}); }
                }
            }
        },
        table: function(){
            var tables = QSA('table');
            var multi = tables.length > 1;
            for(var ti=0;ti<tables.length;ti++){
                var table = tables[ti];
                var headers = [];
                var theadThs = table.querySelectorAll('thead th');
                var headerConsumed = false;
                if(theadThs.length){
                    for(var i=0;i<theadThs.length;i++){ headers.push(TXT(theadThs[i])); }
                } else {
                    var firstRow = table.querySelector('tr');
                    if(firstRow){
                        var cells = firstRow.querySelectorAll('th, td');
                        if(cells.length){
                            for(var k=0;k<cells.length;k++){ headers.push(TXT(cells[k])); }
                            headerConsumed = true;
                        }
                    }
                }
                if(!headers.length){
                    var maxCols = 0;
                    var allTrs = table.querySelectorAll('tr');
                    for(var r=0;r<allTrs.length;r++){
                        var c = allTrs[r].querySelectorAll('th, td');
                        if(c.length > maxCols){ maxCols = c.length; }
                    }
                    for(var n=0;n<maxCols;n++){ headers.push('col_' + n); }
                }
                var bodyRows = [];
                if(theadThs.length){
                    var tb = table.querySelector('tbody');
                    if(tb){ bodyRows = Array.prototype.slice.call(tb.querySelectorAll('tr')); }
                } else {
                    bodyRows = Array.prototype.slice.call(table.querySelectorAll('tr'));
                    if(headerConsumed && bodyRows.length){ bodyRows = bodyRows.slice(1); }
                }
                for(var b=0;b<bodyRows.length;b++){
                    var tds = bodyRows[b].querySelectorAll('th, td');
                    var row = {};
                    for(var c2=0;c2<headers.length;c2++){
                        row[headers[c2]] = c2 < tds.length ? TXT(tds[c2]) : '';
                    }
                    if(multi){ row['_table'] = ti + 1; }
                    out.push(row);
                }
            }
        },
        links: function(){
            var as = QSA('a');
            for(var i=0;i<as.length;i++){
                var a = as[i];
                var href = a.getAttribute('href') || '';
                out.push({text: TXT(a), href: href ? ABS(href) : ''});
            }
        },
        images: function(){
            var imgs = QSA('img');
            for(var i=0;i<imgs.length;i++){
                var im = imgs[i];
                out.push({src: ABS(im.src || im.getAttribute('src') || ''), alt: im.alt || im.getAttribute('alt') || ''});
            }
        },
        text: function(){
            out.push({text: document.body ? document.body.innerText : ''});
        },
        html: function(){
            out.push({html: document.documentElement ? document.documentElement.outerHTML : ''});
        },
        regex: function(){
            if(!@@PATTERN@@){ return; }
            var html = document.documentElement ? document.documentElement.outerHTML : '';
            var re;
            try { re = new RegExp(@@PATTERN@@, @@FLAGS@@); }
            catch(e){ return; }
            var matches = [];
            try {
                if(re.global){
                    var it = html.matchAll(re);
                    for(var m = it.next(); !m.done; m = it.next()){ matches.push(m.value); }
                } else {
                    var single = html.match(re);
                    if(single){ matches.push(single); }
                }
            } catch(e){ return; }
            for(var i=0;i<matches.length;i++){
                var rec = {match: matches[i][0]};
                if(matches[i].length > 1){ rec.groups = Array.prototype.slice.call(matches[i], 1); }
                out.push(rec);
            }
        },
        jsonld: function(){
            var scripts = QSA('script[type="application/ld+json"]');
            for(var i=0;i<scripts.length;i++){
                var txt = (scripts[i].textContent || '').trim();
                if(!txt){ continue; }
                try {
                    var data = JSON.parse(txt);
                    if(Object.prototype.toString.call(data) === '[object Array]'){
                        for(var j=0;j<data.length;j++){ out.push(data[j]); }
                    } else {
                        out.push(data);
                    }
                } catch(e){}
            }
        },
        meta: function(){
            var metas = QSA('meta');
            for(var i=0;i<metas.length;i++){
                var m = metas[i];
                out.push({name: m.getAttribute('name') || m.getAttribute('property') || '', content: m.getAttribute('content') || ''});
            }
        },
        forms: function(){
            var forms = QSA('form');
            for(var i=0;i<forms.length;i++){
                var f = forms[i];
                var fieldList = [];
                var inputs = f.querySelectorAll('input, select, textarea');
                for(var j=0;j<inputs.length;j++){
                    var el = inputs[j];
                    fieldList.push({
                        name: el.getAttribute('name') || el.id || '',
                        type: el.type || el.tagName.toLowerCase(),
                        value: el.value || ''
                    });
                }
                out.push({
                    action: ABS(f.getAttribute('action') || f.action || ''),
                    method: (f.getAttribute('method') || 'get').toLowerCase(),
                    fields: fieldList
                });
            }
        },
        video: function(){
            var nodes = QSA('video, video source');
            var seen = {};
            for(var i=0;i<nodes.length;i++){
                var v = nodes[i];
                var src = '';
                if(v.tagName.toLowerCase() === 'video'){
                    src = v.getAttribute('src') || '';
                    if(!src){
                        var s = v.querySelector('source');
                        src = s ? (s.getAttribute('src') || '') : '';
                    }
                } else {
                    src = v.getAttribute('src') || '';
                }
                src = ABS(src);
                if(src && !seen[src]){ seen[src] = true; out.push({src: src}); }
            }
        },
        iframe: function(){
            var frames = QSA('iframe');
            for(var i=0;i<frames.length;i++){
                out.push({src: ABS(frames[i].getAttribute('src') || '')});
            }
        },
        rss: function(){
            var links = QSA('link[type*="rss"], link[type*="atom"]');
            for(var i=0;i<links.length;i++){
                var l = links[i];
                out.push({title: l.getAttribute('title') || '', href: ABS(l.getAttribute('href') || '')});
            }
        },
        sitemap: function(){
            var nodes = QSA('a[href*="sitemap"], link[rel="sitemap"]');
            for(var i=0;i<nodes.length;i++){
                var n = nodes[i];
                var text = '';
                if(n.tagName.toLowerCase() === 'a'){
                    text = TXT(n) || n.getAttribute('href') || '';
                } else {
                    text = n.getAttribute('title') || '';
                }
                out.push({text: text, href: ABS(n.getAttribute('href') || '')});
            }
        },
        contacts: function(){
            var txt = document.body ? document.body.innerText : '';
            var emailRe = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
            var m;
            while((m = emailRe.exec(txt)) !== null){
                out.push({type: 'email', value: m[0]});
            }
            var phoneRe = /(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,4}[\s-]?\d{4}/g;
            while((m = phoneRe.exec(txt)) !== null){
                out.push({type: 'phone', value: m[0].trim()});
            }
        },
        embedded_json: function(){
            var scripts = QSA('script[type="application/json"], script[type="text/json"]');
            for(var i=0;i<scripts.length;i++){
                var txt = (scripts[i].textContent || '').trim();
                if(!txt){ continue; }
                try { out.push(JSON.parse(txt)); } catch(e){}
            }
        },
        page_cookies: function(){
            out.push({cookies: document.cookie});
        }
    };
    var mode = @@MODE@@;
    try {
        if(Object.prototype.hasOwnProperty.call(H, mode)){ H[mode](); }
    } catch(e){}
    return JSON.stringify(out);
})();
"""


def _field_dict(f) -> dict:
    """把 Field 对象或 dict 归一化为 {"name","selector","type","attr"}。"""
    if isinstance(f, dict):
        return {
            "name": str(f.get("name") or ""),
            "selector": str(f.get("selector") or ""),
            "type": str(f.get("type") or "text"),
            "attr": str(f.get("attr") or ""),
        }
    return {
        "name": str(getattr(f, "name", None) or ""),
        "selector": str(getattr(f, "selector", None) or ""),
        "type": str(getattr(f, "type", None) or "text"),
        "attr": str(getattr(f, "attr", None) or ""),
    }


def build_extract_js(mode, selector, fields, pattern, flags):
    """生成 IIFE 提取 JS：立即执行并返回 JSON 字符串。"""
    items = [_field_dict(f) for f in (fields or [])]
    return _inject(
        _EXTRACT_TEMPLATE,
        FIELDS=json.dumps(items, ensure_ascii=True),
        SELECTOR=json.dumps(str(selector or "")),
        PATTERN=json.dumps(str(pattern or "")),
        FLAGS=json.dumps(str(flags or "g")),
        MODE=json.dumps(str(mode)),
    )
