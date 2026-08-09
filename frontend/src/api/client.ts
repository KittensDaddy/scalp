import type {
  DevelopingSnapshot,
  HealthInfo,
  MetaInfo,
  PositionsSnapshot,
  ScannerSnapshot,
  SymbolDetail,
  TradeEventsResponse,
} from "./types";

// Default to the API on the same host the page was served from, so opening the
// dashboard at http://<miniserver-ip>:5173 talks to http://<miniserver-ip>:8000.
// Hardcoding 127.0.0.1 pointed a LAN browser at the *laptop*, which silently
// serves nothing. VITE_API_BASE still overrides for split deployments.
function defaultApiBase(): string {
  const env = import.meta.env.VITE_API_BASE as string | undefined;
  if (env) {
    return env;
  }
  if (typeof window !== "undefined" && window.location?.hostname) {
    const { protocol, hostname, port, origin } = window.location;
    // Vite dev server: the API is the sibling process on 8000.
    if (port === "5173") {
      return `${protocol}//${hostname}:8000`;
    }
    // Served by the API itself (the headless/miniserver path) — same origin, so
    // no CORS is involved and it works on whatever port the API is bound to.
    return origin;
  }
  return "http://127.0.0.1:8000";
}

export const API_BASE: string = defaultApiBase();

export const WS_BASE: string = API_BASE.replace(/^http/, "ws");

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) {
    throw new Error(`${path} -> ${resp.status}`);
  }
  return (await resp.json()) as T;
}

export function fetchScanner(): Promise<ScannerSnapshot> {
  return getJson<ScannerSnapshot>("/api/v1/scanner");
}

export function fetchSymbol(symbol: string): Promise<SymbolDetail> {
  return getJson<SymbolDetail>(`/api/v1/symbol/${encodeURIComponent(symbol)}`);
}

export function fetchHealth(): Promise<HealthInfo> {
  return getJson<HealthInfo>("/api/v1/health");
}

export function fetchMeta(): Promise<MetaInfo> {
  return getJson<MetaInfo>("/api/v1/meta");
}

export function fetchDeveloping(): Promise<DevelopingSnapshot> {
  return getJson<DevelopingSnapshot>("/api/v1/developing");
}

export function fetchPositions(): Promise<PositionsSnapshot> {
  return getJson<PositionsSnapshot>("/api/v1/positions");
}

export function fetchPositionEvents(tradeId: string): Promise<TradeEventsResponse> {
  return getJson<TradeEventsResponse>(
    `/api/v1/positions/${encodeURIComponent(tradeId)}/events`,
  );
}

export interface ControlResult {
  ok: boolean;
  status: number;
  detail?: string;
}

async function control(path: string, method: "POST" | "DELETE", token: string): Promise<ControlResult> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}` },
  });
  if (resp.ok) {
    return { ok: true, status: resp.status };
  }
  let detail: string | undefined;
  try {
    const body = (await resp.json()) as { detail?: string };
    detail = body.detail;
  } catch {
    detail = undefined;
  }
  return { ok: false, status: resp.status, detail };
}

export function engageKillSwitch(token: string): Promise<ControlResult> {
  return control("/api/v1/control/kill-switch", "POST", token);
}

export function clearKillSwitch(token: string): Promise<ControlResult> {
  return control("/api/v1/control/kill-switch", "DELETE", token);
}

export function fetchKillSwitchStatus(): Promise<{ killed: boolean }> {
  return getJson<{ killed: boolean }>("/api/v1/control/kill-switch");
}
