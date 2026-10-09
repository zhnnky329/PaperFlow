# PaperFlow V1 — Codex 启动 Prompt

> **使用方法**：把下面 `--- PROMPT START ---` 与 `--- PROMPT END ---` 之间的内容完整复制到一个**新的 Codex 会话**中。把本包所有 `.md` 文件先放进同一个空的项目目录。无需把本文件的解释文字复制给 Codex。

--- PROMPT START ---

你现在是我的个人工程开发代理。请在当前仓库从零构建 **PaperFlow V1**，一个基于 localhost 的本地论文管理与双语阅读 Web 应用，给我自己长期在 macOS 上使用。不要只交付 UI Demo 或产品规划；目标是可安装、可运行、可测试、可恢复的真实应用。

## 一、强制先阅读项目规格

请完整读取当前目录下：

- `README.md`
- `AGENTS.md`
- `PRD.md`
- `ARCHITECTURE.md`
- `DESIGN.md`
- `TASKS.md`
- `TEST_PLAN.md`
- `REFERENCES.md`

这些文档是任务边界和验收标准。创建 `DECISIONS.md` 记录你做出的关键技术选择。若必要，先检查当前工作目录与已有代码，避免覆盖已有内容。

## 二、必须实现的完整产品

1. **Library**：PDF 上传（拖拽/文件选择）、arXiv URL/ID 导入、元信息管理、Collections/Tags、搜索/排序、阅读状态、重复去重、重启持久化。
2. **PDF Reader**：PDF.js 真正加载本地 PDF，页码/缩放、阅读进度保存和恢复。
3. **HTML Reader**：优先打开确实存在的 arXiv 官方 HTML（外部标签页）；没有则对 PDF 一键调用 Marker 生成本地 HTML，支持公式/图片/表格/TOC/暗色/阅读进度。
4. **Translation**：以用户已安装的 Read Frog 扩展 + 用户自己配置的 DeepSeek API 为首选。内部 HTML 必须通过 localhost 的稳定普通 DOM 提供，兼容 Read Frog 段落双语翻译。Read Frog 操作不应靠虚构的 SDK/扩展接口。若实际测试不能正常翻译且调整 DOM 无效，按照 `ARCHITECTURE.md` 实现受控、缓存、公式保护的原生 DeepSeek 翻译 fallback；V1 不允许翻译功能缺位。
5. **Conversion**：Marker 子进程、后台单任务队列、任务状态、错误重试、持久化、内容缓存、原子发布；失败时 PDF Reader 仍可用。
6. **Modern UI**：遵循 DESIGN.md 的 Linear/Raycast 风格；功能完整、有合格空态/加载/错误态、支持 macOS 深色模式。
7. **Privacy & reliability**：SQLite、本地数据目录、API 与 HTML 净化、受限 URL/文件路径、loopback-only、真实自动化测试。

## 三、技术偏好

Frontend：React + TypeScript + Vite + Tailwind + shadcn/ui + PDF.js。
Backend：Python FastAPI + SQLAlchemy + Alembic + SQLite。
Worker：独立受控 subprocess 调用 Marker，Apple Silicon 默认优先尝试 fast 模式。
不引入 Next.js、Redis、Celery、PostgreSQL、Electron、Docker 等不必要基础设施。

## 四、请按阶段自主推进，而不是停在讲方案

严格按照 `TASKS.md` 的 M0 → M7 顺序，优先做 M0 的真实 Marker + Read Frog 兼容性 Gate。随后实现后端、数据库、导入、Library、PDF 阅读、Marker 任务、HTML 阅读和系统回归；**每个阶段都必须留下可执行代码和可复现验证**。如果你能在当前会话继续实现下一个阶段，就继续，不需要每一个阶段都只询问“是否继续”。

但请注意：若当前环境无法真的运行 Chrome 扩展，不能假装已经通过 Read Frog 测试。标明人工验证 `NOT RUN`，写下如何在我的 Chrome 上测试；继续完成其他可实现部分。遇到模型下载、网络或硬件阻碍时，保持应用核心路径可用并写清楚阻断项，不要跳过安全性和数据持久化。

## 五、严格禁止

- 不要只构建 landing page、虚构论文列表或假按钮，然后说已经完成 V1。
- 不要调用不存在的 Read Frog SDK 或凭空假设 arXiv HTML 必定存在。
- 不要让 LLM 直接重写整篇 HTML；默认复用浏览器插件翻译。
- 不要把 Marker 放到同步 HTTP handler 长时间运行。
- 不要用未净化的 Markdown/HTML 直接插入可执行脚本。
- 不要要求我在前端粘贴 DeepSeek API Key，除非确实启用原生 fallback；即使启用也必须安全管理后端密钥。
- 不要提交任何真实 PDF、个人 Library、Key、模型权重和运行缓存至 Git。
- 不要声称没有实际执行的测试、没有实际截图的页面、没有真实转换的 Marker 已通过验证。

## 六、交付规范

在项目根目录维护：`README.md`（实际启动指南）、`DECISIONS.md`、`TASKS.md`（阶段进度）、`.env.example`、测试和 lockfiles。提供至少一个可靠的本地启动入口，例如 `make dev` 与 `make serve`；安装说明覆盖 Apple Silicon、Marker 首次模型依赖、Chrome Read Frog 配置和本地数据备份。

每个阶段结束用中文给我：

- 哪些功能真实完成、修改了哪些文件；
- 运行了哪些命令，真实 PASS/FAIL 输出；
- 哪些仍需我在 macOS/Chrome 做人工测试；
- 目前有什么 P0 blocker；
- 下一步是什么。

**现在先读取上述文档，开始 M0 技术验证并创建真实项目骨架；不要把本回复停留在“我建议这么做”的规划阶段。**

--- PROMPT END ---

## 常用后续 Prompt（如 Codex 会话中断或按阶段检查）

**继续开发：**

> 读取 `TASKS.md`、`DECISIONS.md`、当前 Git 状态和最近的测试记录，定位上次未完成的最早 Mx。先复现已有测试，再继续实现该里程碑直至满足退出条件。不要重做已完成且通过验证的模块，不要声称未运行的测试已通过。

**阶段验收：**

> 暂停实现新功能。按 `TEST_PLAN.md` 审核当前阶段：列出每个 P0 用例的 PASS/FAIL/NOT RUN、对应的测试命令和证据。修复能自动验证的阻断项；将需要我在 Mac/Chrome 操作的测试写成逐步清单。

**UI 打磨：**

> 在不改动数据模型和业务 API 的前提下，对照 `DESIGN.md` 打磨 Library、PDF Reader、HTML Reader 的真实页面。优先修复空态、错误态、响应式溢出、暗色模式和操作反馈，保持 Read Frog 对 HTML 正文 DOM 的兼容性。不得用 mock 替换功能。

**准备 V1 交付：**

> 以 `TEST_PLAN.md` 为发布门槛执行 V1 release audit。检查启动、数据库迁移、数据目录、模型依赖、Read Frog 人工验证记录、文件/HTML 安全、API Key 泄露和备份说明。列出所有未关闭阻断项。只有满足验收条件才标记 V1 可交付。
