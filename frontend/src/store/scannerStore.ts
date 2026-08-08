import { create } from "zustand";
import { WS_BASE, fetchScanner } from "../api/client";
import type { ScannerDeltaMessage, ScannerRow } from "../api/types";

export type ConnectionState = "connecting" | "open" | "closed";

interface ScannerStore {
  rows: Record<string, ScannerRow>;
  seq: number;
  connection: ConnectionState;
  lastMessageAt: number | null;
  resnapshotCount: number;
  selectedSymbol: string | null;
  connect: () => void;
  select: (symbol: string | null) => void;
}

let socket: WebSocket | null = null;
let reconnectAttempt = 0;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

async function resnapshot(set: (partial: Partial<ScannerStore>) => void) {
  const snapshot = await fetchScanner();
  const rows: Record<string, ScannerRow> = {};
  for (const row of snapshot.rows) rows[row.symbol] = row;
  set({ rows, seq: snapshot.seq });
}

export const useScannerStore = create<ScannerStore>((set, get) => ({
  rows: {},
  seq: 0,
  connection: "closed",
  lastMessageAt: null,
  resnapshotCount: 0,
  selectedSymbol: null,

  select: (symbol) => set({ selectedSymbol: symbol }),

  connect: () => {
    if (socket) return;

    const open = () => {
      set({ connection: "connecting" });
      socket = new WebSocket(`${WS_BASE}/api/v1/stream/scanner`);

      socket.onopen = () => {
        reconnectAttempt = 0;
        set({ connection: "open" });
      };

      socket.onmessage = (event) => {
        const msg = JSON.parse(event.data as string) as ScannerDeltaMessage;
        set({ lastMessageAt: Date.now() });

        if (msg.type === "snapshot") {
          const rows: Record<string, ScannerRow> = {};
          for (const row of msg.rows ?? []) rows[row.symbol] = row;
          set({ rows, seq: msg.seq });
          return;
        }

        // delta: only apply if it's the very next seq; otherwise resnapshot
        // (SCANNER_DASHBOARD_PLAN.md §G: "Client resnapshots if it misses a seq")
        const currentSeq = get().seq;
        if (msg.seq !== currentSeq + 1) {
          set((s) => ({ resnapshotCount: s.resnapshotCount + 1 }));
          void resnapshot(set);
          return;
        }
        const rows = { ...get().rows };
        for (const row of msg.upserts ?? []) rows[row.symbol] = row;
        for (const symbol of msg.removals ?? []) delete rows[symbol];
        set({ rows, seq: msg.seq });
      };

      socket.onclose = () => {
        set({ connection: "closed" });
        socket = null;
        const delay = Math.min(30_000, 1000 * 2 ** reconnectAttempt);
        reconnectAttempt += 1;
        reconnectTimer = setTimeout(open, delay);
      };

      socket.onerror = () => {
        socket?.close();
      };
    };

    // seed from REST first so the table isn't empty while the WS handshakes
    void resnapshot(set);
    open();
  },
}));

export function stopScannerConnection(): void {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  socket?.close();
  socket = null;
}
