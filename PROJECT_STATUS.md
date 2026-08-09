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

Test suite: 475 passed. `uv run pytest -q` and `uv run ruff check src tests` both
clean. Frontend: `npx tsc -b` clean (needs `npm install` first — a bare checkout
reports missing `node`/`vite/client` type roots, which is a dependency artifact,
not a type error).

Migrations: through `b2c3d4e5f6a7` (score_snapshots, calibration_stats, presets,
backtest_jobs, incidents) on top of trade_events / developing_setups / etc.

## Microstructure track (live v1 proxies)

`DOCS/strategy-microstructure-multiasset.md` — all 8 strategy IDs evaluate in
`--run` with best-effort proxies from `bookTicker` + 1m candles (no full L2/CVD
yet): `OFI_BTC`, `ETH_LEADLAG`, `ALT_RESIDUAL`, `SWEEP_MID`, `COMPRESS_SMALL`,
`LISTING_OR`, `VSHOCK`, `PUMP_DEFENSIVE`. Scanner STRAT column shows the winning
plugin; paper can fill non-CAEMS signals. Sub-second OFI/depth-recovery gates
remain future work once L2/trade-tape feeds exist.

## Paper-run readiness (audited + fixed 2026-08-09)

The audit found the `--run` paper path started and traded end to end, but that
what it recorded would not have been usable as the PLAN §8 sample. All findings
below are **fixed**; each has tests that fail against the old behavior.

1. **Venue now sees the book at WS rate.** `MarketDataManager` takes
   `book_sinks`, and `--run` subscribes `PaperVenue.on_book_ticker`. Previously
   the venue only got one registry snapshot replayed per eval tick (~1 Hz), and
   `entry_ttl_s` was `0.05` — a resting GTX order was queried back 50 ms after
   placement, before the book could move through it, so **no maker entry could
   ever fill**. Every attempt became `TAKER_CONVERT`/`ABANDONED` and the campaign
   would have carried a taker-only cost basis. TTL now defaults to the strategy's
   3 s (`SCALPING_PAPER_ENTRY_TTL_S`).
2. **Markouts are recorded.** `PaperExecutor` samples mid at +5 s / +30 s after
   each fill and writes back to the entry attempt (`save_entry_attempt` now
   flushes and returns the row id; `update_entry_attempt_markouts` fills them in
   per offset). §8 criterion 6 has data instead of four hardcoded `None`s.
3. **Cooldowns are set, persisted, and restored.** Closed trades cool the symbol
   down (`post_loss_s` > `post_trade_s`); WS disconnects set a global
   `api_reconnect` cooldown; `--run` reloads active cooldowns from the DB at
   startup. `StrategyRunner` now checks global scope as well as symbol scope, and
   reports the new `RejectionReason.COOLDOWN` rather than `SYMBOL_DISABLED`.
4. **Drawdown survives restarts and rolls over.** `PaperExecutor.sync_closes`
   already fed `risk.on_trade_closed`, but the protection-timeout close path
   skipped it, nothing ever called `reset_daily`/`reset_weekly` (so the first day
   to breach `daily_loss_cap_r` halted entries permanently), and state was
   in-memory only. Now: `PeriodTracker` (`runtime/periods.py`) rolls the UTC
   day/week boundaries from the tick, `load_drawdown_snapshot` rebuilds daily and
   weekly R from the trade record at startup, and every close path records.
5. **Evidence bar has a readout.** `GET /api/v1/evidence` and `scalping
   --evidence` evaluate all eight §8 criteria against live campaign data
   (`edge/campaign.py`). Testnet-only criteria (§8.7 reconciliation, §8.8 kill
   switch) report unverified unless explicitly operator-asserted, so a paper
   campaign can never render an overall PASS on its own. An unmeasured protection
   gap fails rather than defaulting to something flattering.

Two execution-correctness bugs surfaced while wiring the above, both of which
would have corrupted the sample rather than merely thinned it:

- **Phantom positions from orphaned protective orders.** Stop and TP were tracked
  independently; whichever fired left the other live, and the survivor would
  later trigger against a flat book and *open* a position (`_apply_position_delta`
  creates one when none exists). Rare at 1 Hz, near-certain at WS rate. The venue
  now applies OCO semantics and reduce-only closes can never open or flip.
- **Exits booked at a stale mark.** `sync_closes` priced the exit at
  `trade.current_price` — whatever the last eval tick marked — so a stop that
  triggered mid-tick was recorded at up to a second-old price. Since R is the
  entire evidence base, that biased every trade. The venue now records the actual
  close fill (touch price at trigger) and the executor books R against it.

Operational preconditions for the run itself:

- Symbol resolution and warm both go through REST. Banned IP with no proxy →
  `--run` exits 1 at universe build. Set `SCALPING_HTTP_PROXY`/`_PROXIES`.
- `_poll_books` failures now log at `warning` (they were `debug`, which made a
  failing poll look identical to a quiet market).
- `SCALPING_WARM_REGISTRY=false` with no proxy means no REST warm; 5m EMAs need
  hours of WS bars before rows become tradeable. A proxy auto-enables warm.
- Defaults at launch: 300-symbol universe, `paper_equity=10_000`,
  `risk_per_trade_pct=0.15`, `max_positions_total=10`.
- Check progress any time with `scalping --evidence` (exit 0 only if the whole
  bar passes) or `GET /api/v1/evidence`.

## Remaining (operational / evidence)

Code for S1–S12 + L1–L6 + supervisor/CLI + production tick/paper path is in place,
and the campaign now instruments itself. What remains is runtime evidence and soak:

- **10c paper campaign** to PLAN §8 evidence bar (n≥300 trades, etc.) —
  `SCALPING_CONTROL_TOKEN=… SCALPING_DASHBOARD_UNKILL_TOKEN=… scalping --run`
  with `SCALPING_ENVIRONMENT=paper`. Closed trades, entry attempts, markouts,
  trade events, cooldowns, and calibration samples all persist automatically.
  Track progress with `scalping --evidence`.
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
- A module that exists and is unit-tested is not wired. Cooldowns, markouts, and
  the evidence bar were all "done" by that standard while nothing in `--run` ever
  called them. New campaign-evidence code gets a test that drives it through the
  runtime path, not just the pure function.
- Paper fills are priced off what the venue actually filled at, never off the last
  mark an eval tick happened to take.
- Candle backtests always carry the sanity-only banner; they gate Lab activation but
  never substitute for the paper evidence bar.
- TanStack Table must stay pinned to `^8`.
- Alembic needs `data/` to exist before migrate (`mkdir -p data`).
- After any live-browser verification pass, kill demo processes by exact PID.
