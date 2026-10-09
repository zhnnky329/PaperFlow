# TEST_PLAN — PaperFlow V1 验收与回归测试

实际执行结果（含 NOT RUN 与发布阻断）持续记录在 [验收状态](docs/validation/acceptance.md)；本文件是验收标准，不代表所有条目已通过。

## 1. 验收原则

- `AUTOMATED PASS`：已运行测试命令并看到通过结果。
- `MANUAL PASS`：已在真实 macOS + Chrome + Read Frog + Marker 场景手动验证并记录环境。
- `NOT RUN`：未操作过，不能写 PASS。
- `FAIL`：失败，注明 issue、复现路径、影响范围。
- 发布条件：全部 P0 用例 PASS 或记录经用户明确接受的替代实现；不能将未完成能力无声降级到 P1。

## 2. Fixture 准备

建议 10 篇论文，测试时不必把受版权限制的 PDF 提交仓库：

| 类别 | 篇数 | 重点 |
|---|---:|---|
| 机器人/规划双栏 born-digital PDF | 4 | 栏序、标题、公式、参考文献 |
| 数学公式密集论文 | 2 | 行内/块公式和翻译干扰 |
| 表格/图像密集论文 | 2 | 表格排版、figure/caption、图片资源 |
| arXiv 官方 HTML 可用论文 | 2 | URL 检测、外链翻译、无本地 HTML |

另需：重复 PDF、伪造 PDF、损坏 PDF、带可疑 HTML 属性的模拟 Marker 产物、PDF 文件不存在、模拟 429/500、进程中断。项目仓库只存小型可公开测试 fixtures 或生成脚本。

## 3. 功能测试矩阵

| ID | 优先级 | 测试场景 | 预期结果 |
|---|---|---|---|
| T01 | P0 | 拖入有效 PDF | 创建论文，文件复制到受控目录，可打开 |
| T02 | P0 | 再次导入同 PDF（改名） | SHA-256 去重，不重复复制 |
| T03 | P0 | 非 PDF/损坏/过大上传 | 明确错误；数据库不残留坏条目 |
| T04 | P0 | 导入有效 arXiv `abs` 链接 | 正确解析 ID、标题作者和版本（或失败降级） |
| T05 | P0 | 导入 arXiv `pdf`、`html` URL 与纯 ID | 归一和去重正确 |
| T06 | P0 | API 429/超时/断网 | 条目保留，异步失败可重试 |
| T07 | P0 | arXiv HTML 实际缺失 | 不构造虚假的“可读 HTML”链接 |
| T08 | P0 | arXiv 官方 HTML 存在 | 在新标签打开正确官方 URL |
| T09 | P0 | 标签、集合、状态、排序、搜索 | 与数据库一致，刷新/重启不丢 |
| T10 | P0 | 长 PDF 翻页、缩放 | 稳定渲染且可读 |
| T11 | P0 | PDF 阅读进度保存/恢复 | 回到记录页码附近 |
| T12 | P0 | Marker 真实转换 | 得到可解析 HTML 和图片/公式资产 |
| T13 | P0 | 转换期间访问其他论文 | UI 不阻塞；PDF 可继续阅读 |
| T14 | P0 | 重复转换相同配置 | 缓存命中，无重复推理 |
| T15 | P0 | 转换任务退出/失败/重试 | 正确状态和错误信息，无坏产物覆盖 |
| T16 | P0 | 任务 running 时重启服务 | 不出现永久 running，可重试/恢复 |
| T17 | P0 | HTML 图片、表格、公式阅读 | 结构可用，局部失败可回 PDF |
| T18 | P0 | HTML 目录与阅读进度 | 章节导航和刷新恢复正确 |
| T19 | P0 | Chrome Read Frog 翻译本地 HTML | 段落双语可用，数学节点不严重损坏 |
| T20 | P0 | Read Frog 翻译后切回 PDF | 正文和 PDF 页面均可正常打开 |
| T21 | P0 | 修改标题、分类、状态后重启 | 无数据损失 |
| T22 | P0 | 删除单篇论文 | 仅当前论文内部资产受影响，有确认提示 |
| T23 | P0 | 没有 Marker 模型/CLI | 应用照常启动，仅转换标为不可用 |
| T24 | P0 | 阅读外部 HTML 后返回 | 状态准确，不虚构远端阅读进度 |
| T25 | P0 | 关闭再启动一键 run | PDF/HTML/分类/阅读位置保留 |

## 4. 安全测试矩阵

| ID | 优先级 | 试验 | 预期 |
|---|---|---|---|
| S01 | P0 | 上传不是 PDF 的 `.pdf` 文件 | 服务端拒绝或解析失败安全退出 |
| S02 | P0 | `../`、绝对路径、URL 编码路径越界请求 | 404/403，不读任意文件 |
| S03 | P0 | HTML 注入 `<script>`, `onerror`, `javascript:` | 执行被阻止/危险内容净化 |
| S04 | P0 | 输入非 arXiv URL / loopback / file scheme | 网络抓取拒绝，不可 SSRF |
| S05 | P0 | 恶意站点跨站 POST / DNS rebinding | 受 Host/Origin/CSRF 检查阻断 |
| S06 | P0 | API Key 配置与日志检查 | 前端 bundle/响应/日志/Git 无密钥 |
| S07 | P0 | Marker subprocess 参数中带特殊字符的文件名 | 不触发 shell 注入 |
| S08 | P0 | symlink 或 manifest 操作尝试读库外文件 | 服务端解析真实路径后拒绝 |
| S09 | P1 | 超大图片或 HTML/批量上传压力 | 拒绝或优雅降级，服务不崩溃 |

## 5. 自动化测试命令（由 Codex 实际建立）

预期至少提供：

```bash
# 以下是预期入口；在项目创建前并不存在
make lint
make typecheck
make test
make e2e
make dev
make serve
```

- Backend：pytest service、API、临时 SQLite、fake Marker subprocess、arXiv HTTP mocked（不依赖真实网络稳定性）。
- Frontend：Vitest 组件/行为、路由、API 错误/空态测试。
- E2E：Playwright 添加/搜索/修改/打开 PDF/删除/重启状态；真实 Marker 可以作为人工/慢速集成测试。
- 实际插件翻译/需要用户真实 DeepSeek Key 的测试**不适合在公开 CI 自动进行**，在人工验收文件记录。

## 6. 人工真实链路验收（用户执行）

1. 在自己的 Mac 上按 README 安装/启动 PaperFlow。
2. 打开 `http://127.0.0.1:<port>`，确认空 Library。
3. 导入一篇带公式的本地 PDF；打开 PDF；滚动到第 6 页并关闭。
4. 点击 `Convert to HTML`；保持 PDF 阅读直到成功；检查图片、公式和表格。
5. 打开内部 HTML；使用 Chrome Read Frog + 已配置 DeepSeek，翻译 Abstract 和 Method 段落。
6. 确认译文没有破坏原始公式和图片，滚到中部；刷新确认 HTML 位置恢复。
7. 导入一篇有 arXiv 官方 HTML 的论文并打开；确认外部页面可用 Read Frog。
8. 给两篇论文分类/标记状态；关闭进程并重新启动；确认 PDF 页码、HTML 位置、收藏和分类保留。
9. 再导入相同 PDF，确认没有重复。
10. 模拟一次失败（例如暂时把 marker executable 配置为不存在），确认仍可读 PDF 且错误可解释。

人工测试报告必须包含：macOS 版本、芯片/内存、Chrome 与 Read Frog 版本、Marker 版本、论文样本/类别、转换 mode、实际观测、PASS/FAIL/NOT RUN；禁止上传完整 API Key 或非公开论文正文。

## 7. 性能/稳定性观察（非拍脑袋 SLA）

记录冷启动耗时、第一次 Marker 模型获取、正常转换耗时、内存峰值（能观测则记录）、PDF 大文件滚动流畅度。V1 不承诺固定秒数，但不得让前端因转换进程被阻塞或卡死；处理 10 篇论文后不应无限增长无用 worker 进程。

## 8. 最终验收报告模板

```text
Version / commit:
Mac / OS / RAM:
Chrome / Read Frog / Marker version:
Automated tests (exact commands and outputs):
P0 Function tests: 25/25 PASS (or list FAIL/NOT RUN)
P0 Security tests: 8/8 PASS (or list FAIL/NOT RUN)
Human Marker + Read Frog Gate: PASS / FAIL / NOT RUN
Remaining blockers:
Known limitations (accepted):
Start command:
Backup/restore procedure:
```
