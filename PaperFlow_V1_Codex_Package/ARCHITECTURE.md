# ARCHITECTURE — PaperFlow V1 技术设计

> 本文是实施约束，不是实际实现记录。Codex 开发时如发现第三方 API 变化，应查官方文档/真实 CLI `--help` 修正，并在 `DECISIONS.md` 写明依据，不得静默跳过能力。

## 1. 分层和运行模型

```text
Chrome / Chromium + Read Frog (用户已配置 DeepSeek)
                |
       http://127.0.0.1:PORT
                |
        Web frontend (React + Vite)
                |
           /api/v1/*
                |
        FastAPI application
          |       |        |
      SQLite  Assets   Conversion Queue / Worker
                |        |
     PDF, HTML, images   Marker subprocess
                |
     ~/Library/Application Support/PaperFlow/
```

推荐栈：React + TypeScript + Vite；Tailwind CSS + shadcn/ui（仅复用必要组件）；React Router；TanStack Query（如真正需要）；Python 3.11+/FastAPI/Pydantic v2/SQLAlchemy/Alembic/SQLite；PDF.js（pdfjs-dist）；pytest；Vitest + Playwright。**不使用** Electron/Tauri（V1）、Next.js、PostgreSQL、Redis、Celery、登录和云账户。

生产样式开发：前端打包静态资源，FastAPI 统一同源服务 SPA、API、经净化的 HTML 阅读页；开发模式可通过 Vite proxy `/api` 至 FastAPI（跨域只允许已知 loopback 开发端口，不用 `*`）。统一稳定 origin 有利于 Read Frog 和本地存储。

Marker 执行环境可与轻量 Web 后端拆开，以免 PyTorch/模型依赖污染 API 环境。v1 可以先共享 Python 环境但**务必**以 subprocess 调用，且非阻塞、有限并发。模型懒加载；用户可配置 worker executable path。

## 2. 模块职责

| 组件 | 职责 | 禁止行为 |
|---|---|---|
| Frontend SPA | Library、PDF Reader、Settings、标签管理、轮询任务、进度提交 | 读任意本地路径、持有 DeepSeek Secret |
| HTML Reader Document | 稳定静态文档 shell + 安全 HTML + 图片+公式+最小进度脚本，供 Read Frog 注入 | 将用户生成 HTML 当作可信脚本，React 高频重渲染正文 |
| PaperService | 文件/元数据创建、去重、更新、删除 | 直接相信浏览器传来的文件系统路径 |
| ArxivService | ID 解析、元数据、官方 HTML 探测、PDF 下载 | 允许用户输入 URL 造成 SSRF、自动爬任意站点 |
| ConversionService | 队列、子进程、缓存与原子发布 | 在同步 HTTP 请求内加载大型模型 |
| ReaderStateService | PDF 页码、HTML 锚点及滚动恢复 | 声称能跟踪外部 arXiv 页面的滚动 |
| StorageService | 生成内部 ID、受控路径、事务与清理 | 将任意绝对路径直接映射 HTTP 服务 |

## 3. 数据路径

macOS 默认路径：`~/Library/Application Support/PaperFlow`；可由环境变量 `PAPERFLOW_DATA_DIR` 覆盖，启动时创建并检查写权限。不要把个人论文写进 Git repo。

```text
PaperFlow/
├── paperflow.sqlite3
├── papers/
│   └── <uuid>/
│       ├── original.pdf             # 若用户导入或主动下载
│       ├── derivatives/
│       │   └── marker/<fingerprint>/
│       │       ├── article.html     # 原始或规范化后的结构源文件
│       │       ├── reader.html      # 安全净化 + 统一阅读排版
│       │       ├── assets/...
│       │       └── manifest.json
│       └── metadata.json            # 可选冗余导出，不是唯一数据库源
├── staging/<job_uuid>/...
├── logs/paperflow.log
└── backups/
```

使用 `uuid` 作为磁盘目录名；所有返回的资源只根据数据库中的内部 ID 构造路径。文件入库采用临时文件、校验、`fsync` 可选、原子 rename；数据库提交失败要清理孤儿文件。衍生物使用 `sha256(pdf) + marker_version + settings_hash` 做缓存指纹；不要因为文件名相同而误判重复。

> 备份：至少实现文档化的“停止应用 → SQLite backup API/一致性拷贝 + papers 目录备份 → 恢复”工作流。SQLite 开启 WAL 时不可简单仅复制主数据库而忽略 WAL。

## 4. 关系模型（Alembic 管理）

### papers

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID / TEXT PK | 内部唯一 ID |
| title | TEXT NOT NULL | 可先用文件名占位 |
| authors_json | TEXT | JSON 数组 |
| abstract | TEXT NULL | 摘要 |
| year | INTEGER NULL | 发表年 |
| arxiv_id | TEXT NULL | 规范化 ID，不含版本 |
| arxiv_version | INTEGER NULL | 版本；无版本则 null |
| doi | TEXT NULL | 可选 |
| source_url | TEXT NULL | 来源 URL |
| official_html_url | TEXT NULL | **确认存在**才赋值 |
| pdf_local_path | TEXT NULL | 内部受控相对路径 |
| pdf_sha256 | TEXT NULL | 已下载/导入文件哈希 |
| read_status | ENUM/TEXT | unread, reading, finished |
| created_at / updated_at / last_read_at | DATETIME | UTC 时间存储 |

约束：`arxiv_id + arxiv_version` 的重复规则明确：如果版本未指定，表示追踪 latest 的规范 ID；再次导入时需要融合逻辑而不是创建重复；具体 unique index 避免 SQLite NULL unique 陷阱，使用业务去重 + 必要 partial index。`pdf_sha256` 可建索引，并在导入服务中事务性检查。

### collections / paper_collections
- `collections(id, name, created_at)`；`paper_collections(paper_id, collection_id)` 复合主键。

### tags / paper_tags
- `tags(id, name)`；`paper_tags(paper_id, tag_id)` 复合主键，名称规范化避免重复大小写标签。

### conversion_jobs

| 字段 | 说明 |
|---|---|
| id, paper_id | 身份及所属论文 |
| status | queued/running/succeeded/failed/canceled |
| input_hash | 源文件 sha256 |
| settings_json / fingerprint | Marker mode、参数、版本 |
| progress_stage | waiting, preparing, converting, publishing 等，**不要伪造百分比** |
| result_relative_path | 成功产物路径 |
| error_code / error_message | 精简用户错误（无隐私、密钥） |
| created_at / started_at / finished_at | UTC 时间戳 |
| attempt | 当前重试次数 |

### reading_positions
- `(paper_id, mode)` 复合唯一，mode `pdf|local_html`。
- `pdf_page`, `pdf_scale`, `html_anchor`, `scroll_ratio`, `updated_at`；做字段校验。
- 外部官方 HTML 不自动上报，不记录虚构进度。

### settings
- KV 或单例表：theme、font_scale、reader_width、marker_mode、marker_executable、auto_convert_on_import、data_dir（实际数据目录最好启动参数决定）。敏感 API 密钥不得直接作为可公开读取的 settings 字段。

## 5. API 合约（/api/v1）

所有返回使用 JSON，错误结构统一：

```json
{"error": {"code": "CONVERSION_FAILED", "message": "转换失败，可查看日志并重试", "request_id": "..."}}
```

| Method | Route | 主要行为 |
|---|---|---|
| GET | `/health` | 启动状况、数据库可用、Marker capability（不启动模型） |
| GET | `/papers?q=&status=&collection=&sort=&page=&page_size=` | 筛选、分页、排序 |
| POST | `/papers/upload` | multipart PDF 上传；返回已存在/新建条目，带 dedupe 标记 |
| POST | `/papers/arxiv` | `{ "input": "https://arxiv.org/abs/..." }`；元数据可降级 |
| GET | `/papers/{id}` | 完整元信息、资源可用性 |
| PATCH | `/papers/{id}` | 标题、作者、年份、状态等白名单字段 |
| DELETE | `/papers/{id}` | 带确认动作；仅删除库内资源 |
| POST | `/papers/{id}/fetch-metadata` | 重试外部元数据获取 |
| POST | `/papers/{id}/download-pdf` | 按需缓存官方 PDF |
| GET | `/papers/{id}/pdf` | 受控 PDF 流，支持 Range Request |
| GET | `/papers/{id}/html-status` | 官方/本地 HTML 资源可用性 |
| POST | `/papers/{id}/conversions` | 创建任务，检测已有成功缓存 |
| GET | `/conversions/{job_id}` | 转换状态、阶段、失败原因 |
| POST | `/conversions/{job_id}/retry` | 重试失败或中断任务 |
| POST | `/conversions/{job_id}/cancel` | 可终止受控子进程（若实现） |
| GET/PUT | `/papers/{id}/reading-position?mode=` | 获取和更新阅读位置 |
| GET/POST/PATCH/DELETE | `/collections`, `/collections/{id}` | 集合管理 |
| GET/POST/PATCH/DELETE | `/tags`, `/tags/{id}` | 标签管理 |
| GET/PATCH | `/settings` | 非敏感配置，字段校验 |

说明：列表/创建路由可能根据实现拆分，应生成 OpenAPI 并保持前端 typed client 一致。使用 UUID 与对象存在性验证，严格限制 `page_size`、上传大小、请求速率和合法 sort 字段。PDF 用 MIME 与签名二次校验，响应正确 `Content-Disposition: inline` 和 `Accept-Ranges`。

HTML 阅读 URL 建议固定为 `GET /read/{paper_id}/html`（**HTML 文档，不是 API JSON**）。其关联的图片资源走内部的 `GET /paper-assets/{paper_id}/{asset_id}`，服务器验证 asset_id 在当前转换 manifest 中，拒绝 `../`。内部 HTML 阅读入口可以链接打开该 URL（同一标签页），返回按钮回到 Library/Reader。不要用不受信任的 raw HTML 直接 `dangerouslySetInnerHTML` 置入 SPA DOM。

## 6. HTML Reader：兼容 Read Frog 的正确架构

**关键设计决定：内部 HTML 为一个可独立访问的稳定 HTML Document，不依赖 React 对正文频繁 rerender。**

1. 使用 Marker 生成 HTML 和图片资源。
2. 解析 HTML：移除脚本、事件处理器、meta refresh、危险 iframe/object/embed/form、非受信任外域资源；处理图片相对路径；保留安全的结构性标签、表格和公式容器。HTML/CSS 均视为不可信输入。
3. 统一 reader shell：导航栏/目录/正文、合理 CSS、适配深色模式。目录和应用 UI 标记 `translate="no"`；正文必须在主文档 DOM 可被 Chrome 扩展扫描。**避免 iframe、Shadow DOM 或 canvas 作为阅读主体**，直到 Read Frog 在真实环境验证兼容。
4. 公式处理：当前 Marker HTML 可能有 `<math>` 标签，可能是 MathML 或包含 LaTeX 文本；需要实际转换样本检查后做适配，不得盲目用 innerHTML；首选原生 MathML / 安全 KaTeX 渲染方案，保护数学节点不被翻译修改。
5. 以独立 reader runtime JS（同源、最小权限）记录滚动位置（debounce 500~1000ms，切换/离开时发送）；不要因进度更新替换正文 DOM。
6. 加合理的 CSP（默认拒绝第三方 script、object/frame），但须验证插件 content script 在该页能正常运行，不能为了翻译完全放开 XSS 安全边界。
7. 图片从应用受控 route 提供，CSS 图片自适应，保留 `<figure>`, `<figcaption>`, `<table>`, `<pre>`, `<math>` 等语义结构。
8. Marker HTML 的公式、脚注、参考文献在 Read Frog 翻译后需人工验证不被错译/破坏。原 PDF 永远可切回。

**Read Frog 集成约束**：它是用户侧独立浏览器扩展。PaperFlow 不读取扩展存储/密钥，不声称有公共 Read Frog SDK，不在页面自动执行扩展内部函数。不需要把它的 GPLv3 代码复制进仓库。提供“如何通过扩展翻译此页”的引导，实际翻译按钮由用户操作 Read Frog。

## 7. Marker Adapter

参考官方命令（**实际开发务必以锁定版本的 `marker_single --help` 复核参数**）：

```bash
marker_single /absolute/path/to/original.pdf \
  --output_format html \
  --output_dir /absolute/path/to/staging \
  --mode fast
```

说明：Marker 当前官方说明 `fast` 在 CPU/MPS 更合适，`balanced` 倾向 GPU；Apple Silicon 如需额外 `llama.cpp` 后端，应在安装文档中明确检测、安装与故障提示。LLM-assisted `--use_llm` 不应默认开启，因为它需要额外服务与密钥，且可能增加成本和外发数据。对 Marker CLI 的输出文件名和文件夹层级**不得靠猜测**；读取实际产物路径并验证后映射到内部 manifest。

Worker 推荐状态机：

```text
    queued -> running -> succeeded
               |   \
               v    -> canceled (可选)
             failed -> retry -> queued
```

- 单工并发数 1（可配置，但初期固定 1）。持久化队列，API 返回 202 + job ID。
- 系统崩溃后扫描 `running` 且无有效 worker 的任务，标记 `interrupted` 或 `failed` 并允许手工 retry；若 schema 只允许 failed，使用 `error_code=INTERRUPTED`。
- `subprocess` 使用参数数组（非 `shell=True`），限制文件/进程权限，采集退出码、超时、标准输出/错误的有限尾部日志。
- 生产不强制超短 timeout，允许合理超时设置和取消；不得杜撰进度 %。
- 输出目录是 staging，完成 HTML、图片路径、必要结构检查后才原子发布。
- 相同 PDF/hash + 配置重复请求返回缓存，不重复耗费算力；用户显式 `force_rebuild` 才重新生成。
- 启动 Web 服务不需要预加载模型。用户若缺少 Marker/模型仅禁用转换，其他功能正常。

## 8. arXiv Adapter

- 解析 `arxiv.org/abs/<id>`、`arxiv.org/pdf/<id>`、`arxiv.org/html/<id>` 和纯 ID；只允许 HTTPS、可信主机，不把用户自由 URL 直接交给后端抓取。
- `arxiv_id` 支持现代 ID 与常见旧版分类 ID（可增加单元测试）；`vN` 分离成版本字段。
- 元数据优先用 arXiv API Atom feed，服务端解析 XML 时禁用 XXE，采用用户代理和有界超时。遵守 arXiv API 使用条款和合理请求间隔（官方建议通常 3s/请求）。
- 验证官方 HTML：**实际发起 HEAD/GET** 到 `https://arxiv.org/html/<id>`；核实最终 URL 的主机仍为受信任官方域名、HTTP 200 且 content-type 合理。HEAD 不可靠时使用受限 GET；重定向需逐跳校验目标 host，避免 SSRF。不要只根据 URL 构造就认定存在。
- metadata API 与 HTML 可用性检查相互独立：某项失败不阻塞另一个步骤。
- 远端 HTML 在浏览器新标签打开；不要代理、改写或者抓取并本地化整站（V1 非目标）。
- arXiv API/HTML 受到速率限制（429）时，友好降级并退避/缓存；避免每次进入 Library 都打外部请求。
- 对不是 arXiv 的任意网站，V1 可以只保存外部 URL（如果实现）但不提供后台爬取与 PDF 自动下载。

## 9. 本地翻译 fallback（仅当兼容性 Gate 失败时纳入 V1）

先解决 Read Frog DOM/CSS 兼容问题；确实无法满足后，启用一个最小原生翻译模块：

- DeepSeek API 使用**服务端** OpenAI-compatible HTTP client；API key 从本机环境变量或 macOS Keychain 读取，绝不从 `/api/settings` 回传明文，也不写 Git/localStorage；默认关闭主动付费请求。
- 对净化 HTML 使用 DOM/树解析，分割段落结构，生成稳定 segment IDs；数学公式、代码、引用 anchor、URL、文献编号及图片标签用占位符保护，不让模型翻译结构。
- 批量但有界大小地发送上下文与 segment IDs，JSON schema/严格格式响应；按 ID 校验数量与原结构，不符合即重试/回退；翻译内容当纯文本插入，不解释为 HTML。
- 支持请求次数/Token 用量提示（若 API 回传）、错误退避、用户中断；按 `sha256(source + source_lang + target_lang + model + prompt_version)` 缓存，防止重复费用。
- 只在翻译被用户明确触发后调用 DeepSeek；关闭不导致 PDF/HTML 无法使用。
- 同一段原文/译文配对显示；不许通过“让模型输出整篇 HTML”实现。

V1 默认不实现 fallback；**只有当 Read Frog 真正测试失败且无法修复时将该分支纳入阻断项**。记录选择及证据。

## 10. 本机安全与隐私

- Server 默认绑定 `127.0.0.1`，绝不默认 `0.0.0.0`；强制仅允许正确 Host / Origin，保护有副作用端点免于恶意网页跨站请求（CSRF / DNS rebinding）；可加入本地会话令牌/CSRF token，API key/访问控制自行管理，不能误认为 loopback 自然安全。
- CORS 默认关闭；若 dev proxy 使用单源；必要时精确白名单允许指定 port。
- 上传文件不信任扩展名、MIME、外部文件路径；限制大小、扩展及数量；服务端自行控制存储名。
- 下载仅限白名单 arXiv 域名，限制重定向、超时、体积、内容类型；绝不支持任意 URL fetch。
- 生成 HTML 严格净化 script、事件属性、`javascript:`/`data:`危险 URL、iframe、svg active content、嵌入对象、危险 CSS、外域脚本；本地 assets 只走按 ID 约束的路由。
- URL 查询/前端 SQL 全部参数化，上传 PDF 不用 `shell=True`；文件访问防 `..` 穿越/symlink 逃逸。
- 日志不得包含用户文件完整路径（可按调试等级适当显示）、API Key、PDF 正文/译文等敏感内容；诊断日志轮转。
- `/health` 不泄露本地文件路径或 Secret。
- Marker's模型权重与工具可能有不同许可证；如公开发布，审查依赖与第三方许可证；不要捆绑他人论文/付费模型权重或 Read Frog 扩展。

## 11. 推荐仓库结构

```text
paperflow/
├── AGENTS.md
├── PRD.md
├── ARCHITECTURE.md
├── DESIGN.md
├── TASKS.md
├── TEST_PLAN.md
├── CODEX_START_PROMPT.md
├── README.md
├── DECISIONS.md                   # Codex 初始化时新建
├── frontend/
│   ├── src/{app,components,features,pages,styles,api}/
│   └── package.json
├── backend/
│   ├── app/{api,core,db,models,schemas,services,workers,reader}/
│   ├── alembic/
│   └── pyproject.toml
├── scripts/
├── tests/                         # API/integration/E2E fixtures
├── .env.example
└── .gitignore
```

所有版本需进入 lockfile/可复现依赖记录。初始化时自动生成 README 使用说明和一致的启动脚本（真实测试后再写“可运行”）。

## 12. 服务启动、备份、资源约束

- `make dev` 可以同时启动 front/back；`make serve` 提供同源成品站点（实际端口以配置为准）。
- 退出 Web 服务时：停止接收新 job，合理中断/结束转换 worker，数据库状态可恢复；操作系统异常杀死进程也不会破坏现有成功产物。
- 内存限制：不要重复启动 Marker 进程/加载模型；队列长度可以无限吗？需要限制提交频率，处理小规模个体使用即可。
- 重要说明：README 明确告知 Marker 初次模型下载可能较大、Apple Silicon 内存限制、离线不可首次推理。转换失败须能提示“查看诊断/切换 fast/检查可用内存”。
