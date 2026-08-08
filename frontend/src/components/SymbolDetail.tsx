import { useEffect, useState } from "react";
import { fetchSymbol } from "../api/client";
import type { SymbolDetail as SymbolDetailData } from "../api/types";

interface Props {
  symbol: string | null;
}

export function SymbolDetail({ symbol }: Props) {
  const [detail, setDetail] = useState<SymbolDetailData | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!symbol) {
      setDetail(null);
      return;
    }
    setLoading(true);
    fetchSymbol(symbol)
      .then(setDetail)
      .finally(() => setLoading(false));
  }, [symbol]);

  if (!symbol) {
    return (
      <div className="symbol-detail empty">
        <p className="muted">select a row to see detail</p>
      </div>
    );
  }

  return (
    <div className="symbol-detail">
      <h2>{symbol}</h2>
      {loading && <p className="muted">loading…</p>}
      {detail?.row && (
        <div className="detail-row-summary">
          <span className={`badge badge-${detail.row.side.toLowerCase()}`}>{detail.row.side}</span>
          <span className="score-big">{detail.row.score.toFixed(1)}</span>
          <span className={`badge badge-${detail.row.state.toLowerCase()}`}>{detail.row.state}</span>
        </div>
      )}

      <h3>Score breakdown</h3>
      {detail?.breakdown ? (
        <table className="breakdown-table">
          <tbody>
            {Object.entries(detail.breakdown.components).map(([name, value]) => (
              <tr key={name}>
                <td>{name}</td>
                <td className={value < 0 ? "neg" : ""}>{value.toFixed(2)}</td>
              </tr>
            ))}
            <tr className="breakdown-total">
              <td>total</td>
              <td>{detail.breakdown.total.toFixed(2)}</td>
            </tr>
          </tbody>
        </table>
      ) : (
        <p className="muted">no breakdown available</p>
      )}

      <h3>Why not?</h3>
      {detail?.why_not.length ? (
        <ul className="why-not-list">
          {detail.why_not.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">—</p>
      )}
    </div>
  );
}
