import { useEffect, useState } from "react";
import { API_BASE } from "../api/client";

interface PresetRow {
  preset_id: string;
  name: string;
  version: number;
  overlay: boolean;
  disabled: boolean;
  activated_paper: boolean;
  activated_live: boolean;
  params: Record<string, unknown>;
  note: string;
}

interface ProvenanceEntry {
  key: string;
  value: unknown;
  layer: string;
}

interface CalibrationBucket {
  score_bucket: string;
  side: string;
  regime: string;
  n: number;
  probability: {
    available: boolean;
    win_probability: number | null;
    ci_low: number | null;
    ci_high: number | null;
    expectancy_r: number | null;
    reason: string | null;
    min_samples: number;
  };
}

interface BacktestResult {
  job_id: string;
  status: string;
  progress: number;
  banner: string;
  result: {
    n_trades?: number;
    win_rate?: number | null;
    avg_r?: number | null;
    profit_factor?: number | null;
  } | null;
  error: string | null;
}

export function StrategyLabPanel() {
  const [presets, setPresets] = useState<PresetRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [provenance, setProvenance] = useState<ProvenanceEntry[]>([]);
  const [calibration, setCalibration] = useState<CalibrationBucket[]>([]);
  const [controlToken, setControlToken] = useState("");
  const [btJob, setBtJob] = useState<BacktestResult | null>(null);
  const [btBusy, setBtBusy] = useState(false);
  const [btError, setBtError] = useState<string | null>(null);
  const [banner] = useState(
    "Candle-level simulation is sanity-only — not evidence of live edge.",
  );

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/presets`)
      .then((r) => r.json())
      .then((rows: PresetRow[]) => {
        setPresets(rows);
        if (rows.length && !selected) {
          setSelected(rows[0].preset_id);
          setSelectedVersion(rows[0].version);
        }
      })
      .catch(() => setPresets([]));
    fetch(`${API_BASE}/api/v1/calibration`)
      .then((r) => r.json())
      .then((body: { buckets: CalibrationBucket[] }) => setCalibration(body.buckets ?? []))
      .catch(() => setCalibration([]));
  }, []);

  useEffect(() => {
    if (!selected) {
      setProvenance([]);
      return;
    }
    fetch(`${API_BASE}/api/v1/presets/${encodeURIComponent(selected)}/effective`)
      .then((r) => r.json())
      .then((body: { provenance: ProvenanceEntry[] }) => setProvenance(body.provenance ?? []))
      .catch(() => setProvenance([]));
  }, [selected]);

  useEffect(() => {
    if (!btJob || btJob.status === "COMPLETED" || btJob.status === "FAILED") return;
    const id = setInterval(() => {
      fetch(`${API_BASE}/api/v1/backtests/${encodeURIComponent(btJob.job_id)}`)
        .then((r) => r.json())
        .then((body: BacktestResult) => setBtJob(body))
        .catch(() => undefined);
    }, 1000);
    return () => clearInterval(id);
  }, [btJob]);

  async function runBacktest() {
    if (!selected || selectedVersion == null) return;
    setBtBusy(true);
    setBtError(null);
    const to = new Date();
    const from = new Date(to.getTime() - 3 * 24 * 3600 * 1000);
    try {
      const resp = await fetch(`${API_BASE}/api/v1/backtests`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${controlToken}`,
        },
        body: JSON.stringify({
          preset_id: selected,
          preset_version: selectedVersion,
          symbols: ["BTCUSDT"],
          date_from: from.toISOString(),
          date_to: to.toISOString(),
          mode: "CANDLE",
        }),
      });
      if (!resp.ok) {
        const body = (await resp.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? `HTTP ${resp.status}`);
      }
      const body = (await resp.json()) as BacktestResult;
      setBtJob(body);
    } catch (err) {
      setBtError(err instanceof Error ? err.message : String(err));
    } finally {
      setBtBusy(false);
    }
  }

  return (
    <div className="lab-panel">
      <div className="lab-banner">{banner}</div>
      <div className="lab-columns">
        <div>
          <h3>Presets</h3>
          <ul className="lab-preset-list">
            {presets.map((p) => (
              <li key={`${p.preset_id}-${p.version}`}>
                <button
                  type="button"
                  className={selected === p.preset_id ? "tab-active" : ""}
                  onClick={() => {
                    setSelected(p.preset_id);
                    setSelectedVersion(p.version);
                  }}
                >
                  {p.name} v{p.version}
                  {p.activated_live ? " · LIVE" : p.activated_paper ? " · PAPER" : ""}
                  {p.overlay ? " · overlay" : ""}
                </button>
              </li>
            ))}
            {presets.length === 0 && (
              <li className="muted">no preset versions in DB yet</li>
            )}
          </ul>
          <h3>Sanity backtest</h3>
          <div className="lab-backtest">
            <input
              className="token-input"
              type="password"
              placeholder="control token"
              value={controlToken}
              onChange={(e) => setControlToken(e.target.value)}
            />
            <button type="button" disabled={btBusy || !selected} onClick={() => void runBacktest()}>
              {btBusy ? "Enqueue…" : "Run 3d BTCUSDT"}
            </button>
            {btError && <div className="lab-error">{btError}</div>}
            {btJob && (
              <div className="lab-bt-status">
                <div>
                  {btJob.job_id.slice(0, 8)} · {btJob.status}
                  {btJob.progress < 1 ? ` · ${(btJob.progress * 100).toFixed(0)}%` : ""}
                </div>
                {btJob.result && (
                  <div>
                    n={btJob.result.n_trades ?? 0}
                    {" · "}
                    WR=
                    {btJob.result.win_rate != null
                      ? `${(btJob.result.win_rate * 100).toFixed(0)}%`
                      : "—"}
                    {" · "}
                    avgR=
                    {btJob.result.avg_r != null ? btJob.result.avg_r.toFixed(2) : "—"}
                    {" · "}
                    PF=
                    {btJob.result.profit_factor != null
                      ? btJob.result.profit_factor.toFixed(2)
                      : "—"}
                  </div>
                )}
                {btJob.error && <div className="lab-error">{btJob.error}</div>}
              </div>
            )}
          </div>
        </div>
        <div>
          <h3>Provenance</h3>
          <table className="scanner-table">
            <thead>
              <tr>
                <th>KEY</th>
                <th>VALUE</th>
                <th>LAYER</th>
              </tr>
            </thead>
            <tbody>
              {provenance.slice(0, 40).map((p) => (
                <tr key={p.key}>
                  <td>{p.key}</td>
                  <td>{String(p.value)}</td>
                  <td>{p.layer}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <h3>Calibration (gated)</h3>
      <table className="scanner-table">
        <thead>
          <tr>
            <th>BUCKET</th>
            <th>SIDE</th>
            <th>REGIME</th>
            <th>N</th>
            <th>P(win)</th>
            <th>CI</th>
            <th>E[R]</th>
          </tr>
        </thead>
        <tbody>
          {calibration.map((b) => (
            <tr key={`${b.score_bucket}-${b.side}-${b.regime}`}>
              <td>{b.score_bucket}</td>
              <td>{b.side}</td>
              <td>{b.regime}</td>
              <td>{b.n}</td>
              <td>
                {b.probability.available && b.probability.win_probability != null
                  ? `${(b.probability.win_probability * 100).toFixed(0)}%`
                  : "insufficient sample"}
              </td>
              <td>
                {b.probability.available && b.probability.ci_low != null
                  ? `${(b.probability.ci_low * 100).toFixed(0)}–${(b.probability.ci_high! * 100).toFixed(0)}%`
                  : "—"}
              </td>
              <td>
                {b.probability.available && b.probability.expectancy_r != null
                  ? b.probability.expectancy_r.toFixed(2)
                  : "—"}
              </td>
            </tr>
          ))}
          {calibration.length === 0 && (
            <tr>
              <td colSpan={7} className="empty-row">
                no calibration buckets yet
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
