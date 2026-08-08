# PLAN OF ACTION (v2)

Status: **Phase 10 complete**. Binance TH removed from scope — this project
targets **Binance USDⓈ-M Futures only** (`BTCUSDT`, `ETHUSDT` initially).

**v2 changes (2026-08-09):** live API self-check phase, quantified
protection-gap requirement, maker adverse-selection instrumentation,
pre-registered evidence bar before live, candle backtest demoted to sanity
check, config-hash provenance, funding awareness, asymmetric kill-switch
auth, edge-model sample plan. CAEMS rules updated separately in
`strategy-caems.md` (v2).

## 1. Objective

Build a reproducible trading system that can:

- prove whether CAEMS has a net executable edge after all costs;
- trade that edge conservatively when it exists;
- refuse trades when economics are unfavorable;
- survive exchange/process failures; and
- record enough evidence to determine exactly why it makes or loses money.

## 2. Verified exchange facts (research date: 2026-08-08)

| Topic | Binance USDⓈ-M Futures |
|---|---|
| REST base | `https://fapi.binance.com` |
| Testnet REST | `https://demo-fapi.binance.com` |
| WS base | `wss://fstream.binance.com` (see below) |
| Products | USDT-margined perpetual futures (long + short) |
| Post-only | `timeInForce=GTX` (no `LIMIT_MAKER` type on futures) |
| Conditional orders | **Algo Order API** `POST /fapi/v1/algoOrder` since 2025-12-09 |
| Legacy conditional | `POST /fapi/v1/order` now rejects `STOP_*`/`TAKE_PROFIT_*` with `-4120` |
| Stop types | `STOP_MARKET`, `TAKE_PROFIT_MARKET`, `STOP`, `TAKE_PROFIT`, `TRAILING_STOP_MARKET` via algo endpoint |
| Reduce/close | `reduceOnly`, `closePosition` supported |
| WS migration | Legacy `/ws` & `/stream` retired 2026-04-23 |
| New WS paths | `/public` (bookTicker), `/market` (klines/mark/depth), `/private` (user stream) |
| Combined streams | Must not mix categories on one connection |
| Signing | HMAC-SHA256, `X-MBX-APIKEY`, `timestamp` + `recvWindow` |
| Rate limits | Weight/IP (futures ≈2400/min) + per-account order count |
| Testnet status | API available; web mock-trading UI under upgrade |

### 2a. Continuous re-verification (new)

A research-date table is not protection. The algo-order migration and WS path
split are recent, breaking, and load-bearing for safety (the protective-stop
path depends on both). Therefore:

- **Startup self-check** (testnet + live): submit and cancel a minimal algo
  order, open one WS connection per category (`/public`, `/market`,
  `/private`), verify expected message shapes. Any divergence from the table
  above → refuse to start trading, raise incident.
- Self-check results persisted with timestamps; dashboard `/health` exposes
  the last verification.
- Algo endpoint has its own rate limits and failure modes distinct from
  `/fapi/v1/order` — tracked separately in the rate limiter.

## 3. Architecture

A **modular asyncio monolith** with strict separation:

```
market data -> validate -> indicators -> signal -> liquidity -> cost -> edge
  -> risk engine (approve/size) -> OMS -> exchange -> reconcile -> protect
  -> monitor -> exit -> accounting -> analytics
```

Modules: unchanged from v1 (`config/`, `domain/`, `exchanges/base/`,
`exchanges/binance/`, `market_data/`, `indicators/`, `strategies/caems/`,
`risk/`, `execution/`, `costmodel/`, `edge/`, `accounting/`, `persistence/`,
`backtest/` `replay/` `paper/`, `api/`, `cli/`, `monitoring/`).

New responsibilities:

- `accounting/` additionally records **entry-attempt outcomes and markouts**
  (maker fill / partial / taker convert / abandoned; mid at +5 s / +30 s) —
  see strategy §Adverse-selection instrumentation.
- `costmodel/` gains **funding awareness**: positions whose remaining time
  stop straddles a funding timestamp include expected funding in the cost
  gate (scalps usually won't; stalled trades do).
- `persistence/` stores a **config hash** with every signal, rejection, and
  trade, so "reproducible from persisted data" survives config edits.
- `execution/` protection requirement is quantified — see §5a.

## 4. Implementation phases (revised)

| # | Phase | Status |
|---|---|---|
| 0 | Research + plan | done |
| 1 | Foundation | done |
| 2 | Market data + indicators | done |
| 3 | CAEMS signal engine + gates | done |
| 4 | Risk engine + drawdown machine | done |
| 5 | Candle backtester + cost/edge model | done |
| 6 | Binance adapter (REST, new WS, algo orders) | done |
| 7 | OMS + reconciliation + protective orders | done |
| 8 | Paper trading | done |
| 9 | Event replay | done |
| 10 | Dashboard | done |
| **10a** | **CAEMS v2 rules + A/B replay validation (variants A–D)** | new |
| **10b** | **Instrumentation: markouts, config hash, funding cost, self-check** | new |
| **10c** | **Paper campaign to the evidence bar (§8)** | new |
| 11 | Testnet verification (now with protection-gap measurement §5a) | |
| 12 | Tiny-capital live (entry gated by §8, not by calendar) | |

10a/10b are small and independently testable; 10c is time — it runs while
scanner/dashboard work (separate plan) proceeds in parallel.

## 5. Key decisions and tradeoffs

- **One execution pipeline for all modes** — unchanged.
- **Strategy ⇄ risk split** — unchanged and structural.
- **Reconcile before retry** — unchanged; idempotency via client order IDs.
- **Persist everything** — now including strength values on every evaluation,
  entry-attempt outcomes, markouts, and config hash.
- **SQLite now, PostgreSQL-compatible schema** — unchanged.
- **Candle backtest demoted (new).** CAEMS uses GTX maker entries; a candle
  backtester cannot model queue position, maker fill probability, or intrabar
  stop-outs. The backtester's role is now explicitly **gross-signal sanity
  check only**. It contributes zero evidence toward the go-live decision;
  only paper/testnet forward data counts. This is written down so the
  backtest cannot quietly become the justification for live capital.
- **Kill-switch asymmetry (new).** Killing must be easy; un-killing must be
  hard. `POST /control/kill-switch` requires the standard control token;
  `DELETE` requires a **separate stronger token**
  (`dashboard_unkill_token`) that is not stored on the dashboard host.

## 5a. Protection-gap requirement (new)

With stops on a separate endpoint from the GTX entry, a fill→protected window
is unavoidable. It is now a measured, bounded quantity:

- Metric: `t_protection = ACK(stop) & ACK(tp) − fill_time`, per trade,
  p50/p99 on `/health`.
- **Hard rule:** if protection unconfirmed within `protection_timeout_ms`
  (default 2000 ms) → emergency reduce-only market close + kill switch +
  incident. Retried placement happens *within* the window, not instead of it.
- **Testnet acceptance criterion:** p99 `t_protection` < 1500 ms over ≥100
  fills before live is considered.

## 6. Open risks

- Binance API changes — now partially mitigated by §2a self-check, still a
  standing risk.
- Futures testnet web UI under maintenance; API path still usable.
- No guaranteed historical trades/bookTicker for 2021–2026; replay depends on
  data availability — one more reason the backtest is sanity-only (§5).
- **Edge-model sample starvation (new).** Bucketed expectancy on two symbols
  accrues slowly, and buckets fragment small n further. Plan: (a) buckets
  stay coarse (side × regime only) until n permits finer keys; (b) widening
  the symbol universe (scanner plan) is the real fix; (c) pooling across
  symbols is itself a hypothesis — test per-symbol vs pooled expectancy
  before trusting pooled numbers.
- **Maker adverse selection (new).** May erase the maker fee saving; decided
  empirically by the pre-registered markout rule in strategy §Adverse-
  selection instrumentation, not by intuition.

## 6a. Dashboard (Phase 10) — as built

Served via `scalping --dashboard`. Read endpoints under `/api/v1/`
(`/account`, `/positions`, `/orders`, `/fills`, `/signals`, `/rejections`,
`/equity`, `/risk`, `/meta`); `/health` reports heartbeat age, latency
p50/p99, **last self-check result, protection-gap p50/p99 (new)**. Control
endpoints require `Authorization: Bearer <token>`; kill-switch clear
additionally requires the un-kill token (§5).

## 6b. Trading loop — unchanged

`scalping --run`: `SymbolTrader` per-symbol event loop, `Trader` supervisor,
`PersistenceWriter`. Persisted hard kill honored at startup.

## 7. Out of scope (per owner)

- Binance TH; non-Binance venues.
- Strategy parameter tuning of frozen knobs (see strategy §Frozen parameters)
  — any change is a new strategy version, validated independently.

## 8. Evidence bar for going live (new, pre-registered NOW)

The go/no-go criterion is fixed before any results exist, so it cannot be
bent to fit them. All of the following, on paper+testnet forward data only:

1. **n ≥ 300 completed trades** (entry attempts ≥ 500) under CAEMS v2 final
   variant.
2. **Net expectancy > 0 with 95% CI excluding zero** (bootstrap over trades),
   after fees, spread, slippage, and funding.
3. **Profit factor ≥ 1.15** on the same sample.
4. **Max drawdown ≤ 6R** over the campaign.
5. **Protection gap** p99 < 1500 ms (§5a) on testnet.
6. **Maker/taker decision resolved** by the markout rule (either default
   confirmed or switched — not left ambiguous).
7. **Zero unreconciled positions** across ≥3 forced restarts and ≥3 forced
   disconnects on testnet.
8. Kill switch verified end-to-end on testnet (set → restart → still killed
   → un-kill with separate token).

If the bar is not met, the outcome is not "tune and retry the same sample" —
it is a documented negative result, and any revised strategy restarts the
campaign as a new version. Failing to find an edge is a success of the
system's purpose.

Tiny-capital live (Phase 12) then starts with: max 1 position, minimum
exchange size, daily loss cap 1R, human review of the first 20 trades.
