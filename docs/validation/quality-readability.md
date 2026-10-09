# 10 篇真实阅读质量抽查 · 2026-10-09

结论：**8/10 SAMPLED PASS，2 篇 LIMITED / 建议 PDF 对照**。覆盖规格的四类样本；这是代理实际查看 PDF 渲染及 Chrome 截图的抽查，不是逐页校对，也不是用户 Read Frog 的 MANUAL PASS。

8 篇真实 Marker fast 任务全部 succeeded、全部图片响应正常、缓存全部 PASS；另 2 篇真实 arXiv 元数据和官方 HTML 可用。Chrome 10/10 页面加载 PASS；8 个本地阅读页图片无损坏、KaTeX 无解析错误、页面 JS 无错误、页面宽度1280px无全页横向溢出、TOC/刷新进度恢复 PASS。公式可渲染不代表逐式识别准确。

| 样本（官方源） | 类别 / 页数 | 真任务秒数 | 图片 / 公式 / 表格 | 抽查结果 |
|---|---|---:|---|---|
| [FAST-LIO2](https://arxiv.org/abs/2107.06829) | 机器人双栏 / 19 | 89.85 | 16 / 22 / 10 | SAMPLED PASS：摘要/章节阅读流、状态模型公式、图片可见；行内符号有字体/上下标差异 |
| [LIO-SAM](https://arxiv.org/abs/2007.00258) | 机器人双栏 / 8 | 60.07 | 8 / 14 / 6 | SAMPLED PASS：双栏重排顺序与正文可读，状态公式可见；部分行内矩阵文本格式需PDF对照 |
| [ORB-SLAM3](https://arxiv.org/abs/2007.11898) | 机器人双栏 / 18 | 46.02 | 12 / 10 / 7 | SAMPLED PASS：实际PDF第2页为双栏（第1页是封面），正文/状态向量及多行残差可见；姓名重音有拆分 |
| [Informed RRT*](https://arxiv.org/abs/1404.2334) | 规划双栏 / 8 | 48.79 | 11 / 20 / 0 | SAMPLED PASS：摘要、问题定义/argmin、规划图片与目录可读 |
| [Attention](https://arxiv.org/abs/1706.03762) | 数学 / 15 | 31.45 | 5 / 9 / 8 | LIMITED：正文/图可用、分式可见，但 Attention 公式被Marker拆为表格内数行，保守不计质量PASS |
| [Neural ODE](https://arxiv.org/abs/1806.07366) | 数学 / 18 | 131.03 | 10 / 61 / 10 | SAMPLED PASS：正文/ODE导数/积分与示意图可见；有些等式被包进表格，不保证逐式保真 |
| [ResNet](https://arxiv.org/abs/1512.03385) | 图表 / 12 | 55.23 | 7 / 26 / 15 | LIMITED：正文/公式/图可用；复杂架构表较宽且重排有瑕疵，保守不计质量PASS |
| [YOLO](https://arxiv.org/abs/1506.02640) | 图表 / 10 | 39.04 | 8 / 3 / 4 | SAMPLED PASS：摘要、检测图/图注、置信度公式与目录可读；原双栏浮动图被线性插入 |
| [HTML papers on arXiv](https://arxiv.org/abs/2402.08954) | 官方HTML | — | 官方资源 | SAMPLED PASS：真实官方页面/目录/正文截图，57段落；未追踪远端进度 |
| [Mamba](https://arxiv.org/abs/2312.00752) | 官方HTML | — | 官方资源 | SAMPLED PASS：真实官方页面/摘要/目录截图，282段落；未追踪远端进度 |

Marker 2.0.0 / Surya0.22.1 / llama.cpp b11523；macOS arm64 16GiB，Chrome154。秒数为从API排队到成功的观测，模型已缓存，不包括每篇下载；不是性能SLA。原PDF与运行Library在 `/tmp/paperflow-quality-gate`，没有纳入Git。每份PDF的SHA256、页数、真实任务结果见 [quality-gate.json](quality-gate.json)，浏览器结果见 [quality-browser.json](quality-browser.json)。

实际发现并修复：宽表格的全局 overflow-wrap:anywhere 会把短标签逐字拆行；表格cell改为正常单词换行与最小宽度，保留局部横向滚动。Attention公式的Marker结构拆分没有用LLM重写掩盖。检查脚本最初重复计数KaTeX生成的MathML，已修正且重新执行；最终数字只计算原始公式节点。

截图保存在 `quality/<arxiv-id>-top/middle/math/figure/table/last-section.png`（无对应元素时不生成）；官方页为 `-official.png`。实际看过8份PDF/HTML对照contact sheet、8份公式截图、ResNet表格、YOLO图和2官方页。其余截图用于复核；不存在“全页全文都人工审核”的声称。

## 复现

```sh
# 使用 README 配置的真实 Marker/llama/model 环境；不调用翻译
.venv/bin/python scripts/quality_gate.py --data-dir /tmp/paperflow-quality-gate --report /tmp/quality-gate.json
# Gate结束释放server.lock后，另一个终端启动隔离库：
PAPERFLOW_DATA_DIR=/tmp/paperflow-quality-gate PAPERFLOW_PORT=8010 .venv/bin/python scripts/run.py serve
.tools/bin/node scripts/quality_browser.mjs /tmp/quality-gate.json http://127.0.0.1:8010 /tmp/quality-browser.json
# 标准Node安装可将 .tools/bin/node 替换为 node
.marker-venv/bin/python scripts/quality_contact.py --samples-dir /tmp/paperflow-quality-gate/samples
```

contact sheet 通过已锁定的PDFium生成，默认留在 `/tmp`；不捆绑论文。首次真正从空模型缓存运行更慢。测试脚本的visual_quality字段刻意为NOT RUN（脚本不判断人类可读性）；本文件记录实际截图审查，不能用自动DOM数量代替。

剩余 P0：用户常用 Chrome + Read Frog + DeepSeek 的注入、段落双语、公式/图片翻译后稳定及完整双语关服重启仍 **NOT RUN**，见 [人工步骤](marker-readfrog.md)。

## 真实备份恢复复现（已执行 PASS）

先停止8010临时服务；目标目录必须不存在，备份文件也必须是新名字：

```sh
.venv/bin/python scripts/backup.py backup --data-dir /tmp/paperflow-quality-gate --archive /tmp/paperflow-quality-backup-20261009.zip
.venv/bin/python scripts/backup.py restore --archive /tmp/paperflow-quality-backup-20261009.zip --target /tmp/paperflow-quality-restored-20261009
.venv/bin/python scripts/recovery_gate.py --source-data-dir /tmp/paperflow-quality-gate --restored-data-dir /tmp/paperflow-quality-restored-20261009 --sample-report docs/validation/quality-gate.json --archive /tmp/paperflow-quality-backup-20261009.zip --report /tmp/recovery-real.json
```

本次10条目、8 PDF Range206、8 HTML、77图片200、8位置一致、缓存PASS；60,162,236 bytes归档，详见recovery-real.json。再次执行需改用新归档/新恢复目录，不要覆盖已有Library。
