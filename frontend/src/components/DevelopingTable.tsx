import type { DevelopingSetup } from "../api/types";

interface Props {
  setups: DevelopingSetup[];
  onSelect: (symbol: string) => void;
}

export function DevelopingTable({ setups, onSelect }: Props) {
  return (
    <div className="scanner-table-wrap">
      <table className="scanner-table">
        <thead>
          <tr>
            <th>SYM</th>
            <th>SCORE</th>
            <th>S</th>
            <th>MISSING</th>
          </tr>
        </thead>
        <tbody>
          {setups.map((s) => (
            <tr key={`${s.symbol}-${s.side}`} onClick={() => onSelect(s.symbol)}>
              <td>{s.symbol}</td>
              <td>{s.score.toFixed(1)}</td>
              <td>{s.side}</td>
              <td title={Object.values(s.projections).join("\n")}>
                {s.missing_conditions.join(", ")}
              </td>
            </tr>
          ))}
          {setups.length === 0 && (
            <tr>
              <td colSpan={4} className="empty-row">
                no developing setups — nothing is near-trigger right now
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
