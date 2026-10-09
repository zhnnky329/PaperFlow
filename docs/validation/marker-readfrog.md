# M0 Marker + Read Frog 真实验证

状态：进行中；所有未经实际验证的条目为 NOT RUN。

环境：macOS 27.0 (26A428)，arm64；Python 3.12.13（conda markitdown 创建的独立 venv）。Marker 源码 pyproject version 2.0.0。

## Chrome 人工 Gate（NOT RUN，仍为 V1 P0 blocker）
1. `make serve`，Chrome 打开 http://127.0.0.1:8000 。
2. 导入公开双栏论文或本人有权使用的 PDF，先打开 PDF 确认原文可读。
3. Convert HTML，等待真实任务 succeeded，打开 `/read/<paper-id>/html`。
4. Chrome `chrome://extensions` 记录 Read Frog 版本，允许此站点；Read Frog 中选择已配置的 DeepSeek provider（key 只留在扩展）。
5. 用扩展 popup 的 Translate 或段落翻译入口翻译 Abstract、Method 至少三段；检查译文位于原文附近，图片/表格/公式/引用仍可读。
6. 导航栏和公式禁翻，正文可翻；切回 PDF，刷新 HTML 和 PDF 确认位置恢复。
7. 若失败记录截图、扩展版本、控制台错误（删除 key/正文），先调整 DOM/CSP，仍失败才启用 ARCHITECTURE §9 原生 fallback。

| 检查 | 结果 |
|---|---|
| CLI `--help` | NOT RUN |
| 真实 Marker fast 转换 | NOT RUN |
| 真实输出图片、公式、表格 | NOT RUN |
| Read Frog 注入 | NOT RUN |
| DeepSeek 段落双语 | NOT RUN |
| 翻译后数学/图片稳定 | NOT RUN |
| 10 篇至少 8 篇 HTML 可读 | NOT RUN |

不把静态 fixture 或 fake worker 测试算作 Marker/翻译 PASS。
