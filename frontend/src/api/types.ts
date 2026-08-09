export type Side = "LONG" | "SHORT";

export interface ScannerRow {
  symbol: string;
  side: Side;
  score: number;
  strategy: string;
  preset: string | null;
  price: number | null;
  spread_bps: number | null;
  vol_24h: number | null;
  atr_pct: number | null;
  rr: number | null;
  net_edge_r: number | null;
  state: "ACCEPTED" | "REJECTED";
  age_ms: number | null;
  reasons_top3: string[];
}

export interface ScannerSnapshot {
  seq: number;
  rows: ScannerRow[];
}

export interface ScannerDeltaMessage {
  type: "snapshot" | "delta";
  seq: number;
  rows?: ScannerRow[];
  upserts?: ScannerRow[];
  removals?: string[];
}

export interface ScoreBreakdown {
  total: number;
  components: Record<string, number>;
}

export interface SymbolDetail {
  symbol: string;
  row: ScannerRow | null;
  breakdown: ScoreBreakdown | null;
  why_not: string[];
}

export interface SelfCheckInfo {
  checked_at: string;
  environment: string;
  passed: boolean;
  details: unknown;
}

export interface HealthInfo {
  self_check: SelfCheckInfo | null;
  protection_gap_ms: { p50: number | null; p99: number | null; n: number };
}

export interface MetaInfo {
  environment: string;
  strategy_version: string;
  config_hash: string;
}

export interface DevelopingSetup {
  symbol: string;
  side: Side;
  score: number;
  missing_conditions: string[];
  projections: Record<string, string>;
  detected_at: string;
}

export interface DevelopingSnapshot {
  seq: number;
  setups: DevelopingSetup[];
}

export interface DevelopingDeltaMessage {
  type: "snapshot" | "delta";
  seq: number;
  setups?: DevelopingSetup[];
}

export type HealthLabel = "HEALTHY" | "AT_RISK" | "NEAR_STOP" | "NEAR_TP";

export type TradeEventType =
  | "OPENED"
  | "PROTECTED"
  | "BREAKEVEN_MOVED"
  | "SCORE_CHANGED"
  | "CLOSED";

export interface ActiveTrade {
  trade_id: string;
  symbol: string;
  side: Side;
  entry_price: number;
  quantity: number;
  stop_price: number;
  take_profit_price: number;
  opened_at: string;
  current_price: number;
  unrealized_r: number;
  mae_r: number;
  mfe_r: number;
  distance_to_stop_r: number;
  distance_to_tp_r: number;
  health: HealthLabel;
  initial_stop_price: number;
  protected: boolean;
  breakeven_moved: boolean;
  score: number | null;
  strategy_version: string;
  closed: boolean;
  exit_reason: string | null;
  closed_at: string | null;
}

export interface PositionsSnapshot {
  seq: number;
  positions: ActiveTrade[];
}

export interface PositionsDeltaMessage {
  type: "snapshot" | "delta";
  seq: number;
  positions?: ActiveTrade[];
}

export interface TradeEvent {
  trade_id: string;
  symbol: string;
  event_type: TradeEventType;
  ts: string;
  payload: Record<string, unknown>;
}

export interface TradeEventsResponse {
  trade_id: string;
  events: TradeEvent[];
}
