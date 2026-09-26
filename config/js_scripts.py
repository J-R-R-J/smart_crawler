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

from config.default_settings import (
    ALL_MEDIA_EXTS, AUDIO_EXTS, IMAGE_EXTS, POPUP_CLOSE_SELECTORS,
    POPUP_HINT_KEYWORDS, VIDEO_EXTS,
)

__all__ = [
    "QWEBCHANNEL_JS", "PICKER_JS", "PICKER_TEARDOWN_JS",
    "POPUP_SCAN_JS", "POPUP_CLOSE_JS", "POPUP_REMOVE_JS",
    "SCROLL_JS", "GET_HTML_JS", "GET_TEXT_JS", "GET_TITLE_JS",
    "STEALTH_JS", "CAPTCHA_PROBE_JS", "LOGIN_PROBE_JS",
    "build_extract_js", "build_stealth_js", "DEFAULT_STEALTH_FLAGS",
]

_PLACEHOLDER_RE = re.compile(
    r"@@(FIELDS|SELECTOR|PATTERN|FLAGS|MODE|POPUP_HINT_KEYWORDS|POPUP_CLOSE_SELECTORS"
    r"|IMG_EXTS|VIDEO_EXTS|AUDIO_EXTS|MEDIA_EXTS|SC_FLAGS)@@"
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
#
# 覆盖的检测面：
#   1. navigator.webdriver（含原型链层面，避免留下 own property 痕迹）
#   2. 经典自动化框架残留标记（__webdriver_*、_selenium、cdc_*、domAutomation 等）
#   3. 语言 / 平台 / 硬件信息 / 插件 / window.chrome 一致性
#   4. Permissions 查询结果、WebGL 厂商与渲染器字符串
#   5. 无头 / 软件渲染常见特征（outerWidth 为 0、document.hasFocus 恒 false 等）
#   6. Canvas / WebGL 指纹干扰（第 12 节，开关 F.canvas）
#   7. WebRTC 真实 IP 泄露防护（第 13 节，开关 F.webrtc）
#   8. 反广告探测脚本干扰（第 14 节，开关 F.adblock）
#   9. UA 与 navigator.userAgentData 一致性（第 15 节，开关 F.uach）
#
# 6~9 节由 build_stealth_js() 的开关控制，开关值注入到 JS 里的 F 对象。
# **为什么要把开关编译进脚本**：本脚本在 DocumentCreation 阶段执行，
# 早于任何页面脚本，Python 在那之前没有机会往里塞配置；改开关时
# 重新生成脚本并替换注入即可（见 core.browser）。
#
# 说明：QtWebEngine 使用自有 IPC，**不暴露 CDP（Chrome DevTools Protocol）**，
# 因此 $cdc_ / Runtime.enable 这类纯 CDP 痕迹通常不存在；这里仍做清理以防万一。
# ---------------------------------------------------------------------------
_STEALTH_TEMPLATE = r"""
(function(){
    'use strict';
    var UNDEF = void 0;
    var F = @@SC_FLAGS@@;

    // ---- 1. navigator.webdriver：优先从原型上删除，避免留下 own property ----
    try {
        var navProto = Object.getPrototypeOf(navigator);
        if (navProto) {
            try { delete navProto.webdriver; } catch (e) {}
            if ('webdriver' in navigator) {
                Object.defineProperty(navProto, 'webdriver', {
                    get: function(){ return UNDEF; },
                    configurable: true
                });
            }
        }
        // 兜底：万一还在实例上
        if (navigator.webdriver !== UNDEF) {
            try { delete navigator.webdriver; } catch (e) {}
        }
    } catch (e) {}

    // ---- 2. 清理自动化框架残留标记 ----
    try {
        var MARKERS = [
            // ChromeDriver
            'cdc_adoQpoasnfa76pfcZLmcfl_Array',
            'cdc_adoQpoasnfa76pfcZLmcfl_Promise',
            'cdc_adoQpoasnfa76pfcZLmcfl_Symbol',
            // Selenium / WebDriver
            '__webdriver_evaluate', '__selenium_evaluate',
            '__webdriver_script_function', '__webdriver_script_func',
            '__webdriver_script_fn', '__fxdriver_evaluate',
            '__driver_evaluate', '__driver_unwrapped',
            '__webdriver_unwrapped', '__selenium_unwrapped',
            '__fxdriver_unwrapped', '_Selenium_IDE_Recorder',
            '_selenium', 'calledSelenium', '_WEBDRIVER_ELEM_CACHE',
            // PhantomJS / Nightmare / Playwright / Puppeteer
            '__nightmare', '_phantom', 'callPhantom',
            '__playwright', '__puppeteer', '__pw_manual', '__PW_inspect',
            // 老式自动化桥
            'domAutomation', 'domAutomationController', 'spawn'
        ];
        for (var i = 0; i < MARKERS.length; i++) {
            var k = MARKERS[i];
            try { if (k in window) { delete window[k]; } } catch (e) {}
            try { if (k in document) { delete document[k]; } } catch (e) {}
        }
        // ChromeDriver 会在 document 上挂 $cdc_ 前缀属性
        try {
            var dkeys = Object.getOwnPropertyNames(document);
            for (var j = 0; j < dkeys.length; j++) {
                if (/^\$?cdc_|^\$?wdc_/i.test(dkeys[j])) {
                    try { delete document[dkeys[j]]; } catch (e) {}
                }
            }
        } catch (e) {}
        try {
            var wkeys = Object.getOwnPropertyNames(window);
            for (var m = 0; m < wkeys.length; m++) {
                if (/^\$?cdc_|^\$?wdc_/i.test(wkeys[m])) {
                    try { delete window[wkeys[m]]; } catch (e) {}
                }
            }
        } catch (e) {}
    } catch (e) {}

    // ---- 3. 语言 / 时区一致性 ----
    try {
        Object.defineProperty(navigator, 'languages', {
            get: function(){ return ['zh-CN', 'zh', 'en-US', 'en']; }
        });
        Object.defineProperty(navigator, 'language', {
            get: function(){ return 'zh-CN'; }
        });
    } catch (e) {}

    // ---- 4. 平台与硬件信息（避免无头环境的空值/异常值） ----
    try {
        Object.defineProperty(navigator, 'platform', { get: function(){ return 'Win32'; } });
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: function(){ return 8; } });
        Object.defineProperty(navigator, 'deviceMemory', { get: function(){ return 8; } });
        Object.defineProperty(navigator, 'maxTouchPoints', { get: function(){ return 0; } });
        Object.defineProperty(navigator, 'vendor', { get: function(){ return 'Google Inc.'; } });
        Object.defineProperty(navigator, 'vendorSub', { get: function(){ return ''; } });
        Object.defineProperty(navigator, 'productSub', { get: function(){ return '20030107'; } });
    } catch (e) {}

    // ---- 5. plugins / mimeTypes（空列表是无头浏览器的典型特征） ----
    try {
        if (!navigator.plugins || navigator.plugins.length === 0) {
            var fakePlugins = [
                { name: 'PDF Viewer', filename: 'internal-pdf-viewer' },
                { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer' },
                { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer' },
                { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer' },
                { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer' }
            ];
            fakePlugins.item = function(i){ return this[i]; };
            fakePlugins.namedItem = function(n){
                for (var i = 0; i < this.length; i++) {
                    if (this[i].name === n) { return this[i]; }
                }
                return null;
            };
            Object.defineProperty(navigator, 'plugins', {
                get: function(){ return fakePlugins; }, configurable: true
            });
            var fakeMimes = [
                { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
                { type: 'text/pdf', suffixes: 'pdf', description: 'Portable Document Format' }
            ];
            fakeMimes.item = function(i){ return this[i]; };
            fakeMimes.namedItem = function(n){
                for (var i = 0; i < this.length; i++) {
                    if (this[i].type === n) { return this[i]; }
                }
                return null;
            };
            Object.defineProperty(navigator, 'mimeTypes', {
                get: function(){ return fakeMimes; }, configurable: true
            });
        }
    } catch (e) {}

    // ---- 6. window.chrome（部分站点会直接检查） ----
    try {
        if (!window.chrome) { window.chrome = {}; }
        if (!window.chrome.runtime) { window.chrome.runtime = {}; }
        if (!window.chrome.app) {
            window.chrome.app = {
                isInstalled: false,
                InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
                RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
            };
        }
        if (!window.chrome.csi) {
            window.chrome.csi = function(){
                return { onloadT: Date.now(), startE: Date.now(), pageT: 1000, tran: 15 };
            };
        }
        if (!window.chrome.loadTimes) {
            window.chrome.loadTimes = function(){
                var t = Date.now() / 1000;
                return {
                    requestTime: t, startLoadTime: t, commitLoadTime: t,
                    finishDocumentLoadTime: t, finishLoadTime: t,
                    firstPaintTime: t, firstPaintAfterLoadTime: 0,
                    navigationType: 'Other', wasFetchedViaSpdy: true,
                    wasNpnNegotiated: true, npnNegotiatedProtocol: 'h2',
                    wasAlternateProtocolAvailable: false, connectionInfo: 'h2'
                };
            };
        }
    } catch (e) {}

    // ---- 7. Permissions 查询结果与 Notification 保持一致 ----
    try {
        if (navigator.permissions && navigator.permissions.query) {
            var origQuery = navigator.permissions.query.bind(navigator.permissions);
            navigator.permissions.query = function(params){
                if (params && params.name === 'notifications') {
                    return Promise.resolve({ state: Notification.permission, onchange: null });
                }
                return origQuery(params);
            };
        }
    } catch (e) {}

    // ---- 8. WebGL 厂商 / 渲染器（软件渲染会暴露 SwiftShader 等特征） ----
    try {
        var VENDOR = 37445, RENDERER = 37446;
        function patchGL(proto){
            if (!proto || !proto.getParameter) { return; }
            var orig = proto.getParameter;
            proto.getParameter = function(p){
                if (p === VENDOR) { return 'Intel Inc.'; }
                if (p === RENDERER) { return 'Intel Iris OpenGL Engine'; }
                return orig.apply(this, arguments);
            };
        }
        patchGL(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
        patchGL(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);
        if (window.WebGLRenderingContext && WebGLRenderingContext.prototype.getExtension) {
            var origGetExt = WebGLRenderingContext.prototype.getExtension;
            WebGLRenderingContext.prototype.getExtension = function(name){
                var ext = origGetExt.apply(this, arguments);
                if (ext && name === 'WEBGL_debug_renderer_info') {
                    // 调试扩展本身保留，但值已被上面的 getParameter 覆盖
                    return ext;
                }
                return ext;
            };
        }
    } catch (e) {}

    // ---- 9. 无头/软件渲染常见特征 ----
    try {
        // outerWidth/outerHeight 为 0 是无头环境的典型特征
        if (!window.outerWidth || !window.outerHeight) {
            Object.defineProperty(window, 'outerWidth', {
                get: function(){ return window.innerWidth || 1280; }, configurable: true });
            Object.defineProperty(window, 'outerHeight', {
                get: function(){ return (window.innerHeight || 800) + 90; }, configurable: true });
        }
        // 无头环境下 hasFocus 常恒为 false
        if (document.hasFocus && !document.hasFocus()) {
            document.hasFocus = function(){ return true; };
        }
    } catch (e) {}

    // ---- 10. 网络信息对象（缺失也是特征之一） ----
    try {
        if (!navigator.connection) {
            Object.defineProperty(navigator, 'connection', {
                get: function(){
                    return { effectiveType: '4g', rtt: 50, downlink: 10,
                             saveData: false, onchange: null };
                },
                configurable: true
            });
        }
    } catch (e) {}

    // ---- 11. 自检：关键现代 API 是否存在（Chromium 应全部具备） ----
    try {
        var REQUIRED = ['fetch', 'Promise', 'Intl', 'Proxy', 'Reflect',
                        'Symbol', 'Map', 'Set', 'WeakMap', 'WeakSet',
                        'requestAnimationFrame', 'IntersectionObserver',
                        'ResizeObserver', 'MutationObserver', 'URL',
                        'URLSearchParams', 'AbortController', 'TextEncoder',
                        'TextDecoder', 'queueMicrotask', 'structuredClone'];
        var missing = [];
        for (var n = 0; n < REQUIRED.length; n++) {
            if (typeof window[REQUIRED[n]] === 'undefined') {
                missing.push(REQUIRED[n]);
            }
        }
        if (missing.length) {
            window.__sc_missing_apis = missing;
        }
    } catch (e) {}

    // ==================================================================
    // 12. Canvas / WebGL 指纹干扰
    //
    // 指纹脚本的套路：画一段固定文字 → toDataURL / getImageData → 哈希。
    // GPU、驱动、字体渲染的细微差异会让哈希在不同机器上不同，于是成为
    // 一个高熵标识符。
    //
    // **关键约束：噪声必须是确定性的。** 同一个 canvas 连续两次读出的
    // 结果必须完全一致 —— 真浏览器的渲染是确定性的，如果两次不同，
    // 反而成了「伪装过的自动化浏览器」的铁证（这比不伪装更容易被抓）。
    // 所以这里用「像素下标 + 会话种子」的伪随机，而不是 Math.random()，
    // 并且**只改动返回给页面的副本，不写回真实 canvas**，
    // 避免多次调用累积漂移。
    // ==================================================================
    if (F.canvas) {
        try {
            var seed = (F.seed | 0) || 1;
            function scNoise(i){
                var x = (i + seed) & 0x7fffffff;
                x = (x ^ (x >>> 13)) * 1597334677;
                x = x & 0x7fffffff;
                x = (x ^ (x >>> 16)) & 0x7fffffff;
                var r = x % 3;
                return r === 0 ? 0 : (r === 1 ? 1 : -1);
            }
            // 每 997 个像素动一个通道：肉眼看不出，但足以改变哈希
            function scDirty(data){
                if (!data || !data.length) { return data; }
                var step = 4 * 997;
                for (var i = 0; i < data.length; i += step) {
                    var d = scNoise(i);
                    if (!d) { continue; }
                    for (var c = 0; c < 3; c++) {
                        var j = i + c;
                        if (j >= data.length) { break; }
                        var v = data[j] + d;
                        data[j] = v < 0 ? 0 : (v > 255 ? 255 : v);
                    }
                }
                return data;
            }
            function scCopyCanvas(el){
                // 复制一份再加噪：真实 canvas 不被修改，
                // 于是重复调用得到的结果始终一致。
                var w = el.width, h = el.height;
                if (!w || !h) { return null; }
                var ctx = null;
                try { ctx = el.getContext('2d'); } catch (e) { return null; }
                if (!ctx) { return null; }
                var img = null;
                try { img = ctx.getImageData(0, 0, w, h); } catch (e) { return null; }
                if (!img) { return null; }
                scDirty(img.data);
                var c2 = document.createElement('canvas');
                c2.width = w; c2.height = h;
                var c2ctx = c2.getContext('2d');
                if (!c2ctx) { return null; }
                try { c2ctx.putImageData(img, 0, 0); } catch (e) { return null; }
                return c2;
            }

            if (window.CanvasRenderingContext2D &&
                CanvasRenderingContext2D.prototype.getImageData) {
                var scOrigGID = CanvasRenderingContext2D.prototype.getImageData;
                CanvasRenderingContext2D.prototype.getImageData = function(){
                    var res = scOrigGID.apply(this, arguments);
                    try { if (res && res.data) { scDirty(res.data); } } catch (e) {}
                    return res;
                };
            }
            if (window.HTMLCanvasElement && HTMLCanvasElement.prototype.toDataURL) {
                var scOrigToData = HTMLCanvasElement.prototype.toDataURL;
                HTMLCanvasElement.prototype.toDataURL = function(){
                    try {
                        var c = scCopyCanvas(this);
                        if (c) { return scOrigToData.apply(c, arguments); }
                    } catch (e) {}
                    return scOrigToData.apply(this, arguments);
                };
            }
            if (window.HTMLCanvasElement && HTMLCanvasElement.prototype.toBlob) {
                var scOrigToBlob = HTMLCanvasElement.prototype.toBlob;
                HTMLCanvasElement.prototype.toBlob = function(cb){
                    var rest = Array.prototype.slice.call(arguments, 1);
                    try {
                        var c = scCopyCanvas(this);
                        if (c) { return scOrigToBlob.apply(c, [cb].concat(rest)); }
                    } catch (e) {}
                    return scOrigToBlob.apply(this, arguments);
                };
            }
            // WebGL readPixels 是另一条常用取指纹路径
            function scPatchGL(proto){
                if (!proto || !proto.readPixels) { return; }
                var orig = proto.readPixels;
                proto.readPixels = function(){
                    var args = arguments;
                    var res = orig.apply(this, args);
                    try {
                        // 第 7 个参数是输出 TypedArray（x,y,w,h,format,type,pixels）
                        var buf = args[6];
                        if (buf && buf.length) {
                            for (var i = 0; i < buf.length; i += 397) {
                                var d = scNoise(i);
                                if (!d) { continue; }
                                var v = buf[i] + d;
                                buf[i] = v < 0 ? 0 : (v > 255 ? 255 : v);
                            }
                        }
                    } catch (e) {}
                    return res;
                };
            }
            scPatchGL(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
            scPatchGL(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);
        } catch (e) {}
    }

    // ==================================================================
    // 13. WebRTC 真实 IP 泄露防护
    //
    // 危害：即使用户配了代理，WebRTC 也会**绕过代理**直接枚举本机网卡，
    // 把 192.168.x.x / 10.x.x.x 乃至真实公网出口 IP 交给页面。
    //
    // 做法（两层）：
    //   a) 强制 iceTransportPolicy='relay'：不收集 host/srflx 候选，
    //      从根上不产生本地地址。没有 TURN 服务器时结果是「零候选」，
    //      这在对内网不友好的企业网络里也真实存在，不算异常；
    //   b) 再兜一层候选过滤：即使站点自己构造 RTCPeerConnection 绕开
    //      a)，含私有 IP 的候选也不会交给页面回调。
    //      mDNS 形式的 xxxx.local 不拦 —— 它本来就是 Chrome 的隐私保护形式。
    // ==================================================================
    if (F.webrtc) {
        try {
            var RTC = window.RTCPeerConnection || window.webkitRTCPeerConnection;
            if (RTC) {
                function scPrivateCandidate(text){
                    if (!text) { return false; }
                    if (/\.local\b/i.test(text)) { return false; }
                    if (/(?:^|[\s:])(?:10\.\d{1,3}\.|127\.\d{1,3}\.|169\.254\.|192\.168\.|0\.0\.0\.0|172\.(?:1[6-9]|2\d|3[01])\.)/.test(text)) {
                        return true;
                    }
                    return /(?:^|[\s:])(?:::1|f[cd][0-9a-f]{2}:|fe80:)/i.test(text);
                }
                function scGuardEvent(ev){
                    try {
                        if (ev && ev.candidate && ev.candidate.candidate &&
                            scPrivateCandidate(ev.candidate.candidate)) {
                            return false;   // 丢弃：不外传
                        }
                    } catch (e) {}
                    return true;
                }
                function scGuardPc(pc){
                    try {
                        var origAdd = pc.addEventListener;
                        pc.addEventListener = function(type, fn, opts){
                            if (type === 'icecandidate' && typeof fn === 'function') {
                                var wrapped = function(ev){
                                    if (!scGuardEvent(ev)) { return; }
                                    return fn.apply(this, arguments);
                                };
                                return origAdd.call(this, type, wrapped, opts);
                            }
                            return origAdd.call(this, type, fn, opts);
                        };
                    } catch (e) {}
                    try {
                        var desc = Object.getOwnPropertyDescriptor(RTC.prototype, 'onicecandidate');
                        if (desc && desc.set) {
                            var stored = null;
                            Object.defineProperty(pc, 'onicecandidate', {
                                configurable: true,
                                get: function(){ return stored; },
                                set: function(fn){
                                    stored = fn;
                                    if (typeof fn !== 'function') {
                                        desc.set.call(pc, fn);
                                        return;
                                    }
                                    desc.set.call(pc, function(ev){
                                        if (!scGuardEvent(ev)) { return; }
                                        return fn.apply(this, arguments);
                                    });
                                }
                            });
                        }
                    } catch (e) {}
                    return pc;
                }
                function scRelayConfig(cfg){
                    var out2 = {};
                    try {
                        for (var k in cfg) { out2[k] = cfg[k]; }
                    } catch (e) { return cfg; }
                    out2.iceTransportPolicy = 'relay';
                    if (!out2.iceServers) { out2.iceServers = []; }
                    return out2;
                }
                var SCWrapped = function(config, constraints){
                    return scGuardPc(new RTC(scRelayConfig(config), constraints));
                };
                SCWrapped.prototype = RTC.prototype;
                try { Object.setPrototypeOf(SCWrapped, RTC); } catch (e) {}
                try {
                    for (var rk in RTC) { SCWrapped[rk] = RTC[rk]; }
                } catch (e) {}
                window.RTCPeerConnection = SCWrapped;
                window.webkitRTCPeerConnection = SCWrapped;
            }
        } catch (e) {}
    }

    // ==================================================================
    // 14. 反广告 / 反拦截脚本干扰
    //
    // 三件事：
    //   a) 把探测变量填成「没装拦截器」的正常值（canRunAds / adsbygoogle）；
    //   b) 恢复诱饵元素：过滤规则会把 id/class 含 adblock 的 1×1 元素隐藏，
    //      脚本据此反推「你装了拦截器」。这里把它恢复成可见的 1px 元素，
    //      让朴素探测得出相反结论；
    //   c) 拆掉「请关闭广告拦截插件」全屏遮罩。
    //
    // **本程序默认不拦可见广告素材**（只拦埋点/追踪域名），所以这里的
    // 目标是「别让站点的反广告脚本误伤抓取流程」，不是帮用户屏蔽广告。
    // 遮罩只在 z-index ≥ 1000 且文字命中关键词时才隐藏，避免误伤正常弹窗。
    // ==================================================================
    if (F.adblock) {
        try {
            if (typeof window.canRunAds === 'undefined') { window.canRunAds = true; }
            if (typeof window.canShowAds === 'undefined') { window.canShowAds = true; }
            if (!window.adsbygoogle) {
                window.adsbygoogle = { loaded: true, push: function(){} };
            } else if (typeof window.adsbygoogle.push !== 'function') {
                try { window.adsbygoogle.push = function(){}; } catch (e) {}
            }
        } catch (e) {}

        var scBaitSelectors = [
            '[id*="adblock" i]', '[class*="adblock" i]',
            '[id*="ad-block" i]', '[class*="ad-block" i]',
            '[id*="ad_banner" i]', '[class*="ad_banner" i]',
            '[id*="banner_ad" i]', '[class*="banner_ad" i]',
            '[class*="adsbox" i]', '[id*="adsbox" i]',
            '[class*="ad-placement" i]', '[id*="ad-placement" i]'
        ];
        var scAdblockWords = /(adblock|ad\s*block|广告拦截|广告屏蔽|拦截插件|关闭广告|disable\s+(your\s+)?adblock|turn\s+off\s+adblock)/i;

        function scDefuseBait(){
            for (var i = 0; i < scBaitSelectors.length; i++) {
                var els;
                try { els = document.querySelectorAll(scBaitSelectors[i]); }
                catch (e) { continue; }
                for (var j = 0; j < els.length; j++) {
                    var el = els[j];
                    var st;
                    try { st = window.getComputedStyle(el); } catch (e) { continue; }
                    if (!st) { continue; }
                    var hidden = (st.display === 'none') ||
                                 (st.visibility === 'hidden') ||
                                 (parseFloat(st.opacity || '1') === 0);
                    var r = null;
                    try { r = el.getBoundingClientRect(); } catch (e) {}
                    var tiny = r && r.width <= 3 && r.height <= 3;
                    if (!hidden && !tiny) { continue; }
                    try {
                        el.style.setProperty('display', 'block', 'important');
                        el.style.setProperty('visibility', 'visible', 'important');
                        el.style.setProperty('opacity', '1', 'important');
                        el.style.setProperty('width', '1px', 'important');
                        el.style.setProperty('height', '1px', 'important');
                    } catch (e) {}
                }
            }
        }

        function scKillOverlay(){
            var nodes;
            try { nodes = document.querySelectorAll('div,section,aside,article'); }
            catch (e) { return; }
            var limit = Math.min(nodes.length, 2500);
            for (var i = 0; i < limit; i++) {
                var el = nodes[i];
                var st;
                try { st = window.getComputedStyle(el); } catch (e) { continue; }
                if (!st || (st.position !== 'fixed' && st.position !== 'absolute')) {
                    continue;
                }
                var z = parseInt(st.zIndex, 10);
                if (!(z >= 1000)) { continue; }
                var txt = '';
                try { txt = (el.innerText || '').slice(0, 400); } catch (e) {}
                if (!txt || !scAdblockWords.test(txt)) { continue; }
                try { el.style.setProperty('display', 'none', 'important'); } catch (e) {}
            }
        }

        function scAdblockPass(){
            try { scDefuseBait(); } catch (e) {}
            try { scKillOverlay(); } catch (e) {}
        }
        try {
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', scAdblockPass, { once: true });
            } else {
                scAdblockPass();
            }
        } catch (e) {}
        // 遮罩与诱饵常在主内容加载完之后才插进来，所以再补两轮
        try {
            setTimeout(scAdblockPass, 1500);
            setTimeout(scAdblockPass, 4000);
        } catch (e) {}
    }

    // ==================================================================
    // 15. UA 与 navigator.userAgentData 一致性
    //
    // QtWebEngine 的 userAgentData 报的是它内嵌的 Chromium 版本。
    // 一旦 UA 被改成别的版本（或用户用环境变量改了），两边就对不上 ——
    // 这是**最容易被自动化检测抓到的一处不一致**，因为它不需要任何
    // 花哨技巧，读两个属性比一下就行。
    // 这里把 userAgentData 按真实 UA 版本重建。
    // ==================================================================
    if (F.uach && F.major) {
        try {
            var M = String(F.major);
            var brands = [
                { brand: 'Chromium', version: M },
                { brand: 'Google Chrome', version: M },
                { brand: 'Not?A_Brand', version: '24' }
            ];
            var fullList = [
                { brand: 'Chromium', version: M + '.0.0.0' },
                { brand: 'Google Chrome', version: M + '.0.0.0' },
                { brand: 'Not?A_Brand', version: '24.0.0.0' }
            ];
            function scHighEntropy(hints){
                var high = {
                    architecture: 'x86', bitness: '64', model: '',
                    platform: 'Windows', platformVersion: '10.0.0',
                    uaFullVersion: M + '.0.0.0', fullVersionList: fullList,
                    wow64: false
                };
                var out2 = {};
                var want = hints || [];
                for (var i = 0; i < want.length; i++) {
                    if (Object.prototype.hasOwnProperty.call(high, want[i])) {
                        out2[want[i]] = high[want[i]];
                    }
                }
                return Promise.resolve(out2);
            }
            Object.defineProperty(navigator, 'userAgentData', {
                configurable: true,
                get: function(){
                    return {
                        brands: brands, mobile: false, platform: 'Windows',
                        getHighEntropyValues: scHighEntropy,
                        toJSON: function(){
                            return { brands: brands, mobile: false,
                                     platform: 'Windows' };
                        }
                    };
                }
            });
        } catch (e) {}
    }
})();
"""

#: SC_FLAGS 的默认值：伪装开着，指纹干扰/泄露防护/反广告探测也开着，
#: 但**不**改 userAgentData（major=0 表示交给引擎自己的值）。
#: core.browser 在真正注入时会用 build_stealth_js() 传入实际值。
DEFAULT_STEALTH_FLAGS = {
    "canvas": True,
    "webrtc": True,
    "adblock": True,
    "uach": True,
    "major": 0,
    "seed": 1,
}

#: 默认（全开）的伪装脚本。保留这个模块级常量，是为了让旧调用方与
#: 「脚本里有没有某个能力」这类静态断言继续有效。
STEALTH_JS = _inject(_STEALTH_TEMPLATE,
                     SC_FLAGS=json.dumps(DEFAULT_STEALTH_FLAGS))


def build_stealth_js(canvas: bool = True, webrtc: bool = True,
                     adblock: bool = True, uach: bool = True,
                     major: int = 0, seed: int = 1) -> str:
    """按开关生成伪装脚本（core.browser 注入时用）。

    ``major`` 为 0 时跳过 userAgentData 重建（表示「不干预」）；
    ``seed`` 决定 Canvas 噪声的具体取值 —— 同一会话内必须保持不变，
    否则同一个 canvas 两次读到不同结果，反而比不伪装更可疑。
    """
    flags = {
        "canvas": bool(canvas),
        "webrtc": bool(webrtc),
        "adblock": bool(adblock),
        "uach": bool(uach),
        "major": int(major or 0),
        "seed": int(seed or 1),
    }
    return _inject(_STEALTH_TEMPLATE, SC_FLAGS=json.dumps(flags))


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
    // ==================================================================
    // 媒体采集（图片 / 视频 / 音频全格式）
    //
    // 为什么不能只查 <img src>：
    //   1. 现代站点几乎都用懒加载 —— 真地址放在 data-src / data-original 里，
    //      src 是个 1×1 占位图或 base64 灰块；
    //   2. 响应式图片的真地址在 srcset / <picture><source> 里，src 只是兜底；
    //   3. 视频站（抖音、B 站、YouTube）**根本不把地址写进 <video src>**，
    //      而是塞在内嵌 JSON（RENDER_DATA / __INITIAL_STATE__）里，
    //      再用 blob: 交给 MSE 播放 —— 只看 DOM 只会得到 0 条；
    //   4. 背景图写在 CSS 里。
    // 所以这里四路并行：DOM 属性、懒加载属性、CSS/背景图、原始文本扫描。
    // ==================================================================
    var MEDIA_EXTS = {
        image: @@IMG_EXTS@@,
        video: @@VIDEO_EXTS@@,
        audio: @@AUDIO_EXTS@@,
        media: @@MEDIA_EXTS@@
    };
    var EXT_RE = {
        image: new RegExp('^(?:' + MEDIA_EXTS.image + ')$'),
        video: new RegExp('^(?:' + MEDIA_EXTS.video + ')$'),
        audio: new RegExp('^(?:' + MEDIA_EXTS.audio + ')$')
    };
    // 懒加载真地址常见属性名（覆盖 lazyload / lozad / echo.js / unveil /
    // 淘宝、京东、知乎等站的私有写法）
    var LAZY_ATTRS = [
        'data-src', 'data-original', 'data-original-src', 'data-lazy',
        'data-lazy-src', 'data-lazyload', 'data-actualsrc', 'data-echo',
        'data-url', 'data-image', 'data-img', 'data-hi-res-src',
        'data-large', 'data-large-src', 'data-cover', 'data-thumb',
        'data-thumbnail', 'data-fallback-src', 'data-cfsrc', 'data-raw-src',
        'data-real-src', 'data-pin-media', 'data-defer-src', 'data-srcset'
    ];
    var BG_ATTRS = ['data-bg', 'data-background', 'data-background-image',
                    'data-cover', 'data-original', 'data-image'];

    var _seen = {};

    function resetSeen(){ _seen = {}; }

    function normUrl(u){
        if(!u){ return ''; }
        u = String(u).replace(/^\s+|\s+$/g, '').replace(/^['"]|['"]$/g, '');
        if(!u){ return ''; }
        var low = u.toLowerCase();
        if(low.indexOf('data:') === 0 || low.indexOf('javascript:') === 0 ||
           low.indexOf('about:') === 0 || low.indexOf('#') === 0){ return ''; }
        return ABS(u);
    }

    function extOf(u){
        var s = String(u || '').split('#')[0].split('?')[0].toLowerCase();
        var slash = s.lastIndexOf('/');
        var dot = s.lastIndexOf('.');
        if(dot < 0 || dot < slash){ return ''; }
        var e = s.slice(dot + 1);
        return /^[a-z0-9]{1,5}$/.test(e) ? e : '';
    }

    function kindOfUrl(u){
        var e = extOf(u);
        if(!e){ return ''; }
        if(EXT_RE.image.test(e)){ return 'image'; }
        if(EXT_RE.video.test(e)){ return 'video'; }
        if(EXT_RE.audio.test(e)){ return 'audio'; }
        return '';
    }

    // ------------------------------------------------------------------
    // 内容平台的**标志串**：有些图片地址没有常规扩展名，靠 URL 里的标记认。
    //
    // 实测抖音：正文图是
    //   https://p3-pc-sign.douyinpic.com/tos-cn-i-0813/xxx.image?biz_tag=aweme_images&...
    // 或者带模板后缀
    //   .../xxx~tplv-dy-aweme-images:q75.webp?biz_tag=aweme_images
    // 这些地址是**按 URL 标记**判定内容图/视频的（社区实现也是这么做的），
    // 单看扩展名会一条都拿不到，只能捞到站点自己的 UI 素材图。
    // ------------------------------------------------------------------
    var CONTENT_MARKERS = [
        [/biz_tag=aweme_images/i, 'image'],
        [/biz_tag=pcweb_cover/i, 'image'],
        [/tos-cn-i-0813/i, 'image'],
        [/~tplv-dy-aweme-images/i, 'image'],
        [/~tplv-[\w-]*image/i, 'image'],
        [/\.image(?:[?#]|$)/i, 'image'],
        [/biz_tag=aweme_video/i, 'video'],
        [/douyinvod/i, 'video'],
        [/\.m3u8(?:[?#]|$)/i, 'video']
    ];

    function markedKind(u){
        var s = String(u || '');
        for(var i=0;i<CONTENT_MARKERS.length;i++){
            if(CONTENT_MARKERS[i][0].test(s)){ return CONTENT_MARKERS[i][1]; }
        }
        return '';
    }

    // 站点自己的 UI 素材（图标 / 表情 / 头像 / 精灵图 / 皮肤资源）。
    // 它们不是用户要的"目标图片"，但混在结果里会淹没真正的正文图 ——
    // 标成 asset=1，界面上可选择过滤掉（过滤在 Python 侧做，见 core/extractor.py）。
    var ASSET_HINTS = [
        '/static-resource/', 'static-resource', 'aweme-client-static',
        '/emoji', 'emoji_', 'sprite', '/icon', 'icon_', '/logo', 'logo_',
        '/avatar', 'avatar_', 'sticker', 'aweme_comment', 'comment_',
        '/skin/', 'placeholder', 'loading.', 'default_cover', 'bg_'
    ];

    function isSiteAsset(u){
        var s = String(u || '').toLowerCase();
        for(var i=0;i<ASSET_HINTS.length;i++){
            if(s.indexOf(ASSET_HINTS[i]) >= 0){ return 1; }
        }
        return 0;
    }

    // 还原内嵌 JSON 里的转义：\/ 、\u002F 、&amp;、
    // 以及**百分号编码**（抖音的 RENDER_DATA 整段是 encodeURIComponent 过的：
    // https%3A%2F%2Fp3-sign.douyinpic.com%2F...%3Fbiz_tag%3Daweme_images）。
    // 只还原 URL 里真正会用到的分隔符，避免把正文里的 %xx 全展开。
    //
    // 引号 / 尖括号 / 空格 / 反斜杠也必须还原：整段 encodeURIComponent 过的 JSON
    // 里，URL 后面紧跟的是 %22（"）、%20、%5C 之类。不还原的话地址会一直粘到
    // 下一个引号，尾部长出 %22%2C%22 这种垃圾，扩展名判断就失效了 ——
    // 表现为"百分号编码里的 .mp3 / .mp4 一条都认不出来"（标记串如
    // tos-cn-i-0813 因为按子串匹配反而能过，所以只有扩展名那类会漏）。
    function percentDecode(s){
        return String(s)
            .replace(/%25/gi, '%').replace(/%3A/gi, ':').replace(/%2F/gi, '/')
            .replace(/%3F/gi, '?').replace(/%3D/gi, '=').replace(/%26/gi, '&')
            .replace(/%23/gi, '#').replace(/%2B/gi, '+').replace(/%2C/gi, ',')
            .replace(/%3B/gi, ';').replace(/%40/gi, '@').replace(/%7E/gi, '~')
            .replace(/%2D/gi, '-').replace(/%5F/gi, '_').replace(/%2E/gi, '.')
            .replace(/%22/gi, '"').replace(/%27/gi, "'").replace(/%20/gi, ' ')
            .replace(/%3C/gi, '<').replace(/%3E/gi, '>').replace(/%5C/gi, '\\')
            .replace(/%5B/gi, '[').replace(/%5D/gi, ']')
            .replace(/%7B/gi, '{').replace(/%7D/gi, '}')
            .replace(/%7C/gi, '|').replace(/%5E/gi, '^').replace(/%60/gi, '`');
    }

    function unescapeRaw(s){
        return String(s).replace(/\\u002[fF]/g, '/').replace(/\\\//g, '/')
                        .replace(/&amp;/g, '&').replace(/\\u0026/g, '&')
                        .replace(/\\u003[dD]/g, '=').replace(/\\u003[fF]/g, '?');
    }

    function addMedia(rec, source, extra){
        var u = normUrl(rec);
        if(!u || _seen[u]){ return; }
        _seen[u] = true;
        var row = {src: u, kind: (extra && extra.kind) || kindOfUrl(u) || '',
                   format: extOf(u), source: source, asset: isSiteAsset(u)};
        if(u.indexOf('blob:') === 0){ row.blob = true; row.downloadable = false; }
        if(extra){
            for(var k in extra){
                if(k === 'kind'){ continue; }
                if(row[k] === undefined || row[k] === '' || row[k] === 0){
                    row[k] = extra[k];
                }
            }
        }
        out.push(row);
    }

    function lastChar(s){ return s ? s.charAt(s.length - 1) : ''; }

    function lazyAttr(el){
        for(var i=0;i<LAZY_ATTRS.length;i++){
            var v = el.getAttribute ? el.getAttribute(LAZY_ATTRS[i]) : '';
            if(v){ return v; }
        }
        return '';
    }

    function parseSrcset(s){
        var res = [];
        if(!s){ return res; }
        var parts = String(s).split(',');
        for(var i=0;i<parts.length;i++){
            var p = parts[i].replace(/^\s+|\s+$/g, '');
            if(!p){ continue; }
            var bits = p.split(/\s+/);
            if(bits[0]){ res.push({url: bits[0], desc: bits[1] || ''}); }
        }
        return res;
    }

    // 取“最大”的候选：w 描述符取最大宽度，x 描述符按 1000 折算，
    // 都没有时取最后一个（约定俗成的最大图）
    function pickBest(cands){
        if(!cands || !cands.length){ return ''; }
        var best = cands[cands.length - 1].url, bestW = -1;
        for(var i=0;i<cands.length;i++){
            var d = cands[i].desc || '', w = 0;
            if(/w$/.test(d)){ w = parseInt(d, 10) || 0; }
            else if(/x$/.test(d)){ w = (parseFloat(d) || 0) * 1000; }
            if(w >= bestW){ bestW = w; best = cands[i].url; }
        }
        return best;
    }

    function bgUrls(text){
        var res = [], re = /url\((['"]?)([^'")]+)\1\)/gi, m;
        while((m = re.exec(text)) !== null){
            res.push(m[2]);
            if(res.length >= 30){ break; }
        }
        return res;
    }

    // CSS 里定义的背景图（.banner{background-image:url(...)}）。
    // 跨域样式表读 cssRules 会抛 SecurityError，必须逐表 try。
    function cssomUrls(limit){
        var res = [];
        try {
            var sheets = document.styleSheets || [];
            var n = 0;
            for(var i=0;i<sheets.length && n < limit;i++){
                var rules = null;
                try { rules = sheets[i].cssRules; } catch(e){ continue; }
                if(!rules){ continue; }
                for(var j=0;j<rules.length && n < limit;j++){
                    var st = rules[j].style;
                    if(!st){ continue; }
                    var vals = [st.backgroundImage, st.background, st.content,
                                st.listStyleImage, st.borderImageSource];
                    for(var v=0;v<vals.length;v++){
                        var val = vals[v];
                        if(val && String(val).indexOf('url(') >= 0){
                            var us = bgUrls(String(val));
                            for(var k=0;k<us.length;k++){ res.push(us[k]); n++; }
                        }
                    }
                }
            }
        } catch(e){}
        return res;
    }

    function metaContent(sel){
        var els = QSA(sel);
        var res = [];
        for(var i=0;i<els.length;i++){
            var c = els[i].getAttribute('content') || '';
            if(c){ res.push(c); }
        }
        return res;
    }

    // 原始文本扫描：内嵌 JSON（RENDER_DATA / __INITIAL_STATE__）、
    // data-* 大对象、内联脚本里的直链。
    //
    // 为什么要扫三种形态：同一个地址在页面里可能写成
    //   https://a.com/b.mp4           （正常）
    //   https:\/\/a.com\/b.mp4        （JSON 转义）
    //   https%3A%2F%2Fa.com%2Fb.mp4   （整段 encodeURIComponent 的 RENDER_DATA）
    // 只认第一种会大面积漏抓 —— 抖音笔记页的正文图全在 RENDER_DATA 里，
    // 而且是**百分号编码**过的，这正是"只能抓到站点素材图"的根因。
    //
    // 同时按**内容标记**（biz_tag=aweme_images 等）认那些没有常规扩展名的
    // 地址；判不出类型的（既无扩展名也无标记）一律不收集，避免把整页链接
    // 都当成媒体。
    function scanRaw(text, kinds, source, limit){
        if(!text){ return; }
        var raw = String(text);
        var variants = [unescapeRaw(raw)];
        var dec = percentDecode(raw);
        if(dec !== variants[0]){ variants.push(unescapeRaw(dec)); }
        var cap = limit || 300, added = 0;
        var want = kinds || ['image'];
        var reAny = /(?:https?:)?\/\/[^\s"'<>()]{4,600}/gi;
        for(var v=0; v<variants.length && added < cap; v++){
            var t = variants[v], m;
            reAny.lastIndex = 0;
            while((m = reAny.exec(t)) !== null){
                if(reAny.lastIndex === m.index){ reAny.lastIndex++; }
                var u = trimUrl(m[0]);
                var k = kindOfUrl(u) || markedKind(u);
                if(!k){ continue; }
                if(want.indexOf(k) < 0 && want.indexOf('media') < 0){ continue; }
                addMedia(u, source, {kind: k});
                added++;
                if(added >= cap){ break; }
            }
        }
    }

    // URL 令牌尾部常粘着 JSON/代码的标点（, } ) ; 等），去掉它们
    function trimUrl(u){
        var s = String(u);
        while(s.length > 8){
            var c = s.charAt(s.length - 1);
            if(c === ',' || c === ';' || c === ')' || c === ']' || c === '}' ||
               c === '.' || c === '\\' || c === "'" || c === '"' || c === ':'){
                s = s.slice(0, -1);
            } else { break; }
        }
        return s;
    }

    function collectImages(){
        var i, j, im, el, ss, cands, best, direct, src, urls;
        // ---- 1) <img>：currentSrc > srcset 最大图 > 懒加载属性 > src ----
        var imgs = QSA('img');
        for(i=0;i<imgs.length;i++){
            im = imgs[i];
            ss = im.getAttribute('srcset') || im.getAttribute('data-srcset') || '';
            cands = parseSrcset(ss);
            best = pickBest(cands);
            direct = im.currentSrc || im.getAttribute('src') || '';
            if(!direct || direct.indexOf('data:') === 0){ direct = lazyAttr(im) || direct; }
            src = best || direct;
            addMedia(src, 'img', {
                kind: 'image', alt: im.getAttribute('alt') || '',
                title: im.getAttribute('title') || '',
                width: im.naturalWidth || 0, height: im.naturalHeight || 0,
                // srcset 里挑的是**最大**候选（用户要的是原图），
                // 浏览器自己选中的那个（currentSrc）记在 current 列里 ——
                // 它可能更小（按视口宽度挑的），但有时才是真正显示出来的那张，
                // 所以两者都保留，只是不分成两行（一行一个 <img> 更好用）。
                current: (direct && best && direct !== best) ? direct : '',
                srcset: ss, variants: cands.length
            });
        }
        // ---- 2) <picture><source srcset> 与 <source type=image/*> ----
        var srcs = QSA('picture source, source[type^="image"], source[srcset]');
        for(i=0;i<srcs.length;i++){
            el = srcs[i];
            ss = el.getAttribute('srcset') || '';
            cands = parseSrcset(ss);
            best = pickBest(cands) || el.getAttribute('src') || '';
            addMedia(best, 'picture', {kind: 'image', srcset: ss,
                                       media: el.getAttribute('media') || '',
                                       variants: cands.length});
        }
        // ---- 3) SVG 内嵌位图 ----
        var svgImgs = QSA('svg image');
        for(i=0;i<svgImgs.length;i++){
            el = svgImgs[i];
            addMedia(el.getAttribute('href') || el.getAttribute('xlink:href') || '',
                     'svg-image', {kind: 'image'});
        }
        // ---- 4) 背景图：内联 style + 专用 data 属性 + CSS 规则 ----
        var styled = QSA('[style*="url("]');
        for(i=0;i<styled.length;i++){
            urls = bgUrls(styled[i].getAttribute('style') || '');
            for(j=0;j<urls.length;j++){
                addMedia(urls[j], 'style-background', {kind: 'image'});
            }
        }
        for(i=0;i<BG_ATTRS.length;i++){
            var bgEls = QSA('[' + BG_ATTRS[i] + ']');
            for(j=0;j<bgEls.length;j++){
                addMedia(bgEls[j].getAttribute(BG_ATTRS[i]), 'bg-attr',
                         {kind: 'image', attr: BG_ATTRS[i]});
            }
        }
        urls = cssomUrls(400);
        for(i=0;i<urls.length;i++){
            addMedia(urls[i], 'css-background', {kind: 'image'});
        }
        // ---- 5) <link> 预加载 / 图标 ----
        var links = QSA('link[rel="preload"][as="image"], link[rel="icon"], ' +
                        'link[rel="shortcut icon"], link[rel="apple-touch-icon"], ' +
                        'link[rel="image_src"], link[rel="mask-icon"]');
        for(i=0;i<links.length;i++){
            el = links[i];
            addMedia(el.getAttribute('href') || '', 'link',
                     {kind: 'image', rel: el.getAttribute('rel') || ''});
        }
        // ---- 6) og:image / twitter:image ----
        var metaImgs = metaContent(
            'meta[property="og:image"], meta[property="og:image:url"], ' +
            'meta[property="og:image:secure_url"], meta[name="twitter:image"], ' +
            'meta[name="twitter:image:src"], meta[itemprop="image"]');
        for(i=0;i<metaImgs.length;i++){
            addMedia(metaImgs[i], 'meta', {kind: 'image'});
        }
        // ---- 7) 视频封面也算图片 ----
        var posters = QSA('video[poster]');
        for(i=0;i<posters.length;i++){
            addMedia(posters[i].getAttribute('poster'), 'poster', {kind: 'image'});
        }
        // ---- 8) 原始 HTML 文本扫描（懒加载库 / 内嵌 JSON 里的真地址） ----
        scanRaw(document.documentElement ? document.documentElement.innerHTML : '',
                ['image'], 'inline-json', 200);
    }

    function collectVideo(){
        var i, j, el, ss, cands, best, srcs;
        // ---- 1) <video>：src / currentSrc / <source> / poster / data-* ----
        var vids = QSA('video');
        for(i=0;i<vids.length;i++){
            el = vids[i];
            var vsrc = el.currentSrc || el.getAttribute('src') || lazyAttr(el) || '';
            ss = el.getAttribute('srcset') || '';
            cands = parseSrcset(ss);
            addMedia(pickBest(cands) || vsrc, 'video', {
                kind: 'video', poster: ABS(el.getAttribute('poster') || ''),
                width: el.videoWidth || el.getAttribute('width') || 0,
                height: el.videoHeight || el.getAttribute('height') || 0,
                duration: el.duration && isFinite(el.duration) ? el.duration : 0,
                autoplay: el.autoplay ? 1 : 0, loop: el.loop ? 1 : 0,
                muted: el.muted ? 1 : 0, controls: el.controls ? 1 : 0,
                srcset: ss, variants: cands.length
            });
            var inner = el.querySelectorAll('source');
            for(j=0;j<inner.length;j++){
                addMedia(inner[j].getAttribute('src') || '',
                         'video-source', {
                             kind: 'video',
                             type: inner[j].getAttribute('type') || '',
                             label: inner[j].getAttribute('label') || '',
                             res: inner[j].getAttribute('res') || ''
                         });
            }
        }
        // ---- 2) 独立的 <source type="video/*">（不在 <video> 里的播放器） ----
        srcs = QSA('source[type^="video"]');
        for(i=0;i<srcs.length;i++){
            addMedia(srcs[i].getAttribute('src') || '', 'source-video',
                     {kind: 'video', type: srcs[i].getAttribute('type') || ''});
        }
        // ---- 3) 预加载 ----
        srcs = QSA('link[rel="preload"][as="video"], link[rel="video_src"]');
        for(i=0;i<srcs.length;i++){
            addMedia(srcs[i].getAttribute('href') || '', 'link', {kind: 'video'});
        }
        // ---- 4) og:video / JSON-LD VideoObject ----
        var metas = metaContent(
            'meta[property="og:video"], meta[property="og:video:url"], ' +
            'meta[property="og:video:secure_url"], meta[name="twitter:player:stream"], ' +
            'meta[itemprop="contentUrl"], meta[itemprop="embedUrl"]');
        for(i=0;i<metas.length;i++){
            addMedia(metas[i], 'meta', {kind: 'video'});
        }
        // ---- 5) 视频平台 iframe（站方播放器，地址本身就有价值） ----
        var frames = QSA('iframe');
        for(i=0;i<frames.length;i++){
            var fsrc = frames[i].getAttribute('src') || '';
            if(/youtube\.com\/embed|youtu\.be|player\.bilibili\.com|player\.youku\.com|v\.qq\.com|douyin\.com\/player|ixigua\.com|kuaishou\.com\/player|vimeo\.com\/video/i.test(fsrc)){
                addMedia(fsrc, 'iframe-player', {kind: 'video-embed'});
            }
        }
        // ---- 6) 原始 HTML / 内嵌 JSON：m3u8、mp4、blob 源等 ----
        scanRaw(document.documentElement ? document.documentElement.innerHTML : '',
                ['video', 'audio'], 'inline-json', 300);
    }

    function collectAudio(){
        var i, j, el, srcs;
        var auds = QSA('audio');
        for(i=0;i<auds.length;i++){
            el = auds[i];
            addMedia(el.currentSrc || el.getAttribute('src') || lazyAttr(el) || '',
                     'audio', {
                         kind: 'audio', autoplay: el.autoplay ? 1 : 0,
                         loop: el.loop ? 1 : 0, muted: el.muted ? 1 : 0,
                         controls: el.controls ? 1 : 0,
                         duration: el.duration && isFinite(el.duration) ? el.duration : 0
                     });
            var inner = el.querySelectorAll('source');
            for(j=0;j<inner.length;j++){
                addMedia(inner[j].getAttribute('src') || '', 'audio-source',
                         {kind: 'audio',
                          type: inner[j].getAttribute('type') || ''});
            }
        }
        srcs = QSA('source[type^="audio"]');
        for(i=0;i<srcs.length;i++){
            addMedia(srcs[i].getAttribute('src') || '', 'source-audio',
                     {kind: 'audio', type: srcs[i].getAttribute('type') || ''});
        }
        srcs = QSA('link[rel="preload"][as="audio"], link[rel="audio_src"]');
        for(i=0;i<srcs.length;i++){
            addMedia(srcs[i].getAttribute('href') || '', 'link', {kind: 'audio'});
        }
        var metas = metaContent(
            'meta[property="og:audio"], meta[property="og:audio:url"], ' +
            'meta[property="og:audio:secure_url"], meta[itemprop="audio"], ' +
            'meta[name="twitter:player:stream"]');
        for(i=0;i<metas.length;i++){
            addMedia(metas[i], 'meta', {kind: 'audio'});
        }
        scanRaw(document.documentElement ? document.documentElement.innerHTML : '',
                ['audio'], 'inline-json', 300);
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
            resetSeen();
            collectImages();
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
            resetSeen();
            collectVideo();
        },
        audio: function(){
            resetSeen();
            collectAudio();
        },
        media: function(){
            // 三路共用一个 _seen：同一地址只在第一次出现时入表，
            // 于是 media 模式天然去重（视频里的音轨、封面里的图都算一份）。
            resetSeen();
            collectImages();
            collectVideo();
            collectAudio();
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
    """生成 IIFE 提取 JS：立即执行并返回 JSON 字符串。

    媒体扩展名表从 config.default_settings 注入（**唯一真值来源**），
    不在 JS 里另抄一份 —— 那样加一个新格式就得改两个地方，
    而漏改的那次不会有任何报错，只会「静默少抓一批地址」。
    """
    items = [_field_dict(f) for f in (fields or [])]
    return _inject(
        _EXTRACT_TEMPLATE,
        FIELDS=json.dumps(items, ensure_ascii=True),
        SELECTOR=json.dumps(str(selector or "")),
        PATTERN=json.dumps(str(pattern or "")),
        FLAGS=json.dumps(str(flags or "g")),
        MODE=json.dumps(str(mode)),
        IMG_EXTS=json.dumps("|".join(IMAGE_EXTS)),
        VIDEO_EXTS=json.dumps("|".join(VIDEO_EXTS)),
        AUDIO_EXTS=json.dumps("|".join(AUDIO_EXTS)),
        MEDIA_EXTS=json.dumps("|".join(ALL_MEDIA_EXTS)),
    )
