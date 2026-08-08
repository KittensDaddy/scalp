# Binance USDⓈ-M Futures Scalping Scanner & Dashboard — Implementation Plan

Status: planning only. No repo was provided in this session, so the current-state audit (§A) is derived from the stated §38 inventory. First real action: run the file-level audit against the actual repo and reconcile this plan.

---

## A. Current-State Audit (assumed from §38 — verify against repo)

Reusable as-is (extend, don't rebuild):

| Component | Reuse role in this plan |
|---|---|
| Typed configuration | Add new config sections (universe filters, scanner, scoring weights, calibration) |
| Domain models | Extend with `SymbolState`, `SignalCandidate`, `ScoreBreakdown`, `DevelopingSetup` |
| Persistence layer | New tables only (see §H); reuse migrations/session patterns |
| Logging | Reuse; add structured event tags for explainability replay |
| Market data module | Becomes the seed of the multi-symbol MarketDataManager (§D) |
| Indicators | Convert/verify incremental (O(1) per bar) variants: EMA, ATR, RSI, RVOL |
| CAEMS strategy | First `Strategy.evaluate()` plugin; wrap, don't modify rules |
| Risk engine + drawdown control | Unchanged decision authority; add correlation/exposure caps |
| Cost model / edge model | Feed scanner net-edge ranking; no changes to formulas initially |
| Backtester + replay | Backbone of Replay Mode (§25) and calibration data generation |
| Binance Futures adapter | Extend: exchangeInfo universe build, combined WS streams, user-data stream |
| OMS + reconciliation + protective orders | Unchanged; verify idempotent clientOrderId scheme covers restart |
| Paper trading | One of five modes on the single pipeline (§26) |
| FastAPI dashboard | Host for new API/WS endpoints; existing endpoints reused where they overlap |
| Continuous trading loop | Refactor from "loop over symbols" to event-driven scheduler if currently polling |

Audit checklist to run on the real repo (Phase 0):
1. Is market data pull-based (REST polling) or push-based (WS)? How many symbols does it currently sustain?
2. Are indicators recomputed over full history per tick, or incremental?
3. Does the strategy read a shared state object or fetch its own data?
4. Is there any frontend beyond FastAPI-served pages? Templates? JS framework?
5. Is persistence sync or async? Which DB (SQLite/Postgres)?
6. Does OMS already confirm protective orders post-fill and alarm on naked positions?
7. What is the existing signal/trade schema — can it carry `features` + `score_breakdown` JSON?

---

## B. Gap Analysis

Missing entirely:
- Dynamic symbol universe builder (exchangeInfo + liquidity/spread/volume/age filters)
- Multi-symbol WS market-data manager (combined streams, shard connections, stale detection, latency metrics)
- Central `SymbolState` registry
- Deterministic 0–100 Setup Score with per-component explanation
- Live scanner service (incremental ranking, delta publication)
- Developing Setups engine (near-trigger detection with missing-condition list)
- Probability calibration store (bucketed empirical stats, min-sample gating)
- Correlation/exposure grouping in risk engine
- Cooldown manager (exists partially? verify)
- Scanner/positions/system WS feeds
- React/TS frontend: scanner table, TradingView embed, symbol detail, active-trade cards, risk bar, mobile cards
- Notification adapter interface
- Trade journal enrichment (MAE/MFE, score-at-exit, auto-notes)
- Explainability persistence ("why score 87" replayable from stored inputs)

Present but needs extension:
- Binance adapter (multi-symbol WS, user-data stream keepalive)
- Replay (must drive the scanner + UI, not just backtests)
- Analytics (add score-bucket / regime / session breakdowns)

---

## C. Proposed Architecture

```
                 ┌─────────────────────────────────────────────┐
                 │                FastAPI process               │
 Binance WS ────▶│ MarketDataManager ──▶ SymbolState Registry   │
 Binance REST ──▶│   (shards, resync)      (in-memory, RW-lock- │
                 │                          free via single     │
                 │                          asyncio loop)       │
                 │            │ state-updated events            │
                 │            ▼                                 │
                 │ FeatureEngine (incremental indicators)       │
                 │            ▼                                 │
                 │ StrategyRunner ── Strategy plugins (CAEMS…)  │
                 │            ▼ SignalCandidate                 │
                 │ Gates: liquidity ▸ cost ▸ edge               │
                 │            ▼                                 │
                 │ ScannerService (rank, diff, publish)         │
                 │   ├─▶ WS /stream/scanner (deltas)            │
                 │   └─▶ DevelopingSetups engine                │
                 │            ▼ READY signals                   │
                 │ RiskEngine ─▶ ExecutionDecision ─▶ OMS ─▶ Binance
                 │            ▼                                 │
                 │ Journal / Stats / Calibration (async writes) │
                 └─────────────────────────────────────────────┘
 Frontend (React/TS) ◀── REST snapshots + WS deltas ── TradingView widget
```

Boundaries preserved: Strategy → Signal; Risk → RiskDecision; OMS → orders; Accounting records independently. Scanner is read-only over the pipeline — it never places orders.

---

## D. Market-Data Architecture (hundreds of symbols)

Universe build (startup + every N hours):
1. `GET /fapi/v1/exchangeInfo` → PERPETUAL, quoteAsset=USDT, status=TRADING.
2. `GET /fapi/v1/ticker/24hr` batch → filter by min quoteVolume (default 20M USDT, config).
3. bookTicker snapshot → filter spread_bps > max (default 3–5 bps, config).
4. Kline availability check → exclude symbols with < min history (default 7 days).
5. Emit `UniverseChanged` event; MarketDataManager diffs subscriptions.

Streams (combined-stream endpoints, ≤ ~200 streams per connection; Binance allows 1024 but keep headroom):
- `<sym>@bookTicker` — all eligible symbols (bid/ask/spread)
- `<sym>@kline_1m` — all eligible symbols; derive 3m/5m/15m by aggregation (avoids 4× stream count)
- `<sym>@aggTrade` — only top-K scanner symbols + active positions (config, default K=30)
- `<sym>@depth5@100ms` — only symbols in READY/ACTIVE state, if strategy uses imbalance
- `!markPrice@arr@1s` — one stream covers funding/mark for everything
- user-data stream — orders/positions/balance; listenKey keepalive every 30 min

Sharding: `WSShard` class owning one connection + subscription set; `MarketDataManager` assigns symbols to shards, rebalances on universe change, staggers reconnects (jittered backoff), and REST-resyncs klines after gap detection (sequence/openTime check).

Staleness: every `SymbolState` carries `last_event_ts` per feed; a watchdog marks `data_age_ms`; any gate sees `stale=True` → signal suppressed and rejection reason recorded. Klines additionally validated for contiguous open times; gaps trigger REST backfill before the symbol becomes eligible again.

Latency metrics: event `E` (exchange ts) → local receipt → state update → strategy eval → publish; histogram per stage exposed at `/api/v1/system`.

CPU budget: bookTicker for 200 symbols ≈ 1–4k msg/s. Handlers must be allocation-light; bookTicker updates mutate floats in place and only trigger strategy re-eval if crossing configured thresholds (spread band change, price moved > x·ATR fraction) or on 1m candle close. Full strategy eval on every tick for every symbol is explicitly out of scope.

---

## E. Setup Score Design (deterministic, 0–100, not probability)

`score = clamp(Σ component_i, 0, 100)`, weights in config, every component logged.

| Component | Range | Source |
|---|---|---|
| trend_alignment | 0–18 | EMA stack agreement across 1m/5m/15m + BTC regime agreement |
| momentum | 0–16 | ROC / candle body ratios, RSI slope |
| relative_volume | 0–14 | RVOL vs 20-period session-adjusted baseline |
| entry_quality | 0–13 | distance from entry_reference to current price in ATR units |
| historical_edge | 0–12 | bucketed expectancy of similar past signals (0 until data exists) |
| liquidity | 0–10 | 24h volume percentile + depth if available |
| volatility_regime | 0–8 | ATR% within tradable band (too low/high → 0) |
| confirmations | 0–4 | strategy-specific extras |
| spread_penalty | −8–0 | spread_bps vs expected TP distance |
| slippage_penalty | −5–0 | cost model estimate vs R |
| staleness_penalty | −100–0 | data_age_ms over threshold nukes the score |

Rules: pure function `score(SymbolState, SignalCandidate, config) -> ScoreBreakdown`; no wall-clock reads inside (timestamp passed in) → replay-deterministic and unit-testable with golden fixtures. Breakdown persisted with every signal.

## F. Probability Calibration Design

- Every closed trade AND every expired signal (signal that would have triggered in paper/replay) is a calibration sample: key = (strategy, side, timeframe, score_bucket, vol_regime, session).
- Nightly job aggregates into `calibration_stats` (n, wins, sum_R, PF, avg_R, Wilson CI).
- Display rule: `n >= min_samples` (default 100) AND CI width ≤ config max → show "Estimated probability: 65–69% (n=482)". Otherwise: "Probability unavailable — insufficient sample size."
- Probability is display/ranking metadata only; it never overrides risk limits.
- Guard against leakage: samples from replay/backtest tagged separately; live display defaults to paper+testnet+live samples only (config).

---

## G. Dashboard Architecture

- Frontend: **React + TypeScript + Vite**, Zustand for state, TanStack Table for the scanner. Justification: WS-delta-driven table with hundreds of rows, per-row selection, sorting freeze, and card views is painful in server-rendered templates; React is boring, well-supported, and does not force backend changes. If audit reveals an existing template UI with meaningful investment, keep it for read-only pages and mount React only for the scanner/trade views.
- Transport: REST for snapshots (`GET /scanner` returns full ranked list + seq number), WS for deltas (`{seq, upserts:[...], removals:[...]}`). Client resnapshots if it misses a seq.
- TradingView: official Advanced Chart embed widget keyed by `BINANCE:{SYMBOL}.P`; symbol switch = widget re-init (cheap). Bot overlays (entry/SL/TP/score) rendered in an adjacent panel, per §3 — the free embed does not support programmatic drawings; do not build a fragile workaround. (If the repo later qualifies for TradingView Charting Library license, overlays become possible; note as Later.)
- Mobile: same app, breakpoint switches scanner table → card list ordered positions ▸ risk ▸ top setups.

## H. Database Changes (additive only)

New tables:
- `symbol_universe` (symbol, status, filters_passed JSON, updated_at)
- `score_snapshots` (signal_id FK, ts, score, breakdown JSON) — written at signal, entry, exit, and material score changes (Δ≥5)
- `developing_setups` (symbol, strategy, ts, score, missing_conditions JSON, projection JSON)
- `calibration_stats` (key cols, n, wins, sum_r, pf, ci_low, ci_high, updated_at; unique index on key)
- `trade_events` (trade_id FK, ts, type, payload JSON) — lifecycle timeline (§11)
- `cooldowns` (scope, symbol, strategy, reason, until_ts)
- `incidents` (ts, severity, source, payload JSON)

Extend: `signals` + `trades` gain `features JSON`, `score_breakdown JSON`, `regime`, `session`, `mae`, `mfe`, `score_at_exit`, `cost_breakdown JSON`. Indexes: signals(strategy, ts), trades(strategy, symbol, ts), score_snapshots(signal_id), calibration key.

Retention: score_snapshots and trade_events pruned by config (default 90 days); raw ticks not persisted.

## I. API / WebSocket Changes

REST (all under `/api/v1`, auth required for mutating; read-only token tier for dashboards):
- `GET /scanner?filters…` — ranked rows + seq
- `GET /symbol/{s}` — full SymbolState + breakdown + why-not list + history
- `GET /strategies`, `GET /positions`, `GET /trades`, `GET /analytics?group_by=…`, `GET /risk`, `GET /system`
- `POST /controls/kill`, `POST /controls/trading-enabled` (auth + confirmation token)

WS:
- `/stream/scanner` — `{type:"snapshot"|"delta", seq, rows|upserts+removals}`
- `/stream/positions` — trade card updates + timeline events
- `/stream/system` — feed health, latency, incidents, mode changes

Row schema (scanner): `{symbol, side, score, strategy, price, spread_bps, vol_24h, atr_pct, rr, net_edge_r, state, age_ms, reasons_top3}`.

## J. Performance Risks

- bookTicker fan-in (1–4k msg/s): keep handlers sync, no per-message allocation of dicts for DB; batch DB writes via queue.
- Indicator recompute: must be incremental; audit item #2 is a blocker if not.
- Python single loop: strategy eval throttled (candle close + threshold triggers) keeps CPU manageable; if not, shard StrategyRunner into a worker process with shared-nothing message passing — but only if measured, not preemptively.
- DB write amplification from score_snapshots: Δ-gated writes + async batching.
- Frontend: 200-row table at 10 updates/s needs delta rendering (React keyed rows), never full re-render; throttle UI paints to ~4 Hz.
- Memory: ring buffers per symbol (e.g., 500 × 1m candles + derived aggregates) ≈ small; cap aggTrade buffers.

## K. Failure Modes & Handling

| Failure | Handling |
|---|---|
| WS disconnect | shard reconnect with jitter; symbols marked stale immediately; kline REST backfill; signals suppressed until fresh |
| Partial stream loss (one shard) | only that shard's symbols degrade; scanner shows per-symbol staleness |
| REST rate limit | token-bucket client, exponential backoff, prioritize reconciliation > backfill > universe refresh |
| Stale data during active trade | position management continues on user-data stream + mark price; if both stale → incident + optional protective flatten (config, default alert-only) |
| Entry filled, protection unconfirmed | existing safety condition: retry stop placement; if unconfirmed within T → emergency reduce-only close + kill switch + incident |
| Process restart | OMS reconciliation from exchange state (positions, open orders) before trading enabled; idempotent clientOrderIds prevent dupes; cooldown "API reconnect" applied |
| Ambiguous order response | reconcile via order query before any retry |
| UI disconnect | client resnapshot on reconnect via seq gap detection |
| DB down | trading pauses (config); market data continues; incidents queue in memory with cap |
| Clock skew | use exchange event timestamps for logic; monitor local-exchange skew |

## L. Testing Plan

- Unit: score function golden fixtures (breakdown-exact); universe filters; incremental indicators vs batch reference; gates (liquidity/cost/edge) accept-reject matrices; cooldown logic; calibration bucketing + min-sample gating.
- Integration: fake Binance WS server — reconnect, out-of-order, gap → backfill, stale suppression; OMS against mock exchange — partial fills, rejects, timeout, duplicate ACK, protection failure path; restart reconciliation.
- Replay: full pipeline over recorded days; assert (a) no look-ahead (signal at t uses only data ≤ t), (b) scanner ranking deterministic across runs, (c) UI feed byte-identical for same input.
- Property tests: score monotonicity per component; state machine of trade lifecycle events.
- UI: component tests for delta application + seq-gap resnapshot; mode badge; kill-switch confirmation flow.
- Testnet: full soak ≥ 1 week, all incidents triaged before live.

## M. Security Review

- API keys: backend env/secret store only; never serialized into WS payloads, logs (log filter redaction), or DB. Verify existing config loader redacts on repr.
- Dashboard auth: session or token; two tiers — read-only vs control. Control endpoints require auth + explicit confirmation param; kill switch requires auth but should be the *easiest* control to hit (no double-confirm on kill; double-confirm on *enabling* live).
- CORS locked to dashboard origin; WS auth on connect.
- Live mode: separate credential set from testnet; live enablement requires config flag + runtime confirmation + visually distinct UI.
- No secrets in Git: add pre-commit secret scan if absent.

## N. Implementation Phases

Ordering rationale: retire data-scale risk first (universe + WS manager), then deterministic scoring, then UI, then trade-monitoring, then calibration — mirrors your M0-first-retire-risk approach on doggyKORE.

**Phase 0 — Repo audit (blocker for everything)**
Goal: answer checklist §A; reconcile this plan. Files: none changed. Tests: n/a. Acceptance: written audit doc mapping every §38 component to files. Risk: audit reveals polling-based data layer → Phase 2 grows.

**Phase 1 — Symbol universe**
Goal: `universe.py` builder + filters + refresh + `symbol_universe` table. Reuses: Binance adapter REST, config, persistence. Tests: filter matrix, refresh diffing. Acceptance: ≥100 eligible symbols listed with pass/fail reasons; refresh handles delist. Risk: rate limits → batch endpoints only.

**Phase 2 — MarketDataManager + SymbolState registry**
Goal: sharded WS, bookTicker+kline_1m for full universe, TF aggregation, staleness watchdog, latency metrics, REST backfill. Reuses: adapter, existing market-data module. Tests: fake-WS integration suite. Acceptance: 24h soak, 150+ symbols, zero undetected gaps, p99 event→state < 50 ms. Risk: highest-complexity phase; timebox and cut depth/aggTrade to later.

**Phase 3 — FeatureEngine + Score**
Goal: incremental indicators on registry; pure score function + breakdown; config weights. Reuses: indicators, CAEMS feature needs. Tests: golden fixtures, incremental-vs-batch parity. Acceptance: deterministic scores across replay runs. Risk: existing indicators not incremental → rewrite cost.

**Phase 4 — StrategyRunner + gates + ScannerService**
Goal: CAEMS as plugin, liquidity/cost/edge gates, ranked list, rejection reasons, cooldowns. Reuses: CAEMS, cost/edge models, risk engine (read-only checks). Tests: gate matrices, ranking determinism, cooldown triggers. Acceptance: ranked scanner over live paper data with explanations for every row incl. rejections. Risk: eval throttling tuning.

**Phase 5 — Scanner API + WS feed**
Goal: `GET /scanner`, `/symbol/{s}`, `/stream/scanner` with seq deltas. Reuses: FastAPI app, auth. Tests: snapshot/delta consistency, seq-gap behavior. Acceptance: client reconstructing state from deltas matches snapshot exactly. 

**Phase 6 — Frontend scanner + TradingView**
Goal: React app: top bar, scanner table (filters/sort/search/favorites), TV chart panel, symbol detail with Why/Why-Not. Tests: delta application, selection, mode badge. Acceptance: click row → chart + detail < 200 ms perceived; mobile card view usable. 

**Phase 7 — Developing Setups engine + tab**
Goal: near-trigger detection (score within Δ of threshold), missing-condition list, conditional projections, `developing_setups` persistence. Tests: condition-diff correctness on fixtures. Acceptance: BTCUSDT-style example renders with accurate missing conditions in replay. 

**Phase 8 — Active-trade monitoring + lifecycle timeline**
Goal: `/stream/positions`, trade cards (R, MAE/MFE live, distance to stop/TP, qualitative health labels), `trade_events` timeline, score-change explanations. Reuses: OMS, user-data stream, journal. Tests: lifecycle state machine, event persistence. Acceptance: full timeline reproduced for a paper trade end-to-end. Risk: percentages forbidden pre-calibration — labels only (enforced in code, not just UI).

**Phase 9 — Journal enrichment + analytics**
Goal: MAE/MFE, score-at-exit, cost breakdown, auto-notes; analytics grouped by strategy/symbol/side/TF/bucket/regime/hour. Tests: metric math vs hand-computed fixtures. Acceptance: analytics page over ≥100 paper trades. 

**Phase 10 — Calibration**
Goal: bucketed stats job, min-sample gating, probability display, EV per bucket. Tests: Wilson CI, gating, leakage tags. Acceptance: probability shown only where n≥min; "insufficient sample" elsewhere. 

**Phase 11 — Notifications + QOL**
Goal: adapter interface + Telegram first; hotkeys, pinned rows, column presets, alert thresholds. Acceptance: alert fires on watchlist score threshold. 

**Phase 12 — Replay-driven UI validation**
Goal: replay feeds the same WS streams; UI indistinguishable from live. Acceptance: recorded day replayed, zero look-ahead violations, decision logs reproducible. 

**Phase 13 — Testnet soak**
Goal: full pipeline on Binance futures testnet ≥ 1 week. Acceptance: all incidents triaged; reconciliation clean across ≥3 forced restarts and ≥3 forced disconnects.

**Phase 14 — Tiny-capital live validation**
Goal: minimum sizes, hard daily loss cap, kill switch verified live. Acceptance criteria defined *before* enabling: max positions 1–2, per-trade risk ≤ configured minimum, human review of first N trades.

## O. Dashboard Wireframe

```
┌──────────────────────────────────────────────────────────────────────┐
│ PAPER ▍Equity 10,000 ▍Day +0.8R ▍Open risk 0.5R ▍WS ● 42ms ▍KILL ■ │
├──────────────┬───────────────────────────────┬───────────────────────┤
│ SCANNER      │                               │ SOLUSDT · CAEMS       │
│ ⌕ search  ★  │                               │ Score 91  ▸ breakdown │
│ #  SYM  SC S │      TradingView chart        │ LONG                  │
│ 1  SOL  91 L │        (1m/3m/5m/15m)         │ Entry 184.20          │
│ 2  ETH  86 S │                               │ Stop  183.61 (−0.32%) │
│ 3  XRP  79 L │                               │ TP1 185.62  TP2 186.41│
│ 4  DOGE 74 L │                               │ RR 2.1 · Net +0.19R   │
│ …            │                               │ Why NOT: —            │
├──────────────┴───────────────────────────────┴───────────────────────┤
│ ACTIVE  SOL LONG +0.46R Healthy │ BTC SHORT −0.12R Weakening        │
├──────────────────────────────────────────────────────────────────────┤
│ Tabs: Developing ▸ Trades ▸ History ▸ Analytics ▸ Risk ▸ System ▸ Log│
└──────────────────────────────────────────────────────────────────────┘
```

## P. QOL Recommendations

Must-have: LIVE badge + kill switch + confirmation on dangerous controls; click-row→chart; connection/latency indicators; remembered filters; rejection reasons visible; stale-data indicators per row.
Useful: hotkeys (j/k row nav, f favorite), pinned rows, compact mode, column presets, alert thresholds, freeze-sort-on-hover, log viewer, auto-lock after repeated execution errors.
Later: TradingView Charting Library overlays (requires license), Discord/mobile push, drawing persistence, sector/correlation heatmap, multi-monitor layouts.

---

## Planning-Rule Compliance Notes

- No live trading until Phase 14; live enablement is config + runtime confirmation.
- No strategy optimization anywhere in this plan; CAEMS is wrapped verbatim.
- Score ≠ probability; probability only from calibration store with sample gating.
- One pipeline across BACKTEST/REPLAY/PAPER/TESTNET/LIVE; only the venue adapter differs.
- Every decision reproducible: features + breakdown + gate results persisted per signal.
- No microservices: one asyncio process, optional worker split only if measured necessary.
