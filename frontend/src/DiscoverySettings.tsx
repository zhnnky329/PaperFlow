import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Plus, Trash2 } from "lucide-react";
import {
  api,
  type DiscoveryInterest,
  type DiscoverySettings as Settings,
  type DiscoveryStatus,
} from "./api";
import { Button } from "./components/ui/button";
import { discoveryDate, splitDiscoveryKeywords } from "./discovery";

type DraftInterest = Omit<
  DiscoveryInterest,
  "keywords" | "exclude_keywords"
> & {
  keywords: string;
  exclude_keywords: string;
};
type Draft = Omit<Settings, "interests"> & { interests: DraftInterest[] };
function draftSettings(settings: Settings): Draft {
  return {
    ...settings,
    interests: settings.interests.map((interest) => ({
      ...interest,
      keywords: interest.keywords.join(", "),
      exclude_keywords: interest.exclude_keywords.join(", "),
    })),
  };
}
const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : "保存失败，请重试";

export function DiscoverySettings() {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [status, setStatus] = useState<DiscoveryStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let alive = true;
    Promise.all([
      api<Settings>("/discovery/settings"),
      api<DiscoveryStatus>("/discovery/status"),
    ])
      .then(([preferences, current]) => {
        if (!alive) return;
        setDraft(draftSettings(preferences));
        setStatus(current);
        setError("");
      })
      .catch((error) => {
        if (alive) setError(errorMessage(error));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [revision]);

  useEffect(() => {
    if (!loading && window.location.hash === "#research-discovery") {
      document.getElementById("research-discovery")?.scrollIntoView();
    }
  }, [loading]);

  function update<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((current) => (current ? { ...current, [key]: value } : current));
  }
  function updateInterest(id: string, changes: Partial<DraftInterest>) {
    setDraft((current) =>
      current
        ? {
            ...current,
            interests: current.interests.map((interest) =>
              interest.id === id ? { ...interest, ...changes } : interest,
            ),
          }
        : current,
    );
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const {
        api_key_configured: _configured,
        api_key_source: _source,
        ...preferences
      } = draft;
      void _configured;
      void _source;
      const result = await api<Settings>("/discovery/settings", {
        method: "PATCH",
        body: JSON.stringify({
          ...preferences,
          interests: preferences.interests.map((interest) => ({
            ...interest,
            keywords: splitDiscoveryKeywords(interest.keywords),
            exclude_keywords: splitDiscoveryKeywords(interest.exclude_keywords),
          })),
        }),
      });
      setDraft(draftSettings(result));
      setNotice(
        "Research Discovery 设置已保存。后续检查将使用新的研究兴趣和限制。",
      );
      setStatus(await api<DiscoveryStatus>("/discovery/status"));
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }
  async function saveKey(remove = false) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api("/discovery/api-key", {
        method: "POST",
        body: JSON.stringify({ api_key: remove ? "" : apiKey.trim() }),
      });
      setApiKey("");
      const [preferences, current] = await Promise.all([
        api<Settings>("/discovery/settings"),
        api<DiscoveryStatus>("/discovery/status"),
      ]);
      setDraft((previous) =>
        previous
          ? {
              ...previous,
              api_key_configured: preferences.api_key_configured,
              api_key_source: preferences.api_key_source,
            }
          : draftSettings(preferences),
      );
      setStatus(current);
      setNotice(
        remove
          ? "本地 DeepSeek API Key 已删除。"
          : "DeepSeek API Key 已保存，输入框已清空。尚未发起模型调用。",
      );
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="settings-section discovery-settings"
      id="research-discovery"
    >
      <h2>Research Discovery</h2>
      <p>
        定期发现论文，按你的科研兴趣生成中文推荐。候选独立保存在
        Discover，由你选择加入 Library。
      </p>
      {error && (
        <div className="notice error" role="alert">
          {error}
          {!draft && (
            <Button onClick={() => setRevision((value) => value + 1)}>
              重试加载
            </Button>
          )}
        </div>
      )}
      {notice && (
        <div className="notice" role="status">
          {notice}
        </div>
      )}
      {loading ? (
        <p role="status">正在读取 Research Discovery 设置…</p>
      ) : (
        draft && (
          <>
            <form onSubmit={save}>
              <fieldset disabled={busy} className="discovery-fieldset">
                <legend>研究兴趣</legend>
                <label
                  className="discovery-stacked-label"
                  htmlFor="research-description"
                >
                  整体研究兴趣
                  <textarea
                    id="research-description"
                    aria-label="整体研究兴趣"
                    rows={3}
                    maxLength={5000}
                    value={draft.interest_description}
                    onChange={(event) =>
                      update("interest_description", event.target.value)
                    }
                    placeholder="用自然语言描述你关注的研究问题、方法或应用场景。"
                  />
                </label>
                <p>
                  方向和关键词提供线索，AI 会结合研究问题与论文内容判断相关性。
                </p>
                <div className="discovery-interest-list">
                  {draft.interests.map((interest, index) => (
                    <details
                      className="discovery-interest"
                      open
                      key={interest.id}
                    >
                      <summary>
                        {interest.name || `新研究方向 ${index + 1}`}
                      </summary>
                      <div className="discovery-interest-fields">
                        <label htmlFor={`interest-name-${interest.id}`}>
                          方向名称
                          <input
                            id={`interest-name-${interest.id}`}
                            required
                            maxLength={100}
                            value={interest.name}
                            onChange={(event) =>
                              updateInterest(interest.id, {
                                name: event.target.value,
                              })
                            }
                          />
                        </label>
                        <label htmlFor={`interest-priority-${interest.id}`}>
                          优先级
                          <select
                            id={`interest-priority-${interest.id}`}
                            aria-label="优先级"
                            value={interest.priority}
                            onChange={(event) =>
                              updateInterest(interest.id, {
                                priority: Number(
                                  event.target.value,
                                ) as DiscoveryInterest["priority"],
                              })
                            }
                          >
                            <option value={3}>高</option>
                            <option value={2}>中</option>
                            <option value={1}>低</option>
                          </select>
                        </label>
                        <label
                          className="discovery-stacked-label"
                          htmlFor={`interest-description-${interest.id}`}
                        >
                          方向描述
                          <textarea
                            id={`interest-description-${interest.id}`}
                            aria-label="方向描述"
                            rows={2}
                            maxLength={3000}
                            value={interest.description}
                            onChange={(event) =>
                              updateInterest(interest.id, {
                                description: event.target.value,
                              })
                            }
                          />
                        </label>
                        <label
                          className="discovery-stacked-label"
                          htmlFor={`interest-keywords-${interest.id}`}
                        >
                          关键词（逗号或换行分隔）
                          <textarea
                            id={`interest-keywords-${interest.id}`}
                            aria-label="关键词（逗号或换行分隔）"
                            rows={2}
                            value={interest.keywords}
                            onChange={(event) =>
                              updateInterest(interest.id, {
                                keywords: event.target.value,
                              })
                            }
                          />
                        </label>
                        <label
                          className="discovery-stacked-label"
                          htmlFor={`interest-exclude-${interest.id}`}
                        >
                          排除词（逗号或换行分隔）
                          <input
                            id={`interest-exclude-${interest.id}`}
                            value={interest.exclude_keywords}
                            onChange={(event) =>
                              updateInterest(interest.id, {
                                exclude_keywords: event.target.value,
                              })
                            }
                          />
                        </label>
                        <Button
                          type="button"
                          variant="ghost"
                          className="discovery-remove-interest"
                          aria-label={`删除研究方向 ${interest.name || index + 1}`}
                          onClick={() =>
                            update(
                              "interests",
                              draft.interests.filter(
                                (item) => item.id !== interest.id,
                              ),
                            )
                          }
                        >
                          <Trash2 size={14} />
                          删除此方向
                        </Button>
                      </div>
                    </details>
                  ))}
                </div>
                <Button
                  type="button"
                  disabled={draft.interests.length >= 30}
                  onClick={() =>
                    update("interests", [
                      ...draft.interests,
                      {
                        id: crypto.randomUUID(),
                        name: "",
                        description: "",
                        keywords: "",
                        exclude_keywords: "",
                        priority: 2,
                      },
                    ])
                  }
                >
                  <Plus size={14} />
                  新增研究方向
                </Button>
                {draft.interests.length === 0 && (
                  <p>添加至少一个方向，为后续论文筛选提供依据。</p>
                )}
              </fieldset>
              <fieldset disabled={busy} className="discovery-fieldset">
                <legend>推荐与更新</legend>
                <label htmlFor="discovery-auto-update">
                  自动检查新论文
                  <input
                    id="discovery-auto-update"
                    type="checkbox"
                    checked={draft.auto_update}
                    onChange={(event) =>
                      update("auto_update", event.target.checked)
                    }
                  />
                </label>
                <label htmlFor="discovery-interval">
                  更新间隔（小时）
                  <input
                    id="discovery-interval"
                    type="number"
                    min={1}
                    max={720}
                    required
                    value={draft.interval_hours}
                    onChange={(event) =>
                      update("interval_hours", Number(event.target.value))
                    }
                  />
                </label>
                <label htmlFor="discovery-min-score">
                  默认最低推荐分数
                  <input
                    id="discovery-min-score"
                    type="number"
                    min={0}
                    max={100}
                    required
                    value={draft.min_score}
                    onChange={(event) =>
                      update("min_score", Number(event.target.value))
                    }
                  />
                </label>
                <label htmlFor="discovery-max-analyses">
                  单次最多分析论文数
                  <input
                    id="discovery-max-analyses"
                    type="number"
                    min={1}
                    max={100}
                    required
                    value={draft.max_analyses}
                    onChange={(event) =>
                      update("max_analyses", Number(event.target.value))
                    }
                  />
                </label>
                <label htmlFor="discovery-full-text">
                  尝试获取全文
                  <input
                    id="discovery-full-text"
                    type="checkbox"
                    checked={draft.try_full_text}
                    onChange={(event) =>
                      update("try_full_text", event.target.checked)
                    }
                  />
                </label>
                <p>
                  优先读取官方 HTML，必要时提取 PDF
                  文本；无法读取正文时明确标记为摘要级判断。程序停止时不会检查，重启后会按计划补查。
                </p>
              </fieldset>
              <fieldset disabled={busy} className="discovery-fieldset">
                <legend>DeepSeek 与用量限制</legend>
                <label htmlFor="discovery-ai-enabled">
                  启用 AI 推荐
                  <input
                    id="discovery-ai-enabled"
                    type="checkbox"
                    checked={draft.ai_enabled}
                    onChange={(event) =>
                      update("ai_enabled", event.target.checked)
                    }
                  />
                </label>
                <p>
                  启用后，自动和手动检查会在设定上限内调用
                  DeepSeek，可能产生费用。保存密钥本身不会调用模型；未开启时仍可抓取和初筛论文。
                </p>
                <label htmlFor="discovery-model">
                  模型名称
                  <input
                    id="discovery-model"
                    required
                    maxLength={100}
                    value={draft.model}
                    onChange={(event) => update("model", event.target.value)}
                  />
                </label>
                <label htmlFor="discovery-token-budget">
                  单次检查 Token 上限
                  <input
                    id="discovery-token-budget"
                    type="number"
                    min={2000}
                    max={2000000}
                    step={1000}
                    required
                    value={draft.token_budget}
                    onChange={(event) =>
                      update("token_budget", Number(event.target.value))
                    }
                  />
                </label>
                <label htmlFor="discovery-output-tokens">
                  每篇最大输出 Token
                  <input
                    id="discovery-output-tokens"
                    type="number"
                    min={300}
                    max={4000}
                    required
                    value={draft.max_output_tokens}
                    onChange={(event) =>
                      update("max_output_tokens", Number(event.target.value))
                    }
                  />
                </label>
              </fieldset>
              <div className="discovery-settings-actions">
                <Button type="submit" variant="default" disabled={busy}>
                  {busy ? "正在保存…" : "保存 Discovery 设置"}
                </Button>
                <Link to="/discover">打开 Discover</Link>
              </div>
            </form>
            <div className="discovery-key-section">
              <h3>DeepSeek API Key</h3>
              <p>
                {draft.api_key_configured
                  ? `已配置（${draft.api_key_source === "environment" ? "环境变量" : "本机保存"}）。密钥不会在页面或接口响应中回显。`
                  : "尚未配置。密钥只提交给本机后端，保存后不会回传。"}
              </p>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  saveKey();
                }}
              >
                <label
                  className="discovery-stacked-label"
                  htmlFor="discovery-api-key"
                >
                  {draft.api_key_configured ? "替换 API Key" : "API Key"}
                  <input
                    id="discovery-api-key"
                    type="password"
                    autoComplete="new-password"
                    spellCheck={false}
                    value={apiKey}
                    onChange={(event) => setApiKey(event.target.value)}
                    placeholder="输入新的 DeepSeek API Key"
                    disabled={busy}
                  />
                </label>
                <div className="discovery-settings-actions">
                  <Button type="submit" disabled={busy || !apiKey.trim()}>
                    保存 API Key
                  </Button>
                  {draft.api_key_source === "local" && (
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => saveKey(true)}
                    >
                      删除本机密钥
                    </Button>
                  )}
                </div>
              </form>
              {draft.api_key_source === "environment" && (
                <p>环境变量中的密钥需在启动配置中修改，页面不能删除。</p>
              )}
            </div>
            {status && (
              <div className="discovery-usage">
                <h3>使用状态</h3>
                <p>
                  累计使用 {status.usage.tokens_used.toLocaleString()}{" "}
                  Token，未确认用量预留{" "}
                  {status.usage.tokens_reserved.toLocaleString()}{" "}
                  Token。上次检查：{discoveryDate(status.last_checked_at)}。
                </p>
                <p>
                  预留量包含超时或中断请求的估算，实际费用以服务商账单为准。
                </p>
                {status.last_run?.error_message && (
                  <p className="discovery-paper-error">
                    最近错误：{status.last_run.error_message}
                  </p>
                )}
                <p>各次检查的获取、分析和用量记录可在 Discover 底部查看。</p>
              </div>
            )}
          </>
        )
      )}
    </section>
  );
}
