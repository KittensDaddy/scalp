import type { DevelopingSnapshot, HealthInfo, MetaInfo, ScannerSnapshot, SymbolDetail } from "./types";

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://127.0.0.1:8000";

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
