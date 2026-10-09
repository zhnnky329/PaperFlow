# PaperFlow

macOS 上运行的本地论文 Library、PDF.js 阅读器与 Marker HTML 阅读器。React/TypeScript/Vite + FastAPI/SQLAlchemy/Alembic/SQLite；默认只监听 `127.0.0.1:8000`。不需要账户、Docker 或云数据库。

**当前是可运行的开发版本，尚未完成 V1 发布验收。** 8 篇不同论文真实 Marker fast、API→HTML→缓存→重启链路通过。10 篇质量抽查有 8 篇可用（含2篇真实官方HTML），Attention/ResNet复杂排版保留PDF对照；见 [质量记录](docs/validation/quality-readability.md)。Chrome Read Frog + 用户 DeepSeek 双语人工 Gate 仍 NOT RUN。证据、真实截图和阻断见 [阶段记录](docs/validation/milestones.md)、[Marker/Read Frog](docs/validation/marker-readfrog.md) 和 [验收状态](docs/validation/acceptance.md)。

## 本机当前启动

本会话已建立 `.venv`、`.marker-venv`、前端 production build；在这个已有 checkout：

```sh
make serve
# Chrome 打开 http://127.0.0.1:8000
# Ctrl-C 停止
```

`make serve` 不依赖 Node，也不预加载模型。本机 ignored `.env` 已配置真实 Marker/llama-server 和持久模型缓存路径；全新安装需按下文配置。仅启动 API 而未 build 时首页会提示构建前端，Library 不会伪造数据。

## 全新安装（Apple Silicon）

Python 3.12 和 Node 24 LTS（含 npm）建议作为开发环境；应用支持 Python >=3.11。macOS 自带 `/usr/bin/python3` 可能过旧。可利用已有 conda：

```sh
conda create -n paperflow python=3.12 -y
conda activate paperflow
# 安装 Node 24 LTS 并确认 node/npm 在 PATH 后：
python --version
node --version
npm --version
make install PYTHON=python
make build
cp .env.example .env
make doctor
make serve
```

本机验证使用 conda markitdown 的 Python 3.12.13 创建 venv，Node 24.19.0 来自 Codex bundled runtime；依赖已锁定到 `backend/requirements.lock` 与 `frontend/package-lock.json`。上面的全新 conda 安装步骤没有在第二台机器执行，标记 NOT RUN；已有环境的依赖安装、build、serve 和测试已实际执行。

开发模式：`make dev` 启动 API 8000 与 Vite 5173，打开 `http://127.0.0.1:5173`。固定开发代理端口 8000；生产端口可用 `.env` 的 `PAPERFLOW_PORT` 配置。HTTP 写操作通过同源 Origin 与 `X-PaperFlow` 标记校验，不开放 CORS；从 curl 调用写 API 也要带这两项。

## Marker（独立环境，按需加载）

不把 PyTorch 装进轻量 API 环境。锁定当前已验证的官方源码提交及其依赖：

```sh
python -m venv .marker-venv
.marker-venv/bin/python -m pip install -r backend/marker-requirements.lock
# Marker 2.0.0 / Surya 0.22.1 的公式、OCR 在 Apple Silicon 需要：
brew install llama.cpp
.marker-venv/bin/marker_single --help
```

在 `.env` 设置（使用你 checkout 的实际绝对路径）：

```dotenv
PAPERFLOW_MARKER_EXECUTABLE="/absolute/path/PaperFlow/.marker-venv/bin/marker_single"
# 若 llama-server 不在 PATH，设置真实二进制绝对路径：
LLAMA_CPP_BINARY="/opt/homebrew/bin/llama-server"
# 可选，模型缓存持久保存在库外，不提交 Git：
# HF_HOME="/Users/you/Library/Caches/PaperFlow/models"
```

本会话安装了项目内官方 llama.cpp b11523 到 `.tools/llama/llama-b11523/llama-server`（已核对官方 SHA256），没有修改系统 Homebrew。可使用该绝对路径；`.tools` 被 Git 忽略。Marker 源码来自官方 commit `e7c67f1d239ea6a805cbf4ed6c6b2056d435e22d`，原用户 `marker/` checkout 保留不改。

首次真实 fast 转换下载约 1.8GB 模型缓存，网络、可用内存和首次模型初始化会影响耗时。模型懒加载；离线不能首次下载。默认 fast、单队列、并发 1，不启用 `--use_llm`，不发送论文到付费 LLM 转换 API。模型/CLI/llama-server 缺失时 PDF 和 Library 可照常使用，转换失败可重试。若内存不足，关闭其他重应用或取消当前任务；不保证任意论文的公式重建完美。

## 日常使用

- Add Paper：拖入多个 PDF 或文件选择；真实签名/解析/大小验证，复制入库，SHA-256 去重。arXiv `abs/pdf/html` URL 或新旧 ID 可直接收藏，latest 与显式版本分别去重。
- 元信息后台获取失败仍保留草稿，可重试；官方 HTML 只有真实 GET 验证后才展示。远端 HTML 新标签打开，**不追踪外部页面滚动**。arXiv 条目默认 Remote only，进入 PDF Reader 可 Download PDF 缓存。
- Library：标题、作者、年份、摘要和来源链接编辑，多标签/多集合，搜索/筛选/排序和阅读状态。`/` 聚焦搜索，`Esc` 关闭弹层；删除有明确二次确认，只删除当前论文在库内的资产。
- PDF.js：连续滚动、页码导航、缩放、适配宽度、可选择文本；保存当前页与比例，刷新/重启恢复。原 PDF 始终保留。
- Convert：后台任务 queued/running/succeeded/failed/canceled；取消/重试/缓存。已有 HTML 仅在新产物成功后替换引用。CLI 超时默认 1800s 可配置；异常退出重启时孤儿 running 标为 interrupted，可重试。
- Local HTML：独立 `/read/<id>/html` 普通 DOM；目录、净化图片、表格、原生 MathML / 本地 KaTeX，字号/宽度、系统暗色和阅读进度。HTML 转换问题可随时回 PDF。

## Read Frog + DeepSeek

在你常用的 Chrome 安装/启用 Read Frog，密钥只配置在扩展内。PaperFlow 不索取、不读取、不存储插件 Key，也不保存插件译文。

1. 启动 PaperFlow，在 Chrome 打开 `http://127.0.0.1:8000`。
2. 导入含公式/图片的 PDF，真实转换成功后打开 Local HTML。
3. 在 Read Frog 中选择你已配置的 DeepSeek，使用扩展 popup 的 Translate 或段落翻译入口。不要在 PaperFlow 中寻找虚构的扩展 SDK 按钮。
4. 如果扩展不出现，检查该站点权限并刷新页面；普通 localhost HTTP 不需要 `file://` 权限。参见 [官方指南](https://www.readfrog.app/en/docs/local-files)。
5. 按 [人工 Gate 清单](docs/validation/marker-readfrog.md) 验证 Abstract、Method、公式、图片、表格、双语布局并记录 Chrome/Read Frog 版本。

翻译会把选定文本发给你配置的服务，可能产生 Token 费用，须主动操作。本会话未调用 DeepSeek；翻译验收 NOT RUN。若实际失败且 DOM/CSP 调整仍无法修复，按 ARCHITECTURE §9 启用服务端密钥、段落缓存和公式保护的原生 fallback；当前该分支未激活，发布 Gate 保持阻断。

## 自定义文件夹与 Finder

点击侧栏文件夹旁的 `+` 创建并命名分类。进入文件夹后 Add Paper 默认导入到这里；已有论文点击“归类”选择文件夹，全部取消则回到“未分类”。文件夹支持重命名和二次确认删除，删除分类会保留论文原文。

文件夹会后台同步为 `~/Library/Application Support/PaperFlow/folders/<名称>/` 的真实目录（自定义 data dir 时位于该目录的 folders 下），可点击“在 Finder 中打开”。保存独立 PDF 副本，多文件夹各占一份磁盘空间；原始 PDF 继续用于阅读和转换。远程条目下载 PDF 后才生成副本。同步方向是应用到 Finder；Finder 新增/移动/改名不反向导入。修改过的副本与额外文件保留，冲突显示错误并可重试。截图、自动化和真实 macOS 验证见 [文件夹验证](docs/validation/folders.md)。

## 数据、备份与恢复

默认数据：`~/Library/Application Support/PaperFlow`，可在 `.env` 用 `PAPERFLOW_DATA_DIR` 指定。数据库使用 WAL 和 Alembic 迁移，启动不清库。PDF/HTML/图片都在受控 UUID 路径；不依赖导入原文件继续存在。不要把数据目录放进 Git。

```sh
# 先 Ctrl-C 停止应用，备份 API 拒绝运行中的数据库/资产拷贝
make backup
# 或显式指定：
.venv/bin/python scripts/backup.py backup --data-dir "/path/to/data" --archive "/path/to/paperflow.zip"
# 先恢复到一个不存在的新目录（不覆盖个人 Library）：
.venv/bin/python scripts/backup.py restore --archive "/path/to/paperflow.zip" --target "/path/to/restored-data"
# 然后将 PAPERFLOW_DATA_DIR 指向 restored-data，make serve 验证
```

备份通过 SQLite backup API 取得一致数据库快照，包含所有论文资产和 Finder 文件夹（含额外文件），附 SHA256 清单；恢复验证 ZIP 路径、哈希、SQLite integrity。不能只复制 `paperflow.sqlite3` 而遗漏 WAL；升级前备份，保留旧目录直到验证完成。

## 真实验证入口

```sh
make lint
make typecheck
make test
# 先停止已有 make serve/dev（E2E 独占 8000 端口）：
make e2e                 # 先 build，生成 35 页测试 PDF 到 /tmp，使用隔离 headless Chrome
# 机器需安装 Chrome；或在 playwright.config.ts 调整为已安装的 Chromium
# 可选慢速真 Marker Gate（不调用翻译）：
.venv/bin/python scripts/marker_gate.py --executable "/path/to/marker_single" --pdf "/path/to/paper.pdf" --output "/tmp/paperflow-gate"
.venv/bin/python scripts/validate_real.py --pdf "/path/to/paper.pdf" --data-dir "/tmp/paperflow-real-test" --executable "/path/to/marker_single" --report "/tmp/report.json"
# 较慢：8 个本地 Marker 任务 + 2 篇官方 HTML；仍需 PDF 对照阅读质量
.venv/bin/python scripts/quality_gate.py --data-dir "/tmp/paperflow-quality-gate" --report "/tmp/quality-report.json"
```

fake CLI 仅用于自动化队列故障测试，不作为 Marker 品质证据。Read Frog/DeepSeek 需用户 Chrome 人工验证，不能用 headless Chrome 测试冒充。没有私人 PDF、模型、密钥或 Library 提交到 Git。10 篇质量已实际抽查，不是逐页逐式校对；首次全新机器安装仍待执行。

## 界面验证

Library、导入弹窗、设置和阅读器支持系统字体、浅/深色、即时按压反馈及减少动态效果；窄屏保留 PDF/HTML 和阅读状态操作。真实 Chrome 截图与可复现命令见 [UI 验证记录](docs/validation/ui-polish.md)。`scripts/capture_ui.mjs` 应仅对隔离的真实论文验证库运行，会保存该库的阅读进度。

## Known limitations

- V1 发布阻断：Read Frog 人工双语与完整双语关服重启验收；未经执行不能宣称翻译完成。
- Marker 复杂公式/表格可能有结构缺陷；始终提供 PDF 对照，未承诺秒级转换或像素级还原。
- 真实 arXiv 网络的 API/HTML 可能受地区/429/超时影响；失败保留条目并可重试，自动化网络用 mock 可重复验证。真实网络证据见验收报告。
- PDF 受损/加密文件拒绝导入；当前不提供 PDF 全文搜索、批量分类或笔记（P1）。
- 项目尚未选定开源 LICENSE。Marker 代码 Apache-2.0，模型权重有单独条款；Read Frog 独立扩展不捆绑。发布前核对依赖/模型许可证，不捆绑论文/权重。
