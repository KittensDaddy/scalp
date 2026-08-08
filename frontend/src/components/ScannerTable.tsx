import { useMemo, useState } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import type { ScannerRow } from "../api/types";

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

const columns = [
  columnHelper.accessor("symbol", { header: "SYM" }),
  columnHelper.accessor("score", {
    header: "SCORE",
    cell: (info) => info.getValue().toFixed(1),
  }),
  columnHelper.accessor("side", { header: "S" }),
  columnHelper.accessor("price", { header: "PRICE", cell: (info) => fmt(info.getValue(), 4) }),
  columnHelper.accessor("spread_bps", { header: "SPREAD", cell: (info) => fmt(info.getValue(), 1) }),
  columnHelper.accessor("atr_pct", {
    header: "ATR%",
    cell: (info) => (info.getValue() === null ? "—" : `${(info.getValue()! * 100).toFixed(2)}%`),
  }),
  columnHelper.accessor("state", { header: "STATE" }),
  columnHelper.accessor("age_ms", { header: "AGE", cell: (info) => ageLabel(info.getValue()) }),
  columnHelper.accessor("reasons_top3", {
    header: "WHY NOT",
    cell: (info) => info.getValue().join(", ") || "—",
  }),
];

interface Props {
  rows: ScannerRow[];
  selected: string | null;
  onSelect: (symbol: string) => void;
}

export function ScannerTable({ rows, selected, onSelect }: Props) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "score", desc: true }]);

  const data = useMemo(() => rows, [rows]);

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="scanner-table-wrap">
      <table className="scanner-table">
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
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
            return (
              <tr
                key={row.id}
                onClick={() => onSelect(row.original.symbol)}
                className={
                  (row.original.symbol === selected ? "row-selected " : "") +
                  (row.original.state === "REJECTED" ? "row-rejected " : "") +
                  (stale ? "row-stale" : "")
                }
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                ))}
              </tr>
            );
          })}
          {table.getRowModel().rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="empty-row">
                no symbols yet — waiting for the scanner to publish
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
