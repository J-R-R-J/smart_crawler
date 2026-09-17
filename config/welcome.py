# -*- coding: utf-8 -*-
"""启动时中间浏览器区域的占位页（深色，与 QSS 主题一致）。

不加载任何外部资源，纯内联样式，避免离线/沙箱环境下出现空白或请求失败。
"""

WELCOME_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>SmartCrawler</title>
<style>
  html, body {
    margin: 0; height: 100%;
    background: #16181c; color: #e6e6e6;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", system-ui, sans-serif;
    overflow: hidden;
  }
  .wrap {
    height: 100%; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 4px;
  }
  .logo {
    font-size: 30px; font-weight: 600; letter-spacing: .5px;
    background: linear-gradient(90deg, #4f8cff, #7ad1ff);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  }
  .sub { color: #8b95a3; font-size: 13px; margin-bottom: 22px; }
  .card {
    background: #1f2228; border: 1px solid #2f333b; border-radius: 10px;
    padding: 20px 28px; font-size: 14px; line-height: 2.1; color: #c8d1dc;
    min-width: 380px;
  }
  .card .k { color: #4f8cff; font-weight: 600; margin-right: 6px; }
  .card .em { color: #e6e6e6; font-weight: 600; }
  .hint {
    margin-top: 20px; color: #6f7885; font-size: 12px;
    max-width: 460px; text-align: center; line-height: 1.8;
  }
</style>
</head>
<body>
  <div class="wrap">
    <div class="logo">SmartCrawler</div>
    <div class="sub">智能可视化爬虫 · 内嵌浏览器</div>
    <div class="card">
      <div><span class="k">1.</span>顶部输入网址，点 <span class="em">加载</span></div>
      <div><span class="k">2.</span>左侧选择 <span class="em">抓取目标格式</span>（默认「结构化记录」）</div>
      <div><span class="k">3.</span>点 <span class="em">拾取元素</span>，在页面上点你要抓的内容</div>
      <div><span class="k">4.</span>点 <span class="em">开始抓取</span>，右侧查看并导出结果</div>
    </div>
    <div class="hint">
      遇到验证码 / 滑块 / 登录墙时，程序会自动暂停并把页面交给你处理，
      处理完成后会在 2 秒内自动继续。
    </div>
  </div>
</body>
</html>
"""
