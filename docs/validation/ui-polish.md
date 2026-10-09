# UI 优化验证 · 2026-10-09

按用户指定的 frontend-design / apple-design 执行。使用本机 Chrome 154.0.8037.98；截图来自已有的真实公开论文验证库（8010）及默认空库（8000），没有为生产界面添加模拟论文。验证脚本会保存验证库阅读位置，不应对个人 Library 运行。

变更：系统字体和字号层级、独立工作区、侧栏选中态、论文行、纸页空态、分段式导入和原生文件选择、设置开关、阅读器工具栏/目录。深色配色、按压反馈、可见键盘焦点、减少动态/透明度/增强对比度及窄屏操作均有对应代码。HTML 正文保持普通 DOM，未引入 iframe 或虚拟滚动。

变更文件：`frontend/src/styles.css`、`App.tsx`、`PdfReader.tsx`、`api.ts`、`components/Modal.tsx`；`backend/app/reader_static/reader.css`；`scripts/capture_ui.mjs`、`tests/e2e/library.spec.ts`；根目录 `README.md`、`DECISIONS.md`、`TASKS.md` 和本验证记录/截图。无新增依赖或 schema 变更。

## 命令与实际结果

| 命令 | 最终实际输出 |
|---|---|
| `make build` | Vite built in 1.42s；Reader KaTeX assets bundled |
| `make lint` | Ruff All checks passed；ESLint exit 0 |
| `make typecheck` | tsc -b exit 0 |
| `make test`（允许 macOS 进程枚举） | pytest 30 passed, 1 warning in 3.12s；Vitest 3 passed |
| `make e2e`（本机 Chrome） | 2 passed (6.3s) |
| `.tools/bin/node scripts/capture_ui.mjs http://127.0.0.1:8010 http://127.0.0.1:8000` | 12 个检查完成，pageErrors=[]；详情 [report.json](ui/report.json) |

实际检查：桌面 Library/HTML/PDF 和 390px Library/导入无整体横向溢出；小屏阅读操作可见；搜索无结果后清除筛选恢复真实论文；PDF/arXiv 切换与 Escape；真实 PDF.js canvas/文本层；真实 HTML 图片/公式；TOC 导航和进度刷新恢复；reduced-motion 下控件过渡为 0s。E2E 使用本机 Chrome 的 filechooser 实际选文件，再执行上传/编辑/分类/搜索/第 6 页和 110% 缩放恢复/删除，以及主题持久化。

首轮发现并修正：截图脚本选到官方 HTML 的未缓存 PDF 条目，改为使用已有 Local HTML 的真实 PDF；过渡中间帧截图用 animations=disabled 消除；E2E 首次 1 failed/1 passed，因为隐藏 input 仍暴露同名 button，改为 HTML hidden 后 2 passed。沙箱内进程清理测试 1 skipped；在具备进程枚举权限后运行，30 个全部通过。依赖仍有 Starlette/httpx 弃用警告，无新增测试失败。

## 可复现视觉检查

先按 README 安装并构建，在隔离验证库已有真实 PDF/Local HTML 的前提下，启动：

```sh
PAPERFLOW_DATA_DIR=/tmp/paperflow-quality-gate PAPERFLOW_PORT=8010 .venv/bin/python scripts/run.py serve
```

另一终端执行（标准 Node 安装可用 `node` 替换本机 wrapper）：

```sh
.tools/bin/node scripts/capture_ui.mjs http://127.0.0.1:8010
```

第二个 URL 为可选参数，只有该 URL 对应真实空 Library 时才使用，用来截图初始空态。`make e2e` 需要 8000 端口空闲，其数据和生成的测试 PDF 均隔离到临时目录。

## 真实 Chrome 截图

- [Library 浅色](ui/library-light.png) / [深色](ui/library-dark.png) / [390px](ui/library-mobile.png)
- [空库](ui/empty-light.png) / [搜索无结果](ui/search-empty.png)
- [PDF 导入](ui/import-light.png) / [arXiv 导入](ui/arxiv-light.png) / [深色导入](ui/import-dark.png)
- [Settings 深色](ui/settings-dark.png)
- [真实 PDF.js](ui/pdf-light.png)
- [真实 Marker HTML 浅色](ui/html-light.png) / [深色](ui/html-dark.png)

## 人工验证与限制

Read Frog + 用户 DeepSeek 的实际双语仍 NOT RUN，是既有 V1 P0 Gate；本轮 UI 未读取密钥或触发收费调用。macOS 系统辅助功能的减少透明度/增强对比度开关及 Safari 的视觉表现需用户手动检查；reduced-motion 已在 Chrome 自动化实际验证。完整无障碍审计及全新机器安装未执行。未新建数据库 schema，也未迁移或清空个人 Library。
