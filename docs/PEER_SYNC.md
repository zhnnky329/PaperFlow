# Ubuntu 与 macOS 双机同步

两端各自运行 PaperFlow、保存自己的 SQLite 和论文文件。Mac 运行 Discovery，Ubuntu 接收远程转换。Mac 原有 Convert / 重建 HTML、模式和自动转换保持原有行为；只有主动选择「使用 Ubuntu 转换」才会提交远程任务。

## 准备

先停止服务并备份两端已有论文库。Ubuntu 使用 `feat/ubuntu-peer-sync`，macOS 使用 `feat/main-peer-sync`，按各自 README 安装、构建。首次启动自动迁移数据库，保留原有论文、分类、进度和任务。回退旧版时恢复升级前备份。

推荐两端安装 Tailscale，加入同一私人网络并允许 Mac 连接 Ubuntu。不同网络可通信，但需要同时在线才能交换；已下载论文可随时本地阅读。无需第三方云端中转。官方说明：<https://tailscale.com/docs/features/tailscale-serve>。

生成一次密钥，将相同值填写到两端 `.env`，不要提交密钥：

```sh
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Ubuntu `.env`（保留已验证的 Marker / llama-server 路径与 CUDA 配置）：

```dotenv
PAPERFLOW_SYNC_ENABLED=true
PAPERFLOW_SYNC_TOKEN="相同的至少32字符随机密钥"
PAPERFLOW_SYNC_ACCEPT_CONVERSIONS=true
PAPERFLOW_DISCOVERY_ONLINE=false
PAPERFLOW_MARKER_DEVICE=cuda
PAPERFLOW_SYNC_INTERVAL=15
```

启动 Ubuntu PaperFlow，然后运行：

```sh
tailscale serve --bg --https=8443 http://127.0.0.1:8000
```

按提示启用 HTTPS，记录它显示的 HTTPS 地址。PaperFlow 继续只监听 loopback；只有持有密钥的服务端请求可访问 `/peer/v1/*`，网页和原有 API 仍要求 localhost Host / Origin。不要开启 Funnel，也不要关闭 Host / CSRF 检查。

Mac `.env`（保留原有本地 Marker 配置，不添加 Ubuntu 专属 CUDA 参数）：

```dotenv
PAPERFLOW_SYNC_ENABLED=true
PAPERFLOW_SYNC_TOKEN="相同的至少32字符随机密钥"
PAPERFLOW_SYNC_PEER_URL="https://实际Ubuntu地址.ts.net:8443"
PAPERFLOW_SYNC_ACCEPT_CONVERSIONS=false
PAPERFLOW_DISCOVERY_ONLINE=true
PAPERFLOW_SYNC_INTERVAL=15
```

重启两端，在 Settings → 双机同步查看状态。Mac 每 15 秒发起双向交换，也可点击「立即同步」。Ubuntu 无需填写 Mac 地址，在交换响应中返回自己的修改。

每端自动生成独立设备 ID。两端已有独立论文库可直接合并，相同 PDF 按 SHA-256 去重，保留各自本机论文 ID。不要通过复制整个数据库建立第二台设备，重复设备 ID 会被拒绝。密钥只从后端配置读取，不返回页面，不进入同步数据或普通备份。

## 使用

1. Mac Discovery 加入论文后先下载 PDF；只有 arXiv 条目不能转换。
2. Library 与 PDF 阅读器均保留本机转换按钮，并增加「使用 Ubuntu 转换」。
3. 远程请求先持久保存于 Mac，连接后上传 PDF、校验并提交 Ubuntu。Mac 随后可关机；Ubuntu 的 PaperFlow 服务保持运行即可继续转换。
4. Mac 下次连接后下载 HTML、图片与清单，校验、重新清理 HTML，再原子发布。下载期间保留原来可读的 HTML。
5. 取消先显示等待确认；重试继续使用 Ubuntu，不自动改成本机转换。重复发送按请求 ID 去重。Ubuntu 进程中断的转换显示失败，可手动重试。

Ubuntu 可通过 `python scripts/run.py serve --no-open` 无浏览器运行，也可自行配置为系统用户服务。开机不等于服务已运行，关闭浏览器不会停止服务，退出未托管的终端会停止服务。

## 数据和冲突

同步论文元信息、PDF、标签、分类树及归属、阅读状态、PDF / HTML 位置、完整 HTML、删除记录。Discovery 候选池、分析任务、Key、预算和设置不复制，按上述配置仅 Mac 联网执行。主题、字号、宽度、缩放、路径、环境、模型、日志和临时文件属于各自设备。

每个论文字段与每条标签/分类归属独立版本化。不同字段的修改可合并；同字段的并发修改按 Lamport 逻辑时钟及设备 ID 选出唯一结果，不依赖电脑系统时钟完全一致，不合并文本内部修改。删除记录持久保留。文件夹并发改名造成同名或循环时暂停同步并提示，先修正原设备的目录后重试。

每台设备最近的 PDF / HTML 位置单独保留，可通过本机 `/api/v1/papers/{id}/device-positions` 查看。打开时恢复最后合并的位置，缩放保留本机设置。若另一端已更新位置，旧页面保存会被拒绝并提示刷新，避免覆盖。HTML 滚动比例在不同屏幕或翻译排版下仍可能偏移。

转换开始时预留结果版本。较早请求即使更晚完成也不会覆盖较新请求的结果，旧结果保留在任务目录中。传输先完成哈希校验，才切换阅读入口。

## 验证与边界

自动测试用两个隔离数据库、真实 peer HTTP 路由和模拟 Marker 子进程，验证双向同步、已有库去重、图片引用、进度版本、鉴权、离线请求重启恢复、取消/重试、缓存及旧结果保护。

协议目前面向一对可信设备，交换完整版本记录，文件按哈希增量传输。第一次同步可能较慢。`PAPERFLOW_MAX_UPLOAD_MB` 同时限制单个 PDF、HTML 压缩包及解压后的 HTML 资源总量，两端请设置足够大的值。传输失败时保留待同步状态，下次重新传输完整资源，暂不支持字节范围续传。

同步不是备份，删除也会传播，请保留独立备份。`peer-cache/` 是可重新获取的传输缓存，不进入普通备份；原文和已发布 HTML 位于 `papers/`，同步记录与任务位于数据库，随现有备份一起保存。
