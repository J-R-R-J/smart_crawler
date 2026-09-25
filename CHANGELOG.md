# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)，格式参考
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

---

## [0.0.4] - 2026-09-25

本批聚焦「抓取引擎扩展与自适应提取」，引入 **Scrapling 融合层**（可选依赖）。

### 新增

- **抓取引擎可选（左侧新增「② 抓取引擎（反检测）」组）**：页面 HTML 从哪里来
  变成可配置项，四种引擎共用同一套检测 / 弹窗 / 提取 / 翻页 / 结果展示流程：
  - **浏览器引擎**：QtWebEngine 自行请求并渲染（默认，兼容 JS 站点）；
  - **HTTP 快速模式**：`curl_cffi` 伪装浏览器 TLS 指纹，**不启动浏览器**，
    静态页速度提升一个数量级；
  - **隐身引擎**：Scrapling `StealthyFetcher`，可自动过 Cloudflare 验证；
  - **动态引擎**：Scrapling `DynamicFetcher`（Playwright），适合 JS 渲染重的页面。

  关键点：反检测作用在**请求阶段**，取回 HTML 后灌入同一个渲染引擎，
  因此后续所有既有能力无需改动即可复用。

- **自适应选择器（网站改版自愈）**：勾选后，常规选择器提取不到数据时，
  改用 Scrapling 依据此前保存的元素特征重新定位元素。
  实测：容器 class 由 `old-card` 整体改为 `brand-new-card` 后，
  原选择器返回 0 条，开启自适应后成功找回全部记录。

- **高级选择器语法**：字段子选择器支持 `::text`、`::attr(name)`、
  XPath、正则等写法，与原有 `text / href / src / html / attr` 类型并存。

- **`core/scrapling_engine.py`**：统一融合层。惰性导入、可选依赖、
  未安装时静默降级；对外返回与 `core.extractor` 相同形状的 `list[dict]`。
  自适应特征库落在 `crawler_data/scrapling_adaptive.db`（不写 cwd）。

- **`core/browser.py` 新增 `load_html()`**：把外部抓到的 HTML 灌入渲染引擎。
  超过约 2MB 的文档自动改走本地文件加载，并注入 `<base href>`，
  保证相对链接仍按原站解析（绕开 `setHtml` 的体积限制）。

- **`tests/test_scrapling.py`**：99 项断言，覆盖解析、自适应自愈、
  降级路径、接入层（Task 字段 / 左面板 / 偏好 / `<base>` 注入）、外挂依赖目录，
  外加两条**防静默故障**的守卫（顶层重名检测、外挂目录真实性验证）。

- **外挂依赖目录**：冻结版会把 `crawler_data/site-packages` 追加到 `sys.path`，
  因此免安装版也能用非浏览器引擎（把 Scrapling `pip --target` 装到那里即可，
  不必改安装目录）。`PLAYWRIGHT_BROWSERS_PATH` 已设置时不覆盖。
  新增 `scrapling_engine.probe()`（`find_spec`，不真正导入）供界面提示使用。

- **控制台窗口运行期开关**：正式版改用 console 子系统打包并**默认保留控制台**，
  界面「④ 执行」新增「显示控制台窗口」，可随时隐藏 / 显示，偏好持久化。
  隐藏只是 `ShowWindow(SW_HIDE)`，日志照常写文件。新增 `utils/console.py`。

### 修复

- **打包版完全没有样式**：spec 的 `datas` 是空的，而 PyInstaller 不会自动收集
  `.qss` 这类非 `.py` 文件，导致 `ui/styles.qss` 从未进过包
  （v0.0.2 ~ v0.0.4 的产物都是无样式裸控件）。现在显式声明 `datas`，
  并给 `ui/main_window.py` 加了多路径兜底与「失败时打印全部候选路径」。

- **窗口左上角没有图标**：`QApplication` 从未调用过 `setWindowIcon()`，
  而 Qt 不会自动继承 exe 资源里的图标。新增 `utils/appicon.py` 负责取图，
  找不到图标文件时用矢量现画。顺带修正 `appicon.ico` 只有一张 256×256 的问题
  （标题栏要 16×16，系统缩放会糊）：现在是 16/32/48/64/256 **原生尺寸**。

- **点击 `target="_blank"` 链接没有反应**：`QWebEnginePage.createWindow()`
  默认返回 `nullptr`，新窗口请求被静默丢弃（不报错、不跳转）。
  新增 `core/browser.CrawlerPage` 把请求接回当前视图，并在日志中说明。
  `tests/test_shell.py` 用**真实 WebEngine 导航**验证该行为。

- **`StealthyFetcher` / `DynamicFetcher` 超时被当作毫秒**：
  同一库内两套刻度（`Fetcher` 用秒，浏览器引擎用毫秒），原先把 60 秒传成
  60 毫秒，页面必然导航超时（`Page.goto: Timeout 60ms exceeded`）。
  现在对外统一用秒，浏览器引擎在传参前换算并设下限。

- **函数重名导致提示失效**：`core/scrapling_engine.py` 里 `install_hint`
  被定义了两次（一次是「下载浏览器」的提示，一次是新增的「装包到外挂目录」
  的提示），后一个静默覆盖前一个 —— 于是界面「装到外挂目录」的提示永远不会
  显示，反而在包没装时让人去跑 `scrapling install`。已改名为
  `site_packages_hint()` 并同步 `ui/left_panel.py` 与 `--selftest`。
  Python 对重名函数不报错也不警告，测试里补了「顶层不得重名」的 AST 守卫。

- `test_packaging.py` 的源码窗口截取过于脆弱（固定长度窗口，函数一变长就误报）；
  改为按函数边界截取，并新增「spec 必须把 styles.qss 收进 datas 且真的传给
  `Analysis`」「数据文件不能被 `_drop_data` 误筛」「正式版默认保留控制台」
  三项防回归测试。

### 变更

- `requirements.txt` 补全 Scrapling 可选依赖的安装说明与打包建议。
- `Task` 新增 `engine` / `adaptive` / `engine_timeout` 字段并纳入校验；
  用户偏好新增 `last_engine` / `last_adaptive` 持久化。

### 说明

- **可选依赖**：未安装 Scrapling 时，非浏览器引擎会在抓取时自动回退为
  浏览器引擎并提示原因，程序其余功能完全不受影响。
- 实测基于 **scrapling 0.4.15**（Python 3.13）。注意该版本中入口类为
  `Selector`，旧文档里的 `Adaptor` 已改名；`auto_save` 必须配合
  `Selector(..., adaptive=True)` 才会生效。

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

[0.0.4]: https://github.com/J-R-R-J/smart_crawler/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/J-R-R-J/smart_crawler/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/J-R-R-J/smart_crawler/releases/tag/v0.0.2
[0.0.1]: https://github.com/J-R-R-J/smart_crawler/releases
