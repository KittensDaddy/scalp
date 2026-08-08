import { useEffect, useState } from "react";
import {
  clearKillSwitch,
  engageKillSwitch,
  fetchKillSwitchStatus,
  fetchMeta,
} from "../api/client";
import type { ConnectionState } from "../store/scannerStore";
import type { MetaInfo } from "../api/types";

interface Props {
  connection: ConnectionState;
  resnapshotCount: number;
}

export function TopBar({ connection, resnapshotCount }: Props) {
  const [meta, setMeta] = useState<MetaInfo | null>(null);
  const [killed, setKilled] = useState<boolean | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMeta().then(setMeta).catch(() => setMeta(null));
    fetchKillSwitchStatus()
      .then((s) => setKilled(s.killed))
      .catch(() => setKilled(null));
  }, []);

  async function handleKill() {
    setBusy(true);
    setError(null);
    try {
      const result = await engageKillSwitch(token);
      if (result.ok) {
        setKilled(true);
      } else {
        setError(result.detail ?? `failed (${result.status})`);
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleUnkill() {
    setBusy(true);
    setError(null);
    try {
      const result = await clearKillSwitch(token);
      if (result.ok) {
        setKilled(false);
      } else {
        setError(result.detail ?? `failed (${result.status})`);
      }
    } finally {
      setBusy(false);
    }
  }

  const dotClass =
    connection === "open" ? "dot dot-live" : connection === "connecting" ? "dot dot-warn" : "dot dot-dead";

  return (
    <header className="topbar">
      <div className="topbar-group">
        <span className={`mode-badge mode-${(meta?.environment ?? "paper").toLowerCase()}`}>
          {(meta?.environment ?? "…").toUpperCase()}
        </span>
        <span className="topbar-item">
          <span className={dotClass} /> WS {connection}
        </span>
        {resnapshotCount > 0 && (
          <span className="topbar-item muted">resnapshots: {resnapshotCount}</span>
        )}
      </div>

      <div className="topbar-group">
        <span className="topbar-item muted">{meta?.strategy_version ?? ""}</span>
      </div>

      <div className="topbar-group">
        {error && <span className="topbar-error">{error}</span>}
        <input
          className="token-input"
          type="password"
          placeholder="control token"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        {killed ? (
          <button className="btn btn-unkill" disabled={busy || !token} onClick={handleUnkill}>
            UN-KILL
          </button>
        ) : (
          <button className="btn btn-kill" disabled={busy || !token} onClick={handleKill}>
            KILL
          </button>
        )}
        <span className={`kill-status ${killed ? "killed" : "live"}`}>
          {killed === null ? "…" : killed ? "KILLED" : "LIVE"}
        </span>
      </div>
    </header>
  );
}
