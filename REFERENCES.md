# REFERENCES — 已核实的第三方能力与限制（2026-10-09）

此文档提供 Codex 的官方资料入口。第三方软件更新很快，真正安装时请以**锁定的 package version + `--help` + 实际测试**为最终依据。以下是设计输入，不是已完成测试。

## 1. Read Frog（翻译扩展）

- GitHub: https://github.com/mengxi-ream/read-frog
- 官方本地文件/localhost 翻译说明: https://www.readfrog.app/en/docs/local-files
- 官方安装说明: https://www.readfrog.app/en/docs/installation
- 文档指出：除了 Chrome/Edge 对 `file://` 需要单独允许扩展访问之外，可以使用 `http://localhost` 的本地 HTTP server 来加载 HTML 并翻译。**这证明技术路径有官方支持，但不证明 PaperFlow 自定义 DOM 的实际兼容性。**
- Read Frog 自身支持 DeepSeek 等 Provider；用户已自行在插件中配置密钥，PaperFlow V1 不应要求用户再配一次。
- Read Frog README 显示 GPLv3 / 商业授权；不要直接复制其源代码进准备独立开源的项目，除非经过许可合规确认。建议**作为独立扩展依赖**，不进行代码捆绑。

## 2. Marker（PDF→HTML）

- GitHub: https://github.com/datalab-to/marker
- 官方 README: https://github.com/datalab-to/marker/blob/master/README.md
- 官方支持 `marker_single /path/file.pdf --output_format html --output_dir ...`。
- 其 HTML 输出包含图片标签与数学结构标签；实际输出质量依论文/模型模式变化。需验证数学格式到底是有效 MathML 还是包裹式文本结构后决定渲染适配，不得预设。
- 官方支持 CPU/GPU/MPS；README 描述 fast 更适合 CPU/MPS，balanced 更适合 GPU。部分当前模式可能需要 llama.cpp 等额外 inference backend；不要无条件保证 `pip install marker-pdf` 后所有 Mac 环境无需其他配置就能成功转换。
- 代码许可证与模型权重许可证不同：代码 Apache-2.0，模型权重带额外使用条款；开源发布前要核对当前版本。不要把 Marker 模型权重提交到项目 repo。

## 3. arXiv 元数据及 HTML

- arXiv API 文档: https://info.arxiv.org/help/api/user-manual.html
- arXiv API 基础: https://info.arxiv.org/help/api/basics.html
- arXiv HTML 功能背景: https://arxiv.org/abs/2402.08954
- 通过 API Atom feed 获取 ID、作者、标题、摘要等。不是每篇 arXiv 都有 HTML，因此 `https://arxiv.org/html/<id>` 需要验证后才提示可用。
- 需要考虑版本号 `vN`、新旧 arXiv ID、网络请求速率、HTTP 429/redirect 和元数据缓存。
- 官方 HTML 为第三方远端页面，默认外部新标签打开；V1 不做自动本地化，也不谎称追踪外部浏览进度。

## 4. PDF.js

- GitHub: https://github.com/mozilla/pdf.js
- 目标是嵌入式原 PDF 查看，不依赖 HTML 重建结果；前后端正确支持 PDF Range 请求更利于大 PDF 阅读。

## 5. 选型补充

- FastAPI: https://fastapi.tiangolo.com/
- SQLite: https://www.sqlite.org/docs.html
- React: https://react.dev/
- Vite: https://vite.dev/
- shadcn/ui: https://ui.shadcn.com/
- PDF.js: https://mozilla.github.io/pdf.js/

## 6. 待真实环境确认的关键项

1. 用户 MacBook Air 的芯片、内存、Python/Node、Marker 安装可用性（项目自检）。
2. 锁定 Marker 版本的确切 output 目录布局和公式类型。
3. Read Frog 在 PaperFlow 实际 HTML 文档中能否翻译全部所需论文片段而不改坏公式。
4. arXiv API 在用户网络环境下的访问与频率限制。
5. 开源之前使用的 UI 图片/字体/第三方依赖许可证。
