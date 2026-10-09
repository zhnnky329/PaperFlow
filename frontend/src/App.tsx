import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  BookOpen,
  Plus,
  Search,
  Settings as SettingsIcon,
  Folder,
  FileText,
  Upload,
  MoreHorizontal,
  ArrowUpRight,
  Library as LibraryIcon,
  X,
} from "lucide-react";
import {
  api,
  preferredLink,
  statusLabel,
  conversionLabel,
  type Paper,
  type Settings,
  type Label,
} from "./api";
import { Button } from "./components/ui/button";
import { Modal } from "./components/Modal";

const message = (error: unknown) =>
  error instanceof Error ? error.message : "操作失败，请重试";
export function App({ settingsPage = false }: { settingsPage?: boolean }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const collection = searchParams.get("folder") || "";
  function setCollection(value: string) {
    setSearchParams(value ? { folder: value } : {});
  }
  const [papers, setPapers] = useState<Paper[]>([]),
    [total, setTotal] = useState(0),
    [collections, setCollections] = useState<Label[]>([]),
    [tags, setTags] = useState<Label[]>([]);
  const [config, setConfig] = useState<Settings | null>(null),
    [query, setQuery] = useState(""),
    [debounced, setDebounced] = useState(""),
    [status, setStatus] = useState(""),
    [tag, setTag] = useState(""),
    [sort, setSort] = useState("recent"),
    [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [add, setAdd] = useState(false),
    [tab, setTab] = useState("pdf"),
    [arxiv, setArxiv] = useState("");
  const [importFolder, setImportFolder] = useState("");
  const [organize, setOrganize] = useState<Paper | null>(null);
  const [selectedFolders, setSelectedFolders] = useState<string[]>([]);
  const [deleteFolder, setDeleteFolder] = useState(false);
  const [edit, setEdit] = useState<Paper | null>(null),
    [remove, setRemove] = useState<Paper | null>(null),
    [taxonomy, setTaxonomy] = useState<{
      kind: "tags" | "collections";
      item?: Label;
    } | null>(null);
  const [revision, setRevision] = useState(0),
    [name, setName] = useState("");
  const input = useRef<HTMLInputElement>(null),
    fileInput = useRef<HTMLInputElement>(null);
  function reload() {
    setRevision((v) => v + 1);
  }
  useEffect(() => {
    const t = setTimeout(() => {
      setDebounced(query);
      setPage(1);
    }, 250);
    return () => clearTimeout(t);
  }, [query]);
  useEffect(() => {
    api<Settings>("/settings")
      .then(setConfig)
      .catch((e) => setError(message(e)));
  }, []);
  useEffect(() => {
    if (config) document.documentElement.dataset.theme = config.theme;
  }, [config]);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).matches("input,textarea,select")) return;
      if (e.key === "/") {
        e.preventDefault();
        input.current?.focus();
      }
      if (e.key === "Escape") {
        setAdd(false);
        setEdit(null);
        setRemove(null);
      }
    };
    addEventListener("keydown", handler);
    return () => removeEventListener("keydown", handler);
  }, []);
  useEffect(() => {
    let alive = true;
    async function fetchLibrary() {
      try {
        const params = new URLSearchParams({
          q: debounced,
          sort,
          page: String(page),
          page_size: "30",
        });
        if (status) params.set("status", status);
        if (collection === "unfiled") params.set("unfiled", "true");
        else if (collection) params.set("collection", collection);
        if (tag) params.set("tag", tag);
        const [result, groups, labels, preferences] = await Promise.all([
          api<{ items: Paper[]; total: number }>("/papers?" + params),
          api<Label[]>("/collections"),
          api<Label[]>("/tags"),
          api<Settings>("/settings"),
        ]);
        if (alive) {
          setPapers(result.items);
          setTotal(result.total);
          setCollections(groups);
          setConfig((prev) =>
            JSON.stringify(prev) === JSON.stringify(preferences)
              ? prev
              : preferences,
          );
          setTags(labels);
          setLoading(false);
        }
      } catch (e) {
        if (alive) {
          setError(message(e));
          setLoading(false);
        }
      }
    }
    fetchLibrary();
    const interval = setInterval(fetchLibrary, 2500);
    return () => {
      alive = false;
      clearInterval(interval);
    };
  }, [debounced, status, collection, tag, sort, page, revision]);
  async function action(operation: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await operation();
      reload();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function uploadFiles(files: FileList | null) {
    if (!files) return;
    setBusy(true);
    setError("");
    setNotice("");
    const results: string[] = [];
    for (const file of Array.from(files)) {
      try {
        const data = new FormData();
        data.set("file", file);
        const result = await api<{ paper: Paper; dedupe: boolean }>(
          "/papers/upload",
          { method: "POST", body: data },
        );
        try {
          await fileIntoFolder(result.paper);
        } catch (e) {
          results.push(`${file.name}：已保留论文，但归类失败：${message(e)}`);
          continue;
        }
        results.push(
          `${file.name}：${result.dedupe ? "已存在，未重复创建" : "导入成功"}`,
        );
      } catch (e) {
        results.push(`${file.name}：${message(e)}`);
      }
    }
    setNotice(results.join("\n"));
    setBusy(false);
    reload();
    if (fileInput.current) fileInput.current.value = "";
  }
  async function importArxiv() {
    await action(async () => {
      const result = await api<{ paper: Paper; dedupe: boolean }>(
        "/papers/arxiv",
        { method: "POST", body: JSON.stringify({ input: arxiv }) },
      );
      await fileIntoFolder(result.paper);
      setNotice(
        result.dedupe
          ? `已存在：${result.paper.title}`
          : "已保存 arXiv 条目；正在后台获取元信息和验证官方 HTML。网络失败可稍后重试。",
      );
      setArxiv("");
    });
  }
  function startImport() {
    setImportFolder(collection === "unfiled" ? "" : collection);
    setNotice("");
    setAdd(true);
  }
  async function fileIntoFolder(paper: Paper) {
    if (!importFolder) return;
    const folder = collections.find((c) => c.id === importFolder);
    if (!folder) throw new Error("目标文件夹已不存在，请重新选择");
    await api(`/papers/${paper.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        collections: [
          ...new Set([...paper.collections.map((c) => c.name), folder.name]),
        ],
      }),
    });
  }
  function organizePaper(paper: Paper) {
    setSelectedFolders(paper.collections.map((c) => c.id));
    setOrganize(paper);
  }
  function open(paper: Paper) {
    if (paper.official_html_url)
      action(() =>
        api(`/papers/${paper.id}/open-official`, { method: "POST" }),
      );
  }
  function editTaxonomy(kind: "collections" | "tags", item?: Label) {
    setTaxonomy({ kind, item });
    setName(item?.name || "");
    setDeleteFolder(false);
  }
  const heading = settingsPage
    ? "Settings"
    : collection
      ? collection === "unfiled"
        ? "未分类"
        : collections.find((c) => c.id === collection)?.name || "文件夹"
      : status
        ? { unread: "未读", reading: "阅读中", finished: "已读" }[status]
        : "Library";
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" to="/">
          <span className="brand-mark">
            <BookOpen size={19} />
          </span>
          PaperFlow
        </Link>
        <div className="local-badge">
          <span />
          Local workspace
        </div>
        <nav>
          <Link
            className={
              !settingsPage && !status && !collection
                ? "nav-item active"
                : "nav-item"
            }
            to="/"
            onClick={() => {
              setStatus("");
              setPage(1);
            }}
          >
            <LibraryIcon size={16} />
            All papers
          </Link>
          {(["unread", "reading", "finished"] as const).map((s) => (
            <Link
              className={
                !settingsPage && status === s ? "nav-item active" : "nav-item"
              }
              to="/"
              key={s}
              onClick={() => {
                setStatus(s);
                setPage(1);
              }}
            >
              <span className={"status-dot " + s} />
              {statusLabel(s)}
            </Link>
          ))}
          <div className="nav-caption">
            <span>文件夹</span>
            <Button
              variant="ghost"
              aria-label="新建文件夹"
              onClick={() => editTaxonomy("collections")}
            >
              <Plus size={14} />
            </Button>
          </div>
          <Link
            to="/?folder=unfiled"
            className={
              collection === "unfiled" && !settingsPage
                ? "nav-item active"
                : "nav-item"
            }
            onClick={() => {
              setStatus("");
              setPage(1);
            }}
          >
            <Folder size={15} />
            未分类
          </Link>
          {collections.map((c) => (
            <div className="taxonomy-row" key={c.id}>
              <Link
                to={`/?folder=${c.id}`}
                className={
                  !settingsPage && collection === c.id
                    ? "nav-item active"
                    : "nav-item"
                }
                onClick={() => {
                  setStatus("");
                  setQuery("");
                  setTag("");
                  setPage(1);
                }}
              >
                <Folder size={15} />
                {c.name}
                <span className="folder-count">{c.paper_count ?? 0}</span>
              </Link>
              <Button
                variant="ghost"
                aria-label={`管理文件夹 ${c.name}`}
                onClick={() => editTaxonomy("collections", c)}
              >
                <MoreHorizontal size={14} />
              </Button>
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <Link
            to="/settings"
            className={settingsPage ? "nav-item active" : "nav-item"}
          >
            <SettingsIcon size={16} />
            Settings
          </Link>
        </div>
      </aside>
      <main className="workspace">
        <header className="workspace-header">
          <div>
            <h1>
              {heading}
              {!settingsPage && <span className="count">{total}</span>}
            </h1>
            <p className="workspace-description">
              {settingsPage
                ? "让工作台适合你的阅读习惯。"
                : collection && collection !== "unfiled"
                  ? "按你的分类整理论文，同步到 Finder 文件夹。"
                  : "整理文献，继续阅读。"}
              {!settingsPage && collection && collection !== "unfiled" && (
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() =>
                    action(() =>
                      api(`/collections/${collection}/reveal`, {
                        method: "POST",
                      }),
                    )
                  }
                >
                  <Folder size={14} />在 Finder 中打开
                </Button>
              )}
            </p>
          </div>
          {!settingsPage && (
            <Button variant="default" onClick={startImport}>
              <Plus size={16} />
              Add Paper
            </Button>
          )}
        </header>
        {error && (
          <div className="notice error" role="alert">
            {error}
            <Button
              onClick={() => {
                setError("");
                reload();
              }}
            >
              重试
            </Button>
            <Button
              aria-label="关闭错误"
              variant="ghost"
              onClick={() => setError("")}
            >
              <X size={15} />
            </Button>
          </div>
        )}
        {notice && !add && (
          <div className="notice" role="status">
            {notice}
            <Button
              aria-label="关闭提示"
              variant="ghost"
              onClick={() => setNotice("")}
            >
              <X size={15} />
            </Button>
          </div>
        )}
        {settingsPage ? (
          <section className="settings-content">
            {config ? (
              <>
                <section className="settings-section">
                  <h2>Appearance</h2>
                  <p>跟随你的 macOS 偏好，让阅读保持舒适。</p>
                  <label>
                    主题
                    <select
                      aria-label="主题"
                      value={config.theme}
                      onChange={(e) =>
                        action(async () => {
                          const theme = e.target.value as Settings["theme"];
                          await api("/settings", {
                            method: "PATCH",
                            body: JSON.stringify({ theme }),
                          });
                          setConfig({ ...config, theme });
                        })
                      }
                    >
                      <option value="system">System</option>
                      <option value="light">Light</option>
                      <option value="dark">Dark</option>
                    </select>
                  </label>
                  <label>
                    HTML 字号
                    <select
                      value={config.font_scale}
                      onChange={(e) =>
                        action(async () => {
                          const font_scale = Number(e.target.value);
                          await api("/settings", {
                            method: "PATCH",
                            body: JSON.stringify({ font_scale }),
                          });
                          setConfig({ ...config, font_scale });
                        })
                      }
                    >
                      {[14, 17, 19, 21, 24].map((n) => (
                        <option key={n} value={n}>
                          {n}px
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    正文宽度
                    <select
                      value={config.reader_width}
                      onChange={(e) =>
                        action(async () => {
                          const reader_width = Number(e.target.value);
                          await api("/settings", {
                            method: "PATCH",
                            body: JSON.stringify({ reader_width }),
                          });
                          setConfig({ ...config, reader_width });
                        })
                      }
                    >
                      {[680, 780, 920].map((n) => (
                        <option key={n} value={n}>
                          {n}px
                        </option>
                      ))}
                    </select>
                  </label>
                </section>
                <section className="settings-section">
                  <h2>Conversion</h2>
                  <p>一次转换一篇论文，PDF 阅读始终可用。</p>
                  <div className="setting-line">
                    Marker CLI{" "}
                    <span className="format">
                      {config.marker_available
                        ? "已检测到"
                        : "未安装 / 路径未配置"}
                    </span>
                  </div>
                  <label>
                    模式
                    <select
                      value={config.marker_mode}
                      onChange={(e) =>
                        action(async () => {
                          const marker_mode = e.target
                            .value as Settings["marker_mode"];
                          await api("/settings", {
                            method: "PATCH",
                            body: JSON.stringify({ marker_mode }),
                          });
                          setConfig({ ...config, marker_mode });
                        })
                      }
                    >
                      <option value="fast">Fast · Apple Silicon 默认</option>
                      <option value="balanced">Balanced · 更高资源消耗</option>
                    </select>
                  </label>
                  <label>
                    导入后自动转换
                    <input
                      type="checkbox"
                      checked={config.auto_convert_on_import}
                      onChange={(e) =>
                        action(async () => {
                          const auto_convert_on_import = e.target.checked;
                          await api("/settings", {
                            method: "PATCH",
                            body: JSON.stringify({ auto_convert_on_import }),
                          });
                          setConfig({ ...config, auto_convert_on_import });
                        })
                      }
                    />
                  </label>
                  <p>
                    首次转换需下载模型；Marker 2.x 的公式/OCR 还需要
                    llama-server。CLI 路径通过 .env 的
                    PAPERFLOW_MARKER_EXECUTABLE 配置，重启生效。
                  </p>
                </section>
                <section className="settings-section">
                  <h2>Translation</h2>
                  <p>
                    在 Chrome 中使用已安装的 Read Frog，将 DeepSeek
                    密钥配置在扩展内。打开 Local HTML
                    后，用扩展的页面或段落翻译入口启用双语。翻译可能产生 API
                    费用。
                  </p>
                  <a
                    href="https://www.readfrog.app/en/docs/local-files"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Read Frog localhost 设置指南 <ArrowUpRight size={14} />
                  </a>
                  <p>插件译文由扩展管理。当前兼容性 Gate 待人工验证。</p>
                </section>
                <section className="settings-section">
                  <h2>Storage & recovery</h2>
                  <p className="storage-path">{config.data_dir}</p>
                  <h3>Finder 文件夹</h3>
                  <p className="storage-path">{config.folders_root}</p>
                  <p>
                    应用内文件夹自动同步为这里的同名目录，保存独立 PDF
                    副本。Finder
                    中新增、移动或改名的文件不会反向导入；修改过的副本及额外文件会保留。
                  </p>
                  <p>
                    PDF 会复制至这个目录。停止应用后运行 make backup；恢复用
                    scripts/backup.py 的 restore 子命令。先验证备份，再升级。
                  </p>
                </section>
              </>
            ) : (
              <p>正在加载设置…</p>
            )}
          </section>
        ) : (
          <>
            {config?.folder_sync?.status === "failed" && (
              <div className="notice error" role="alert">
                {config.folder_sync.error}
                <Button
                  disabled={busy}
                  onClick={() =>
                    action(() => api("/collections/sync", { method: "POST" }))
                  }
                >
                  重试 Finder 同步
                </Button>
              </div>
            )}
            {!collection && !query && !status && !tag && (
              <section className="folder-section" aria-label="我的文件夹">
                <div className="folder-section-heading">
                  <h2>我的文件夹</h2>
                  <Button
                    variant="ghost"
                    onClick={() => editTaxonomy("collections")}
                  >
                    <Plus size={14} />
                    新建文件夹
                  </Button>
                </div>
                {collections.length ? (
                  <div className="folder-grid">
                    {collections.map((c) => (
                      <Link
                        className="folder-card"
                        key={c.id}
                        to={`/?folder=${c.id}`}
                      >
                        <Folder size={25} />
                        <strong>{c.name}</strong>
                        <span>{c.paper_count ?? 0} 篇论文</span>
                      </Link>
                    ))}
                  </div>
                ) : (
                  <p className="muted">
                    创建自己的分类，例如 SLAM、路径规划或待读文献。
                  </p>
                )}
              </section>
            )}
            <div className="library-toolbar">
              <div className="search-box">
                <Search size={16} />
                <input
                  ref={input}
                  aria-label="搜索论文"
                  placeholder="搜索标题、作者、arXiv 或标签…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
                {query ? (
                  <Button
                    variant="ghost"
                    aria-label="清空搜索"
                    onClick={() => setQuery("")}
                  >
                    <X size={14} />
                  </Button>
                ) : (
                  <kbd>/</kbd>
                )}
              </div>
              <select
                aria-label="标签筛选"
                value={tag}
                onChange={(e) => {
                  setTag(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All tags</option>
                {tags.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
              <select
                aria-label="排序"
                value={sort}
                onChange={(e) => {
                  setSort(e.target.value);
                  setPage(1);
                }}
              >
                <option value="recent">最近添加</option>
                <option value="read">最近阅读</option>
                <option value="year">发表年份</option>
                <option value="title">标题</option>
              </select>
              <Button variant="ghost" onClick={() => editTaxonomy("tags")}>
                管理标签
              </Button>
            </div>
            {loading ? (
              <div className="empty">正在读取本地 Library…</div>
            ) : papers.length === 0 ? (
              <div className="empty">
                <div className="empty-icon" aria-hidden="true">
                  <BookOpen size={32} />
                </div>
                <h2>
                  {query || status || tag
                    ? "没有匹配的论文"
                    : collection && collection !== "unfiled"
                      ? "这个文件夹还没有论文"
                      : collection === "unfiled"
                        ? "没有未分类的论文"
                        : "你的下一篇论文，从这里开始"}
                </h2>
                <p>
                  {query || status || tag
                    ? "调整搜索词或筛选条件。"
                    : collection && collection !== "unfiled"
                      ? "在这里导入 PDF，或从全部论文中选择论文放入这个文件夹。"
                      : collection === "unfiled"
                        ? "新论文可以直接导入指定文件夹，也可以稍后整理。"
                        : "拖入 PDF，或收藏 arXiv 链接。原文、分类与阅读进度都留在本机。"}
                </p>
                {query || status || tag ? (
                  <Button
                    onClick={() => {
                      setQuery("");
                      setStatus("");
                      setTag("");
                      setPage(1);
                    }}
                  >
                    清除筛选
                  </Button>
                ) : (
                  <Button variant="default" onClick={startImport}>
                    <Plus size={15} />
                    添加论文
                  </Button>
                )}
              </div>
            ) : (
              <div className="paper-list">
                {papers.map((p) => (
                  <article className="paper-row" key={p.id}>
                    <div className="paper-icon">
                      <FileText size={22} />
                    </div>
                    <div className="paper-info">
                      <a
                        className="paper-title"
                        href={preferredLink(p)}
                        target={p.official_html_url ? "_blank" : undefined}
                        rel="noreferrer"
                        onClick={() => open(p)}
                      >
                        {p.title}
                      </a>
                      <p>
                        {p.authors.length
                          ? p.authors.slice(0, 3).join(", ")
                          : "作者待补全"}
                        {p.authors.length > 3 ? " 等" : ""}{" "}
                        <span>{p.year || "年份待补全"}</span>
                        {p.arxiv_id && (
                          <span>
                            arXiv:{p.arxiv_id}
                            {p.arxiv_version ? `v${p.arxiv_version}` : ""}
                          </span>
                        )}
                      </p>
                      <div className="paper-meta">
                        {p.collections.map((c) => (
                          <Link
                            className="tag folder-tag"
                            key={c.id}
                            to={`/?folder=${c.id}`}
                          >
                            <Folder size={11} />
                            {c.name}
                          </Link>
                        ))}
                        <span className="format">
                          {p.official_html_url
                            ? "Official HTML ↗"
                            : p.has_html
                              ? "Local HTML"
                              : p.has_pdf
                                ? "PDF"
                                : "Remote only"}
                        </span>
                        {p.official_html_url && (
                          <span className="muted">外部页面，不记录滚动</span>
                        )}
                        {p.tags.map((t) => (
                          <span className="tag" key={t.id}>
                            {t.name}
                          </span>
                        ))}
                        {p.metadata_status === "pending" && (
                          <span className="muted">元信息获取中…</span>
                        )}
                        {p.metadata_status === "failed" && (
                          <Button
                            variant="ghost"
                            disabled={busy}
                            onClick={() =>
                              action(() =>
                                api(`/papers/${p.id}/fetch-metadata`, {
                                  method: "POST",
                                }),
                              )
                            }
                          >
                            重试元信息
                          </Button>
                        )}
                      </div>
                      {p.conversion && p.conversion.status !== "succeeded" && (
                        <div
                          className={
                            "job-state " +
                            (p.conversion.status === "failed" ? "failed" : "")
                          }
                        >
                          <span>{conversionLabel(p.conversion)}</span>
                          {p.conversion.error_message && (
                            <span>{p.conversion.error_message}</span>
                          )}
                          {["queued", "running"].includes(
                            p.conversion.status,
                          ) && (
                            <Button
                              disabled={busy}
                              variant="ghost"
                              onClick={() =>
                                action(() =>
                                  api(
                                    `/conversions/${p.conversion!.id}/cancel`,
                                    { method: "POST" },
                                  ),
                                )
                              }
                            >
                              取消
                            </Button>
                          )}
                          {["failed", "canceled"].includes(
                            p.conversion.status,
                          ) && (
                            <Button
                              disabled={busy}
                              variant="ghost"
                              onClick={() =>
                                action(() =>
                                  api(
                                    `/conversions/${p.conversion!.id}/retry`,
                                    { method: "POST" },
                                  ),
                                )
                              }
                            >
                              重试转换
                            </Button>
                          )}
                        </div>
                      )}
                    </div>
                    <div className="paper-actions">
                      <select
                        aria-label={`${p.title} 阅读状态`}
                        value={p.read_status}
                        onChange={(e) =>
                          action(() =>
                            api(`/papers/${p.id}`, {
                              method: "PATCH",
                              body: JSON.stringify({
                                read_status: e.target.value,
                              }),
                            }),
                          )
                        }
                      >
                        {(["unread", "reading", "finished"] as const).map(
                          (s) => (
                            <option value={s} key={s}>
                              {statusLabel(s)}
                            </option>
                          ),
                        )}
                      </select>
                      <div>
                        <Button
                          variant="ghost"
                          aria-label={`整理 ${p.title} 到文件夹`}
                          onClick={() => organizePaper(p)}
                        >
                          <Folder size={14} />
                          归类
                        </Button>
                        <Button asChild variant="ghost">
                          <Link to={`/papers/${p.id}/pdf`}>PDF</Link>
                        </Button>
                        {p.has_html && (
                          <Button asChild variant="ghost">
                            <a href={`/read/${p.id}/html`}>HTML</a>
                          </Button>
                        )}
                        {p.has_pdf &&
                          !["queued", "running"].includes(
                            p.conversion?.status || "",
                          ) && (
                            <Button
                              variant="ghost"
                              disabled={busy}
                              onClick={() =>
                                action(() =>
                                  api(`/papers/${p.id}/conversions`, {
                                    method: "POST",
                                    body: JSON.stringify({
                                      force_rebuild: p.has_html,
                                    }),
                                  }),
                                )
                              }
                            >
                              {p.has_html ? "重建 HTML" : "Convert"}
                            </Button>
                          )}
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      aria-label={`编辑 ${p.title}`}
                      onClick={() => setEdit(p)}
                    >
                      <MoreHorizontal size={18} />
                    </Button>
                  </article>
                ))}
              </div>
            )}
            {total > 30 && (
              <div className="pagination">
                <Button disabled={page === 1} onClick={() => setPage(page - 1)}>
                  上一页
                </Button>
                <span>
                  {page} / {Math.ceil(total / 30)}
                </span>
                <Button
                  disabled={page * 30 >= total}
                  onClick={() => setPage(page + 1)}
                >
                  下一页
                </Button>
              </div>
            )}
            <footer className="workspace-footer">
              <span>论文与阅读进度保存在本机</span>
              <span>
                {["queued", "running"].includes(
                  config?.folder_sync?.status || "",
                )
                  ? "正在同步 Finder 文件夹…"
                  : config?.marker_available
                    ? "Marker 已就绪"
                    : "Marker 未安装；可继续使用 Library 和 PDF"}
              </span>
            </footer>
          </>
        )}
      </main>
      {add && (
        <Modal
          title="Add Paper"
          description="导入原文，留住每一次阅读。"
          close={() => {
            if (!busy) setAdd(false);
          }}
        >
          <label className="field">
            存入文件夹
            <select
              aria-label="存入文件夹"
              disabled={busy}
              value={importFolder}
              onChange={(e) => setImportFolder(e.target.value)}
            >
              <option value="">未分类（稍后整理）</option>
              {collections.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <div className="tabs">
            <Button
              variant={tab === "pdf" ? "default" : "ghost"}
              aria-pressed={tab === "pdf"}
              onClick={() => setTab("pdf")}
            >
              PDF File
            </Button>
            <Button
              variant={tab === "arxiv" ? "default" : "ghost"}
              aria-pressed={tab === "arxiv"}
              onClick={() => setTab("arxiv")}
            >
              arXiv Link
            </Button>
          </div>
          {tab === "pdf" ? (
            <div
              className="drop-zone"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                if (!busy) uploadFiles(e.dataTransfer.files);
              }}
            >
              <Upload size={28} />
              <h3>将 PDF 拖到这里</h3>
              <p>支持多个 PDF。复制到本机数据目录，自动识别重复文件。</p>
              <input
                ref={fileInput}
                hidden
                aria-label="选择 PDF 文件"
                type="file"
                accept="application/pdf,.pdf"
                multiple
                disabled={busy}
                onChange={(e) => uploadFiles(e.target.files)}
              />
              <Button
                variant="default"
                disabled={busy}
                onClick={() => fileInput.current?.click()}
              >
                {busy ? "正在导入…" : "选择 PDF 文件"}
              </Button>
            </div>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                importArxiv();
              }}
            >
              <label className="field">
                arXiv URL / ID
                <input
                  autoFocus
                  value={arxiv}
                  onChange={(e) => setArxiv(e.target.value)}
                  placeholder="https://arxiv.org/abs/1706.03762"
                  required
                />
              </label>
              <p className="muted">
                支持论文链接或 ID。导入后自动获取标题、作者及可用的官方 HTML。
              </p>
              <Button variant="default" disabled={busy}>
                {busy ? "保存中…" : "导入 arXiv"}
              </Button>
            </form>
          )}
          {busy && <p role="status">正在导入，请稍候…</p>}
          {notice && (
            <div role="status" className="notice import-results">
              {notice}
              <p>关闭此窗口后可在 Library 打开新条目或已有条目。</p>
            </div>
          )}
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
        </Modal>
      )}
      {edit && (
        <Modal title="论文详情" close={() => setEdit(null)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const data = new FormData(e.currentTarget);
              action(async () => {
                await api(`/papers/${edit.id}`, {
                  method: "PATCH",
                  body: JSON.stringify({
                    title: data.get("title"),
                    authors: String(data.get("authors"))
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                    year: data.get("year") ? Number(data.get("year")) : null,
                    abstract: data.get("abstract"),
                    source_url: String(data.get("source_url")) || null,
                    tags: String(data.get("tags")).split(",").filter(Boolean),
                  }),
                });
                setEdit(null);
              });
            }}
          >
            <label className="field">
              标题
              <input name="title" required defaultValue={edit.title} />
            </label>
            <label className="field">
              作者（逗号分隔）
              <input name="authors" defaultValue={edit.authors.join(", ")} />
            </label>
            <label className="field">
              年份
              <input
                name="year"
                type="number"
                min="1500"
                max="2200"
                defaultValue={edit.year || ""}
              />
            </label>
            <label className="field">
              来源链接（HTTPS）
              <input
                name="source_url"
                type="url"
                defaultValue={edit.source_url || ""}
              />
            </label>
            <label className="field">
              摘要
              <textarea name="abstract" rows={4} defaultValue={edit.abstract} />
            </label>
            <label className="field">
              Tags（逗号分隔）
              <input
                name="tags"
                defaultValue={edit.tags.map((t) => t.name).join(", ")}
              />
            </label>
            <div className="detail-folders">
              <span>
                文件夹：
                {edit.collections.map((c) => c.name).join("、") || "未分类"}
              </span>
              <Button
                type="button"
                onClick={() => {
                  const paper = edit;
                  setEdit(null);
                  organizePaper(paper);
                }}
              >
                整理到文件夹
              </Button>
            </div>
            <div className="form-actions">
              <Button
                type="button"
                variant="destructive"
                onClick={() => {
                  setRemove(edit);
                  setEdit(null);
                }}
              >
                删除论文
              </Button>
              <Button variant="default" disabled={busy}>
                保存更改
              </Button>
            </div>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
          </form>
        </Modal>
      )}
      {remove && (
        <Modal title="删除这篇论文？" close={() => setRemove(null)}>
          <p>
            <strong>{remove.title}</strong>
          </p>
          <p>
            将删除此 Library 条目及 PaperFlow 数据目录中属于此条目的
            PDF、HTML、图片和阅读位置。你最初导入的原文件不会修改。
          </p>
          <div className="form-actions">
            <Button onClick={() => setRemove(null)}>取消</Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() =>
                action(async () => {
                  await api(`/papers/${remove.id}?confirm=true`, {
                    method: "DELETE",
                  });
                  setRemove(null);
                })
              }
            >
              确认删除条目和本地文件
            </Button>
          </div>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
        </Modal>
      )}
      {taxonomy && (
        <Modal
          title={
            taxonomy.kind === "collections"
              ? taxonomy.item
                ? "管理文件夹"
                : "新建文件夹"
              : "管理 Tag"
          }
          close={() => setTaxonomy(null)}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action(async () => {
                const saved = await api<Label>(
                  "/" +
                    taxonomy.kind +
                    (taxonomy.item ? "/" + taxonomy.item.id : ""),
                  {
                    method: taxonomy.item ? "PATCH" : "POST",
                    body: JSON.stringify({ name }),
                  },
                );
                if (taxonomy.kind === "collections" && !taxonomy.item)
                  setCollection(saved.id);
                setTaxonomy(null);
              });
            }}
          >
            <label className="field">
              名称
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={80}
              />
            </label>
            {taxonomy.kind === "collections" && (
              <p className="muted">
                同步到 Finder 中的同名目录。原始 PDF 保留在论文库中。
              </p>
            )}
            {deleteFolder && (
              <p className="error">
                仅清理这个分类及未修改的 PDF 副本。论文原文、其他文件夹及 Finder
                中额外文件保留。
              </p>
            )}
            <div className="form-actions">
              {taxonomy.item && (
                <Button
                  type="button"
                  variant="destructive"
                  disabled={busy}
                  onClick={() =>
                    !deleteFolder
                      ? setDeleteFolder(true)
                      : action(async () => {
                          await api(
                            "/" + taxonomy.kind + "/" + taxonomy.item!.id,
                            {
                              method: "DELETE",
                            },
                          );
                          setTaxonomy(null);
                          setCollection("");
                          setTag("");
                        })
                  }
                >
                  {deleteFolder
                    ? taxonomy.kind === "collections"
                      ? "确认删除文件夹（保留论文）"
                      : "确认删除标签"
                    : taxonomy.kind === "collections"
                      ? "删除文件夹（保留论文）"
                      : "删除标签"}
                </Button>
              )}
              <Button variant="default" disabled={busy}>
                保存
              </Button>
            </div>
          </form>
          {taxonomy.kind === "tags" && !taxonomy.item && (
            <div className="tag-management">
              {tags.map((t) => (
                <Button
                  key={t.id}
                  onClick={() => {
                    setTaxonomy({ ...taxonomy, item: t });
                    setName(t.name);
                  }}
                >
                  {t.name}
                </Button>
              ))}
            </div>
          )}
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
        </Modal>
      )}
      {organize && (
        <Modal
          title="整理到文件夹"
          description={organize.title}
          close={() => setOrganize(null)}
        >
          <p className="muted">
            选择要存放的文件夹，可同时放入多个。取消全部勾选后归入未分类。
          </p>
          <div className="folder-picker">
            {collections.map((c) => (
              <label key={c.id}>
                <input
                  type="checkbox"
                  checked={selectedFolders.includes(c.id)}
                  onChange={(e) =>
                    setSelectedFolders((current) =>
                      e.target.checked
                        ? [...current, c.id]
                        : current.filter((id) => id !== c.id),
                    )
                  }
                />
                <Folder size={16} />
                <span>{c.name}</span>
              </label>
            ))}
            {!collections.length && <p>先在侧栏创建一个文件夹，再整理论文。</p>}
          </div>
          <div className="form-actions">
            <Button onClick={() => setOrganize(null)}>取消</Button>
            <Button
              variant="default"
              disabled={busy}
              onClick={() =>
                action(async () => {
                  await api(`/papers/${organize.id}`, {
                    method: "PATCH",
                    body: JSON.stringify({
                      collections: collections
                        .filter((c) => selectedFolders.includes(c.id))
                        .map((c) => c.name),
                    }),
                  });
                  setOrganize(null);
                })
              }
            >
              保存归类
            </Button>
          </div>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </Modal>
      )}
    </div>
  );
}
