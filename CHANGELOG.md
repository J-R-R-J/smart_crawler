# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)，格式参考
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

---

## [0.0.3] - 2026-09-20

本版聚焦「界面可用性 + 反检测加固 + 下载控制」。

### 新增

- **下载格式白名单**：左侧面板新增「下载格式」，只放行指定扩展名（如 `pdf,csv,xlsx`），
  留空表示不限；与原有的下载大小上限共同构成两道关卡，均在**发起阶段**拦截。
  支持全角逗号、大小写混写与前导点（`.PDF` 等价于 `pdf`）。
- **左侧配置面板可滚动**：面板内容改用滚动区承载，配置项再多也不会被窗口高度截断。
- **窗口尺寸自适应**：初始尺寸按可用屏幕计算（最多占 90%），并设最小尺寸 1000×620，
  解决「默认窗口高过屏幕看不到底部」与「最大化后控件被挤压」两个问题。
- **反爬特征自检工具**：`tools/probe_stealth.py` 升级为完整指纹报告，
  分组打印实际取值并标出与期望不符的项，另附 18 个现代 JS API 的可用性检查。

### 反检测加固

- **`navigator.webdriver` 彻底移除**：改为从 `Navigator.prototype` 上 `delete`，
  不再留下 own property 痕迹；`'webdriver' in navigator` 现为 `false`
  （此前只在实例上覆盖，属性依然存在，反而更易被识别）。
- **启动参数新增 `--disable-blink-features=AutomationControlled`**：
  让 Chromium 从源头不设置该自动化标志，比事后用 JS 覆盖更彻底。
- **清理自动化框架残留标记**：批量移除 Selenium / WebDriver / ChromeDriver
  （`cdc_`、`$wdc_` 前缀动态扫描）/ PhantomJS / Nightmare / Playwright /
  Puppeteer，以及 `domAutomation` 等老式自动化桥标记。
- **扩充环境一致性伪装**：补齐 `window.chrome.app/csi/loadTimes`、
  `navigator.connection`、`outerWidth/outerHeight`（无头下为 0）、
  `document.hasFocus()`（无头下恒 false）；`plugins` 与 `mimeTypes` 一起补齐；
  WebGL 伪装同时覆盖 WebGL 与 WebGL2 两个上下文。

### 变更

- **User-Agent 不再带工具标识**：原先 UA 结尾的 `SmartCrawler/1.0` 等于向站点自报
  「我是自动化工具」，会让其他所有伪装失效。现改为纯正桌面 Chrome UA；
  如需保持可识别性（更透明的做法），可设置环境变量 `SMARTCRAWLER_UA_SUFFIX` 追加。
- 测试扩充至 **183 项**（功能 64 / 界面 64），新增下载白名单、滚动面板、
  窗口尺寸、关键词配置隔离等断言。

### 说明

- QtWebEngine 基于完整 Chromium，`fetch` / `Promise` / `Intl` / `Proxy` /
  `ResizeObserver` / `AbortController` / `structuredClone` 等现代 API 全部原生可用，
  实测 18/18 通过，不存在「API 缺失导致指纹异常」的问题。
- QtWebEngine 使用自有 IPC，不暴露 CDP（Chrome DevTools Protocol），
  `$cdc_`、`Runtime.enable` 这类纯 CDP 痕迹本就不存在，程序仍做清理以防万一。

---

## [0.0.2] - 2026-09-18

本次更新以「降低误判、增强检测、补齐工程细节」为主。

### 新增

- **多格式复选**：抓取格式由单选改为可勾选列表，可一次提取多种格式并合并结果，
  每条记录带 `_mode` 字段标记来源；新增「全选 / 清空选择」快捷按钮。
- **检测关键词可自定义**：新增「检测关键词设置」对话框，三组关键词（验证码 / 访问频控 /
  登录墙）均可编辑，保存到 `crawler_data/keywords.json` 并立即生效，无需重启。
- **检测数据源扩展**：在 HTML 源码之外，同时扫描页面标题、当前 URL 与**渲染后的可见文本**
  （`body.innerText`），可识别由 JS 动态渲染或写入 CSS `content` 的关键词。
- **抗混淆归一化**：检测前去除零宽字符（`\u200b`、`\u200c`、`\u200d`、`\u2060`、`\ufeff`
  等）并折叠空白，去空白后再比对一次，可识破 `验<ZWSP>证<ZWSP>码` 与 `验 证 码` 两类伪装。
- **验证码 / 登录墙结构化确认**：命中关键词后进一步扫描页面是否**真的存在验证组件**
  （验证码输入框、第三方验证 iframe、已知组件容器、图形验证码），
  据此区分「已确认」与「疑似」，显著降低误判。
- **无提示验证组件也能识别**：结构检查排在关键词之前，因此没有任何文字提示的
  裸验证组件同样会被识别。
- **误判可跳过**：横幅新增「跳过（误判）」按钮，跳过后立即继续抓取，
  并在**本任务内**不再因验证暂停；重新开始任务会恢复检测，日志留痕。
- **反爬对抗**：新增浏览器特征伪装（`navigator.webdriver`、`languages`、`platform`、
  `plugins`、`window.chrome`、`permissions`、WebGL 厂商等）与每页延迟 ±30% 随机抖动，
  可在界面开关。
- **下载大小限制**：可设置单个文件的下载大小上限，服务端给出总大小时直接拒绝，
  未给出时按已接收字节实时监控并中断；下载文件归档到 `crawler_data/downloads/`。
- **临时文件清理**：界面新增「清理临时文件」，可清理引擎缓存、`__pycache__` 与临时日志，
  并报告释放空间；新增 `utils/maintenance.py` 提供统计与清理 API。
- **导出目录可自定义**：新增「导出目录…」按钮，设置后持久化，实际保存后自动记忆，
  取消选择即恢复默认目录。
- **启动占位页**：启动时浏览器区域显示使用说明页，不再是空白页。
- **辅助脚本**：新增 `tools/probe_stealth.py`（验证反爬伪装是否生效）。

### 修复

- **导航按钮报错**：Qt6 已移除 `QWebEnginePage.back()/forward()/reload()`，
  改为 `triggerAction(WebAction.*)`，修复点击「后退 / 前进 / 刷新」抛 `AttributeError`。
- **停止后无法再次开始**：`stop_task()` 未发出 `task_finished`，导致「开始抓取」
  按钮一直处于禁用状态，现已复位并保留已抓取数据。
- **用户偏好静默丢失**：「设为默认 Profile」「上次使用的格式」等设置实际未保存
  （`QSettings` 默认写系统注册表，无写权限时静默失败）。改用
  `crawler_data/settings.ini`（INI 文本），便携且可靠。
- **地址栏破坏非 HTTP 协议**：原先对任何非 `http(s)` 输入强行补 `https://`，
  导致 `file://`、`about:` 等地址失效；改为仅在没有 `://` 时补全。
- **退出阶段崩溃**：profile 先于 page 销毁触发
  `Release of profile requested but WebEnginePage still not deleted`，
  严重时导致访问违例退出。现按「page 先、profile 后」顺序强制销毁，
  并在 `closeEvent` / `aboutToQuit` 中统一清理。
- **弹窗扫描失效**：`runJavaScript` 对数组 / 对象返回值返回空串，
  `POPUP_SCAN_JS` 未做 `JSON.stringify`，导致弹窗永远检测不到。
- **Cookie 删除失败**：Qt 会将 domain 规范化为带前导点（`example.com` → `.example.com`），
  删除时按键不匹配；现兼容两种写法。
- **视频地址重复**：`<video>` 与其 `<source>` 被各计一次，现按 src 去重。
- **Cookie 面板构造参数笔误**：`ui/right_panel.py` 中 `CookiePanel(prefs)`
  引用了未定义变量。

### 变更

- **多 Profile 实现方式**：单进程渲染下 QtWebEngine 只允许一个引擎实例（创建第二个会崩溃），
  因此 Profile 改为「同一引擎 + 按名称持久化的 Cookie 集」，切换即
  保存 → 清空 → 载入，登录态隔离效果不变。
- **界面文案去表情符号**：按钮与标签统一为纯文字，便于在任意字体环境下显示。
- **目录结构调整**：测试移入 `tests/`（含 `testdata/`）、辅助脚本移入 `tools/`、
  截图移入 `docs/`。
- **测试扩充**：由 1 套扩展为 4 套（冒烟 / 端到端 / 功能覆盖 / 界面交互），
  断言数由 126 增至 168，全部通过。
- **README 重写**：补充反爬检测原理、反爬对抗机制、下载限制与清理、
  自定义关键词等章节。
- 版本号在窗口标题与启动日志中显示。

---

## [0.0.1] - 2026-09-16

首个版本。

### 新增

- 基于 PySide6 + QtWebEngine 的桌面爬虫：内嵌浏览器，所见即所抓。
- 18 种抓取格式：结构化记录、列表文本、表格、链接、图片、页面文本、HTML、正则、
  JSON-LD、Meta、表单、视频、iframe、RSS、Sitemap、联系方式、内嵌 JSON、页面 Cookie。
- 可视化元素拾取：点击页面元素自动生成 CSS 选择器。
- 反爬识别与人机协作：检测到验证码 / 登录墙时自动暂停，处理完成后自动继续。
- 弹窗处理三策略：只报告 / 点关闭按钮 / 直接移除 DOM。
- Cookie 管理面板：查看、编辑、删除、清空、导入、导出。
- 多 Profile：隔离不同站点的登录态。
- 自动翻页与懒加载滚动。
- 结果导出 CSV / JSON，日志按天落盘并轮转。
- 单进程软渲染默认开启，可在容器 / 无 GPU / 远程桌面环境下运行。

[0.0.3]: https://github.com/J-R-R-J/smart_crawler/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/J-R-R-J/smart_crawler/releases/tag/v0.0.2
[0.0.1]: https://github.com/J-R-R-J/smart_crawler/releases
