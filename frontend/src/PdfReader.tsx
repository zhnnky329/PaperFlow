import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getDocument,
  GlobalWorkerOptions,
  TextLayer,
  type PDFDocumentProxy,
} from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { ArrowLeft, Minus, Plus } from "lucide-react";
import {
  api,
  conversionLabel,
  type Paper,
  type Position,
  type Settings,
} from "./api";
import { Button } from "./components/ui/button";
GlobalWorkerOptions.workerSrc = workerUrl;

function PdfPage({
  doc,
  page,
  scale,
}: {
  doc: PDFDocumentProxy;
  page: number;
  scale: number;
}) {
  const container = useRef<HTMLDivElement>(null),
    canvas = useRef<HTMLCanvasElement>(null),
    text = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false),
    [height, setHeight] = useState(842),
    [width, setWidth] = useState(595),
    [error, setError] = useState("");
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          setVisible(entry.isIntersecting);
        }
      },
      { rootMargin: "600px" },
    );
    if (container.current) {
      observer.observe(container.current);
    }
    return () => {
      observer.disconnect();
    };
  }, [page]);
  useEffect(() => {
    let canceled = false;
    let renderTask:
      | ReturnType<Awaited<ReturnType<PDFDocumentProxy["getPage"]>>["render"]>
      | undefined;
    let layer: TextLayer | undefined;
    if (!visible) return;
    (async () => {
      const pdfPage = await doc.getPage(page);
      if (canceled) return;
      const base = pdfPage.getViewport({ scale: 1 });
      const view = pdfPage.getViewport({ scale });
      setHeight(base.height);
      setWidth(base.width);
      const target = canvas.current;
      if (!target || !text.current) return;
      const ratio = Math.min(devicePixelRatio, 2);
      target.width = view.width * ratio;
      target.height = view.height * ratio;
      renderTask = pdfPage.render({
        canvas: target,
        viewport: view,
        transform: [ratio, 0, 0, ratio, 0, 0],
      });
      await renderTask.promise;
      if (canceled) return;
      text.current.replaceChildren();
      text.current.style.setProperty("--scale-factor", String(scale));
      layer = new TextLayer({
        textContentSource: await pdfPage.getTextContent(),
        container: text.current,
        viewport: view,
      });
      await layer.render();
    })().catch((e) => {
      if (!canceled) setError(String(e));
    });
    return () => {
      canceled = true;
      renderTask?.cancel();
      layer?.cancel();
      if (canvas.current) {
        canvas.current.width = 0;
        canvas.current.height = 0;
      }
      text.current?.replaceChildren();
    };
  }, [doc, page, scale, visible]);
  return (
    <div
      className="pdf-page"
      ref={container}
      data-page={page}
      style={{ width: width * scale, minHeight: height * scale }}
    >
      {error ? (
        <div role="alert">
          第 {page} 页渲染失败：{error}
        </div>
      ) : (
        <>
          <canvas
            ref={canvas}
            style={{ width: width * scale, height: height * scale }}
          />
          <div className="textLayer" ref={text} />
        </>
      )}
      <span className="page-label">{page}</span>
    </div>
  );
}

export function PdfReader() {
  const { id } = useParams();
  const [paper, setPaper] = useState<Paper | null>(null),
    [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1),
    [scale, setScale] = useState(1),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [ready, setReady] = useState(false);
  const restored = useRef(false),
    pageRef = useRef(1),
    scaleRef = useRef(1),
    timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const save = useCallback(() => {
    if (restored.current)
      api(`/papers/${id}/reading-position?mode=pdf`, {
        method: "PUT",
        keepalive: true,
        body: JSON.stringify({
          pdf_page: pageRef.current,
          pdf_scale: scaleRef.current,
        }),
      }).catch(() => setError("进度保存失败，请检查后端连接。"));
  }, [id]);
  const onVisible = useCallback(
    (next: number) => {
      if (!restored.current) return;
      pageRef.current = next;
      setPage(next);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(save, 700);
    },
    [save],
  );
  useEffect(() => {
    let frame = 0;
    const track = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (!restored.current) return;
        const pages = Array.from(
          document.querySelectorAll<HTMLElement>(".pdf-page"),
        );
        const active = pages.find((node) => {
          const rect = node.getBoundingClientRect();
          return rect.top <= 125 && rect.bottom > 125;
        });
        if (active) onVisible(Number(active.dataset.page));
      });
    };
    addEventListener("scroll", track, true);
    return () => {
      removeEventListener("scroll", track, true);
      cancelAnimationFrame(frame);
    };
  }, [onVisible]);
  const refresh = useCallback(
    () =>
      api<Paper>(`/papers/${id}`)
        .then(setPaper)
        .catch((e) => setError(e.message)),
    [id],
  );
  useEffect(() => {
    api<Settings>("/settings")
      .then((value) => {
        document.documentElement.dataset.theme = value.theme;
      })
      .catch(() => {});
  }, []);
  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 2500);
    return () => clearInterval(interval);
  }, [refresh]);
  useEffect(() => {
    if (!paper?.has_pdf) return;
    let canceled = false;
    const task = getDocument({
      url: `/api/v1/papers/${id}/pdf`,
      enableXfa: false,
    });
    restored.current = false;
    setReady(false);
    Promise.all([
      task.promise,
      api<Position>(`/papers/${id}/reading-position?mode=pdf`),
    ])
      .then(([pdf, position]) => {
        if (canceled) return;
        setDoc(pdf);
        const target = Math.min(position.pdf_page, pdf.numPages);
        setPage(target);
        pageRef.current = target;
        setScale(position.pdf_scale);
        scaleRef.current = position.pdf_scale;
        setTimeout(() => {
          document.querySelector(`[data-page="${target}"]`)?.scrollIntoView();
          restored.current = true;
          setReady(true);
          save();
        }, 250);
      })
      .catch((e) => setError(`PDF 加载失败：${e.message}。请刷新或重新导入。`));
    return () => {
      save();
      canceled = true;
      restored.current = false;
      task.destroy();
    };
  }, [id, paper?.has_pdf, save]);
  useEffect(() => {
    addEventListener("pagehide", save);
    return () => {
      removeEventListener("pagehide", save);
      if (timer.current) clearTimeout(timer.current);
    };
  }, [save]);
  function navigate(next: number) {
    if (!doc || !restored.current) return;
    next = Math.max(1, Math.min(next, doc.numPages));
    setPage(next);
    pageRef.current = next;
    document.querySelector(`[data-page="${next}"]`)?.scrollIntoView();
    save();
  }
  function zoom(value: number) {
    value = Math.max(0.25, Math.min(value, 4));
    setScale(value);
    scaleRef.current = value;
    save();
  }
  async function act(action: string) {
    setBusy(true);
    setError("");
    try {
      await api(`/papers/${id}/${action}`, { method: "POST", body: "{}" });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="pdf-reader">
      <header className="reader-toolbar">
        <Link to="/" aria-label="返回 Library">
          <ArrowLeft size={19} />
        </Link>
        <strong>{paper?.title || "加载论文…"}</strong>
        {paper && (
          <select
            aria-label="阅读状态"
            value={paper.read_status}
            onChange={(e) =>
              api<Paper>(`/papers/${id}`, {
                method: "PATCH",
                body: JSON.stringify({ read_status: e.target.value }),
              })
                .then(setPaper)
                .catch((e) => setError(e.message))
            }
          >
            <option value="unread">未读</option>
            <option value="reading">阅读中</option>
            <option value="finished">已读</option>
          </select>
        )}
        {paper?.has_html && <a href={`/read/${id}/html`}>Local HTML</a>}
        {paper?.official_html_url && (
          <a href={paper.official_html_url} target="_blank" rel="noreferrer">
            Official HTML ↗
          </a>
        )}
        {paper?.has_pdf && (
          <Button
            disabled={
              busy ||
              ["queued", "running"].includes(paper.conversion?.status || "")
            }
            onClick={() => act("conversions")}
          >
            Convert HTML
          </Button>
        )}
        {doc && (
          <div className="reader-controls" aria-label="PDF 阅读控制">
            <Button aria-label="上一页" onClick={() => navigate(page - 1)}>
              ‹
            </Button>
            <input
              aria-label="页码"
              disabled={!ready}
              type="number"
              min="1"
              max={doc.numPages}
              value={page}
              onChange={(e) => navigate(Number(e.target.value) || 1)}
            />
            <span>/ {doc.numPages}</span>
            <Button aria-label="下一页" onClick={() => navigate(page + 1)}>
              ›
            </Button>
            <Button aria-label="缩小" onClick={() => zoom(scale - 0.1)}>
              <Minus size={14} />
            </Button>
            <span>{Math.round(scale * 100)}%</span>
            <Button aria-label="放大" onClick={() => zoom(scale + 0.1)}>
              <Plus size={14} />
            </Button>
            <Button onClick={() => zoom((innerWidth - 80) / 595)}>
              适配宽度
            </Button>
          </div>
        )}
      </header>
      {error && (
        <div className="notice error" role="alert">
          {error}
          <Button onClick={() => location.reload()}>刷新重试</Button>
        </div>
      )}
      {paper?.conversion && paper.conversion.status !== "succeeded" && (
        <div className="conversion-strip">
          {conversionLabel(paper.conversion)} {paper.conversion.error_message}
        </div>
      )}
      {paper && !paper.has_pdf ? (
        <div className="empty">
          <h2>这篇论文尚未缓存 PDF</h2>
          <p>arXiv 条目仍保存在 Library，下载后可离线阅读。</p>
          <Button disabled={busy} onClick={() => act("download-pdf")}>
            {busy ? "下载中…" : "Download PDF"}
          </Button>
        </div>
      ) : !doc ? (
        <div className="empty">正在加载原始 PDF…</div>
      ) : (
        <div className="pdf-pages">
          {Array.from({ length: doc.numPages }, (_, i) => (
            <PdfPage key={i} doc={doc} page={i + 1} scale={scale} />
          ))}
        </div>
      )}
    </div>
  );
}
