import type { ActiveTrade, HealthLabel, TradeEvent } from "../api/types";

interface Props {
  positions: ActiveTrade[];
  selectedTradeId: string | null;
  timeline: TradeEvent[];
  onSelect: (tradeId: string, symbol: string) => void;
}

function formatR(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}R`;
}

function healthClass(health: HealthLabel): string {
  switch (health) {
    case "HEALTHY":
      return "health-healthy";
    case "AT_RISK":
      return "health-at-risk";
    case "NEAR_STOP":
      return "health-near-stop";
    case "NEAR_TP":
      return "health-near-tp";
  }
}

function summarizePayload(event: TradeEvent): string {
  const p = event.payload;
  switch (event.event_type) {
    case "OPENED":
      return `entry ${p.entry_price} · stop ${p.stop_price} · tp ${p.take_profit_price}`;
    case "PROTECTED":
      return p.t_protection_ms != null ? `t_protection ${p.t_protection_ms}ms` : "stops ACKed";
    case "BREAKEVEN_MOVED":
      return `stop ${p.old_stop} → ${p.new_stop}`;
    case "SCORE_CHANGED":
      return `${p.old_score ?? "—"} → ${p.new_score}${p.explanation ? ` · ${p.explanation}` : ""}`;
    case "CLOSED":
      return `${p.exit_reason} @ ${p.exit_price} · ${formatR(Number(p.r_multiple ?? 0))}`;
    default:
      return JSON.stringify(p);
  }
}

export function ActiveTradesPanel({ positions, selectedTradeId, timeline, onSelect }: Props) {
  return (
    <div className="active-trades">
      {positions.length === 0 ? (
        <div className="active-empty">no open positions</div>
      ) : (
        <div className="active-cards">
          {positions.map((t) => (
            <button
              key={t.trade_id}
              type="button"
              className={`active-card ${selectedTradeId === t.trade_id ? "active-card-selected" : ""}`}
              onClick={() => onSelect(t.trade_id, t.symbol)}
            >
              <div className="active-card-top">
                <span className="active-sym">{t.symbol}</span>
                <span className={`badge ${t.side === "LONG" ? "badge-long" : "badge-short"}`}>
                  {t.side}
                </span>
                <span className={`active-r ${t.unrealized_r >= 0 ? "r-pos" : "r-neg"}`}>
                  {formatR(t.unrealized_r)}
                </span>
                <span className={`health-label ${healthClass(t.health)}`}>{t.health}</span>
              </div>
              <div className="active-card-meta">
                <span>MAE {t.mae_r.toFixed(2)}R</span>
                <span>MFE {t.mfe_r.toFixed(2)}R</span>
                <span>→stop {t.distance_to_stop_r.toFixed(2)}R</span>
                <span>→tp {t.distance_to_tp_r.toFixed(2)}R</span>
                {t.protected ? <span className="flag-ok">PROT</span> : <span className="flag-warn">NAKED</span>}
                {t.breakeven_moved && <span className="flag-ok">BE</span>}
              </div>
            </button>
          ))}
        </div>
      )}

      {selectedTradeId && (
        <div className="timeline">
          <h3>Timeline</h3>
          {timeline.length === 0 ? (
            <div className="active-empty">loading events…</div>
          ) : (
            <ol className="timeline-list">
              {timeline.map((e, i) => (
                <li key={`${e.event_type}-${e.ts}-${i}`}>
                  <span className="timeline-type">{e.event_type}</span>
                  <span className="timeline-ts">{new Date(e.ts).toLocaleTimeString()}</span>
                  <span className="timeline-detail">{summarizePayload(e)}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}
