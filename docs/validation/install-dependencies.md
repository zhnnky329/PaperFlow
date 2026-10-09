# 安装与依赖回归 · 2026-10-10

环境：macOS Apple Silicon，Python 3.12.13、Node 24.19.0、Chrome 154.0.8037.98。同一台 Mac 上的独立源码目录，新的 `.venv` 和 `node_modules`；未导入个人 Library、`.env`、模型权重或运行缓存。

## 安装

真实执行以下步骤，均完成。Python 来自本机 conda；Node 24 已加入 PATH。

```sh
make install PYTHON=/opt/miniconda3/envs/markitdown/bin/python3.12
cp .env.example .env
make build
make lint
make typecheck
make test
```

首次安装发现旧 npm 锁文件有 5 个审计项，因此未直接交付该依赖版本。升级后，在同一独立目录重新执行 `make install-frontend`、lint、typecheck、test 和 E2E，均通过。独立目录仍在同一台机器上，其他机器安装 **NOT RUN**。

## 依赖修复

| 依赖 | 原锁定版本 | 新锁定版本 |
|---|---|---|
| pdfjs-dist | 5.7.284 | 6.4.299 |
| katex | 0.16.47 | 0.19.0 |
| vitest | 3.2.7 | 5.0.3 |

PDF.js 改为 `getDocument({ url, enableXfa: false })`，使用包内 worker 和类型定义。迁移中两次类型检查失败（旧字符串参数、已移除的 `isEvalSupported`），均已修复。

实际审计命令：

```sh
cd frontend
npm audit --json
```

最终输出：`vulnerabilities: {}`，`metadata.vulnerabilities.total: 0`，退出码 0。

## 自动化结果

| 命令 | 实际结果 |
|---|---|
| `make lint` | Ruff `All checks passed!`，ESLint 退出码 0 |
| `make typecheck` | TypeScript 退出码 0 |
| `make test` | pytest `34 passed, 1 warning`；Vitest `3 passed` |
| `make build` | Vite 构建成功，KaTeX 本地资产打包成功 |
| `make e2e` | Chrome `3 passed (8.5s)` |

完整测试在允许进程枚举的本机环境执行。沙箱内首次 pytest 为 `33 passed, 1 skipped`，跳过的是进程清理测试；取得该权限后 34 项全部执行。非失败警告为 Starlette TestClient 对 httpx 的弃用提示。

E2E 覆盖真实上传、编辑、搜索、PDF.js canvas/文本层、35 页 PDF、第 6 页与 110% 缩放恢复、删除、主题、文件夹分类和 Finder 副本。为保留用户运行中的 8000 服务，仅在临时目录将 Playwright 的 baseURL、health URL 和 `PAPERFLOW_PORT` 改为 8018；生产配置未改。测试库独立。

## 真实 HTML 回归

复制已有公开论文测试库到临时目录，在 8019 启动隔离服务，使用本次安装的 KaTeX 打开 8 篇此前真实 Marker 转换的 HTML。运行：

```sh
node scripts/quality_browser.mjs /tmp/paperflow-marker-samples.json \
  http://127.0.0.1:8019 /tmp/paperflow-dependency-html.json
```

输入为 `quality-gate.json` 中 `reader == "marker"` 的 8 个样本。脚本新增 `renderedMath` 计数，避免把未渲染的公式误判为通过。完整结果见 [dependency-html.json](dependency-html.json)：8/8 页面检查 PASS、77 张图片、165 个已渲染公式、60 个表格；坏图、KaTeX 错误和页面脚本错误均为 0，8/8 目录与进度恢复 PASS。实际执行时输入文件名为临时目录内的 `.quality-input.json`，以上用固定 `/tmp` 路径展示同一调用方式。

截图保存于临时目录，查看了 Attention 的公式截图，分式、根号和上标可见。该样本原有公式拆行限制仍在，详见 [quality-readability.md](quality-readability.md)。这次复用已转换产物，没有重新执行 Marker；页面检查通过不代表公式内容和排版逐项校对通过。

## 当前可用范围

个人服务只读检查：首页、health、settings 均 HTTP 200，health 为 `status: ok`、`database: ok`、`marker_available: true`。论文管理、PDF、文件夹和本地转换可用于日常试用。

用户 Chrome 的 Read Frog 扩展测试、其他机器安装、长期使用仍 **NOT RUN**。应用继续标为开发版本，既有 V1 发布 Gate 保留。

源码上传内容已检查，没有 PDF、个人数据库、`.env`、密钥、模型权重或运行缓存。MIT LICENSE 和使用文档已准备。用户自行通过 Git SSH 提交；代理没有推送、创建发布或修改仓库公开设置。

待提交源码共 174 个文件，禁用资产、密钥格式候选、符号链接和超过 10 MB 的单文件均为 0。检查了已安装包的许可声明：Marker 2.0.0、Surya 0.22.1、PDF.js 6.4.299 为 Apache-2.0；KaTeX 0.19.0、Vitest 5.0.3 为 MIT。模型权重不随源码发布，仍按上游各自许可使用。
