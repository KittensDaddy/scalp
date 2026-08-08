import { create } from "zustand";
import { WS_BASE, fetchDeveloping } from "../api/client";
import type { DevelopingDeltaMessage, DevelopingSetup } from "../api/types";

export type ConnectionState = "connecting" | "open" | "closed";

interface DevelopingStore {
  setups: DevelopingSetup[];
  seq: number;
  connection: ConnectionState;
  connect: () => void;
}

let socket: WebSocket | null = null;
let reconnectAttempt = 0;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

async function resnapshot(set: (partial: Partial<DevelopingStore>) => void) {
  const snapshot = await fetchDeveloping();
  set({ setups: snapshot.setups, seq: snapshot.seq });
}

export const useDevelopingStore = create<DevelopingStore>((set) => ({
  setups: [],
  seq: 0,
  connection: "closed",

  connect: () => {
    if (socket) return;

    const open = () => {
      set({ connection: "connecting" });
      socket = new WebSocket(`${WS_BASE}/api/v1/stream/developing`);

      socket.onopen = () => {
        reconnectAttempt = 0;
        set({ connection: "open" });
      };

      socket.onmessage = (event) => {
        const msg = JSON.parse(event.data as string) as DevelopingDeltaMessage;
        // the developing feed republishes the full ranked list every pass rather
        // than upserts/removals (SCANNER_DASHBOARD_PLAN.md §S7 has no delta shape
        // for it), so any message — snapshot or otherwise — replaces state wholesale.
        set({ setups: msg.setups ?? [], seq: msg.seq });
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

    void resnapshot(set);
    open();
  },
}));

export function stopDevelopingConnection(): void {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  socket?.close();
  socket = null;
}
