import { useEffect, useState } from "react";
import { API_BASE } from "../api/client";

interface AnalyticsGroup {
  key: string;
  n: number;
  wins: number;
  sum_r: number;
  avg_r: number | null;
  win_rate: number | null;
  avg_mae: number | null;
  avg_mfe: number | null;
  profit_factor: number | null;
  profit_factor_infinite: boolean;
}

interface AnalyticsResponse {
  group_by: string;
  n_trades: number;
  groups: AnalyticsGroup[];
}

interface ClosedTrade {
  trade_id: string;
  symbol: string;
  side: string;
  strategy_version: string;
  r_multiple: number;
  exit_reason: string | null;
  opened_at: string;
  closed_at: string;
  mae: number | null;
  mfe: number | null;
}

const GROUP_OPTIONS = ["symbol", "side", "strategy", "exit_reason", "hour"] as const;

export function AnalyticsPanel() {
  const [groupBy, setGroupBy] = useState<string>("symbol");
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [trades, setTrades] = useState<ClosedTrade[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    fetch(`${API_BASE}/api/v1/analytics?group_by=${encodeURIComponent(groupBy)}`)
      .then((r) => r.json())
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, [groupBy]);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/trades?limit=100`)
      .then((r) => r.json())
      .then((rows: ClosedTrade[]) => setTrades(Array.isArray(rows) ? rows : []))
      .catch(() => setTrades([]));
    const id = window.setInterval(() => {
      fetch(`${API_BASE}/api/v1/trades?limit=100`)
        .then((r) => r.json())
        .then((rows: ClosedTrade[]) => setTrades(Array.isArray(rows) ? rows : []))
        .catch(() => undefined);
    }, 15_000);
    return () => window.clearInterval(id);
  }, []);

  const wins = trades.filter((t) => t.r_multiple > 0).length;
  const losses = trades.filter((t) => t.r_multiple < 0).length;

  return (
    <div className="analytics-panel">
      <div className="pane-toolbar">
        <label>
          group by{" "}
          <select value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>
            {GROUP_OPTIONS.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </label>
        <span className="muted">{data ? `${data.n_trades} closed` : "…"}</span>
        <span className="muted">
          journal W {wins} / L {losses}
        </span>
      </div>
      {error && <div className="topbar-error">{error}</div>}

      <h3>Closed trades (W / L)</h3>
      <table className="scanner-table">
        <thead>
          <tr>
            <th>RESULT</th>
            <th>SYM</th>
            <th>S</th>
            <th>STRAT</th>
            <th>R</th>
            <th>EXIT</th>
            <th>CLOSED</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => {
            const win = t.r_multiple > 0;
            const flat = t.r_multiple === 0;
            return (
              <tr key={t.trade_id}>
                <td className={flat ? "" : win ? "r-pos" : "r-neg"}>
                  {flat ? "—" : win ? "W" : "L"}
                </td>
                <td>{t.symbol}</td>
                <td>{t.side}</td>
                <td>{t.strategy_version}</td>
                <td className={t.r_multiple >= 0 ? "r-pos" : "r-neg"}>
                  {t.r_multiple >= 0 ? "+" : ""}
                  {t.r_multiple.toFixed(2)}
                </td>
                <td>{t.exit_reason ?? "—"}</td>
                <td className="muted">{t.closed_at?.replace("T", " ").slice(0, 19)}</td>
              </tr>
            );
          })}
          {trades.length === 0 && (
            <tr>
              <td colSpan={7} className="empty-row">
                no closed trades yet — W/L appears after paper positions exit
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <h3>Aggregates</h3>
      <table className="scanner-table">
        <thead>
          <tr>
            <th>KEY</th>
            <th>N</th>
            <th>WR</th>
            <th>AVG R</th>
            <th>SUM R</th>
            <th>MAE</th>
            <th>MFE</th>
            <th>PF</th>
          </tr>
        </thead>
        <tbody>
          {(data?.groups ?? []).map((g) => (
            <tr key={g.key}>
              <td>{g.key}</td>
              <td>{g.n}</td>
              <td>{g.win_rate != null ? `${(g.win_rate * 100).toFixed(0)}%` : "—"}</td>
              <td>{g.avg_r != null ? g.avg_r.toFixed(2) : "—"}</td>
              <td>{g.sum_r.toFixed(2)}</td>
              <td>{g.avg_mae != null ? g.avg_mae.toFixed(2) : "—"}</td>
              <td>{g.avg_mfe != null ? g.avg_mfe.toFixed(2) : "—"}</td>
              <td>
                {g.profit_factor_infinite
                  ? "∞"
                  : g.profit_factor != null
                    ? g.profit_factor.toFixed(2)
                    : "—"}
              </td>
            </tr>
          ))}
          {data && data.groups.length === 0 && (
            <tr>
              <td colSpan={8} className="empty-row">
                no closed trades yet — analytics fills as the journal grows
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
