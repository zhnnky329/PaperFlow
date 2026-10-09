# 验收状态 · 2026-10-09

当前：可运行开发版本，**不是已验收的 V1 / Release Candidate**。

环境：macOS 27.0 (26A428)、arm64、RAM 16GiB、Chrome 154.0.8037.98、Python 3.12.13、Node 24.19.0；Marker 2.0.0 / Surya 0.22.1 / llama.cpp b11523。芯片具体型号、模型峰值内存：未测。真实样本只在库外保存，不提交 PDF/模型/Library。

## 命令证据

| 命令 | 实际结果 |
|---|---|
| `.venv/bin/python -m pytest tests -q`（允许进程枚举环境） | 文件夹扩展后 34 passed, 1 warning in 4.14s |
| `make lint` | ruff All checks passed；eslint exit 0 |
| `make typecheck` | tsc -b exit 0 |
| `make test` 前端部分 | Vitest 3 passed |
| `make e2e` | 文件夹扩展后 3 passed (8.0s)；Chrome 真 canvas/textLayer + 第 6 页视窗/110%缩放恢复、编辑/搜索/删除、暗色设置恢复 |
| `make build` | Vite build exit 0；Library 324.07kB，PDF Reader 按需 chunk 421.24kB，worker 独立本地资源 |
| `make dev` | Vite ready 220ms；proxy health 200、同源 mutation 200；Ctrl-C shutdown complete |
| `make serve` | API startup complete，127.0.0.1；应用不预加载模型 |
| `scripts/marker_gate.py` Attention fast | returncode=0，312.1s（含首次下载/初始化），5 images / 9 math / 8 tables |
| 同上 FAST-LIO2 双栏 fast | returncode=0，55.28s，16 images / 22 math / 10 tables；全部图片文件存在 |
| `scripts/validate_real.py` | 真 API→Marker→净化 HTML→全部图片响应→缓存→重启 PASS，33.42s，见 real-integration.json |
| `scripts/capture_real.mjs` | Chrome 真 HTML：5 images、9 math/KaTeX、0 KaTeX error、0 broken image、0 page JS error、TOC/progress PASS |
| `scripts/validate_arxiv_browser.mjs` | 真 UI 导入→Atom 元数据→官方 HTML验证→新标签→本地状态/最近阅读时间 PASS |
| `tests/test_supervisor.py` | 真父进程退出后 detached 推理子进程清理 PASS；sandbox 禁止枚举时该测试 SKIP，不能算 PASS |
| `scripts/quality_gate.py` | 8不同论文真Marker fast succeeded/cache PASS + 2篇真实官方HTML succeeded；PDF SHA256已记录 |
| `scripts/quality_browser.mjs` | 10 Chrome页面PASS；8本地页77图片/165公式/60表格，0坏图/KaTeX错误/JS错误，目录/进度/无全页溢出PASS |
| `scripts/quality_contact.py` + 实际截图审查 | 8/10 SAMPLED PASS（6本地+2官方），2篇LIMITED；细节见 quality-readability.md；不是逐页逐式校对 |
| backup.py backup/restore + recovery_gate.py | 真实10条目恢复到新目录；8 PDF206/8 HTML/77图片200、8位置相同、缓存PASS；recovery-real.json |

有一条 Starlette TestClient/httpx 弃用 warning，未导致失败。CLI 早期真实 FAIL、图片净化/页恢复/公式 DOM 的问题及修复保留在 milestones.md；最后成功不抹掉失败证据。

## P0 功能矩阵

| ID | 状态与实际覆盖 |
|---|---|
| T01 | AUTOMATED PASS：Chrome 文件选择、API真实 PDF解析/复制；拖拽 handler 实现，物理拖拽人工 NOT RUN |
| T02 | AUTOMATED PASS：改名相同内容 SHA 去重 |
| T03 | AUTOMATED PASS：伪造/损坏/有界上传、无坏条目 |
| T04 | REAL PASS：2402.08954 经 Chrome UI、官方 Atom API |
| T05 | AUTOMATED PASS：abs/pdf/html、纯 ID、旧 ID、版本归一与去重 |
| T06 | AUTOMATED PASS：网络失败/无效 XML/429 cooldown，草稿保留并可重试；异常重启 pending 恢复 |
| T07 | REAL + AUTOMATED PASS：9999.99999 HTML 实际 404；缺失内容不设官方 URL |
| T08 | REAL PASS：官方 HTML 真 GET 与 Chrome 新标签 |
| T09 | AUTOMATED PASS：标签集合/状态/搜索排序/DB 重启；部分筛选 UI 为代码+API测试 |
| T10 | AUTOMATED PASS（生成的 35 页 PDF）：真 PDF.js/文本层/翻页/缩放至110%；长期大论文流畅度人工 NOT RUN |
| T11 | AUTOMATED + REAL PASS：Chrome 第 6 页视窗及110%缩放刷新恢复，独立 app/进程读取持久数据 |
| T12 | REAL PASS：8不同论文实际 Marker fast 输出，非 fake CLI |
| T13 | REAL PASS：转换 running 时 PDF Range 206、health 200；Chrome 同时滚动转换期间人工 NOT RUN |
| T14 | REAL + AUTOMATED PASS：同 fingerprint 缓存、不再启动推理 |
| T15 | AUTOMATED PASS：真实 fake subprocess 非0、取消、重试；新失败保留旧 HTML/PDF |
| T16 | AUTOMATED PASS：孤儿 running → interrupted failed；真 detached 子进程父退出清理 |
| T17 | REAL PASS（抽查范围）：8本地/2官方HTML浏览器，8/10质量抽查可用；Attention/ResNet复杂结构LIMITED并保留PDF，不声称逐式保真 |
| T18 | REAL PASS：Chrome 目录与 HTML 位置刷新恢复 |
| T19 | **NOT RUN：用户 Chrome Read Frog + DeepSeek 段落双语** |
| T20 | **NOT RUN：Read Frog 翻译后切回 PDF**（普通 HTML→PDF 链接已实现） |
| T21 | AUTOMATED + REAL PASS：分类/标题/状态/进度跨 SQLite engine 与真实新进程保留 |
| T22 | AUTOMATED PASS：二次确认删除、拒绝活动任务、仅受控当前目录 |
| T23 | AUTOMATED PASS：缺 CLI 仍 health/Library/PDF 正常，转换独立失败 |
| T24 | REAL PASS：官方 HTML 新标签、阅读状态与最近阅读时间、明确不追踪外部滚动 |
| T25 | REAL PASS（核心链路）：停服新 factory/新进程恢复 PDF/HTML/分类/位置；**双语完整演练仍 NOT RUN** |

## 安全矩阵

| ID | 状态 |
|---|---|
| S01 | AUTOMATED PASS：PDF 签名/解析/体积 |
| S02 | AUTOMATED PASS：UUID/../、未知 SPA路径、受控资源与越界路径 |
| S03 | AUTOMATED PASS：script/style/onerror/javascript/iframe/svg 净化；真页面 CSP 与无 JS errors |
| S04 | AUTOMATED PASS：官方 URL白名单/HTTPS/端口/用户信息、逐跳重定向校验；REAL官方请求 |
| S05 | AUTOMATED PASS：Host/Origin/X-PaperFlow；开发代理实际同源 mutation PASS |
| S06 | AUTOMATED PASS（应用边界）：无前端Key输入/回传、settings拒绝Key字段、异常不re-raise且响应/日志无测试私密文本；子进程不继承KEY/TOKEN/远端Surya地址，关闭access log；用户Key从未获取，插件内部存储不在范围 |
| S07 | AUTOMATED PASS：subprocess 参数数组，UUID 文件名；实际带空格 checkout CLI PASS |
| S08 | AUTOMATED PASS：symlink库外 PDF访问403、图片逃逸拒绝、manifest查验、ZIP slip拒绝 |
| S09 | 有大小/像素/HTML/队列限制；并发大压力与内存峰值 NOT RUN（P1） |

## 发布阻断与下一步

1. 用户常用 Chrome profile 的 Read Frog/DeepSeek 双语 T19/T20 没有执行。隔离 headless Chrome 没有用户扩展；未触发付费 API。按 marker-readfrog.md 实测并记录版本/截图/公式。若失败，先修 DOM，仍失败则依 ARCHITECTURE §9 实现原生 fallback；未激活该分支不代表发布允许缺翻译。
2. 10篇抽查已补齐四类样本，8/10可用，详细限制见quality-readability.md；长期使用和逐页校对未执行，不能把质量抽查当成逐式保真。
3. 第二台/全新环境安装、长时间日常流畅度、完整含双语的关服重启演练仍待人工验证。2026-10-10 用户明确选用 MIT，已添加根目录 LICENSE；尚未执行开源发布，既有发布验收项保持待验证。

## 截图

均由实际 Chrome 生成：library-empty.png、library-real.png、library-arxiv-real.png、pdf-reader.png、settings-dark.png、html-real.png、html-dark-real.png、html-math-real.png。生成 fixture PDF 截图不算科研论文质量样本，真实论文图截图分别标明在 M0。

最终默认 `make serve` 真启动：health/Library/UI 均HTTP200，空个人库0条，Marker capability=true；验收推理结束后llama-server剩余进程0。数据默认Application Support，10篇验收数据未植入个人Library。重启命令仍为make serve。

最新文件夹/Finder 扩展验收见 [folders.md](folders.md)，保留原有 Marker 与 Read Frog Gate 状态。
