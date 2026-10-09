# PaperFlow 技术决策

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
