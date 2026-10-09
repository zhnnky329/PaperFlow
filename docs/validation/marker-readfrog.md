# M0 Marker + Read Frog 真实验证

更新：2026-10-09。Marker 真运行 PASS；用户 Chrome Read Frog/DeepSeek **MANUAL TEST PENDING / NOT RUN**，仍为 V1 P0 release blocker。

环境：macOS 27.0 (26A428)、arm64、16GiB RAM；Python 3.12.13（conda markitdown 创建隔离 venv），Chrome 154.0.8037.98。Marker 2.0.0、Surya 0.22.1；官方源码 commit `e7c67f1d239ea6a805cbf4ed6c6b2056d435e22d`。模型峰值内存未测。

## 真实 Marker

CLI `--help` 确认 mode fast/balanced、output_format html、output_dir。首次 fast FAIL：缺失 llama-server。安装官方 llama.cpp b11523 arm64 二进制并核验 SHA256 `5dc551427a61719a2aa9dc77c59dbeb525c357e0dbba3b7db3a6772f0737794f` 后重跑。

实际调用参数：`marker_single <PDF> --output_format html --output_dir <output> --mode fast`。可复现入口（LLAMA_CPP_BINARY/HF_HOME 按 README 设置环境，PDF 只留库外）：

```sh
.marker-venv/bin/marker_single --help
.venv/bin/python scripts/marker_gate.py --executable "$PWD/.marker-venv/bin/marker_single" --pdf /tmp/paperflow-m0-attention.pdf --output /tmp/paperflow-m0-output-retry
.venv/bin/python scripts/marker_gate.py --executable "$PWD/.marker-venv/bin/marker_single" --pdf /tmp/paperflow-m0-fastlio2.pdf --output /tmp/paperflow-m0-fastlio2-output
```

| 真实样本 | 结果 | runner 耗时 | 原始输出 |
|---|---|---:|---|
| [Attention Is All You Need](https://arxiv.org/abs/1706.03762) | returncode 0 | 312.1s（含首次初始化） | 63,451 bytes HTML、102段落、5图片、9公式、8表格，5/5 图片存在 |
| [FAST-LIO2](https://arxiv.org/abs/2107.06829) | returncode 0 | 55.28s | 178,294 bytes HTML、220段落、16图片、22公式、10表格，16/16 图片存在；19页 PDF 第一页实查双栏 |

Marker 日志 inference 分别为 294.8929s 与 38.7548s，不与 runner 时间混用。首次缓存约 1.8GB，持久缓存本机 `.env` 指向 Library/Caches/PaperFlow/models-marker2。

应用内 Attention 真 API→Marker→净化→图片响应→缓存→重启 PASS，33.42s，见 [real-integration.json](real-integration.json)。Chrome 内部 HTML：5图片、9公式、8表格、26目录项，0坏图片、0 KaTeX error、0页面 JS error；TOC/进度 PASS，见 [html-browser.json](html-browser.json)。

实际截图发现 KaTeX 放在 MathML math 容器会隐藏分式，已修复为普通 span/div；分式、根号、上标可见。Marker inline/block 和复杂表格仍有局部断行；数量、无解析错误不等于逐式数学重建准确。原 PDF 永久可对照。

## Chrome 人工 Gate（NOT RUN，仍为 V1 P0 blocker）
1. `make serve`，在自己常用且已安装扩展的 Chrome profile 打开 http://127.0.0.1:8000 。隔离 headless Chrome 没有用户扩展，不能当此 Gate。
2. 导入公开双栏论文或本人有权使用的 PDF，先打开 PDF 确认原文可读。
3. Convert HTML，等待真实任务 succeeded，打开 `/read/<paper-id>/html`。
4. Chrome `chrome://extensions` 记录 Read Frog 版本，允许此站点；Read Frog 中选择已配置的 DeepSeek provider（key 只留在扩展）。
5. 主动用扩展 popup 的 Translate 或段落翻译入口翻译 Abstract、Method 至少三段；检查译文位于原文附近，图片/表格/公式/引用仍可读。可能产生用户自己的 API 费用，本会话未触发。
6. 导航栏和公式禁翻，正文可翻；切回 PDF，刷新 HTML 和 PDF 确认位置恢复。
7. 若失败记录截图、扩展版本、控制台错误（删除 key/正文），先调整 DOM/CSP，仍失败才启用 ARCHITECTURE §9 后端密钥、段落缓存、公式保护原生 fallback。NOT RUN 不是“插件已失败”。

| 检查 | 结果 |
|---|---|
| CLI `--help` | PASS |
| 真实 Marker fast 转换 | PASS（包含双栏样本） |
| 真实输出图片、公式、表格 | PASS（上述实际范围，仍有局部布局瑕疵） |
| 普通 DOM、目录、暗色、进度 | Chrome PASS |
| Read Frog 注入 | NOT RUN |
| DeepSeek 段落双语 | NOT RUN |
| 翻译后数学/图片稳定 | NOT RUN |
| 10 篇至少 8 篇 HTML 可读 | SAMPLED PASS：8/10；2篇LIMITED，见 [实际质量抽查](quality-readability.md)，不是逐式校对 |

不把静态 fixture 或 fake worker 测试算作 Marker/翻译 PASS。
