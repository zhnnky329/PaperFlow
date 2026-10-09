# PaperFlow 技术决策

以下为按时间追加的决策与验证记录；最新状态以末尾及docs/validation/acceptance.md为准，保留早期失败与待验证快照。

## 2026-10-09 · 规格位置和现有内容
根 README 原内容只有 `PaperFlow`。完整输入规格在 `PaperFlow_V1_Codex_Package/`，完整阅读后复制到根目录以供持续执行。保留规格包和已有 `marker/` 源码，不把第三方嵌套仓库及其测试 PDF 纳入应用提交。

## 2026-10-09 · 环境隔离和 M0 Gate
本机 macOS 27.0 arm64，conda markitdown Python 3.12.13 用于创建 `.venv` 和 `.marker-venv`，不修改用户现有 conda 环境。默认 PATH 未找到 Node/npm、Marker CLI，开发验证可用 Codex bundled Node，最终启动入口允许用户传入标准 PATH。安装 Marker 采用现有源码 2.0.0；实际 CLI/help/转换证据写入 docs/validation/marker-readfrog.md。

## 2026-10-09 · 翻译选择
Read Frog 是用户独立扩展，只提供普通 DOM 与使用帮助，不读取其 key，不调用不存在的 SDK。官方文档支持 localhost HTTP：https://www.readfrog.app/en/docs/local-files 。插件未实测时必须保留发布阻断；不因 NOT RUN 擅自触发付费 API。依 ARCHITECTURE §9，只有实际失败且 DOM 调整无效才激活 native fallback。

## 2026-10-09 · 持久化与安全
FastAPI 同源静态服务；SQLite WAL + Alembic；受控 UUID 存储、PDF 签名和解析校验；HTML 白名单净化、图片解码重编码、公式节点禁翻。写 API 要求同源 Origin 和自定义请求标记，Host 精确验证。单 worker 使用 subprocess 参数数组、进程组、限时，队列存 SQLite；衍生物成功后原子发布，旧产物保留至新产物成功。

## 2026-10-09 · M0 实测结果与推理依赖
真实 macOS arm64 / 16GB RAM / Chrome 154.0.8037.98 / Node 24.19.0。CLI help PASS。首次 fast 失败为缺少 llama-server，安装官方 b11523 arm64 发布资产并核验 SHA256 后修复。Attention fast runner 312.1s（推理日志 294.8929s）；双栏 FAST-LIO2 55.28s（推理 38.7548s）。应用内实际转换、5 张图片、缓存、停止重启 PASS。模型缓存复制到 macOS Library/Caches/PaperFlow/models-marker2，本机 `.env` 私有配置绝对路径（无 key）。不把硬件峰值或 10 篇质量测试标为通过。

## 2026-10-09 · 公式实际渲染修复
Marker 输出的 `math` 实测是 LaTeX 文本，包含分式。把 KaTeX HTML 放到 MathML `math` 容器会隐藏分式，实际截图发现后修复：文本公式转为普通 span/div 并保护 translate=no，已有真正 MathML 子树保留。KaTeX trust=false、maxExpand=500，公式源码长度有界。修复后的截图确认分式/根号/上标可见，9 个公式、0 KaTeX errors；Marker fast 的 inline/block 分类仍可能使公式断行，保留 PDF 对照。

## 2026-10-09 · 受控进程树、网络和恢复
Surya 会以新 session 启动 llama-server，单杀 Marker 进程组不足以可靠清理推理子进程。新增独立 supervisor 追踪自己创建的子进程，监测父进程退出，只清理这些 PID（psutil 防 PID 复用）；实际父进程终止的 detached child 清理 PASS。元数据 pending 在异常重启后变为可重试失败，429 加入有界 Retry-After cooldown，不无限重试。错误只记录异常类型和去除路径/源码行内容的栈帧，不记录论文正文、CLI 原始 stderr 或 Key。

## 2026-10-09 · 交付与未完成 Gate
完成实现和可复现自动化，提供 dev/serve/backup/restore；PDF 引擎按需加载以缩小 Library 初始 bundle。Read Frog 操作留在用户独立 Chrome 扩展；本会话没有触发付费 DeepSeek。未将 NOT RUN 当成兼容性失败，故未擅自启用原生 fallback。当前不宣布 V1/Release Candidate：Read Frog 人工双语和 10 篇至少 8 篇质量 Gate 仍须通过；失败后按 §9 实施 fallback。

## 2026-10-09 · 错误日志与推理出站边界
Starlette 的最外层异常处理会重新抛出异常，可能使 Uvicorn 输出未脱敏错误。改在 HTTP 安全 middleware 内捕获意外异常，只记录类型、request id 与无路径/源码的栈帧；测试人为注入含私密文本的异常，验证不 re-raise、响应和日志均无原始内容。启动关闭 access log，避免搜索 query 留在终端日志。Marker 子进程去除继承的 SURYA_INFERENCE_URL 和 KEY/TOKEN 变量，强制本地推理 host；fake 子进程实际断言环境隔离。完整回归 28 + 3 + 2 PASS。

非法URL端口与不完整IPv6括号应返回422，避免解析库ValueError变成500；补测后pytest 30 passed。Gate工具也采用受控supervisor并加载本机.env；质量对照复用已锁定的PDFium，不额外引入PyMuPDF。

## 2026-10-09 · 十篇质量 Gate 补齐
真实执行8个不同PDF的Marker任务和2个官方HTML导入；8本地Chrome页面77图片/165公式/60表格无坏图/解析/脚本错误、目录进度PASS。实际PDF渲染对照与截图审查保守计8/10可用，Attention公式拆行、ResNet宽表/识别瑕疵不计质量PASS，保留PDF。修复表格cell逐字换行，未用LLM重写整篇HTML。该抽查关闭样本数量门槛，不代表逐式数学校对或Read Frog已验收；详情quality-readability.md。

## 2026-10-09 · 阅读工作台 UI 优化
用户明确要求按 frontend-design 和 apple-design 优化高级感。采用本机系统字体、纸白/石墨灰结构面、单一靛蓝强调色；侧栏与论文工作区分层，标题 32px，列表以论文标题为中心，空态采用 CSS 纸页形态。仅顶栏/弹窗背景使用有意义的半透明材料，按钮在按下时即时反馈；不添加动画库、网络字体或装饰图片。支持减少动态效果/透明度/增强对比度偏好，强制颜色模式保留原生 checkbox。

保留原有 API、PDF.js 文本层与 HTML 普通 DOM；隐藏重复的成功转换状态，中文显示进行中/失败状态；小屏保留 PDF/HTML/阅读状态操作；无结果提供清除筛选。文件选择改为可见按钮调用隐藏原生 input，首轮 Chrome E2E 暴露同名控件后用 hidden 修正辅助技术树，并实际通过 filechooser 验证。

最终证据：make build/lint/typecheck PASS；make test 在沙箱内 29 passed/1 skipped，具备进程枚举权限后 30 passed（1 个依赖弃用警告），Vitest 3 passed；make e2e 2 passed/6.3s。真实公开论文库的浅/深色、导入、390px、PDF/HTML 页面截图与报告见 docs/validation/ui-polish.md。Read Frog 扩展、macOS 系统辅助功能手动切换仍 NOT RUN，不把外观回归当翻译验收。

## 2026-10-09 · 自定义文件夹与 Finder 目录
用户明确要求自定义可命名文件夹分类，并对应 Finder 中真实目录。将现有 Collections 的界面改成文件夹，保留已有多对多分类及 UUID 原始 PDF，避免静默迁移/清空用户数据。真实目录位于 data_dir/folders/<名称>，异步单线程将原始 PDF 原子复制到目录，重启重新对账；不使用硬链接，Finder 修改副本不会破坏 PDF Reader/Marker 的原始文件。此同步为应用→Finder，Finder 新文件/移动/改名不反向导入。

目录及副本有管理清单，只删除清单中且校验未变化的 PDF；额外文件和改过的副本保留；拒绝符号链接、路径分隔符、同名外部目录覆盖。同步失败独立持久化并可重试，不阻断原始 PDF。备份包含 folders。新增界面提供命名/计数/筛选、导入目的地、已有论文归类、移出及 Finder 打开入口。无需数据库 schema 变化；Folder Gate 的实际结果在后续验证记录中追加。

## 2026-10-10 · 文件夹验证结果
文件夹功能完整回归：34 pytest / 3 Vitest / 3 Chrome E2E PASS；真实 FAST-LIO2 在隔离库中通过原生文件选择导入并归类，Finder 副本与原文逐字节一致，实际 macOS open 返回成功。Finder 窗口内容人工检查仍 NOT RUN。根目录 symlink 故障不应使 GET collections/Library 失败，因此查询仅提供路径文本，写入/打开才检查真实边界；专门回归通过。备份恢复包含 PDF 副本及用户额外 note；无数据库迁移、无已知新 P0，既有 Read Frog Gate 保留。详情 docs/validation/folders.md。

## 2026-10-10 · MIT 许可证与公开使用文档
用户明确选用 MIT 许可证。根目录添加 LICENSE，正文采用 SPDX 的标准 MIT 文本，版权署名为仓库所有者 zhnnky329；README 链接该许可证并在末尾致谢 Marker。MIT 适用于 PaperFlow 自身，第三方依赖及模型权重仍遵循其上游许可，不重新授权或捆绑模型。

参考 Memos、Zettlr 和 Marker 的 README，按项目介绍、安装、操作步骤、可选转换配置、备份和开发组织文档。浏览器插件只保留一句使用提示；详细测试状态继续保存在 docs/validation，不改变尚未执行的验收结论。本次验证：本地链接及目录锚点、10 个 Shell 示例的 sh -n 语法、Make target 名称、LICENSE 与 SPDX MIT 正文核对、git diff --check 均 PASS；仅修改文档与许可证，未重复运行应用回归。

## 2026-10-10 · 源码安装验证与依赖安全升级

将源码复制到独立临时目录，创建新的 Python venv 并运行 npm ci，不复用项目 node_modules 或个人 Library。真实安装发现旧锁文件存在 5 个 npm 审计项，涉及 PDF.js、KaTeX 和 Vitest 的依赖链。升级并精确锁定 PDF.js 6.4.299、KaTeX 0.19.0、Vitest 5.0.3；保留 Vite 7 和 Node 24。依据已安装 PDF.js 的类型与源码，将 getDocument 的字符串参数改为对象 URL；关闭 XFA，不添加已移除或虚构的参数。

初次迁移的类型检查分别发现旧字符串签名和不再支持的 isEvalSupported 参数，修正后完整回归通过：34 pytest、3 Vitest、3 Chrome E2E；lint/typecheck/build PASS；npm audit 0 项漏洞。对隔离的公开论文库副本检查 8 篇已有真实 Marker HTML，77 图片、165 个 KaTeX 公式、60 表格，无坏图/解析/页面脚本错误，目录与进度恢复通过。这次未重新运行 Marker 推理，也未操作用户 Read Frog 扩展；保留原有排版质量限制及人工 Gate。

该验证使用同一台 Mac 和已有系统运行时/模型缓存，不能宣称第二台机器或全新系统安装通过。用户明确表示自行使用 Git SSH 提交，代理停止远端操作；新增修复和验证记录留在工作区。命令与证据见 docs/validation/install-dependencies.md。
