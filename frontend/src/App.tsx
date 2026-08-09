import { useEffect, useMemo, useState } from "react";
import { TopBar } from "./components/TopBar";
import { ScannerTable, navigateRows } from "./components/ScannerTable";
import { DevelopingTable } from "./components/DevelopingTable";
import { ActiveTradesPanel } from "./components/ActiveTradesPanel";
import { AnalyticsPanel } from "./components/AnalyticsPanel";
import { StrategyLabPanel } from "./components/StrategyLabPanel";
import { SymbolDetail } from "./components/SymbolDetail";
import { TradingViewPanel } from "./components/TradingViewPanel";
import { useScannerStore } from "./store/scannerStore";
import { useDevelopingStore } from "./store/developingStore";
import { usePositionsStore } from "./store/positionsStore";

type Tab = "scanner" | "developing" | "active" | "analytics" | "lab";

const ALERT_KEY = "scalping.alertThreshold";

export default function App() {
  const [tab, setTab] = useState<Tab>("scanner");
  const [alertThreshold, setAlertThreshold] = useState<number | null>(() => {
    const raw = localStorage.getItem(ALERT_KEY);
    return raw ? Number(raw) : null;
  });

  const rows = useScannerStore((s) => s.rows);
  const connection = useScannerStore((s) => s.connection);
  const resnapshotCount = useScannerStore((s) => s.resnapshotCount);
  const selected = useScannerStore((s) => s.selectedSymbol);
  const select = useScannerStore((s) => s.select);
  const connect = useScannerStore((s) => s.connect);

  const setups = useDevelopingStore((s) => s.setups);
  const connectDeveloping = useDevelopingStore((s) => s.connect);

  const positions = usePositionsStore((s) => s.positions);
  const selectedTradeId = usePositionsStore((s) => s.selectedTradeId);
  const timeline = usePositionsStore((s) => s.timeline);
  const connectPositions = usePositionsStore((s) => s.connect);
  const selectTrade = usePositionsStore((s) => s.selectTrade);

  const rowList = useMemo(
    () =>
      Object.values(rows).sort((a, b) => {
        const d = b.score - a.score;
        return d !== 0 ? d : a.symbol.localeCompare(b.symbol);
      }),
    [rows],
  );

  useEffect(() => {
    connect();
    connectDeveloping();
    connectPositions();
  }, [connect, connectDeveloping, connectPositions]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (tab !== "scanner") return;
      if (e.key === "j") {
        select(navigateRows(rowList, selected, 1) ?? selected);
      } else if (e.key === "k") {
        select(navigateRows(rowList, selected, -1) ?? selected);
      } else if (e.key === "p" && selected) {
        // pin toggle is handled in the table button; p focuses pin via click simulation
        const btn = document.querySelector(
          `tr[data-symbol="${selected}"] .pin-btn`,
        ) as HTMLButtonElement | null;
        btn?.click();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tab, rowList, selected, select]);

  function onAlertChange(value: string) {
    if (!value) {
      setAlertThreshold(null);
      localStorage.removeItem(ALERT_KEY);
      return;
    }
    const n = Number(value);
    setAlertThreshold(n);
    localStorage.setItem(ALERT_KEY, String(n));
  }

  return (
    <div className="app">
      <TopBar connection={connection} resnapshotCount={resnapshotCount} />
      <main className="main-grid">
        <section className="scanner-pane">
          <div className="pane-tabs">
            {(
              [
                ["scanner", `Scanner`],
                ["developing", `Developing (${setups.length})`],
                ["active", `Active (${positions.length})`],
                ["analytics", "Analytics"],
                ["lab", "Strategy Lab"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                className={tab === id ? "tab-active" : ""}
                onClick={() => setTab(id)}
              >
                {label}
              </button>
            ))}
          </div>
          {tab === "scanner" && (
            <>
              <div className="pane-toolbar">
                <label className="muted">
                  alert ≥{" "}
                  <input
                    className="token-input"
                    style={{ width: 64 }}
                    type="number"
                    placeholder="off"
                    value={alertThreshold ?? ""}
                    onChange={(e) => onAlertChange(e.target.value)}
                  />
                </label>
              </div>
              <ScannerTable
                rows={rowList}
                selected={selected}
                onSelect={select}
                alertThreshold={alertThreshold}
              />
            </>
          )}
          {tab === "developing" && <DevelopingTable setups={setups} onSelect={select} />}
          {tab === "active" && (
            <ActiveTradesPanel
              positions={positions}
              selectedTradeId={selectedTradeId}
              timeline={timeline}
              onSelect={(tradeId, symbol) => {
                selectTrade(tradeId);
                select(symbol);
              }}
            />
          )}
          {tab === "analytics" && <AnalyticsPanel />}
          {tab === "lab" && <StrategyLabPanel />}
        </section>
        <section className="chart-pane">
          <TradingViewPanel
            symbol={selected}
            position={
              positions.find((t) => t.symbol === selected && !t.closed) ?? null
            }
          />
        </section>
        <section className="detail-pane">
          <SymbolDetail symbol={selected} />
        </section>
      </main>
      {positions.length > 0 && (
        <footer className="active-bar">
          {positions.map((t) => (
            <button
              key={t.trade_id}
              type="button"
              className="active-bar-chip"
              onClick={() => {
                setTab("active");
                selectTrade(t.trade_id);
                select(t.symbol);
              }}
            >
              <span>{t.symbol}</span>
              <span className={t.side === "LONG" ? "r-pos" : "r-neg"}>{t.side}</span>
              <span className={t.unrealized_r >= 0 ? "r-pos" : "r-neg"}>
                {t.unrealized_r >= 0 ? "+" : ""}
                {t.unrealized_r.toFixed(2)}R
              </span>
              <span className={`health-label health-${t.health.toLowerCase().replace("_", "-")}`}>
                {t.health}
              </span>
            </button>
          ))}
        </footer>
      )}
    </div>
  );
}
