<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/paperflow-logo-dark.png">
    <img src="docs/images/paperflow-logo.png" alt="PaperFlow" width="560">
  </picture>
</p>

<p align="center"><strong>从发现到阅读，你的本地论文工作台。</strong></p>
<p align="center">AI 论文推荐 · 本地文献管理 · PDF / HTML 阅读</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-5964C0?style=flat-square" alt="MIT License"></a>
  <a href="#快速开始"><img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.11+"></a>
  <a href="#快速开始"><img src="https://img.shields.io/badge/macOS-Apple_Silicon-555555?style=flat-square&amp;logo=apple&amp;logoColor=white" alt="macOS Apple Silicon"></a>
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="#ai-discovery">AI 推荐</a> ·
  <a href="#日常使用">使用指南</a> ·
  <a href="#界面预览">界面预览</a> ·
  <a href="https://github.com/zhnnky329/PaperFlow/issues">反馈问题</a>
</p>

PaperFlow 是一个集成 AI 论文推荐的本地论文管理与阅读工具。通过浏览器使用，论文库和阅读记录保存在自己的电脑上，无需注册账号，主要面向 macOS Apple Silicon。

可选的 [Ubuntu / macOS 双机同步与远程转换](docs/PEER_SYNC.md)：两端各自保存论文库，Mac 运行 Discovery，可选择本机 Marker 或交给 Ubuntu CUDA 转换，并同步阅读进度与完整 HTML。默认关闭，保留现有本机入口。

## 核心功能

| 功能 | 可以做什么 |
| --- | --- |
| **🆕 AI 论文推荐** | 自定义研究方向、关键词和优先级，定期从 arXiv 发现论文，生成中文总结与推荐理由，感兴趣的一键加入文献库。 |
| **📥 PDF 与 arXiv 统一管理** | 拖入本地 PDF，或导入 arXiv 链接 / ID，自动补全论文信息，重复 PDF 按内容去重。 |
| **📂 文件夹与 Finder 同步** | 自定义多层分类，一篇论文可放入多个文件夹；分类对应 Finder 中的真实目录，支持双向整理。 |
| **📖 PDF 与 HTML 阅读** | 保留 PDF 原始排版，打开 arXiv 官方 HTML，或通过 Marker 将本地 PDF 转成 HTML，配合 Read Frog 等浏览器翻译插件阅读。 |
| **🔖 阅读进度保存** | 记住 PDF 页码、缩放和本地 HTML 阅读位置，下次打开接着读。 |
| **🔎 搜索与阅读状态** | 按标题、作者、arXiv ID 和标签搜索，标记未读 / 阅读中 / 已读，支持浅色与深色主题。 |
| **💻 本地存储与备份** | 论文、分类和阅读记录保存在本机，支持备份恢复；已有 PDF 和本地 HTML 可离线阅读。 |

## 界面预览

| Discover · AI 论文推荐 | Library · 论文库与文件夹 |
| --- | --- |
| [![Discover 真实运行截图：中文总结、推荐理由和相关性评分](docs/images/discover.jpg)](docs/images/discover.jpg) | [![论文库真实运行截图：文件夹、论文列表与阅读入口](docs/images/library-current.jpg)](docs/images/library-current.jpg) |

*真实运行截图，点击可查看大图。*

## 快速开始

需要 **Python 3.11+（推荐 3.12）**、**Node.js 24 LTS**、Git 和 make。Node.js 用于安装和构建前端，构建后日常运行不需要它。

<details>
<summary>使用 conda 准备 Python 环境（可选）</summary>

```sh
conda create -n paperflow python=3.12 -y
conda activate paperflow
```

下面的 `python3` 应指向 Python 3.11+ 环境。

</details>

```sh
git clone https://github.com/zhnnky329/PaperFlow.git
cd PaperFlow
make install PYTHON=python3
cp .env.example .env
make build
make serve
```

服务就绪后会自动打开浏览器，也可以访问 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**。以后只需在项目目录运行 `make serve`，保持终端开启，按 `Ctrl-C` 停止服务；关闭浏览器标签页不会停止应用。

基础导入、管理和 PDF 阅读无需安装 Marker 或配置 AI。

## 日常使用

<a id="ai-discovery"></a>

### 1. 让 AI 帮你找论文

1. 在 **Settings → Research Discovery** 填写研究方向、描述、关键词和优先级。
2. 配置自己的 **DeepSeek API Key**，设置每轮分析数量和预算，开启 **AI 分析**并保存。
3. 进入 **Discover**，点击 **检查新论文**。抓取完成后开始分析，可查看中文总结、推荐理由、匹配方向及分析依据。

推荐支持标记「感兴趣 / 稍后阅读 / 不感兴趣」，也可点击 **加入文献库**，继续归类和阅读。

默认在应用运行时每 **48 小时**检查 arXiv 的 **cs.CV、cs.RO、cs.AI**，首次查看最近七天。AI 默认关闭；开启后会把候选论文的摘要或正文发送给 DeepSeek，按 API 用量计费。结果会注明「全文 / 部分正文 / 仅摘要」，相关性评分仅供筛选参考。更多细节见 [Research Discovery](docs/RESEARCH_DISCOVERY.md)。

### 2. 导入与整理论文

点击 **Add Paper**，拖入 PDF 或粘贴 arXiv 链接 / ID。原始 PDF 会复制到论文库，元信息会在后台补全，也可以通过 **…** 手动编辑。

侧栏 **+** 创建文件夹，进入后可新建子文件夹。通过论文的 **整理** 按钮选择一个或多个分类，点击 **在 Finder 中打开**可查看对应目录。

<details>
<summary>Finder 同步与文件副本说明</summary>

- 分类目录默认位于 `~/Library/Application Support/PaperFlow/folders/`，里面保存 PDF 的独立副本；同一篇论文放入多个分类会生成多份副本。
- 在 Finder 中新建、重命名、移动分类，或放入、移动 PDF，应用运行时会同步到论文库；停机期间的改动会在下次启动后同步。
- 删除 Finder 中的 PDF 副本只取消对应分类，删除分类也不会删除 Library 中的论文和阅读记录。
- 请保留目录中的隐藏文件 `.paperflow.json`。修改 PDF 内容可能触发冲突，可另存为新文件名导入；原文不会被覆盖。

</details>

arXiv 导入初始只保存条目和链接。需要离线阅读时，打开 **PDF → Download PDF**；下载后才会在分类目录中生成 PDF 副本。

### 3. 选择阅读方式

| 入口 | 用途 | 进度保存 |
| --- | --- | --- |
| **PDF** | 查看原始排版、公式和图表 | 页码、缩放和滚动位置 |
| **Official HTML ↗** | 打开已确认可用的 arXiv 官方 HTML | 外部页面，不记录阅读位置 |
| **HTML / Local HTML** | 阅读 Marker 转换的正文，使用目录、调整字号和宽度 | 章节和滚动位置 |

本地 HTML 通过论文的 **Convert** 按钮生成，转换期间可以继续阅读 PDF。HTML 页面可配合 Read Frog 等浏览器翻译插件使用，插件需要自行安装和配置。

## 可选配置

<details>
<summary><strong>Marker：将本地 PDF 转成 HTML</strong></summary>

Marker 安装在独立环境中。先在项目目录执行：

```sh
python3 -m venv .marker-venv
.marker-venv/bin/python -m pip install -r backend/marker-requirements.lock
```

Apple Silicon 还需要 llama.cpp 的 `llama-server`。使用 Homebrew 安装：

```sh
brew install llama.cpp
command -v llama-server
```

也可使用 [llama.cpp 官方二进制](https://github.com/ggml-org/llama.cpp/releases)，选择 arm64 版本。在 `.env` 中填写实际路径：

```dotenv
PAPERFLOW_MARKER_EXECUTABLE="/absolute/path/PaperFlow/.marker-venv/bin/marker_single"
LLAMA_CPP_BINARY="/opt/homebrew/bin/llama-server"
```

重启后，在 **Settings → Conversion** 检查是否识别到 Marker；`make doctor` 可检查依赖和路径。默认使用 Fast 模式，自动转换默认关闭。首次转换会下载模型，之后复用缓存。任务支持取消、失败重试和重建 HTML，原始 PDF 始终保留。

</details>

<details>
<summary><strong>数据位置与网络设置</strong></summary>

默认数据目录是 `~/Library/Application Support/PaperFlow/`，实际位置可在 **Settings → Storage & recovery** 查看。以下配置写入 `.env`，修改后重启生效：

| 配置 | 默认值 / 用途 |
| --- | --- |
| `PAPERFLOW_DATA_DIR` | 数据目录，使用绝对路径 |
| `PAPERFLOW_PORT` | `8000`，服务仅监听本机地址 |
| `PAPERFLOW_MAX_UPLOAD_MB` | `100`，单个 PDF 上传上限 |
| `PAPERFLOW_MARKER_TIMEOUT` | `1800`，转换超时秒数 |
| `PAPERFLOW_METADATA_ONLINE` | `true`，允许向 arXiv / Crossref 查询元信息 |
| `PAPERFLOW_DISCOVERY_ONLINE` | `true`，允许发现任务联网 |

DeepSeek Key 可在设置中保存，也可通过 `PAPERFLOW_DEEPSEEK_API_KEY` 配置；环境变量优先。Key 仅保存在服务端，不在页面回显，普通备份不包含本机 Key 文件。

更换数据目录时，请先备份再恢复；修改路径本身不会迁移已有论文库。

</details>

## 备份与更新

先按 `Ctrl-C` 停止服务，再备份：

```sh
make backup
```

备份默认保存在数据目录的 `backups/` 下，包含论文库、论文文件、分类和阅读记录；不包含 `.env`、API Key 文件、Python 环境或模型缓存。

获取新版源码后，保留已有 `.env`，在项目目录执行：

```sh
make install PYTHON=python3
make build
make serve
```

<details>
<summary>从备份恢复</summary>

保持应用停止，将备份恢复到一个尚不存在的新目录：

```sh
.venv/bin/python scripts/backup.py restore \
  --archive "/path/to/paperflow-backup.zip" \
  --target "/path/to/restored-data"
```

将 `.env` 中的 `PAPERFLOW_DATA_DIR` 改为恢复目录，再运行 `make serve`。恢复后检查论文、分类和阅读位置，并重新配置本机保存的 DeepSeek Key。请使用完整备份，不要只复制数据库文件。

</details>

## 常见问题

- **端口被占用？** 先停止已有 PaperFlow 服务，再运行 `make serve`。修改过端口时，浏览器地址也要对应修改。
- **首页只显示 “PaperFlow API ready”？** 执行 `make build` 后刷新。
- **开启 AI 后还没有推荐？** 保存设置后到 Discover 点击「检查新论文」，查看抓取与分析进度；开启开关本身不会立即新建分析任务。
- **Marker 未识别或转换失败？** 运行 `make doctor`，核对 Marker 与 llama-server 路径、网络和可用内存。Marker 在独立环境中，后端环境提示 `marker-pdf: MISSING` 属于正常情况。

## 反馈与许可

欢迎通过 [Issues](https://github.com/zhnnky329/PaperFlow/issues) 反馈问题，请附系统版本、复现步骤和错误提示，避免上传私人论文、密钥或数据库。

项目使用 [MIT License](LICENSE)，第三方依赖与模型遵循各自许可。感谢 [Marker](https://github.com/datalab-to/marker)、[PDF.js](https://github.com/mozilla/pdf.js) 和 [KaTeX](https://github.com/KaTeX/KaTeX) 提供 PDF 转换、渲染与公式支持。
