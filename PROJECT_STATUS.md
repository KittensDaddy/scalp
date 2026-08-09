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

**Scanner/dashboard track — S1 through S12:**
- S1 — symbol universe builder
- S2 — MarketDataManager + SymbolStateRegistry
- S3 — Setup Score
- S4 — StrategyRunner + ScannerService, cooldowns, exposure caps
- S5 — Scanner REST + WS API
- S6 — React scanner + TradingView + kill-switch UI
- S7 — Developing Setups engine + tab
- S8 — Active-trade monitoring + lifecycle timeline (`ActiveTradeService`,
  `trade_events`, HealthLabel-only, probability fields rejected in code)
- S9 — Journal enrichment + analytics (`accounting/journal.py`, `GET /analytics`,
  enriched `/trades`, Analytics tab)
- S10 — Calibration (Wilson CI, min-sample gating, `calibration_stats`,
  `GET /calibration` — probabilities only when n≥min)
- S11 — Notifications + QOL (Telegram adapter + `AlertEngine`, hotkeys j/k,
  pinned rows, column presets, alert threshold in localStorage)
- S12 — Replay-driven UI feed (`replay/ui_feed.py`) — byte-identical frames
  across identical replays

**Strategy Lab — L1 through L6:**
- L1 — presets table + `resolve_with_provenance` + frozen-key / tighten-only validation
- L2/L3 — Strategy Lab UI (presets list, provenance, calibration panel) + versioning
  + paper activation API
- L4 — `BacktestJobRunner` (sanity banner permanent, refused in LIVE by default)
- L5 — compare mode (`POST /backtests/compare`)
- L6 — live activation gated server-side (completed backtest + paper min + confirm)

**Runtime:**
- `TraderSupervisor` (`runtime/supervisor.py`) — eval + heartbeat loops, kill-switch
  aware, broadcaster heartbeats
- `ProductionTick` (`runtime/tick.py`) + context builder — StrategyRunner →
  scanner/developing publish + active-trade marks; per-symbol CAEMS class presets
  via `SymbolClassResolver` (`config/class_resolver.py` + `DOCS/caems_presets.yaml`)
- Multi-plugin `StrategyRunner` — `caems_v2` + live `ALT_RESIDUAL` + microstructure
  stubs (`OFI_BTC`, …) that reject `DATA_UNAVAILABLE` until L2 feed exists
- `PaperExecutor` (`runtime/paper_executor.py`) — entry_flow + protection on
  `PaperVenue`, ActiveTradeService cards, per-symbol EffectiveConfig sizing
- CLI: `scalping --dashboard` (API + Lab candle loader) and `scalping --run`
  (warm registry from REST, WS market data, production tick, paper execution when
  `SCALPING_ENVIRONMENT=paper`, dashboard API on the same process). Default
  `SCALPING_RUN_SYMBOLS=auto` builds the liquid USDT-perp universe (capped by
  `SCALPING_UNIVERSE_MAX_SYMBOLS`, default 150). Optional
  `SCALPING_PRESETS_PATH`, `SCALPING_ENABLED_STRATEGIES`.
- Lab: `POST /api/v1/backtests` enqueues candle jobs via injectable candle loader;
  Strategy Lab UI can start a 3d BTCUSDT sanity run
- Journal persistence: closed paper trades → `trades` (+ auto-notes), entry
  attempts → `entry_attempts`, lifecycle → `trade_events`, score samples →
  `calibration_stats` (`persistence/trades_repo.py`)

Test suite: 427 passed. `uv run pytest -q` and `uv run ruff check src tests` both
clean. Frontend: `npx tsc -b` clean.

Migrations: through `b2c3d4e5f6a7` (score_snapshots, calibration_stats, presets,
backtest_jobs, incidents) on top of trade_events / developing_setups / etc.

## Microstructure track (live v1 proxies)

`DOCS/strategy-microstructure-multiasset.md` — all 8 strategy IDs evaluate in
`--run` with best-effort proxies from `bookTicker` + 1m candles (no full L2/CVD
yet): `OFI_BTC`, `ETH_LEADLAG`, `ALT_RESIDUAL`, `SWEEP_MID`, `COMPRESS_SMALL`,
`LISTING_OR`, `VSHOCK`, `PUMP_DEFENSIVE`. Scanner STRAT column shows the winning
plugin; paper can fill non-CAEMS signals. Sub-second OFI/depth-recovery gates
remain future work once L2/trade-tape feeds exist.

## Remaining (operational / evidence, not missing modules)

Code for S1–S12 + L1–L6 + supervisor/CLI + production tick/paper path is in place.
What remains is runtime evidence and soak:

- **10c paper campaign** to PLAN §8 evidence bar (n≥300 trades, etc.) —
  `SCALPING_CONTROL_TOKEN=… SCALPING_DASHBOARD_UNKILL_TOKEN=… scalping --run`
  with `SCALPING_ENVIRONMENT=paper`. Closed trades, entry attempts, trade events,
  and calibration samples now persist automatically into the DB.
- **S13 testnet soak** ≥1 week (ops), reconciliation across forced restarts.
- **S14 tiny-capital live** — only after evidence bar; max 1–2 positions, human
  review of first N trades.
- Finish microstructure strategies once L2/CVD feeds exist; seed Lab presets from YAML.

## Conventions established (follow these)

- Pure business logic with injectable I/O boundaries everywhere — mirrors the
  `ExchangePort` pattern. Network/wall-clock code stays in thin adapters; everything
  else is unit-testable without a live connection.
- "Evaluate every condition independently, don't short-circuit" pattern for anything
  that needs to explain *all* the reasons something failed (see `universe.py`,
  `diagnostics.py`) vs. the short-circuiting cascade used for actual decisions
  (`caems/engine.py`).
- Every new service with a live/WS view gets a seq-numbered snapshot/publish/delta
  shape (`ScannerService`, `DevelopingSetupsService`, `ActiveTradeService`).
- Never fabricate data for fields the pipeline doesn't populate yet — return `null`/
  empty with a comment explaining what wires it up later.
- Probabilities only from calibration store with min-sample gating (S10); S8 health
  labels remain geometry-only.
- Candle backtests always carry the sanity-only banner; they gate Lab activation but
  never substitute for the paper evidence bar.
- TanStack Table must stay pinned to `^8`.
- Alembic needs `data/` to exist before migrate (`mkdir -p data`).
- After any live-browser verification pass, kill demo processes by exact PID.
