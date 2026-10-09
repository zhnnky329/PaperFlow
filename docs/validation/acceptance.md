# 验收状态 · 2026-10-09

当前：可运行开发版本，**不是已验收的 V1 / Release Candidate**。

环境：macOS 27.0 (26A428)、arm64、RAM 16GiB、Chrome 154.0.8037.98、Python 3.12.13、Node 24.19.0；Marker 2.0.0 / Surya 0.22.1 / llama.cpp b11523。芯片具体型号、模型峰值内存：未测。真实样本只在库外保存，不提交 PDF/模型/Library。

## 命令证据

| 命令 | 实际结果 |
|---|---|
| `.venv/bin/python -m pytest tests -q`（允许进程枚举环境） | 27 passed, 1 warning in 3.09s |
| `make lint` | ruff All checks passed；eslint exit 0 |
| `make typecheck` | tsc -b exit 0 |
| `make test` 前端部分 | Vitest 3 passed |
| `make e2e` | 2 passed；Chrome 真 canvas/textLayer + 第 6 页视窗恢复、编辑/搜索/删除、暗色设置恢复 |
| `make build` | Vite build exit 0；Library 317.62kB，PDF Reader 按需 chunk 421.19kB，worker 独立本地资源 |
| `make dev` | Vite ready 220ms；proxy health 200、同源 mutation 200；Ctrl-C shutdown complete |
| `make serve` | API startup complete，127.0.0.1；应用不预加载模型 |
| `scripts/marker_gate.py` Attention fast | returncode=0，312.1s（含首次下载/初始化），5 images / 9 math / 8 tables |
| 同上 FAST-LIO2 双栏 fast | returncode=0，55.28s，16 images / 22 math / 10 tables；全部图片文件存在 |
| `scripts/validate_real.py` | 真 API→Marker→净化 HTML→全部图片响应→缓存→重启 PASS，33.42s，见 real-integration.json |
| `scripts/capture_real.mjs` | Chrome 真 HTML：5 images、9 math/KaTeX、0 KaTeX error、0 broken image、0 page JS error、TOC/progress PASS |
| `scripts/validate_arxiv_browser.mjs` | 真 UI 导入→Atom 元数据→官方 HTML验证→新标签→本地状态/最近阅读时间 PASS |
| `tests/test_supervisor.py` | 真父进程退出后 detached 推理子进程清理 PASS；sandbox 禁止枚举时该测试 SKIP，不能算 PASS |

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
| T10 | AUTOMATED PASS（生成的 35 页 PDF）：真 PDF.js/文本层/翻页；长期大论文流畅度人工 NOT RUN |
| T11 | AUTOMATED + REAL PASS：Chrome 第 6 页视窗刷新恢复、API存储 scale、独立 app/进程读取持久数据 |
| T12 | REAL PASS：两篇实际 Marker fast 输出，非 fake CLI |
| T13 | REAL PASS：转换 running 时 PDF Range 206、health 200；Chrome 同时滚动转换期间人工 NOT RUN |
| T14 | REAL + AUTOMATED PASS：同 fingerprint 缓存、不再启动推理 |
| T15 | AUTOMATED PASS：真实 fake subprocess 非0、取消、重试；新失败保留旧 HTML/PDF |
| T16 | AUTOMATED PASS：孤儿 running → interrupted failed；真 detached 子进程父退出清理 |
| T17 | REAL PASS（单篇浏览器样本）：图片/表格/分式可见，9 公式0渲染错误；10篇质量未覆盖 |
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
| S06 | AUTOMATED PASS（应用边界）：不存在前端 Key输入/回传、settings拒绝 Key字段、错误栈去路径/正文；真实用户Key从未获取，插件内部存储不在应用测试范围 |
| S07 | AUTOMATED PASS：subprocess 参数数组，UUID 文件名；实际带空格 checkout CLI PASS |
| S08 | AUTOMATED PASS：symlink库外 PDF访问403、图片逃逸拒绝、manifest查验、ZIP slip拒绝 |
| S09 | 有大小/像素/HTML/队列限制；并发大压力与内存峰值 NOT RUN（P1） |

## 发布阻断与下一步

1. 用户常用 Chrome profile 的 Read Frog/DeepSeek 双语 T19/T20 没有执行。隔离 headless Chrome 没有用户扩展；未触发付费 API。按 marker-readfrog.md 实测并记录版本/截图/公式。若失败，先修 DOM，仍失败则依 ARCHITECTURE §9 实现原生 fallback；未激活该分支不代表发布允许缺翻译。
2. M5 10 篇至少 8 篇质量门槛 NOT RUN，目前只转换两篇；一篇实查内部浏览器排版。补齐机器人/数学/图表/官方HTML类别并人工对照原 PDF。
3. 第二台/全新环境安装、长时间日常流畅度、完整含双语的关服重启演练仍待人工验证。不开源发布、没有擅自选 LICENSE。

## 截图

均由实际 Chrome 生成：library-empty.png、library-real.png、library-arxiv-real.png、pdf-reader.png、settings-dark.png、html-real.png、html-dark-real.png、html-math-real.png。生成 fixture PDF 截图不算科研论文质量样本，真实论文图截图分别标明在 M0。
