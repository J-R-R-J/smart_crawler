# SmartCrawler 智能可视化爬虫

一个基于 **PySide6 + QtWebEngine** 的桌面爬虫工具：把浏览器内核嵌进界面，所见即所抓；
遇到验证码、人机校验、登录墙或弹窗时自动暂停，把页面交给人处理，处理完自动继续抓取。

适用于需要登录态、需要人工过验证、页面结构不规整的中小规模采集场景。

![界面截图](docs/screenshot.png)

---

## 目录

- [主要特性](#主要特性)
- [环境要求](#环境要求)
- [安装](#安装)
- [快速开始](#快速开始)
- [抓取格式一览](#抓取格式一览)
- [人机协作机制](#人机协作机制)
- [弹窗处理策略](#弹窗处理策略)
- [Profile 与 Cookie 管理](#profile-与-cookie-管理)
- [结果查看与导出](#结果查看与导出)
- [项目结构](#项目结构)
- [配置说明](#配置说明)
- [扩展开发](#扩展开发)
- [测试](#测试)
- [常见问题](#常见问题)
- [已知限制](#已知限制)
- [许可与免责声明](#许可与免责声明)

---

## 主要特性

| 能力 | 说明 |
| --- | --- |
| 内嵌浏览器 | QtWebEngine（Chromium 内核），渲染结果与手写选择器完全一致 |
| 反爬识别 | 内置验证码 / 滑块 / 人机校验 / 访问频控 / 登录墙关键词识别 |
| 人机协作 | 检测到验证时自动暂停，轮询检测恢复后自动继续，无需重跑任务 |
| 可视化拾取 | 点击页面上任意元素自动生成 CSS 选择器，无需手写 |
| 18 种抓取格式 | 覆盖结构化记录、表格、链接、图片、正则、JSON-LD 等常见需求，可扩展 |
| 弹窗处理 | 三种策略可选：只报告 / 点击关闭按钮 / 直接移除 DOM，处理多轮弹窗 |
| Cookie 管理 | 表格化查看、编辑、删除、清空、导入、导出，支持会话标记显示 |
| 多 Profile | 不同站点使用不同身份，登录态互相隔离，可新建 / 删除 / 设为默认 |
| 自动翻页 | 支持自定义「下一页」选择器与最大页数，翻页失败有兜底逻辑 |
| 懒加载滚动 | 可选自动滚动触发懒加载，适配无限滚动页面 |
| 结果导出 | CSV（UTF-8 BOM，Excel 可直接打开）与 JSON |
| 日志落盘 | 按天生成日志文件，单文件 5 MB 轮转，保留 3 份历史 |
| 单进程渲染 | 默认单进程软渲染，在容器 / 无 GPU / 远程桌面 / CI 环境下也能稳定运行 |

---

## 环境要求

- **Python 3.10 或更高版本**
- **PySide6 >= 6.6.0**（必须包含 QtWebEngine，即完整版 `PySide6`，不是 `PySide6-Essentials`）
- 操作系统：Windows / Linux / macOS

---

## 安装

### 方式一：pip 安装依赖

```bash
pip install -r requirements.txt
```

### 方式二：手动安装

```bash
pip install PySide6
```

### 方式三：一键启动脚本

- Windows：双击 `run.bat`
- Linux / macOS：`bash run.sh`

启动脚本会自动检测虚拟环境、检查依赖并在缺失时安装。

> 若项目目录下存在 `.venv`，`run.bat` / `run.sh` 会优先使用它。

---

## 快速开始

### 第 1 步：启动程序

```bash
python main.py
```

界面分为三栏：

- **左侧**：抓取配置（格式、选择器、字段映射、翻页、延迟）
- **中间**：内嵌浏览器（所见即所得）
- **右侧**：五个标签页（数据 / JSON / Cookie / 日志 / 任务）

### 第 2 步：加载目标页面

在顶部地址栏输入网址，点击 **加载**。页面会直接渲染在中间区域。

### 第 3 步：选择抓取格式

在左侧 **抓取目标格式** 下拉框中选择。常用场景：

| 场景 | 推荐格式 |
| --- | --- |
| 列表页 + 详情字段 | 结构化记录 |
| 只要列表文字 | 列表文本 |
| 表格型站点 | 表格数据 |
| 只要所有链接 | 链接列表 |
| 页面结构复杂、想用正则 | 正则提取 |

### 第 4 步：配置选择器

点击顶部 **拾取元素** 按钮，然后在浏览器中点选目标元素，程序会自动生成并填入 CSS 选择器。

若抓取格式为 **结构化记录**，在 **字段映射** 文本框中按行描述字段，格式为：

```
字段名 | 子选择器 | 取值类型 | 属性名
```

示例：

```
标题 | h3 > a  | text |
链接 | h3 > a  | href |
价格 | .price  | text |
封面 | img      | src  |
编码 | .item    | attr | data-id
```

取值类型支持：`text`（文本）、`href`（链接）、`src`（资源地址）、`html`（内部 HTML）、`attr`（自定义属性，需在第 4 列指定属性名）。

### 第 5 步：配置翻页（可选）

- **下一页选择器**：如 `a.next`、`.pagination .next`
- **最大页数**：限制抓取页数，避免失控
- **每页延迟**：秒，建议不低于 1 秒，降低被封风险
- **自动滚动触发懒加载**：适合无限滚动页面

### 第 6 步：开始抓取

点击 **开始抓取**。过程中可以：

- 在 **日志** 标签页查看实时进度
- 在 **数据** 标签页查看已抓取的行
- 点击 **停止** 随时中断

### 第 7 步：导出结果

在 **数据** 标签页点击 **导出 CSV** 或 **导出 JSON**，文件默认保存到 `crawler_data/exports/`。

---

## 抓取格式一览

| # | 格式名 | 标识 | 说明 | 需要选择器 |
| --- | --- | --- | --- | --- |
| 1 | 结构化记录 | `records` | 容器选择器 + 字段映射，适合列表页提取多条记录 | 是 |
| 2 | 列表文本 | `list` | 提取容器下所有元素的文本行 | 是 |
| 3 | 表格数据 | `table` | 提取页面 `<table>` 的二维数据，自动识别表头 | 否 |
| 4 | 链接列表 | `links` | 提取所有 `<a>` 的文本与链接 | 否 |
| 5 | 图片列表 | `images` | 提取所有 `<img>` 的地址与 alt | 否 |
| 6 | 页面文本 | `text` | 提取页面纯文本内容 | 否 |
| 7 | 页面 HTML | `html` | 提取完整 HTML 源码 | 否 |
| 8 | 正则提取 | `regex` | 用正则表达式从 HTML 中提取，支持捕获组 | 否 |
| 9 | JSON-LD | `jsonld` | 解析 `<script type="application/ld+json">` 结构化数据 | 否 |
| 10 | Meta 信息 | `meta` | 提取 title / description / keywords 等元信息 | 否 |
| 11 | 表单数据 | `forms` | 提取所有 `<form>` 的字段、类型与默认值 | 否 |
| 12 | 视频地址 | `video` | 提取 `<video>` 与 `<source>` 的地址（自动去重） | 否 |
| 13 | iframe 地址 | `iframe` | 提取所有 `<iframe>` 的 src | 否 |
| 14 | RSS 订阅 | `rss` | 提取页面声明的 RSS / Atom 订阅地址 | 否 |
| 15 | Sitemap | `sitemap` | 提取页面声明的站点地图链接 | 否 |
| 16 | 联系方式 | `contacts` | 从页面文本中提取邮箱与电话号码 | 否 |
| 17 | 内嵌 JSON | `embedded_json` | 解析页面内嵌的 JSON 脚本块 | 否 |
| 18 | 页面 Cookie | `page_cookies` | 提取当前页面的 Cookie 快照 | 否 |

所有格式统一输出为「字典列表」，便于导出与二次处理。

---

## 人机协作机制

这是本项目与普通爬虫脚本最大的区别。

### 检测阶段

每页加载完成后，程序会对页面 HTML 与标题做分类，判定顺序为：

1. **验证码 / 人机验证（CAPTCHA）**：命中 `captcha`、`验证码`、`人机验证`、`recaptcha`、`hcaptcha`、`turnstile`、`cf-challenge`、`challenge-platform`、`滑块` 等关键词
2. **访问频控（HUMAN）**：命中 `访问过于频繁`、`unusual traffic`、`temporarily blocked` 等关键词
3. **登录墙（LOGIN）**：同时命中登录关键词且页面存在密码输入框
4. 以上都不命中则正常继续

### 处理阶段

一旦判定需要人类介入：

1. 顶部弹出提示横幅，说明检测原因
2. 任务状态切换为「等待人类」，**所有自动动作停止**
3. 你直接在中间浏览器窗口中手动完成验证（点选图片、拖动滑块、输入账号密码）
4. 程序每 **2 秒** 自动重新检测一次，识别到页面恢复正常后**自动继续**抓取
5. 也可以点击横幅上的 **我已处理完成，继续抓取** 按钮手动触发检测

整个过程不会丢失已抓取的数据，也不会重跑任务。

---

## 弹窗处理策略

很多站点会在加载后弹出遮罩层、公告框、订阅提示。程序在每页加载后自动扫描并处理，
顶部下拉框可切换三种策略：

| 策略 | 标识 | 行为 | 适用场景 |
| --- | --- | --- | --- |
| 只报告 | `notify` | 仅在日志中记录发现的弹窗，不做任何干预 | 调试阶段、不想误伤页面结构 |
| 点关闭按钮 | `close` | 尝试点击弹窗的关闭按钮（默认，推荐） | 绝大多数场景 |
| 直接移除 DOM | `remove` | 直接从 DOM 中删除弹窗节点 | 关闭按钮无效、弹窗反复出现 |

- 每轮加载最多处理 **3 轮** 弹窗，直到页面不再出现新的弹窗
- 关闭按钮选择器可在 `config/default_settings.py` 的 `POPUP_CLOSE_SELECTORS` 中扩充
- 弹窗识别关键词可在 `POPUP_HINT_KEYWORDS` 中扩充

---

## Profile 与 Cookie 管理

### 为什么需要 Profile

同一个站点用不同身份访问、或需要多账号登录时，登录态（Cookie）必须隔离。
本程序用 **Profile** 承载这种隔离。

### 实现方式

QtWebEngine 在单进程渲染模式下**只允许存在一个浏览器引擎实例**（创建第二个会直接崩溃）。
因此本项目把 Profile 实现为：

> **同一个引擎 + 按 Profile 名持久化的 Cookie 集**

- 每个 Profile 对应 `crawler_data/profiles/<名称>/cookies.json`
- 切换 Profile 时执行：**保存当前 Cookie 集 → 清空 Cookie 存储 → 载入目标 Profile 的 Cookie 集**
- 所有 Cookie 变更会自动去抖持久化，程序重启后登录态仍在

这在效果上等价于多身份隔离，同时完全兼容单进程渲染环境。

### 用法

在右侧 **Cookie** 标签页：

- 顶部下拉框切换 Profile
- **新建** 创建新 Profile；**删除** 移除 Profile（`default` 受保护）
- **设为默认** 记住下次启动使用的 Profile
- Cookie 表格支持双击编辑、右键菜单、批量删除、清空、导入、导出

---

## 结果查看与导出

右侧五个标签页：

| 标签页 | 内容 |
| --- | --- |
| 数据 | 抓取结果的表格视图，列会自动适配 |
| JSON | 原始结果 JSON，方便复制或二次处理 |
| Cookie | Profile 与 Cookie 管理 |
| 日志 | 实时运行日志（同时写入磁盘） |
| 任务 | 任务汇总信息（条数、耗时、当前 URL、Profile、弹窗策略） |

导出格式：

- **CSV**：UTF-8 with BOM 编码，Excel 直接双击即可正常显示中文
- **JSON**：标准 JSON 数组，缩进 2 空格

导出目录默认为 `crawler_data/exports/`，可在导出对话框中另存到任意位置。

---

## 项目结构

```
smart_crawler/
├── main.py                     程序入口（环境准备 + 启动主窗口）
├── requirements.txt            依赖清单
├── run.bat / run.sh            一键启动脚本
├── clean.bat                   临时文件清理脚本
├── README.md
├── LICENSE
├── .gitignore
│
├── config/                     配置层
│   ├── constants.py            路径常量与应用元信息
│   ├── default_settings.py     格式注册表、反爬关键词、弹窗策略与选择器
│   ├── js_scripts.py           全部注入 JS（提取脚本生成器 + 桥接 + 拾取 + 弹窗）
│   └── welcome.py              启动占位页 HTML
│
├── core/                       业务层
│   ├── signals.py              全局信号总线（模块间解耦）
│   ├── user_prefs.py           用户偏好持久化（QSettings）
│   ├── browser.py              浏览器引擎、页面、QWebChannel 桥接
│   ├── cookie_manager.py       Cookie 增删查改与 Profile Cookie 集持久化
│   ├── detector.py             反爬分类（CAPTCHA / HUMAN / LOGIN / NONE）
│   ├── extractor.py            18 种格式的提取调度与结果规范化
│   ├── picker.py               元素拾取（JS 注入 + 桥接回传）
│   ├── pager.py                翻页检测与点击
│   ├── popup_handler.py        弹窗扫描与三策略处理
│   └── crawler.py              抓取状态机总调度
│
├── models/                     数据模型
│   ├── field.py                字段映射解析
│   ├── task.py                 任务数据类
│   └── record.py               结果清洗、去重、列合并
│
├── ui/                         界面层
│   ├── styles.qss              深色主题样式表
│   ├── main_window.py          主窗口，组装与信号绑定
│   ├── top_bar.py              地址栏、导航、拾取、弹窗策略
│   ├── banner.py               人类验证提示横幅
│   ├── left_panel.py           抓取配置面板
│   ├── center_panel.py         浏览器视图
│   ├── right_panel.py          右侧五个标签页
│   └── cookie_panel.py         Cookie 与 Profile 管理面板
│
├── utils/                      工具层
│   ├── logger.py               日志落盘（按天 + 5MB 轮转）
│   ├── exporters.py            CSV / JSON / Cookie 导出导入
│   └── js_runner.py            runJavaScript 封装（限流 + 同步等待）
│
├── docs/
│   └── screenshot.png          界面截图
│
├── tools/
│   └── make_screenshot.py      离屏渲染界面截图（用于更新 README 图片）
│
├── tests/
│   ├── test_smoke.py           冒烟测试
│   ├── test_e2e.py             端到端抓取测试
│   ├── test_feature.py         功能覆盖测试
│   └── testdata/               测试用本地页面
│       ├── page1.html
│       ├── page2.html
│       ├── rich.html
│       └── captcha.html
│
└── crawler_data/               运行时数据（自动创建，已被 .gitignore 忽略）
    ├── profiles/               Profile 与 Cookie 集
    ├── logs/                   日志文件
    ├── exports/                导出结果
    ├── cookies/                Cookie 备份
    └── engine/                 浏览器引擎存储
```

---

## 配置说明

### 路径与元信息

`config/constants.py` 定义了全部运行时目录，导入时自动创建：

```python
BASE_DIR     # 项目根目录
DATA_DIR     # crawler_data/
PROFILE_DIR  # crawler_data/profiles/
LOG_DIR      # crawler_data/logs/
EXPORT_DIR   # crawler_data/exports/
COOKIE_DIR   # crawler_data/cookies/
```

### 默认设置

`config/default_settings.py`：

| 常量 | 作用 |
| --- | --- |
| `SUPPORTED_FORMATS` | 抓取格式注册表，增删此处即可改变下拉框内容 |
| `CAPTCHA_KEYWORDS` | 验证码 / 人机验证识别关键词 |
| `HUMAN_VERIFY_KEYWORDS` | 访问频控类识别关键词 |
| `LOGIN_KEYWORDS` | 登录墙识别关键词 |
| `POPUP_STRATEGIES` | 弹窗策略列表（标识、显示名、提示语） |
| `POPUP_CLOSE_SELECTORS` | 弹窗关闭按钮选择器表 |
| `POPUP_HINT_KEYWORDS` | 弹窗容器特征关键词 |
| `DETECT_INTERVAL_MS` | 人类验证轮询间隔，默认 2000 毫秒 |
| `MAX_POPUP_ROUNDS` | 每页弹窗处理最大轮数，默认 3 |

### 用户偏好

通过 `QSettings` 持久化，由 `core/user_prefs.py` 管理，包括上次使用的格式、
延迟、最大页数、自动滚动、上次 Profile、默认 Profile、弹窗策略。

### 浏览器启动参数

`main.py` 默认设置：

```
QTWEBENGINE_CHROMIUM_FLAGS = --no-sandbox --disable-gpu --single-process
                             --disable-gpu-driver-bug-workarounds
```

在普通桌面环境如需启用 GPU 加速或多进程渲染，可在启动前覆盖：

```bat
set QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu-driver-bug-workarounds
python main.py
```

```bash
export QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu-driver-bug-workarounds
python main.py
```

---

## 扩展开发

### 新增抓取格式

只需两步。

**第一步**：在 `config/default_settings.py` 的 `SUPPORTED_FORMATS` 中追加一行：

```python
SUPPORTED_FORMATS = [
    # ... 现有 18 项 ...
    ("styles", "样式表", "提取页面引用的所有样式表"),
]
```

**第二步**：在 `config/js_scripts.py` 的 `build_extract_js` 内，向 `H` 对象添加同名函数：

```javascript
styles: function(){
    var nodes = QSA('link[rel="stylesheet"], style');
    for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        var href = el.getAttribute('href');
        if (href) { out.push({ href: ABS(href) }); }
    }
},
```

其中 `QSA` 为选择器查询辅助函数，`ABS` 把相对地址转为绝对地址，`out` 为结果数组。

完成后重新启动程序，新格式会自动出现在左侧下拉框中。

### 新增反爬识别关键词

在 `config/default_settings.py` 对应列表中追加即可，`core/detector.py` 会自动使用：

```python
CAPTCHA_KEYWORDS.append("新出现的验证形态")
```

### 更换界面主题

编辑 `ui/styles.qss`，所有颜色与控件样式集中在该文件中。

### 新增弹窗关闭选择器

```python
POPUP_CLOSE_SELECTORS.append(".my-site-close-btn")
```

---

## 测试

项目自带三套无头测试，覆盖从模块导入到真实页面抓取的完整链路。

在项目根目录执行：

```bash
# 冒烟测试：配置、模型、工具、UI 与 core 组装（44 项）
.venv\Scripts\python.exe tests\test_smoke.py

# 端到端测试：真实页面加载 + 翻页抓取 + Cookie + 元素拾取（9 项）
.venv\Scripts\python.exe tests\test_e2e.py

# 功能覆盖测试：18 种格式 + 弹窗三策略 + 验证码检测 + 多 Profile（29 项）
.venv\Scripts\python.exe tests\test_feature.py
```

Linux / macOS 使用 `python tests/test_smoke.py` 等形式即可。

测试结果（本机 Python 3.13 + PySide6 6.9.3）：

```
test_smoke.py    : 44 passed, 0 failed
test_e2e.py      :  9 passed, 0 failed
test_feature.py  : 29 passed, 0 failed
合计             : 82 passed, 0 failed
```

测试使用 `--single-process` 单进程渲染，因此可在无 GPU、无桌面（offscreen）环境中运行，
适合放进 CI。

### 清理临时文件

```bat
clean.bat          # 清理 __pycache__、临时目录、编译产物、测试日志
clean.bat -a       # 追加清理运行数据（日志 / 导出 / Cookie 备份，保留 Profile）
```

---

## 常见问题

**Q：提示找不到 QtWebEngine？**

安装完整版 PySide6，而不是 `PySide6-Essentials`（后者不含 WebEngine）：

```bash
pip install PySide6
```

**Q：在容器 / 无 GPU / 远程桌面 / CI 中启动后崩溃？**

程序默认已启用单进程软渲染，这类环境下可直接运行。若仍异常，检查是否被外部环境变量
覆盖了 `QTWEBENGINE_CHROMIUM_FLAGS`。

**Q：Linux 下启动崩溃？**

```bash
export QTWEBENGINE_DISABLE_SANDBOX=1
```

以 root 运行时需要确保 `--no-sandbox` 生效。

**Q：抓取结果为空？**

依次排查：

1. 页面是否已加载完成（观察中间浏览器区域是否已渲染出内容）
2. 容器选择器是否正确（用 **拾取元素** 重新点选）
3. 是否需要登录（先在浏览器中登录，或切换已有登录态的 Profile）
4. 是否动态渲染（勾选 **自动滚动触发懒加载**）

**Q：为什么多 Profile 不是多个浏览器实例？**

因为单进程渲染模式下 QtWebEngine 只允许一个引擎实例，创建第二个会导致进程崩溃。
因此 Profile 以「Cookie 集」形式实现，登录态隔离效果一致，详见
[Profile 与 Cookie 管理](#profile-与-cookie-管理)。

**Q：某些站点一直卡在验证？**

尝试切换 Profile（更换身份）、调整每页延迟、或降低并发与抓取速度。

**Q：Cookie 导出后还能导入回来吗？**

可以。导出格式为标准 JSON 数组，点 **导入** 选择该文件即可。

**Q：抓取速度太慢？**

单进程软渲染优先保证兼容性。在普通桌面环境下可覆盖
`QTWEBENGINE_CHROMIUM_FLAGS` 启用多进程与 GPU 加速以提升速度。

---

## 已知限制

1. **必须联网**：程序依赖真实浏览器渲染，无法离线分析页面结构。
2. **单进程渲染默认开启**：为保证在受限环境下可用，默认关闭 GPU 与多进程；
   高并发、高频抓取不是本工具的设计目标。
3. **不做验证码自动破解**：识别到验证后交由人工处理，这是刻意的设计选择，
   既合规也更可靠。
4. **未实现分布式与代理池**：如需大规模采集，建议在 `core/browser.py` 中接入
   代理配置，或改用专门的分布式爬虫框架。
5. **选择器依赖页面结构**：站点改版后需要重新拾取。若站点提供 API，优先使用 API。

---

## 许可与免责声明

本项目采用 [MIT License](LICENSE) 开源。

**免责声明**：本工具仅供学习、研究与合法的数据采集用途。使用者应自行确保：

- 遵守目标网站的 `robots.txt`、服务条款与接口使用政策
- 遵守《网络安全法》《数据安全法》《个人信息保护法》等适用法律法规
- 不采集、不传播个人隐私数据与受版权保护的内容
- 控制请求频率，不对目标站点造成服务压力

因不当使用本工具产生的一切后果由使用者自行承担。
