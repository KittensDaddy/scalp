import { useEffect, useState } from "react";
import { TopBar } from "./components/TopBar";
import { ScannerTable } from "./components/ScannerTable";
import { DevelopingTable } from "./components/DevelopingTable";
import { SymbolDetail } from "./components/SymbolDetail";
import { TradingViewPanel } from "./components/TradingViewPanel";
import { useScannerStore } from "./store/scannerStore";
import { useDevelopingStore } from "./store/developingStore";

type Tab = "scanner" | "developing";

export default function App() {
  const [tab, setTab] = useState<Tab>("scanner");

  const rows = useScannerStore((s) => s.rows);
  const connection = useScannerStore((s) => s.connection);
  const resnapshotCount = useScannerStore((s) => s.resnapshotCount);
  const selected = useScannerStore((s) => s.selectedSymbol);
  const select = useScannerStore((s) => s.select);
  const connect = useScannerStore((s) => s.connect);

  const setups = useDevelopingStore((s) => s.setups);
  const connectDeveloping = useDevelopingStore((s) => s.connect);

  useEffect(() => {
    connect();
    connectDeveloping();
  }, [connect, connectDeveloping]);

  const rowList = Object.values(rows);

  return (
    <div className="app">
      <TopBar connection={connection} resnapshotCount={resnapshotCount} />
      <main className="main-grid">
        <section className="scanner-pane">
          <div className="pane-tabs">
            <button
              className={tab === "scanner" ? "tab-active" : ""}
              onClick={() => setTab("scanner")}
            >
              Scanner
            </button>
            <button
              className={tab === "developing" ? "tab-active" : ""}
              onClick={() => setTab("developing")}
            >
              Developing ({setups.length})
            </button>
          </div>
          {tab === "scanner" ? (
            <ScannerTable rows={rowList} selected={selected} onSelect={select} />
          ) : (
            <DevelopingTable setups={setups} onSelect={select} />
          )}
        </section>
        <section className="chart-pane">
          <TradingViewPanel symbol={selected} />
        </section>
        <section className="detail-pane">
          <SymbolDetail symbol={selected} />
        </section>
      </main>
    </div>
  );
}
