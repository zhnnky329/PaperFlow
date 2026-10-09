# 阶段执行记录（2026-10-09，持续更新）

所有 PASS 仅针对实际运行的验证范围，不代表整个 V1 已验收。

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
