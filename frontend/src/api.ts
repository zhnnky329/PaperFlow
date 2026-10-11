export type Label = {
  id: string;
  name: string;
  paper_count?: number;
  finder_path?: string;
};
export type Job = {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "canceled";
  progress_stage: string;
  error_message: string | null;
  attempt: number;
};
export type Paper = {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  abstract: string;
  source_url: string | null;
  arxiv_id: string | null;
  arxiv_version: number;
  official_html_url: string | null;
  has_pdf: boolean;
  has_html: boolean;
  read_status: "unread" | "reading" | "finished";
  metadata_status: string;
  doi: string | null;
  venue: string | null;
  venue_kind: "journal" | "conference" | null;
  affiliations: { name: string; authors: string[] }[];
  metadata_sources: Record<string, string>;
  metadata_candidates: MetadataCandidate[];
  metadata_error: string | null;
  publication_sources: {
    kind: "journal" | "conference" | "publication" | "arxiv";
    label: string;
    url: string | null;
  }[];
  created_at: string;
  updated_at: string;
  last_read_at: string | null;
  tags: Label[];
  collections: Label[];
  conversion: Job | null;
};
export type MetadataCandidate = {
  doi: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  venue_kind: "journal" | "conference" | null;
  affiliations: Paper["affiliations"];
};
export type Settings = {
  theme: "system" | "light" | "dark";
  font_scale: number;
  reader_width: number;
  marker_mode: "fast" | "balanced";
  auto_convert_on_import: boolean;
  marker_available: boolean;
  data_dir: string;
  folders_root: string;
  folder_sync: {
    status: "queued" | "running" | "succeeded" | "failed";
    error: string | null;
  };
};
export type Position = {
  pdf_page: number;
  pdf_scale: number;
  html_anchor: string;
  scroll_ratio: number;
};
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.method && options.method !== "GET")
    headers.set("X-PaperFlow", "1");
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch("/api/v1" + path, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error?.message || `请求失败 (${response.status})`);
  }
  return response.json();
}
export function preferredLink(p: Paper): string {
  return (
    p.official_html_url ||
    (p.has_html ? `/read/${p.id}/html` : `/papers/${p.id}/pdf`)
  );
}
export function statusLabel(status: Paper["read_status"]) {
  return { unread: "未读", reading: "阅读中", finished: "已读" }[status];
}
export function conversionLabel(job: Job) {
  if (job.status === "running") {
    return (
      {
        preparing: "准备转换…",
        converting: "正在生成 HTML…",
        publishing: "正在保存 HTML…",
      }[job.progress_stage] || "正在转换…"
    );
  }
  return {
    queued: "等待转换",
    succeeded: "HTML 已生成",
    failed: "转换失败",
    canceled: "转换已取消",
  }[job.status];
}
