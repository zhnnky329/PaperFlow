import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  Check,
  RefreshCw,
  SlidersHorizontal,
} from "lucide-react";
import {
  api,
  type DiscoveryPaper,
  type DiscoveryRun,
  type DiscoverySettings,
  type DiscoveryStatus,
  type Paper,
} from "./api";
import { Button } from "./components/ui/button";
import {
  discoveryBasis,
  discoveryDate,
  discoveryQuery,
  discoveryStage,
  type DiscoveryView,
} from "./discovery";

const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : "操作失败，请重试";

export function Discover({
  onNewCountChange,
}: {
  onNewCountChange: (count: number) => void;
}) {
  const [settings, setSettings] = useState<DiscoverySettings | null>(null);
  const [status, setStatus] = useState<DiscoveryStatus | null>(null);
  const [runs, setRuns] = useState<DiscoveryRun[]>([]);
  const [papers, setPapers] = useState<DiscoveryPaper[]>([]);
  const [total, setTotal] = useState(0);
  const [view, setView] = useState<DiscoveryView>("recommended");
  const [sort, setSort] = useState("score");
  const [interest, setInterest] = useState("");
  const [minScore, setMinScore] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [revision, setRevision] = useState(0);
  const [markedSeen, setMarkedSeen] = useState(false);
  const params = discoveryQuery({ view, sort, interest, minScore, page });

  useEffect(() => {
    api("/discovery/seen", { method: "POST" })
      .then(() => {
        onNewCountChange(0);
        setMarkedSeen(true);
      })
      .catch(() => setMarkedSeen(true));
  }, [onNewCountChange]);

  useEffect(() => {
    if (!markedSeen) return;
    let alive = true;
    setLoading(true);
    async function refresh() {
      try {
        const [result, preferences, current, history] = await Promise.all([
          api<{ items: DiscoveryPaper[]; total: number }>(
            "/discovery/papers?" + params,
          ),
          api<DiscoverySettings>("/discovery/settings"),
          api<DiscoveryStatus>("/discovery/status"),
          api<DiscoveryRun[]>("/discovery/runs"),
        ]);
        if (!alive) return;
        setPapers(result.items);
        setTotal(result.total);
        setSettings(preferences);
        setStatus(current);
        setRuns(history);
        onNewCountChange(current.new_count);
        setError("");
      } catch (error) {
        if (alive) setError(errorMessage(error));
      } finally {
        if (alive) setLoading(false);
      }
    }
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => {
      alive = false;
      clearInterval(interval);
    };
  }, [params, revision, onNewCountChange, markedSeen]);

  async function action(key: string, operation: () => Promise<void>) {
    setBusy(key);
    setError("");
    setNotice("");
    try {
      await operation();
      setRevision((value) => value + 1);
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setBusy("");
    }
  }

  async function check() {
    await action("check", async () => {
      const result = await api<{ run: DiscoveryRun; dedupe: boolean }>(
        "/discovery/check",
        { method: "POST" },
      );
      setNotice(
        result.dedupe
          ? "已有检查正在进行，将继续显示该任务。"
          : "已开始检查新论文，可以继续阅读 Library。所有候选保留在 Discover，加入文献库由你决定。",
      );
    });
  }

  async function retry(run: DiscoveryRun) {
    await action("retry", async () => {
      const result = await api<{ run: DiscoveryRun; dedupe: boolean }>(
        `/discovery/runs/${run.id}/retry`,
        { method: "POST" },
      );
      setNotice(
        result.dedupe
          ? "已有检查正在进行，将继续显示该任务。"
          : "已重试失败的检查。已成功的分析会复用缓存；AI 已启用时，待分析与失败候选可能产生新的 Token 用量。",
      );
    });
  }

  function changeView(value: DiscoveryView) {
    setView(value);
    setPage(1);
  }

  const active = status?.active_run;
  const aiReady = settings?.ai_enabled && status?.key_configured;
  return (
    <section className="discover-content" aria-label="论文发现">
      <header className="workspace-header">
        <div className="workspace-heading">
          <h1>
            Discover <span className="count">{total}</span>
          </h1>
          <p className="workspace-description">
            发现与你的研究有关的新论文，由你决定下一篇读什么。
          </p>
        </div>
        <Button
          variant="default"
          disabled={Boolean(busy) || Boolean(active)}
          onClick={check}
        >
          <RefreshCw size={15} />
          {active ? "检查进行中" : "检查新论文"}
        </Button>
      </header>
      <div className="discovery-status">
        <div>
          <p className="discovery-status-main" role="status">
            {active
              ? discoveryStage(active)
              : `上次检查：${discoveryDate(status?.last_checked_at || null)}`}
          </p>
          <p className="discovery-help">
            {active
              ? `已获取 ${active.fetched_count} 篇，已分析 ${active.analyzed_count} 篇。`
              : status?.next_check_at
                ? `下次自动检查：${discoveryDate(status.next_check_at)}，仅在应用运行时执行。`
                : "可手动检查，或在 Settings 中开启自动更新。"}
          </p>
        </div>
        <Link
          className="discovery-settings-link"
          to="/settings#research-discovery"
        >
          <SlidersHorizontal size={14} />
          研究兴趣与设置
        </Link>
      </div>
      {status && !status.online && (
        <p className="notice">
          发现联网已关闭。历史推荐和 Library 仍可使用；开启后可检查新论文。
        </p>
      )}
      {settings && !aiReady && (
        <div className="discovery-guidance">
          <p>
            {!status?.key_configured
              ? "尚未配置 DeepSeek API Key。"
              : "AI 推荐尚未开启。"}
            仍可获取论文并进行基础初筛，AI 中文总结与推荐将在启用后生成。
          </p>
          <Link to="/settings#research-discovery">配置 Research Discovery</Link>
        </div>
      )}
      {error && (
        <div className="notice error" role="alert">
          {error}
          <Button onClick={() => setRevision((value) => value + 1)}>
            重试加载
          </Button>
        </div>
      )}
      {notice && (
        <div className="notice" role="status">
          {notice}
        </div>
      )}
      {status?.last_run?.status === "failed" && !active && (
        <div className="notice error" role="alert">
          上次检查失败：
          {status.last_run.error_message || "请重试检查或查看更新记录。"}
          <Button
            disabled={Boolean(busy)}
            onClick={() => retry(status.last_run!)}
          >
            重试检查
          </Button>
          {aiReady && <span>AI 已启用，重试可能使用 Token。</span>}
        </div>
      )}
      <div className="discovery-toolbar">
        <label>
          查看
          <select
            aria-label="推荐范围"
            value={view}
            onChange={(event) =>
              changeView(event.target.value as DiscoveryView)
            }
          >
            <option value="recommended">为你推荐</option>
            <option value="latest">最近新增推荐</option>
            <option value="interested">感兴趣 / 稍后阅读</option>
            <option value="history">全部发现记录</option>
            <option value="dismissed">不感兴趣</option>
          </select>
        </label>
        <label>
          研究方向
          <select
            aria-label="研究方向筛选"
            value={interest}
            onChange={(event) => {
              setInterest(event.target.value);
              setPage(1);
            }}
          >
            <option value="">全部方向</option>
            {settings?.interests.map((item) => (
              <option value={item.id} key={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          最低相关分
          <select
            aria-label="最低推荐分数"
            value={minScore}
            onChange={(event) => {
              setMinScore(event.target.value);
              setPage(1);
            }}
          >
            <option value="">
              {view === "recommended" || view === "latest"
                ? `使用设置（${settings?.min_score ?? 70}）`
                : "不限分数"}
            </option>
            {[0, 40, 50, 60, 70, 80, 90].map((value) => (
              <option value={value} key={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          排序
          <select
            aria-label="推荐排序"
            value={sort}
            onChange={(event) => {
              setSort(event.target.value);
              setPage(1);
            }}
          >
            <option value="score">相关性优先</option>
            <option value="recent">最新发表</option>
          </select>
        </label>
      </div>
      <p className="discovery-help discovery-score-note">
        相关分是 AI
        对研究兴趣匹配程度的判断参考，不代表论文质量。分析依据会单独标明。
      </p>
      {loading && papers.length === 0 ? (
        <div className="library-loading" aria-busy="true">
          <p className="loading-caption" role="status">
            正在读取发现记录…
          </p>
          {[0, 1, 2].map((index) => (
            <div className="discovery-skeleton" key={index} aria-hidden="true">
              <span className="skeleton-line long" />
              <span className="skeleton-line short" />
              <span className="skeleton-line long" />
            </div>
          ))}
        </div>
      ) : papers.length === 0 && !error ? (
        <div className="empty discovery-empty">
          <h2>
            {view === "recommended" || view === "latest"
              ? "还没有符合条件的推荐"
              : "这里还没有论文"}
          </h2>
          <p>
            {status?.pending_count
              ? `有 ${status.pending_count} 篇候选等待 AI 判断。配置并开启 AI 后，检查新论文将继续分析。`
              : "检查新论文后，候选和分析结果会保存在这里。调整方向或最低分也能查看不同结果。"}
          </p>
          {view !== "history" ? (
            <Button onClick={() => changeView("history")}>
              查看全部发现记录
            </Button>
          ) : (
            <Button disabled={Boolean(busy) || Boolean(active)} onClick={check}>
              检查新论文
            </Button>
          )}
        </div>
      ) : (
        <div className="discovery-list" aria-busy={loading}>
          {papers.map((paper) => {
            const analysis = paper.analysis;
            const selected =
              paper.feedback === "interested" || paper.feedback === "later";
            return (
              <article
                className="discovery-paper"
                key={paper.id}
                aria-label={paper.title}
              >
                <div className="discovery-paper-heading">
                  <a
                    className="discovery-title"
                    href={paper.source_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {paper.title}
                  </a>
                  {analysis && (
                    <div
                      className="discovery-score"
                      title="研究兴趣相关分，非论文质量评分"
                    >
                      <strong>{analysis.score}</strong>
                      <span>相关分</span>
                    </div>
                  )}
                </div>
                <p className="discovery-byline">
                  {paper.authors.slice(0, 4).join(", ") || "作者信息待补全"}
                  {paper.authors.length > 4 && " 等"}
                </p>
                <div className="discovery-meta">
                  <time dateTime={paper.published_at}>
                    {discoveryDate(paper.published_at, false)}
                  </time>
                  <span>{paper.venue || "arXiv"}</span>
                  <span>
                    {paper.arxiv_id}v{paper.arxiv_version}
                  </span>
                  {paper.categories.map((category) => (
                    <span key={category}>{category}</span>
                  ))}
                  {paper.is_new && <span className="tag">新增</span>}
                  {paper.paper_id && <span className="tag">已在 Library</span>}
                </div>
                {analysis && paper.analysis_status !== "succeeded" && (
                  <p className="discovery-stale-analysis" role="status">
                    {paper.analysis_status === "running"
                      ? "正在重新分析，以下保留上次结果。"
                      : paper.analysis_status === "failed"
                        ? "本次分析失败，以下保留上次结果。"
                        : "以下为上次分析，当前版本待重新判断。"}
                    {paper.analysis_error && ` ${paper.analysis_error}`}
                  </p>
                )}
                {analysis ? (
                  <>
                    <div className="discovery-analysis-meta">
                      <span className="discovery-basis">
                        {discoveryBasis(analysis.basis)}
                      </span>
                      <span>
                        {paper.analysis_status !== "succeeded"
                          ? "上次分析："
                          : ""}
                        {analysis.decision === "recommend"
                          ? "AI 建议阅读"
                          : "AI 建议跳过"}
                      </span>
                      {analysis.matched_directions.map((id) => (
                        <span className="tag" key={id}>
                          {settings?.interests.find((item) => item.id === id)
                            ?.name || id}
                        </span>
                      ))}
                    </div>
                    {analysis.summary && (
                      <p className="discovery-summary" lang="zh-CN">
                        {analysis.summary}
                      </p>
                    )}
                    <p className="discovery-reason">
                      <strong>推荐依据</strong>
                      {analysis.reason}
                    </p>
                  </>
                ) : (
                  <div className="discovery-unanalysed">
                    <p className="discovery-analysis-label">
                      {paper.analysis_status === "running"
                        ? "正在分析论文…"
                        : paper.analysis_status === "failed"
                          ? "AI 分析失败"
                          : paper.analysis_status === "filtered"
                            ? "基础初筛未通过"
                            : "候选论文，等待 AI 分析"}
                    </p>
                    {paper.analysis_error && (
                      <p className="discovery-paper-error">
                        {paper.analysis_error}
                      </p>
                    )}
                    <details>
                      <summary>查看原始摘要</summary>
                      <p lang="en">{paper.abstract || "来源尚未提供摘要。"}</p>
                    </details>
                  </div>
                )}
                <div className="discovery-actions">
                  <Button asChild>
                    <a href={paper.source_url} target="_blank" rel="noreferrer">
                      阅读原文
                      <ArrowUpRight size={13} />
                    </a>
                  </Button>
                  {paper.paper_id ? (
                    <Button asChild>
                      <Link to={`/papers/${paper.paper_id}/pdf`}>
                        <Check size={14} />
                        打开 Library 论文
                      </Link>
                    </Button>
                  ) : (
                    <Button
                      variant="default"
                      disabled={Boolean(busy)}
                      onClick={() =>
                        action(paper.id, async () => {
                          const result = await api<{
                            paper: Paper;
                            dedupe: boolean;
                          }>(`/discovery/papers/${paper.id}/import`, {
                            method: "POST",
                          });
                          setNotice(
                            result.dedupe
                              ? `已关联 Library 中的论文：${result.paper.title}`
                              : `已加入 Library：${result.paper.title}。PDF 可在阅读器中按需下载。`,
                          );
                        })
                      }
                    >
                      {busy === paper.id ? "正在保存…" : "加入文献库"}
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    aria-pressed={paper.feedback === "interested"}
                    disabled={Boolean(busy)}
                    onClick={() =>
                      action(`feedback-${paper.id}`, async () => {
                        await api(`/discovery/papers/${paper.id}/feedback`, {
                          method: "POST",
                          body: JSON.stringify({
                            feedback:
                              paper.feedback === "interested"
                                ? "none"
                                : "interested",
                          }),
                        });
                      })
                    }
                  >
                    {paper.feedback === "interested" ? "已感兴趣" : "感兴趣"}
                  </Button>
                  <Button
                    variant="ghost"
                    aria-pressed={paper.feedback === "later"}
                    disabled={Boolean(busy)}
                    onClick={() =>
                      action(`feedback-${paper.id}`, async () => {
                        await api(`/discovery/papers/${paper.id}/feedback`, {
                          method: "POST",
                          body: JSON.stringify({
                            feedback:
                              paper.feedback === "later" ? "none" : "later",
                          }),
                        });
                      })
                    }
                  >
                    {paper.feedback === "later" ? "已存稍后阅读" : "稍后阅读"}
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={Boolean(busy)}
                    onClick={() =>
                      action(`feedback-${paper.id}`, async () => {
                        await api(`/discovery/papers/${paper.id}/feedback`, {
                          method: "POST",
                          body: JSON.stringify({
                            feedback:
                              paper.feedback === "dismissed"
                                ? "none"
                                : "dismissed",
                          }),
                        });
                        setNotice(
                          paper.feedback === "dismissed"
                            ? "已恢复到推荐池。"
                            : "已记录不感兴趣，可在“不感兴趣”中恢复。",
                        );
                      })
                    }
                  >
                    {paper.feedback === "dismissed" ? "恢复推荐" : "不感兴趣"}
                  </Button>
                  {selected && (
                    <span className="sr-only">已保存你的阅读意向</span>
                  )}
                  <details className="discovery-more">
                    <summary>分析操作</summary>
                    <Button
                      variant="ghost"
                      disabled={
                        Boolean(busy) ||
                        Boolean(active) ||
                        !aiReady ||
                        Boolean(paper.paper_id)
                      }
                      onClick={() =>
                        action(`analyze-${paper.id}`, async () => {
                          await api(`/discovery/papers/${paper.id}/reanalyze`, {
                            method: "POST",
                          });
                          setNotice(
                            "已请求重新分析，将使用 DeepSeek 并计入 Token 上限。",
                          );
                        })
                      }
                    >
                      重新分析（使用 AI）
                    </Button>
                  </details>
                </div>
              </article>
            );
          })}
        </div>
      )}
      {total > 20 && (
        <div className="workspace-footer">
          <span>
            共 {total} 篇，第 {page} 页
          </span>
          <div className="discovery-pagination">
            <Button
              disabled={page === 1 || loading}
              onClick={() => setPage((value) => value - 1)}
            >
              上一页
            </Button>
            <Button
              disabled={page * 20 >= total || loading}
              onClick={() => setPage((value) => value + 1)}
            >
              下一页
            </Button>
          </div>
        </div>
      )}
      <details className="discovery-run-history">
        <summary>更新记录{runs.length > 0 ? `（${runs.length}）` : ""}</summary>
        {runs.length === 0 ? (
          <p className="discovery-help">尚无检查记录。</p>
        ) : (
          <ul>
            {runs.map((run) => (
              <li key={run.id}>
                <div>
                  <strong>{discoveryStage(run)}</strong>
                  <time dateTime={run.created_at}>
                    {discoveryDate(run.created_at)}
                  </time>
                </div>
                <p>
                  获取 {run.fetched_count} 篇，新增 {run.new_count} 篇，分析{" "}
                  {run.analyzed_count} 篇，推荐 {run.recommended_count} 篇，使用{" "}
                  {run.tokens_used.toLocaleString()} Token。
                </p>
                {run.error_message && (
                  <p className="discovery-paper-error">{run.error_message}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </details>
    </section>
  );
}
