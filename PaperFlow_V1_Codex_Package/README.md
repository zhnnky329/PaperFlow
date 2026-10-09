# PaperFlow V1 · Codex 开发规格包

> 状态：开发输入文档，不代表已实现应用。  
> 更新：2026-10-09  
> 目标平台：macOS（Apple Silicon 优先）+ Chrome/Chromium；本地 Web 应用（localhost）。

## 项目定位

PaperFlow 是**个人使用、local-first 的论文管理与阅读器**，不是 Zotero 全功能替代品。它将论文收藏、PDF 阅读、arXiv 官方 HTML 跳转、Marker PDF→HTML 和 Read Frog 双语翻译整合成一条低摩擦工作流。

**V1 的定义是：真的能日常使用**。不能只生成可点击的静态 UI；必须接通文件、数据库、真实转换进程和阅读视图，并提供自动化测试与人工验收证据。

## 文件阅读顺序

1. [`CODEX_START_PROMPT.md`](./CODEX_START_PROMPT.md) —— 复制到新 Codex 会话的主 Prompt。
2. [`AGENTS.md`](./AGENTS.md) —— Codex 的长期开发行为、验收和安全规则（应该保留在项目根目录）。
3. [`PRD.md`](./PRD.md) —— V1 产品需求及功能优先级。
4. [`ARCHITECTURE.md`](./ARCHITECTURE.md) —— 数据、文件结构、接口、任务、阅读文档、安全边界。
5. [`DESIGN.md`](./DESIGN.md) —— UI、布局、颜色、交互和响应式规范。
6. [`TASKS.md`](./TASKS.md) —— 按依赖顺序开发的里程碑与退出条件。
7. [`TEST_PLAN.md`](./TEST_PLAN.md) —— 自动化、手工和真实性验证矩阵。
8. [`REFERENCES.md`](./REFERENCES.md) —— 第三方能力、限制和官方资料。

## 给 Codex 的使用方式

1. 新建空目录 `paperflow/`，将本包的所有 `.md` 文件复制到项目根目录。
2. 在该目录启动 Codex CLI（或 Codex IDE）。
3. 将 `CODEX_START_PROMPT.md` 的正文粘贴给 Codex。
4. 按 `TASKS.md` 顺序实现；在每一里程碑之后要求 Codex给出**可复现的命令、测试输出和剩余风险**。
5. 真实的 Read Frog + DeepSeek 翻译需在你自己的 Chrome 中验证；不要把真实 API Key 发给 Codex 或提交 Git。

## 不可妥协的开发原则

- **先验证核心链路，再大面积开发 UI**：Marker HTML + Read Frog 的实际体验是首个 gate。
- **PDF 是原始资产**；HTML 是阅读衍生物。对于仅有 arXiv URL 的收藏，原始远端资源和本地缓存状态必须区分。
- **单用户本地优先**：默认绑定 `127.0.0.1`，SQLite，不引入 Docker / Redis / PostgreSQL / 登录系统。
- **可恢复**：重启后论文、阅读状态、转换历史仍然存在；转换中断可重试。
- **翻译可用**：以 Read Frog 为默认方案；如果真实测试无法满足要求，启用最小化原生 DeepSeek 翻译 fallback，而不是把双语阅读移出 V1。
- **安全**：PDF/Marker HTML 视为外部输入；不运行转换产物中的任意脚本；避免本地文件路径穿越、任意 URL 请求与 API Key 泄露。

## 建议的启动体验（最终目标，不是已经存在的命令）

第一次安装按 README 自动检查 Python、Node、Marker；开发期间使用 `make dev` 或等价脚本；成熟后提供 `./scripts/start.sh`，单命令打开 `http://127.0.0.1:<port>`。启动应用**不应强制加载 Marker 大模型**。

## V1 交付清单

- 可运行的源码与锁定依赖版本
- macOS 本地启动/停止说明
- 数据库迁移/备份说明
- 示例配置 `.env.example`（绝不包含密钥）
- `pytest` + 前端单元测试 + E2E 烟雾测试
- Marker 转换和 Read Frog 人工兼容性检查记录
- 已知限制列表与 `LICENSE`（若决定公开发布）

**项目完成的判定标准是 `TEST_PLAN.md` 全部阻断项通过，而不是“页面看起来做好了”。**
