import { useEffect, useState } from "react";
import { api } from "./api";
import { Button } from "./components/ui/button";

type SyncStatus = {
  enabled: boolean;
  device_id: string;
  peer_configured: boolean;
  online: boolean;
  accept_conversions: boolean;
  last_success: string | null;
  error: string | null;
  pending_conversions: number;
};

export function PeerSettings() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    const refresh = () => api<SyncStatus>("/sync/status")
      .then((value) => { if (alive) { setStatus(value); setError(""); } })
      .catch(() => { if (alive) setError("无法读取设备同步状态"); });
    void refresh();
    const timer = setInterval(refresh, 5000);
    return () => { alive = false; clearInterval(timer); };
  }, []);
  async function synchronize() {
    setBusy(true);
    try {
      await api("/sync/now", { method: "POST" });
      setError("");
    } catch (error) {
      setError(error instanceof Error ? error.message : "同步请求失败");
    } finally { setBusy(false); }
  }
  return <section className="settings-section" aria-label="双机同步">
    <h2>双机同步</h2>
    <p>两台电脑各自保存论文和阅读记录，连接后自动同步。现有本机 Marker 转换仍可使用。</p>
    {status && <>
      <div className="setting-line">同步状态 <span className="format">
        {!status.enabled ? "未启用" : status.online ? "已连接" : "等待设备连接"}
      </span></div>
      <p>本机设备 ID：<code>{status.device_id}</code></p>
      <p>{status.accept_conversions ? "此设备接收远程转换任务。" : "此设备不接收远程转换任务。"}
        {status.peer_configured && " 转换时可选择使用 Ubuntu。"}</p>
      {status.last_success && <p>最近同步：{new Date(status.last_success).toLocaleString()}</p>}
      {status.pending_conversions > 0 && <p>待完成的 Ubuntu 转换：{status.pending_conversions}</p>}
      <Button disabled={!status.enabled || busy} onClick={synchronize}>立即同步</Button>
      <details><summary>连接配置</summary>
        <p>在两端 .env 中启用 PAPERFLOW_SYNC_ENABLED，并填写相同的 PAPERFLOW_SYNC_TOKEN。
          Mac 设置 PAPERFLOW_SYNC_PEER_URL 为 Ubuntu 的 HTTPS 地址；Ubuntu 设置
          PAPERFLOW_SYNC_ACCEPT_CONVERSIONS=true，PAPERFLOW_DISCOVERY_ONLINE=false。
          保存后重启。完整说明见仓库 docs/PEER_SYNC.md。</p>
      </details>
    </>}
    {(error || status?.error) && <p role="alert">{error || status?.error}</p>}
  </section>;
}
