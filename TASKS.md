# TASKS — Codex 分阶段实施计划

> 规则：完成 = 有代码 + 可复现验证 + 记录证据。禁止将“写好了按钮”视为功能完成。首要 Gate 优先级高于任何 UI 美化。


## 实施状态（2026-10-09）

阶段详细证据见 [docs/validation/milestones.md](docs/validation/milestones.md)。

| 阶段 | 当前状态 |
|---|---|
| M0 | CLI/双栏 FAST-LIO2/Attention 真 fast PASS；Read Frog 人工 NOT RUN，Gate 保留 |
| M1 | 骨架/迁移/health/启动与构建已实现，验证 PASS |
| M2 | Library/API/导入/去重/分类 PASS；自定义文件夹与 Finder 独立 PDF 副本、重命名/未分类/重启恢复 PASS；见 [文件夹验证](docs/validation/folders.md) |
| M3 | Chrome 真 PDF.js + 35 页、文本层、第 6 页及 110% 缩放恢复 PASS |
| M4 | 真 API→Marker→净化发布→缓存→重启 PASS；队列故障/取消/重试/孤儿恢复 PASS |
| M5 | 8篇真Marker/2篇官方HTML，10篇抽查8可用、2保留排版限制；Chrome图/公式/TOC/进度PASS，插件待人工 |
| M6 | 配置/备份恢复/启动文档/依赖锁定完成；按两项设计 skill 优化 UI，真实截图和回归见 [UI 验证](docs/validation/ui-polish.md)；全新机器安装 NOT RUN |
| M7 | lint/typecheck/Pytest 34/Vitest 3/Chrome E2E 3 PASS；发布 Gate 仍未关闭 |

## 全局完成定义（Definition of Done）

每个阶段 Codex 应：

1. 提交真实源码，不用只有 mock 的 API。
2. 运行该阶段所有可自动化测试，并贴出命令/结果（失败必须说明原因）。
3. 明确哪些需要用户在 macOS + Chrome + Read Frog 环境手工测试，**不能代替用户宣称插件已验证**。
4. 维护 `DECISIONS.md`、`README.md`、`.env.example`，更新不一致规范。
5. 无未说明的 P0 阻断问题才进入下一阶段。

## M0 — 环境探测 + 真实转换/翻译 Gate（最高优先级）

**任务**
- 检查 `python3`, `node`, `npm/pnpm`, `marker_single`, macOS 架构、安装路径和内存，不要求在仓库中硬编码本地路径。
- 初始化最小后端和静态 HTML test fixture（不是整个 UI）。
- 使用 1 篇用户有权使用的真实双栏 PDF（可先由用户提供，缺失则用可公开下载测试样本）实际运行 Marker `--output_format html --mode fast`；记录 exact command、CLI/version、耗时、是否完整输出、产物图片/公式布局。
- 通过本地 HTTP 路由 `http://127.0.0.1:...` 提供这份 HTML，配合 Chrome Read Frog 手工验证 ①可注入 ②翻译正常 ③图片未消失 ④公式不崩 ⑤多段双语布局可读。
- 产出 `/docs/validation/marker-readfrog.md` 和一份测试结果 checklist。

**退出条件**
- Marker 实际可用或明确记录环境阻断与可执行修复路径；不能只说 “理论支持”。
- Read Frog Chrome 插件测试若无人可操作，要标 `MANUAL TEST PENDING` 并把这个门槛继续保留为 V1 release blocker；其他研发可以继续，但不得将兼容性标 PASS。
- 如兼容性有问题，优先尝试净化 HTML 和稳定普通 DOM 渲染；无法修复时激活 `ARCHITECTURE.md §9` fallback 工作。

## M1 — 项目骨架、数据库和本地启动

**任务**
- 建立 FastAPI、React+Vite、Tailwind+shadcn、router 与 UI tokens。
- SQLite + Alembic migrations；Data dir、日志、配置与 `/api/v1/health`。
- 前端 API client typed contract、基础 loading/error 状态；统一 dev/serve 启动脚本。
- CI/本地 `lint`, `typecheck`, `pytest`, `vitest` 初始框架。

**退出条件**
- 一条命令能启动前后端，Library 空态真实连接 API；关掉再启动数据库内容保留。
- 没安装 Marker 时仍可启动应用，并显示缺失转换能力。

## M2 — 本地论文库、导入与去重

**任务**
- PDF 上传：校验、复制、sha256、SQLite 事务、重复检测。
- arXiv ID 解析/URL 归一、metadata、HTML availability、下载缓存按需；失败降级与退避。
- Paper CRUD、Tags、Collections、状态、查询/排序。
- Library 主视图真实数据、导入 modal、编辑 metadata、删除确认。

**退出条件**
- 连续导入多个 PDF，重复检测有效；arXiv 导入元数据可用且外部不可用时不丢数据。
- 数据路径受控；不能上传 HTML 伪装 PDF、无法传 `../../etc/passwd` 读本地文件。
- 重新启动后 PDF 与分类仍存在，搜索/排序实际生效。

## M3 — PDF Reader

**任务**
- 接入 pdfjs-dist + PDF 流式 HTTP 路由，支持页码/缩放/滚动。
- Reader header、论文标题、状态、返回 Library。
- PDF 阅读位置保存/恢复；仅 URL 论文下载 PDF 后可阅读。
- PDF 文件不存在、解析失败、网络下载失败展示明确状态。

**退出条件**
- 真实 30+ 页 PDF 正常滚动/翻页、缩放；刷新恢复到正确页附近；浏览器后退有效。
- 转换能力缺失时 PDF Reader 仍正常运行。

## M4 — Marker 任务队列、可靠缓存

**任务**
- 实现 `ConversionService` + subprocess + 单 worker + 持久化 job 状态。
- staging → 安全规范化 HTML/图片 → 验证 → atomically publish。
- API 状态轮询、失败可重试、相同 fingerprint 缓存命中。
- 无依赖、无 PDF、模型失败、进程退出码非 0、任务中断等异常处理。

**退出条件**
- 同一 PDF 重复转换不再触发 Marker；强制重新转换不覆盖旧版可用结果直至新版本成功。
- 意外停止 worker / Web 服务后重启，无永远显示 running 的任务。
- 未经安全净化的 Marker HTML 无法执行恶意 JS 或越权读文件。

## M5 — HTML Reader + Read Frog 兼容

**任务**
- 实现 `/read/{paper_id}/html` 稳定普通 DOM reader shell；TOC、数学公式、图片/表格、暗色、字号与宽度。
- 进度锚点与 scroll ratio 持久化，正文 DOM 不随状态更新重建。
- Read Frog 翻译区域验证：应用 UI 排除翻译，文章段落保留可翻译性。
- 官方 HTML 链接外部打开；不伪称追踪远端阅读进度。
- 更新 `marker-readfrog.md` 记录人工检查实际效果。必要时实施原生翻译 fallback。

**退出条件**
- 10 篇覆盖不同复杂度的论文中，至少 8 篇能以 HTML 正常阅读（公式/图片/阅读流可用；具体转换瑕疵有 PDF 对照），余下可安全退回 PDF；不要求 Marker 完美重排所有 PDF。
- 用户能使用 Read Frog + DeepSeek 在至少一篇 Marker HTML 实测双语翻译；若失败，有可正常工作的原生替代方案。

## M6 — UI 全面收口 + 配置 + 文档

**任务**
- Library 搜索/状态/标签/排序/空态/错误态完整交互；Reader PDF/HTML 入口一致。
- Settings 主题、字体、HTML 宽度、Marker 模式、auto-convert；调整暗色下公式和表格可读性。
- 写好安装、首次 Marker 模型下载、Read Frog 配置、运行/停止、备份/恢复、macOS 故障排查指南。
- 锁定依赖、清理 mock/demo 数据、完善 `.gitignore`（数据、模型、缓存、密钥不提交）。

**退出条件**
- Chrome 1280px 桌面布局无明显溢出、截断或误操作；暗色模式可用。
- 用户无需改代码就可以导入 PDF、收藏 arXiv 和日常阅读。

## M7 — 稳定性回归 + Release Candidate

**任务**
- 运行 `TEST_PLAN.md` 的自动化和手动测试，填写每项结果。
- 做一次从空数据目录到完整论文导入→转换→双语阅读→关应用→重启→恢复进度的真实演练。
- 检查 XSS、目录穿越、外部 URL 请求边界、Host/Origin/CSRF、防止密钥暴露；检查日志安全。
- 打包源码（不开源许可证交用户选定，勿擅自使用不兼容许可证）；发布前维护 Known Limitations。

**退出条件**
- 全部 P0 release blocker 关闭；非阻断问题单独建 issue/记录。
- 附可复制的运行与测试命令，以及真实测试环境、测试用 PDF 清单；**不要声称未执行过的测试已通过**。

## 开发节奏与停机策略

- Codex 优先完成当前里程碑，测试通过再动下一里程碑；如上下文/资源不足，保存状态并提供下一段继续 Prompt，而不是跳到前端样式收工。
- M0 发现 Apple Silicon Marker 运行太重时，可调整 `fast`/依赖环境或允许用户预先外部转换；但 V1 `one-click Convert` 仍是目标，不能永久移除。
- 真实 Chrome 插件无法在 agent 的执行环境中操作时，写出**精确可复现的用户手工步骤**并标记待验证，开发其他部分，但最终不得将其计为 PASS。

## 阶段验收报告模板

```text
Milestone: Mx
Implemented:
- ...
Changed files:
- ...
Commands run:
- <command> => PASS/FAIL (brief output)
Manual verification:
- PASS / FAIL / NOT RUN (reason)
Known issues / blockers:
- ...
Next task:
- ...
```
