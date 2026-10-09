import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
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
  type Paper,
  type Settings,
  type Label,
} from "./api";
import { Button } from "./components/ui/button";
import { Modal } from "./components/Modal";

const message = (error: unknown) =>
  error instanceof Error ? error.message : "操作失败，请重试";
export function App({ settingsPage = false }: { settingsPage?: boolean }) {
  const [papers, setPapers] = useState<Paper[]>([]),
    [total, setTotal] = useState(0),
    [collections, setCollections] = useState<Label[]>([]),
    [tags, setTags] = useState<Label[]>([]);
  const [config, setConfig] = useState<Settings | null>(null),
    [query, setQuery] = useState(""),
    [debounced, setDebounced] = useState(""),
    [status, setStatus] = useState(""),
    [collection, setCollection] = useState(""),
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
        if (collection) params.set("collection", collection);
        if (tag) params.set("tag", tag);
        const [result, groups, labels] = await Promise.all([
          api<{ items: Paper[]; total: number }>("/papers?" + params),
          api<Label[]>("/collections"),
          api<Label[]>("/tags"),
        ]);
        if (alive) {
          setPapers(result.items);
          setTotal(result.total);
          setCollections(groups);
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
      setNotice(
        result.dedupe
          ? `已存在：${result.paper.title}`
          : "已保存 arXiv 条目；正在后台获取元信息和验证官方 HTML。网络失败可稍后重试。",
      );
      setArxiv("");
    });
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
  }
  const heading = settingsPage
    ? "Settings"
    : collection
      ? collections.find((c) => c.id === collection)?.name || "Collection"
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
              setCollection("");
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
                setCollection("");
                setPage(1);
              }}
            >
              <span className={"status-dot " + s} />
              {statusLabel(s)}
            </Link>
          ))}
          <div className="nav-caption">
            <span>Collections</span>
            <Button
              variant="ghost"
              aria-label="新建集合"
              onClick={() => editTaxonomy("collections")}
            >
              <Plus size={14} />
            </Button>
          </div>
          {collections.length === 0 && (
            <p className="sidebar-hint">按研究主题整理你的论文</p>
          )}
          {collections.map((c) => (
            <div className="taxonomy-row" key={c.id}>
              <Link
                to="/"
                className={
                  !settingsPage && collection === c.id
                    ? "nav-item active"
                    : "nav-item"
                }
                onClick={() => {
                  setCollection(c.id);
                  setStatus("");
                  setPage(1);
                }}
              >
                <Folder size={15} />
                {c.name}
              </Link>
              <Button
                variant="ghost"
                aria-label={`管理集合 ${c.name}`}
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
          <p>论文与阅读进度保存在本机</p>
        </div>
      </aside>
      <main className="workspace">
        <header className="workspace-header">
          <div>
            <span className="breadcrumb">个人论文库</span>
            <h1>
              {heading}
              {!settingsPage && <span className="count">{total}</span>}
            </h1>
          </div>
          {!settingsPage && (
            <Button
              variant="default"
              onClick={() => {
                setAdd(true);
                setNotice("");
              }}
            >
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
                <div className="empty-icon">
                  <BookOpen size={32} />
                </div>
                <h2>
                  {query || status || tag || collection
                    ? "没有匹配的论文"
                    : "你的下一篇论文，从这里开始"}
                </h2>
                <p>
                  {query || status || tag || collection
                    ? "调整搜索词或筛选条件。"
                    : "拖入 PDF，或收藏 arXiv 链接。原文、分类与阅读进度都留在本机。"}
                </p>
                <Button variant="default" onClick={() => setAdd(true)}>
                  <Plus size={15} />
                  添加论文
                </Button>
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
                      {p.conversion && (
                        <div
                          className={
                            "job-state " +
                            (p.conversion.status === "failed" ? "failed" : "")
                          }
                        >
                          <span>
                            HTML {p.conversion.status}{" "}
                            {["running", "queued"].includes(p.conversion.status)
                              ? `· ${p.conversion.progress_stage}`
                              : ""}
                          </span>
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
              <span>Local-first · SQLite</span>
              <span>
                {config?.marker_available
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
          close={() => {
            if (!busy) setAdd(false);
          }}
        >
          <div className="tabs">
            <Button
              variant={tab === "pdf" ? "default" : "ghost"}
              onClick={() => setTab("pdf")}
            >
              PDF File
            </Button>
            <Button
              variant={tab === "arxiv" ? "default" : "ghost"}
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
                aria-label="选择 PDF 文件"
                type="file"
                accept="application/pdf,.pdf"
                multiple
                disabled={busy}
                onChange={(e) => uploadFiles(e.target.files)}
              />
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
                先保存条目，后台获取元信息；只有验证真实存在才提供官方 HTML。
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
                    collections: String(data.get("collections"))
                      .split(",")
                      .filter(Boolean),
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
            <label className="field">
              Collections（逗号分隔）
              <input
                name="collections"
                defaultValue={edit.collections.map((c) => c.name).join(", ")}
              />
            </label>
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
            taxonomy.kind === "collections" ? "管理 Collection" : "管理 Tag"
          }
          close={() => setTaxonomy(null)}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action(async () => {
                await api(
                  "/" +
                    taxonomy.kind +
                    (taxonomy.item ? "/" + taxonomy.item.id : ""),
                  {
                    method: taxonomy.item ? "PATCH" : "POST",
                    body: JSON.stringify({ name }),
                  },
                );
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
            <div className="form-actions">
              {taxonomy.item && (
                <Button
                  type="button"
                  variant="destructive"
                  disabled={busy}
                  onClick={() =>
                    action(async () => {
                      await api("/" + taxonomy.kind + "/" + taxonomy.item!.id, {
                        method: "DELETE",
                      });
                      setTaxonomy(null);
                      setCollection("");
                      setTag("");
                    })
                  }
                >
                  删除分类（保留论文）
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
    </div>
  );
}
