# DESIGN — PaperFlow V1 UI/UX 规范

## 0. 设计方向

**关键词：** Linear 的克制感、Raycast 的效率、Arc/Notion 式易读排版。不是把 Zotero 换个皮肤，而是让论文阅读成为界面中心。

**目标**：轻、快、低视觉噪声、可靠、桌面优先；macOS Safari 不作为 V1 翻译必验浏览器，因为 Read Frog 主要依赖 Chromium 浏览器扩展。

优先实现一致性、清晰信息层次和真正可用的空/加载/失败态，不要用炫目的动画、无意义的渐变或假数据充当完成品。

## 1. Design tokens（可按真实预览微调）

- 字体：`Inter`, `-apple-system`, `BlinkMacSystemFont`, `SF Pro Text`（系统可用时）, `Noto Sans CJK SC`/系统中文后备；论文正文可切换衬线。
- 字号：应用 UI 13–14px，正文默认 17px，行高 1.7；论文标题 28–34px。
- 圆角：卡片 10px、弹层 12px、按钮 8px。避免全页面 pill 形控件。
- 阴影：低对比轻阴影，线框为主。
- 动效：120–180ms，尊重 `prefers-reduced-motion`。
- 强调色：建议 slate/indigo 单一低饱和色（例如 `#5E6AD2`），不使用彩虹配色。

Light tokens（示例）：

```css
:root {
  --bg: #F8F9FB;
  --surface: #FFFFFF;
  --sidebar: #F4F5F7;
  --text: #20232A;
  --text-muted: #69707D;
  --border: #E5E8EE;
  --accent: #5E6AD2;
  --accent-soft: #EEF0FD;
  --danger: #CE4D4D;
}
```

Dark tokens（示例）：

```css
.dark {
  --bg: #111317;
  --surface: #191C22;
  --sidebar: #16191F;
  --text: #E8EAF0;
  --text-muted: #9BA3B1;
  --border: #2B303A;
  --accent: #8490EF;
  --accent-soft: #272B48;
  --danger: #EE8181;
}
```

确保实际按钮、提示与正文的对比度达到可读要求，tokens 是初值而非硬性固定色值。

## 2. IA：信息架构

```text
App
├── Library
│   ├── All Papers
│   ├── Unread
│   ├── Reading
│   ├── Finished
│   └── Collections (+ Tags filter)
├── Reader
│   ├── PDF
│   ├── Local HTML
│   └── Official HTML (external link)
└── Settings
    ├── Appearance
    ├── Storage
    ├── Conversion / Marker
    └── Translation (Read Frog how-to)
```

**统一核心操作**：`Add Paper`、全局搜索、最近阅读、当前论文 `Open`、`Convert HTML`、`Open original PDF`。

## 3. Library — 桌面布局

- 整体最大宽度视窗，不固定中间窄盒子。
- 左侧 sidebar 220–240px：Logo、搜索、All/Unread/Reading/Finished、Collections、Settings。
- 主区 header：`Library`、总数量、搜索（Cmd/Ctrl+K 可选）、`+ Add Paper` 按钮。
- 默认 List view；一篇论文一行/卡（标题为视觉焦点，第二行作者·年份·标签，右侧状态及菜单）。支持密度适中的列表，避免奢侈级空白导致每屏只显示几篇。
- 辅助阅读格式标签（Official HTML / Local HTML / PDF）小而明确。转换状态不滥用醒目颜色，仅 failed 显示警告状态。
- 有意义的空状态：无论文、无搜索结果、过滤后为空、导入失败。每种都提供下一步操作。

ASCII 结构：

```text
┌─────────────────────────────────────────────────────────────────┐
│ PaperFlow   [ Search papers... ]                      + Add Paper│
├────────────────┬────────────────────────────────────────────────┤
│ All papers 128 │ Library                        Sort: Recent ▼  │
│ Unread         │                                                │
│ Reading        │ ┌────────────────────────────────────────────┐ │
│ Finished       │ │ SGNav: ...                                │ │
│                │ │ Authors · 2025       VLN · Reading · HTML  │ │
│ Collections    │ └────────────────────────────────────────────┘ │
│ + New          │ ┌────────────────────────────────────────────┐ │
│ Motion Plan    │ │ FAST-LIO2 ...                             │ │
│ SLAM           │ │ Authors · 2022       SLAM · Finished · PDF  │ │
│ VLN            │ └────────────────────────────────────────────┘ │
│                │                                                │
│ Settings       │                                                │
└────────────────┴────────────────────────────────────────────────┘
```

## 4. Add Paper — 单一入口

点击 `+ Add Paper` 打开有明确层级的 Modal（宽 560px 左右）：

- Tab A `PDF File`：拖放区 + file picker，支持多文件；导入过程每个文件独立反馈。
- Tab B `arXiv Link`：输入 URL/ID，提交后显示元数据请求状态。
- 输入可识别类型，若检测到 URL/ID 可以智能切换，但不应隐藏明确的用户操作入口。
- 对重复 PDF/arXiv：显示“已存在”和 `Open existing`，不要偷偷创建第二条。
- 如果 API 失败：明确提示“已保存为待补全条目，可稍后重试”。

## 5. Reader — 阅读优先

### PDF Reader

- header 固定高度 52–60px：Back、论文短标题、`PDF | HTML` segment、当前阅读状态、更多菜单。
- 原始 PDF 以 PDF.js 组件渲染，右上页码与缩放控件，支持滚轮/触控板。
- 必要时左侧显示简易目录/页缩略图（可在 V1 仅实现 PDF.js 导航，不承诺全功能缩略图）。
- 读书器如果无 PDF（arXiv 仅链接）展示 `Download PDF`，不应显示白屏。

### Local HTML Reader

**正文需要属于可被 Read Frog 扫描的普通 DOM**。建议服务端构建独立 `/read/{id}/html` 页面，并保持应用视觉一致，避免 iframe/Shadow DOM 正文。

布局：
- 顶栏：← Library、论文简称、打开 PDF、Reader settings、`Translate with Read Frog` 帮助入口。
- 左侧可折叠目录 240px，跟随当前小节高亮。
- 正文默认 max-width 780px（可选 compact 680px / wide 920px），留足左右边距。
- `h1`、`h2`、`h3` 层级明确；公式横向溢出时局部滚动，不让页面整体错位；图片等比缩放，有 caption；table 容器允许横向滚动。
- 避免在正文元素上部署不稳定虚拟滚动/视窗卸载，Read Frog 的段落级翻译需要稳定文本节点。
- 用 `translate="no"` 标记导航、工具栏、论文元数据占位符、公式/代码等区域，**真实正文不要全局禁翻**。

### Official arXiv HTML

点击 `Open official HTML ↗` 新标签页打开 arXiv。显示 `External website · Read Frog works there` 的轻提示。外部网站阅读位置不可自动采集；返回 Library 后用户仍可手动标注状态。V1 不显示“已自动同步外部进度”。

### 通用状态

- 当没有 HTML：显示 PDF + `Convert to HTML` CTA（PDF 可用时）；若 PDF 不存在则先 `Download PDF`。
- 转换中：顶部显示小型任务状态，可继续 PDF 阅读。
- 转换失败：失败原因、重试按钮、继续阅读 PDF。
- 完成时通过轻提示告知可切换，不强制中断当前阅读。

## 6. Settings

**Appearance**：Theme（Light/Dark/System），reader width，font size，默认阅读模式（优先 Official HTML/Local HTML/PDF，受是否可用约束）。

**Storage**：数据目录只读展示、占用量（可延迟实现）、备份说明。

**Conversion**：Marker status（installed/missing）、mode（fast 默认、balanced 可选）、auto-convert（默认关闭）、重试/诊断信息；深度参数折叠在 Advanced。

**Translation**：Read Frog extension 链接、Chrome localhost 翻译指南、提示 DeepSeek Key 由 Read Frog 自行管理；除 fallback 确实启用外不展示 PaperFlow 自身 API Key 输入框。

## 7. 交互细节

- 搜索框防抖 200–300ms；有清空按钮；Esc 退出查询/弹层。
- Popup menu 的危险删除操作必须二次确认且按钮描述清晰。
- 文件导入支持拖拽和原生 file picker；文件太大/不是 PDF 要有错误反馈。
- `read_status` 默认 unread；首次打开阅读器可自动切到 reading（但不能覆盖 finished）；用户仍能手动标完成。
- 阅读位置滚动保存节流/防抖，刷新恢复；未完全加载/图片未展开前不要恢复到错误位置。
- 允许通过浏览器后退返回；不强制拦截快捷键。
- 所有 loading、empty、error、success state 真正可操作，而非纯装饰。

## 8. 无障碍 & 响应式

- 主要目标 MacBook Air 屏幕分辨率/缩放；在 1280px 宽度阅读不横向滚动（复杂 table 局部滚动除外）。
- 小于 900px 时 sidebar 可折叠，正文不挤压；V1 不需要专门手机应用。
- 图标按钮有 tooltip / aria-label；键盘导航和可见焦点；文本对比足够。

## 9. 禁止的 UI 捷径

- 不得只返回 6 张好看的假论文卡而不调用 API。
- 不得以浏览器 `alert()` 代替正式错误/确认 UI。
- 不得用 screenshot/canvas 伪装可搜索、可翻译的 HTML 论文。
- 不得为了视觉“沉浸感”隐藏所有工具，让 PDF/HTML 切换困难。
- 不得用任意第三方 CDN 引入与隐私/离线目标冲突的资源；静态字体图标尽量随应用打包。
