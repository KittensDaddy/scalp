import { create } from "zustand";
import { WS_BASE, fetchPositionEvents, fetchPositions } from "../api/client";
import type { ActiveTrade, PositionsDeltaMessage, TradeEvent } from "../api/types";

export type ConnectionState = "connecting" | "open" | "closed";

interface PositionsStore {
  positions: ActiveTrade[];
  seq: number;
  connection: ConnectionState;
  selectedTradeId: string | null;
  timeline: TradeEvent[];
  connect: () => void;
  selectTrade: (tradeId: string | null) => void;
  loadTimeline: (tradeId: string) => Promise<void>;
}

let socket: WebSocket | null = null;
let reconnectAttempt = 0;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

async function resnapshot(set: (partial: Partial<PositionsStore>) => void) {
  const snapshot = await fetchPositions();
  set({ positions: snapshot.positions, seq: snapshot.seq });
}

export const usePositionsStore = create<PositionsStore>((set, get) => ({
  positions: [],
  seq: 0,
  connection: "closed",
  selectedTradeId: null,
  timeline: [],

  connect: () => {
    if (socket) return;

    const open = () => {
      set({ connection: "connecting" });
      socket = new WebSocket(`${WS_BASE}/api/v1/stream/positions`);

      socket.onopen = () => {
        reconnectAttempt = 0;
        set({ connection: "open" });
      };

      socket.onmessage = (event) => {
        const msg = JSON.parse(event.data as string) as PositionsDeltaMessage;
        set({ positions: msg.positions ?? [], seq: msg.seq });
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

  selectTrade: (tradeId) => {
    set({ selectedTradeId: tradeId, timeline: [] });
    if (tradeId) {
      void get().loadTimeline(tradeId);
    }
  },

  loadTimeline: async (tradeId) => {
    const resp = await fetchPositionEvents(tradeId);
    if (get().selectedTradeId === tradeId) {
      set({ timeline: resp.events });
    }
  },
}));

export function stopPositionsConnection(): void {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  socket?.close();
  socket = null;
}
