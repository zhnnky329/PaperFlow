# 自定义文件夹与 Finder · 2026-10-10

已实现用户明确要求的文件夹分类和 Finder 同名真实目录。现有 Collections 数据保留，界面提供我的文件夹、数量、未分类、命名/重命名、导入目的地、已有论文的归类和移出。选择多个文件夹时，各目录都有独立 PDF 副本。

真实目录：`<PAPERFLOW_DATA_DIR>/folders/<文件夹名>/`。默认 `~/Library/Application Support/PaperFlow/folders/`。副本文件名包含论文标题及完整 UUID，避免重名；UTF-8 文件名长度有界。原始 PDF 仍由 UUID 目录管理，阅读/Marker 不依赖 Finder 副本。文件夹名称保留大小写，大小写不同的同名创建会去重。

同步是应用 → Finder，后台单线程、queued/running/succeeded/failed 持久化、原子副本发布、重启对账和失败重试。应用内重命名会重命名真实目录。Finder 新增/移动/改名不会反向导入；副本有独立磁盘占用，未下载的远程论文待缓存 PDF 后才产生副本。

目录管理清单 `.paperflow.json` 防止覆盖外部目录，仅删除已管理且 SHA256 未变化的副本。修改过的副本及额外文件保留。根目录/副本/目标目录符号链接拒绝写入，路径分隔符/控制字符拒绝作为新名称。同步失败时 Library 和原始 PDF 仍可用。停止应用后备份包含数据库、原始资产及 folders（包括额外文件），恢复后重新对账。

## 实际验证

| 命令 | 实际结果 |
|---|---|
| `make lint` | Ruff All checks passed；ESLint exit 0 |
| `make typecheck` | tsc -b exit 0 |
| `make build` | Vite build PASS（1.65s）；KaTeX 本地打包 |
| `make test` | pytest 34 passed, 1 warning in 4.14s；Vitest 3 passed |
| `make e2e` | 本机 Chrome 3 passed (8.0s) |
| `.tools/bin/node scripts/validate_folders.mjs http://127.0.0.1:8010 /tmp/paperflow-quality-gate/samples/2107.06829.pdf` | FAST-LIO2 真实 PDF 归类、副本字节一致、实际点击 Finder 打开入口返回 opened=true，pageErrors=[] |

原有集合 rename 测试曾预期名称被强制转小写，首轮 1 failed/10 passed；按新的保留用户命名行为更新断言后通过。没有用减少断言绕过文件夹安全性。后台测试覆盖多文件夹、计数、去重、重命名冲突、未分类、独立 inode、原始文件不受副本修改影响、重启补齐丢失副本、保留额外文件、symlink 根目录失败时 Library 仍可用、失败重试及备份恢复。

Chrome E2E：新建文件夹 → 导入指定文件夹 → 编辑/分类/阅读恢复；新建中文文件夹 → 磁盘 PDF 副本 → 刷新保持当前文件夹 → 重命名目录 → 取消归类 → 未分类出现论文 → 删除空文件夹仍保留论文。PDF.js 原有第 6 页及 110% 缩放、深色持久化继续通过。

真实公开论文在隔离 `/tmp/paperflow-quality-gate`，未填充默认个人 Library，未提交 PDF/库/模型/Key。截图：[真实文件夹](ui/folder-real.png)、[文件夹总览](ui/folders-real.png)；机器结果：[folders-report.json](ui/folders-report.json)。Finder 的 `/usr/bin/open` 实际调用成功，但 Finder 窗口内容人工视觉审查 NOT RUN。

## 使用与复现

1. 刷新 localhost，点击侧栏文件夹右侧 `+` 或“我的文件夹”中的新建按钮，填写名称并保存。
2. 进入文件夹点击 Add Paper，会默认导入到当前文件夹；多个 PDF 可一起选择或拖入。其他页面可在导入弹窗选择存入文件夹。
3. 已有论文点击“归类”，勾选目的地并保存；全部取消则进入未分类。
4. 等待后台同步完成，点击“在 Finder 中打开”；设置页也显示根目录。失败提示可重试同步。
5. 文件夹右侧管理入口支持改名和删除二次确认；删除分类保留论文原文及未管理/修改过的文件。

复现真实 Gate：按 README 启动隔离且含公开论文的验证库到 8010，再运行上述 `validate_folders.mjs`。此脚本会在该隔离库创建/归类 `SLAM 研究` 并打开对应 Finder 目录；不要对个人库执行。完整测试用 `make test`、`make e2e`（后者需要 8000 空闲，数据隔离）。

## 人工待办 / 既有阻断

Finder 窗口显示及用户自己的批量分类体验需人工检查；本轮没有实现 Finder 文件系统双向监控或嵌套子文件夹。Read Frog 双语人工 Gate 仍 NOT RUN，是既有 V1 发布阻断，本次未使用 DeepSeek Key 或进行收费调用。

变更文件：`backend/app/folders.py`、`main.py`、`scripts/backup.py`；`frontend/src/App.tsx`、`api.ts`、`styles.css`；`tests/test_folders.py`、`test_library.py`、`test_backup.py`、`tests/e2e/library.spec.ts`；`scripts/validate_folders.mjs` 和相关文档。无 schema/依赖变更。
