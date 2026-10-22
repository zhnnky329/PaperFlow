import type { DiscoveryPaper, DiscoveryRun } from "./api";

export type DiscoveryView =
  | "recommended"
  | "latest"
  | "history"
  | "interested"
  | "dismissed";

export function discoveryQuery(filters: {
  view: DiscoveryView;
  sort: string;
  interest: string;
  minScore: string;
  page: number;
}) {
  const params = new URLSearchParams({
    view: filters.view,
    sort: filters.sort,
    page: String(filters.page),
    page_size: "20",
  });
  if (filters.interest) params.set("interest_id", filters.interest);
  if (filters.minScore !== "") params.set("min_score", filters.minScore);
  return params.toString();
}

export function discoveryBasis(
  basis: NonNullable<DiscoveryPaper["analysis"]>["basis"],
) {
  return {
    full_text: "基于全文",
    partial_text: "基于部分正文",
    abstract: "仅基于摘要判断",
  }[basis];
}

export function discoveryStage(run: DiscoveryRun) {
  if (run.status === "queued") return "等待检查";
  if (run.status === "failed") return "检查失败";
  if (run.status === "succeeded") return "检查完成";
  return (
    {
      fetching: "正在检索 arXiv…",
      screening: "正在初筛候选论文…",
      filtering: "正在初筛候选论文…",
      analyzing: "正在阅读并分析论文…",
      reading: "正在获取论文正文…",
      preparing: "正在准备检查…",
    }[run.stage] || "正在检查新论文…"
  );
}

export function discoveryDate(value: string | null, time = true) {
  if (!value) return "尚未检查";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    ...(time ? ({ hour: "2-digit", minute: "2-digit" } as const) : {}),
  }).format(date);
}

export function splitDiscoveryKeywords(value: string) {
  return [
    ...new Set(
      value
        .split(/[,，\n]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ];
}
