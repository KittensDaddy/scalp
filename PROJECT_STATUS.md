# CAEMS v2 Scalping System — Project Status

Handoff log for continuing this build. Source of truth for scope/order is
`DOCS/PLAN_OF_ACTION.md`, `DOCS/strategy-caems.md`, `DOCS/SCANNER_DASHBOARD_PLAN.md`,
`DOCS/DASHBOARD_STRATEGY_LAB.md`. This is a from-scratch build (the DOCS falsely
claimed phases were "done" — they weren't; everything here was actually built).

## Done (all tested, ruff-clean, migrations current as of this commit)

**Core engine — P1 through P10 (PLAN_OF_ACTION.md phases 0-10):**
config/settings (typed, frozen strategy params), persistence (SQLAlchemy + alembic,
SQLite/PG-compatible), Binance REST/WS client + rate limiter, incremental indicators
(EMA/ATR/RSI/rolling median), CAEMS v2 signal engine (12 conditions + mirrors, full
20-value RejectionReason enum), risk engine + drawdown machine + asymmetric kill
switch, cost/edge model + candle backtester (sanity-only), Binance algo-order adapter
+ startup self-check, OMS + reconciliation + protection-gap safety mechanism +
breakeven move, paper venue, event replay, FastAPI dashboard v1 (read endpoints +
control endpoints + CORS lock), CAEMS A/B validation harness, entry-attempt/markout
instrumentation + pre-registered maker/taker decision rule.

**Scanner/dashboard track — S1 through S7 (SCANNER_DASHBOARD_PLAN.md phases):**
- S1 — symbol universe builder (`market_data/universe.py`)
- S2 — MarketDataManager: sharding, 1m→3m/5m/15m aggregation, SymbolStateRegistry,
  latency tracking (`market_data/`)
- S3 — Setup Score: pure `scoring/score.py` + `scoring/features.py`
- S4 — StrategyRunner + ScannerService, cooldowns, exposure/correlation caps
- S5 — Scanner REST + WS API (`api/routers/scanner.py`)
- S6 — React/TS/Vite/Zustand/TanStack-Table-v8 frontend, TradingView embed,
  asymmetric kill-switch UI — **verified live in a real browser** (scanner table,
  chart, score breakdown, rejection reasons, full kill/un-kill flow)
- S7 — Developing Setups engine: non-short-circuiting CAEMS condition evaluator
  (`strategies/caems/diagnostics.py`), near-trigger detection (`scanner/developing.py`),
  `developing_setups` persistence, `/api/v1/developing` + `/stream/developing`,
  frontend "Developing" tab — **verified live in a real browser**

All verification demo scripts were scratch files (`/tmp/run_dashboard*.py`) and are
NOT part of the repo — they seeded fake data to drive the UI for a human-observable
check, then were torn down. To re-run a similar check, write a small script that
calls `create_app()` with a seeded `ScannerService`/`DevelopingSetupsService`.

Test suite: 359 passed. `uv run pytest -q` and `uv run ruff check src tests` both
clean as of this commit. Frontend: `npx tsc -b && npm run build` clean.

## In progress / next up

Was starting **S8 — Active-trade monitoring + lifecycle timeline**
(SCANNER_DASHBOARD_PLAN.md phase 8) when this session ran out of budget. Nothing
written yet for S8 — planning only. Design notes from that planning pass:

- Reuse `domain.models.Position`/`Trade`/`Fill` (already exist, from P7/P8).
- New `TradeEvent` domain model + `trade_events` persistence table: event_type
  (OPENED, PROTECTED, BREAKEVEN_MOVED, SCORE_CHANGED, CLOSED, ...), trade_id/symbol,
  ts, payload JSON. `Position` already tracks `protected`/`breakeven_moved` flags to
  drive some of these.
- Pure MAE/MFE update function: `update_mae_mfe(position, price) -> (mae, mfe)` —
  keep it side-effect-free like everything else in this codebase.
- **Hard constraint (spec, not a suggestion): qualitative health labels only —
  percentages/probabilities are forbidden pre-calibration (S10), and this must be
  enforced in code, not just the UI layer.** E.g. a `HealthLabel` enum
  (HEALTHY / AT_RISK / NEAR_STOP / NEAR_TP or similar) derived from deterministic
  geometry (distance-to-stop/TP as a fraction of R) — never a numeric win-probability.
  Distance/R-multiple numbers themselves are fine; a % chance-of-anything is not.
- `ActiveTradeService` mirroring `ScannerService`/`DevelopingSetupsService`'s
  seq-numbered publish/snapshot shape, feeding the **already-existing**
  `/api/v1/stream/positions` WS route (`api/routers/scanner.py` — currently just
  accepts connections and forwards the broadcaster's "positions" channel; nothing
  publishes to it yet) and a new/extended `GET /api/v1/positions` (currently a stub
  returning `[]` in `api/routers/read.py`).
- Acceptance per the plan: "full timeline reproduced for a paper trade end-to-end" —
  will need either a paper-trading integration test driving a position through its
  full lifecycle, or a replay-driven one.

After S8, remaining phases in order (none started):
- S9 — journal enrichment + analytics (MAE/MFE, score-at-exit, cost breakdown,
  auto-notes, analytics grouped by strategy/symbol/side/TF/bucket/regime/hour/session)
- S10 — probability calibration (Wilson CI, min-sample gating, per-symbol vs pooled
  expectancy testing) — this is what unblocks percentages/probabilities anywhere in
  the UI
- S11 — notifications (Telegram) + QOL (hotkeys, pinned rows, column presets, alerts)
- S12 — replay-driven UI validation (zero look-ahead, UI indistinguishable from live)
- L1-L6 — Strategy Lab track (presets table + resolution engine + provenance,
  Strategy Lab UI, backtest job runner, compare mode/A-B workflow, live activation)
- Also still outstanding regardless of track: the actual `scalping --run` trading-loop
  supervisor wiring P1-P10's pieces into a continuously-running process. Nothing in
  S1-S7 required it because everything is tested via dependency-injected
  fakes/mocks — but S8's "real" position data and any live paper-campaign evidence
  (PLAN_OF_ACTION.md §8, n≥300 trades) need it to mean anything.

## Conventions established (follow these)

- Pure business logic with injectable I/O boundaries everywhere — mirrors the
  `ExchangePort` pattern. Network/wall-clock code stays in thin adapters; everything
  else is unit-testable without a live connection.
- "Evaluate every condition independently, don't short-circuit" pattern for anything
  that needs to explain *all* the reasons something failed (see `universe.py`,
  `diagnostics.py`) vs. the short-circuiting cascade used for actual decisions
  (`caems/engine.py`).
- Every new service with a live/WS view gets a seq-numbered snapshot/publish/delta
  shape (`ScannerService`, `DevelopingSetupsService`) so the frontend can reuse the
  same seq-gap-resnapshot client pattern.
- Never fabricate data for fields the pipeline doesn't populate yet — return `null`/
  empty with a comment explaining what wires it up later (see `read.py`, `scanner.py`
  serializers).
- TanStack Table must stay pinned to `^8` — `npm install @tanstack/react-table` alone
  pulls in a v9 pre-release with an incompatible API.
- Alembic needs `data/` to exist before `alembic revision --autogenerate` or
  `alembic upgrade head` will run (SQLite file target) — `mkdir -p data` first, and
  `rm -rf data` afterward (it's gitignored and not meant to persist).
- After any live-browser verification pass, kill the demo processes by exact PID
  (`pgrep -af "run_dashboard\|vite"`) — `pkill` substring matches can hit multiple
  demo scripts at once and leave orphans.
