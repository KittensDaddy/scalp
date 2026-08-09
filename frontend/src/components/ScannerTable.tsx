import { useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import type { ScannerRow } from "../api/types";

const PIN_KEY = "scalping.pinnedSymbols";
const PRESET_KEY = "scalping.columnPreset";
const SCROLL_KEY = "scalping.scannerScroll";

const columnHelper = createColumnHelper<ScannerRow>();

function fmt(n: number | null, digits = 2): string {
  return n === null ? "—" : n.toFixed(digits);
}

function ageLabel(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return "<1s";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.round(s / 60)}m`;
}

function loadPins(): Set<string> {
  try {
    const raw = localStorage.getItem(PIN_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function savePins(pins: Set<string>) {
  localStorage.setItem(PIN_KEY, JSON.stringify([...pins]));
}

const allColumns = [
  columnHelper.accessor("symbol", { header: "SYM", id: "symbol" }),
  columnHelper.accessor("score", {
    header: "SCORE",
    id: "score",
    cell: (info) => info.getValue().toFixed(1),
  }),
  columnHelper.accessor("side", { header: "S", id: "side" }),
  columnHelper.accessor("strategy", { header: "STRAT", id: "strategy" }),
  columnHelper.accessor("preset", {
    header: "PRESET",
    id: "preset",
    cell: (info) => info.getValue() ?? "—",
  }),
  columnHelper.accessor("price", {
    header: "PRICE",
    id: "price",
    cell: (info) => fmt(info.getValue(), 4),
  }),
  columnHelper.accessor("spread_bps", {
    header: "SPREAD",
    id: "spread_bps",
    cell: (info) => fmt(info.getValue(), 1),
  }),
  columnHelper.accessor("atr_pct", {
    header: "ATR%",
    id: "atr_pct",
    cell: (info) => (info.getValue() === null ? "—" : `${(info.getValue()! * 100).toFixed(2)}%`),
  }),
  columnHelper.accessor("state", { header: "STATE", id: "state" }),
  columnHelper.accessor("age_ms", {
    header: "AGE",
    id: "age_ms",
    cell: (info) => ageLabel(info.getValue()),
  }),
  columnHelper.accessor("reasons_top3", {
    header: "WHY NOT",
    id: "reasons_top3",
    cell: (info) => info.getValue().join(", ") || "—",
  }),
];

interface Props {
  rows: ScannerRow[];
  selected: string | null;
  onSelect: (symbol: string) => void;
  alertThreshold: number | null;
}

export function ScannerTable({ rows, selected, onSelect, alertThreshold }: Props) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "score", desc: true }]);
  const [pins, setPins] = useState<Set<string>>(() => loadPins());
  const [compact, setCompact] = useState(() => localStorage.getItem(PRESET_KEY) === "compact");
  const scrollRef = useRef<HTMLDivElement>(null);
  const scrollTopRef = useRef(0);
  const restoredRef = useRef(false);

  const columns = useMemo(() => {
    if (!compact) return allColumns;
    const keep = new Set(["symbol", "score", "side", "state", "reasons_top3"]);
    return allColumns.filter((c) => keep.has(c.id as string));
  }, [compact]);

  const data = useMemo(() => {
    const pinned = rows.filter((r) => pins.has(r.symbol));
    const rest = rows.filter((r) => !pins.has(r.symbol));
    // Stable secondary key so score ties don't reshuffle DOM every tick.
    const bySym = (a: ScannerRow, b: ScannerRow) => a.symbol.localeCompare(b.symbol);
    pinned.sort(bySym);
    rest.sort(bySym);
    return [...pinned, ...rest];
  }, [rows, pins]);

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row) => row.symbol,
  });

  // Restore scroll after live snapshot re-renders (and once after hard refresh).
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (!restoredRef.current) {
      restoredRef.current = true;
      const saved = Number(sessionStorage.getItem(SCROLL_KEY) ?? "0");
      if (saved > 0) {
        scrollTopRef.current = saved;
        el.scrollTop = saved;
        return;
      }
    }
    if (el.scrollTop !== scrollTopRef.current) {
      el.scrollTop = scrollTopRef.current;
    }
  });

  function togglePin(symbol: string) {
    setPins((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      savePins(next);
      return next;
    });
  }

  function toggleCompact() {
    setCompact((c) => {
      const next = !c;
      localStorage.setItem(PRESET_KEY, next ? "compact" : "full");
      return next;
    });
  }

  return (
    <div className="scanner-panel">
      <div className="pane-toolbar">
        <button type="button" className="btn btn-unkill" onClick={toggleCompact}>
          {compact ? "columns: compact" : "columns: full"}
        </button>
        <span className="muted">pins {pins.size} · j/k navigate · p pin</span>
      </div>
      <div
        className="scanner-table-wrap"
        ref={scrollRef}
        onScroll={(e) => {
          scrollTopRef.current = e.currentTarget.scrollTop;
          sessionStorage.setItem(SCROLL_KEY, String(scrollTopRef.current));
        }}
      >
        <table className="scanner-table">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                <th />
                {hg.headers.map((header) => (
                  <th key={header.id} onClick={header.column.getToggleSortingHandler()}>
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {{ asc: " ▲", desc: " ▼" }[header.column.getIsSorted() as string] ?? ""}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => {
              const stale = (row.original.age_ms ?? 0) > 90_000;
              const alertHit =
                alertThreshold != null && row.original.score >= alertThreshold;
              return (
                <tr
                  key={row.id}
                  data-symbol={row.original.symbol}
                  onClick={() => onSelect(row.original.symbol)}
                  className={
                    (row.original.symbol === selected ? "row-selected " : "") +
                    (row.original.state === "REJECTED" ? "row-rejected " : "") +
                    (stale ? "row-stale " : "") +
                    (alertHit ? "row-alert" : "")
                  }
                >
                  <td>
                    <button
                      type="button"
                      className="pin-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        togglePin(row.original.symbol);
                      }}
                      title="pin"
                    >
                      {pins.has(row.original.symbol) ? "★" : "☆"}
                    </button>
                  </td>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              );
            })}
            {table.getRowModel().rows.length === 0 && (
              <tr>
                <td colSpan={columns.length + 1} className="empty-row">
                  no symbols yet — waiting for the scanner to publish
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Hotkey helper used by App — j/k move selection through sorted row list. */
export function navigateRows(
  rows: ScannerRow[],
  selected: string | null,
  direction: 1 | -1,
): string | null {
  if (rows.length === 0) return selected;
  const idx = rows.findIndex((r) => r.symbol === selected);
  const next = idx < 0 ? 0 : Math.max(0, Math.min(rows.length - 1, idx + direction));
  return rows[next]?.symbol ?? selected;
}
