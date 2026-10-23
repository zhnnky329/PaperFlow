export type Label = {
  id: string;
  name: string;
  paper_count?: number;
  folder_path?: string;
  parent_id?: string | null;
  path?: string;
  depth?: number;
};
export type Job = {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "canceled";
  progress_stage: string;
  error_message: string | null;
  attempt: number;
  execution_target?: "local" | "ubuntu";
  cancel_requested?: boolean;
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
  sync_enabled: boolean;
  remote_conversion_available: boolean;
  theme: "system" | "light" | "dark";
  font_scale: number;
  reader_width: number;
  marker_mode: "fast" | "balanced";
  auto_convert_on_import: boolean;
  marker_available: boolean;
  marker_device: "cpu" | "cuda";
  marker_backend: "llamacpp";
  llama_available: boolean;
  folder_open_available: boolean;
  data_dir: string;
  folders_root: string;
  folder_sync: {
    status: "queued" | "running" | "succeeded" | "failed";
    error: string | null;
  };
};
export type Position = {
  revision?: string;
  pdf_page: number;
  pdf_scale: number;
  html_anchor: string;
  scroll_ratio: number;
};
export type DiscoveryInterest = {
  id: string;
  name: string;
  description: string;
  keywords: string[];
  exclude_keywords: string[];
  priority: 1 | 2 | 3;
};
export type DiscoverySettings = {
  auto_update: boolean;
  interval_hours: number;
  min_score: number;
  max_analyses: number;
  try_full_text: boolean;
  ai_enabled: boolean;
  model: string;
  token_budget: number;
  max_output_tokens: number;
  interest_description: string;
  interests: DiscoveryInterest[];
  api_key_configured: boolean;
  api_key_source: "environment" | "local" | null;
};
export type DiscoveryRun = {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  trigger: string;
  stage: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  fetched_count: number;
  new_count: number;
  analyzed_count: number;
  recommended_count: number;
  tokens_used: number;
  tokens_reserved: number;
  error_code: string | null;
  error_message: string | null;
};
export type DiscoveryStatus = {
  active_run: DiscoveryRun | null;
  last_run: DiscoveryRun | null;
  last_checked_at: string | null;
  next_check_at: string | null;
  new_count: number;
  pending_count: number;
  key_configured: boolean;
  usage: { tokens_used: number; tokens_reserved: number };
  online: boolean;
};
export type DiscoveryPaper = {
  id: string;
  arxiv_id: string;
  arxiv_version: number;
  doi: string | null;
  title: string;
  authors: string[];
  abstract: string;
  categories: string[];
  published_at: string;
  updated_at: string;
  source_url: string;
  venue: string | null;
  first_seen_at: string;
  analysis_status: "pending" | "running" | "succeeded" | "failed" | "filtered";
  analysis: {
    decision: "recommend" | "skip";
    score: number;
    matched_directions: string[];
    reason: string;
    summary: string;
    basis: "full_text" | "partial_text" | "abstract";
    source_url: string;
    tokens_used: number;
  } | null;
  analyzed_at: string | null;
  analysis_error: string | null;
  feedback: "none" | "interested" | "later" | "dismissed";
  paper_id: string | null;
  is_new: boolean;
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
  const prefix = job.execution_target === "ubuntu" ? "Ubuntu · " : "";
  if (job.cancel_requested && ["queued", "running"].includes(job.status))
    return prefix + "等待确认取消…";
  if (job.progress_stage === "waiting_connection") return prefix + "等待设备连接…";
  if (job.progress_stage === "downloading") return prefix + "正在下载 HTML…";
  if (job.progress_stage === "superseded") return prefix + "转换完成，保留更新的 HTML";
  if (job.status === "running") {
    return (
      prefix + ({
        preparing: "准备转换…",
        converting: "正在生成 HTML…",
        publishing: "正在保存 HTML…",
      }[job.progress_stage] || "正在转换…")
    );
  }
  return prefix + {
    queued: "等待转换",
    succeeded: "HTML 已生成",
    failed: "转换失败",
    canceled: "转换已取消",
  }[job.status];
}
