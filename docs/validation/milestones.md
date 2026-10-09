# 阶段执行记录（2026-10-09，持续更新）

所有 PASS 仅针对实际运行的验证范围，不代表整个 V1 已验收。

最新：30个后端/3个前端/2个Chrome E2E PASS；8真Marker+2官方HTML完成，10篇抽查8可用；真实Library备份恢复已验证。以下按时间保留历史失败及阶段快照，最新收尾记录在末尾。Read Frog/DeepSeek人工仍NOT RUN。

## M0
文件：scripts/doctor.py、scripts/marker_gate.py、docs/validation/marker-readfrog.md、DECISIONS.md、隔离环境（Git ignored）。
- 默认 PATH Marker/Node 缺失；conda Python 3.12.13 创建 .venv/.marker-venv。Marker 源码 commit e7c67f1d239ea6a805cbf4ed6c6b2056d435e22d，package 2.0.0。
- `marker_single --help` PASS：实际确认 mode fast/balanced、output_format html、output_dir。
- 首次真实 fast FAIL：SpawnError，缺失 llama-server。修复：官方 llama.cpp b11523 macOS arm64 二进制，SHA256 5dc551427a61719a2aa9dc77c59dbeb525c357e0dbba3b7db3a6772f0737794f。
- Attention Is All You Need fast 重跑：returncode=0，runner elapsed 312.1s，Marker 日志 inference 294.8929s，HTML 63451 bytes，102 p、5 img、9 math、8 table，5/5 图片实际存在。模型缓存约 1.8G。视觉与双栏补测继续中。
- Chrome Read Frog + DeepSeek：NOT RUN，保留发布 blocker；不是“插件失败”，不能因此擅自收费调用 fallback。

## M1
文件：backend/app/config.py、db.py、alembic、main.py，frontend package/tsconfig/Vite、Makefile、scripts/run.py。
- Alembic 初始 migration 实际创建数据库，API factory 34 routes。
- pytest 首轮 15 passed，含 health/空列表/无 Marker 启动、独立数据库连接持久化；生产 build PASS、lint/typecheck PASS。
- 默认数据目录仍按规格使用 macOS Application Support，验证均使用 /tmp 临时目录。

## M2
文件：storage.py、arxiv.py、schemas.py、main.py、frontend/src/App.tsx、api.ts，tests/test_library.py/test_security.py。
- 自动化 PDF 真实解析/复制/去重、标签集合搜索、状态与进度跨连接保留、Range 206、确认删除 PASS。
- arXiv URL/旧 ID/版本归一、禁止非官方输入、断网保留与重复规则 PASS（mock 网络，不能计为真实 arXiv PASS）。
- Chrome 实际上传、编辑、搜索已执行；完整 E2E 回归继续中。

## M3
文件：frontend/src/PdfReader.tsx、scripts/create_fixture.py、tests/e2e/library.spec.ts。
- pdfjs-dist 真加载生成的 35 页 PDF，canvas 与可选择文本层已在 Chrome 验证。
- 首轮 E2E FAIL：测试把 1x DPR 误写为 Retina 2x；修复断言。
- 次轮 E2E FAIL：初始位置恢复竞态覆盖过早翻页；禁用导航直到恢复就绪后复跑。
- 实际科研 PDF 视觉与长文阅读人工流畅度尚未完成。

## M4
文件：worker.py、scripts/controlled_marker.py、tests/test_worker_html.py。
- 使用真实受控子进程执行 fake CLI 的单队列、缓存命中、失败不覆盖 HTML/PDF、强制重试、取消与孤儿 running 恢复 PASS。
- 注意 fake CLI PASS 不是 Marker 质量 PASS。Marker 真输出见 M0；应用内真实转换尚需执行。
- supervisor 监测父进程退出并追踪 detached 推理子进程；进程枚举在 sandbox 受限时只处理直接子进程，真实 macOS 测试继续中。

## M5
文件：html.py、reader_static/reader.js/reader.css、scripts/build_reader.py。
- 稳定普通 HTML DOM、TOC、公式禁翻、KaTeX 离线资源、暗色和进度实现；XSS/路径/symlink/image 净化测试 PASS。
- 测试发现净化 protocols 空白名单误删内部 img src，已修复并通过图片路径测试。
- Read Frog 和 10 篇质量门槛 NOT RUN，保持未完成。

## M6
文件：App.tsx、styles.css、components/ui/button.tsx、Modal.tsx、scripts/backup.py、README/lockfiles。
- 生产 build/typecheck、API tests 20 passed、Vitest 3 passed；深色持久化 Chrome E2E PASS（次轮）。
- 备份停服锁、SQLite backup API、资产校验、恢复新目录、拒绝 zip slip PASS。
- UI 截图评审和安装文档继续收口。

## M7
尚未完成发布验收。人工 Read Frog、10 篇 HTML 质量、真实全过程关服重启仍有 NOT RUN，不能称 Release Candidate。

## 后续验证与阶段收尾（以上失败保留为历史记录）

统一回归命令：`make lint typecheck test e2e` 实际 exit 0；ruff All checks passed、eslint/tsc exit 0、pytest **28 passed, 1 warning in 3.29s**、Vitest **3 passed**、Playwright Chrome **2 passed (6.6s)**。warning 是 Starlette TestClient/httpx 弃用提示。真实推理与插件测试不计入 fake CLI 自动化数量。

| 阶段 | 真实完成与文件 | 验证结果 | 人工待办 / P0 / 下一步 |
|---|---|---|---|
| M0 | Marker/llama依赖隔离、真实双栏；doctor.py/marker_gate.py/marker-readfrog.md/DECISIONS.md | CLI help PASS；Attention fast 312.1s、FAST-LIO2 fast 55.28s，returncode0；公开双栏PDF已渲染实查 | 用户Chrome Read Frog/DeepSeek NOT RUN，P0保留；按人工清单验证 |
| M1 | FastAPI/React/Vite、SQLite迁移、loopback启动；config.py/db.py/alembic/run.py/Makefile | make build/serve PASS；make dev Vite220ms，代理health及同源写入200；缺Marker可启动 | 第二台全新安装NOT RUN；核心无已知P0，继续实际使用 |
| M2 | 真实导入/去重/分类/search/metadata与429退避；storage.py/arxiv.py/main.py/App.tsx | API自动化PASS；Chrome上传编辑搜索删除PASS；真实arXiv Atom与官方HTML200、缺失404；官方新标签与阅读状态PASS | 物理拖拽人工NOT RUN；网络可失败但保留条目；继续常用论文 |
| M3 | 真PDF.js/文本层、页码/缩放恢复；PdfReader.tsx/e2e/library.spec.ts | Chrome 35页、Page6文本实际入视窗、110%刷新恢复PASS | 长期大PDF滚动人工NOT RUN；原文保真路径可用 |
| M4 | 持久单队列、受控进程树、原子发布/缓存；worker.py/controlled_marker.py | validate_real.py 真API→Marker33.42s→5资产200→cache→重启PASS；转换时PDF206/health200；孤儿恢复/取消/失败重试PASS；父进程死亡清理detached child PASS | 无扩展依赖；更多质量样本继续M5；PDF不受转换失败影响 |
| M5 | 独立净化HTML、TOC/公式/图片/表格/暗色/位置；html.py/reader_static/*/capture_real.mjs | Chrome5图片、9KaTeX/0错误、8表格、0坏图/JS错误、TOC/progress PASS；截图实查分式并修复隐藏问题 | Read Frog P0待人工；quality_gate.py/quality_browser.mjs补齐10篇，不用DOM数量冒充阅读质量 |
| M6 | UI空/错/载态、设置、备份恢复、安装文档与锁；styles.css/backup.py/README/lockfiles | 1280×900 Chrome实际截图、暗色刷新PASS；备份manifest/SQLite完整性、新目录恢复/ZIP slip拒绝PASS | 全新机器安装及长期使用NOT RUN；开放源码LICENSE未选 |
| M7 | 安全回归/真实链路/验收矩阵；tests/*/acceptance.md/DECISIONS.md | 28+3+2 PASS；真arXiv与真Marker链路PASS；私密异常不泄露与子进程环境隔离PASS | 尚不是V1/RC；关闭Read Frog双语与阅读质量Gate后再验收 |

真实数据和PDF保存在库外；`real-integration.json`、`html-browser.json`、`arxiv-network.json`、`arxiv-browser.json` 是已执行证据。截图由实际Chrome生成，不是UI渲染设计图。完整含双语的关服重启仍NOT RUN。

随后补充非法 URL port/IPv6 bracket 校验，`make lint typecheck test` 真实 PASS：pytest **30 passed, 1 warning in 3.35s**，Vitest 3 passed。E2E 2 passed 为此前同一前端实现；没有因此重复算新的浏览器执行。`make doctor` PASS：configured Marker/llama绝对路径存在，16GiB RAM；PATH 缺CLI且API环境无Marker包符合独立推理环境设计。

质量对照辅助脚本初次 `quality_contact.py --help` FAIL：误用未安装的PyMuPDF；改用Marker锁文件已安装的PDFium 5.10.1后 `--help`/ruff PASS，未为了截图加入新依赖。

M5最终补测：`scripts/quality_gate.py` 真8个Marker任务+2官方HTML 10/10 succeeded；`quality_browser.mjs` 真Chrome10页面PASS，8本地页77图片/165公式/60表格、0坏图/KaTeX/JS错误，TOC/进度/1280px无全页溢出PASS。实际PDF/HTML对照抽查保守8/10可用，Attention与ResNet LIMITED，详见quality-readability.md。修复表格逐字换行后Chrome复测PASS；不是逐页逐式保真。

M6/M7恢复演练：CLI对真实10篇验收库停服备份、恢复到新目录，再新factory检查：10条目、8 PDF Range206、8 HTML、77资产200、8位置与源库相同、8缓存命中PASS；archive60,162,236 bytes，见recovery-real.json。临时服务8010正常关闭，未覆盖个人Library。下一步仅关闭用户Read Frog双语Gate和完整双语关服重启；翻译未测试不宣布V1/RC。

最终阶段末完整回归 `make lint typecheck test e2e` exit0：ruff/eslint/tsc PASS，pytest **30 passed, 1 warning in3.50s**，Vitest **3 passed**，build PASS，Chrome E2E **2 passed in6.5s**。随后重新make serve供使用。遗留：Read Frog双语与完整双语演练P0待人工；第二台全新安装、长时/高压力P1 NOT RUN。
