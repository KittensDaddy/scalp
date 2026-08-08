# Dashboard Extension — Strategy Lab (Presets + Backtesting)

Adds two capabilities to the existing FastAPI dashboard: editable strategy
presets and in-dashboard backtesting. Reuses `backtest/`, `replay/`,
`persistence/`, and the existing auth model. No changes to the live pipeline's
decision logic — the dashboard *configures and tests*; it never bypasses the
strategy→risk→OMS chain.

---

## 1. Preset system

### Data model

- `presets` table: id, name, class_rule JSON, params JSON, version, overlay
  bool, disabled bool, created_at, author, note.
- Editing a preset = new version row (immutable history). Live trading always
  pins a version; "latest" is only a UI convenience.
- Every signal/rejection/trade already stores config_hash — extend with
  `preset_id, preset_version`.

### Resolution

`effective_config(symbol) = defaults ⊕ class_preset ⊕ overlays ⊕ per_symbol_override`

- Exactly one class preset per symbol (priority: btc > eth > meme > hype >
  major_alt > mid_alt > new_listing > low_liquidity).
- Overlays (high_funding, event_risk) may only tighten, never loosen — the
  merge function enforces this key-by-key and rejects violating edits at save
  time.
- Frozen strategy parameters (EMAs, TP ratio, time stop) are not preset keys;
  the API refuses them with a clear error. Changing those = new strategy
  version, separate workflow.

### API

- `GET  /api/v1/presets` — all presets + versions
- `GET  /api/v1/presets/{id}/effective?symbol=SOLUSDT` — resolved config with
  per-key provenance (which layer set it)
- `POST /api/v1/presets/{id}/versions` — create new version (auth: control token)
- `POST /api/v1/presets/{id}/activate` — pin version for PAPER (control token)
- `POST /api/v1/presets/{id}/activate-live` — pin for LIVE (control token +
  confirm param + only allowed if this exact version has a completed backtest
  AND a paper sample >= min_trades; enforced server-side, not just UI)
- `GET  /api/v1/symbols/{s}/config` — what the trader is actually using now

### UI (new "Strategy Lab" tab)

```
┌────────────────────────────────────────────────────────────────┐
│ PRESETS                    │ EDITOR: meme (v3 draft)           │
│ ● btc          v1  LIVE    │ strength_min      0.30   [0.20-0.5]│
│ ● eth          v1  LIVE    │ rvol_min          2.0    [1.0-3.0]│
│ ● major_alt    v2  PAPER   │ entry_max_atr     0.35            │
│ ● mid_alt      v1  PAPER   │ spread_max_bps    3.0             │
│ ● meme         v2→v3 draft │ risk_per_trade    0.08%  ⚠ ceiling│
│ ○ new_listing  DISABLED    │ ...                               │
│ ○ low_liquid   DISABLED    │ [Diff vs v2] [Backtest] [Save v3] │
│ ▣ high_funding OVERLAY     │ Matched symbols now: 14  [list]   │
│ ▣ event_risk   OVERLAY     │ Provenance: rvol_min ← preset     │
└────────────────────────────────────────────────────────────────┘
```

- Every field shows its allowed range and a diff vs the active version.
- "Matched symbols now" shows which live symbols the class rule captures.
- Guardrails in the editor mirror server-side: risk ceilings per class
  (e.g. meme risk can be lowered, never raised above 0.10%), overlay
  tighten-only rule, frozen-key refusal.
- LIVE activation is a distinct, visually loud flow with the same
  confirmation asymmetry as the kill switch.

---

## 2. In-dashboard backtesting

### What it is (and honestly is not)

Runs the existing candle backtester + replay engine against a chosen preset
version over a chosen symbol set and date range, from the browser. Per
PLAN §5: candle backtests are a **gross-signal sanity check** — the results
panel carries a permanent banner:

> "Candle-level simulation. Maker fill probability, queue position and
> intrabar stop sequencing are approximated. This result is NOT evidence of
> live edge — see paper campaign."

The value is fast comparative iteration: does preset v3 reject the trades v2
lost on, over identical data? That question candle backtests answer well.

### Backend

- `backtest_jobs` table: id, preset_id, preset_version, symbols JSON,
  date_from, date_to, mode (CANDLE|REPLAY), status, progress, result JSON,
  created_at, config_hash.
- `POST /api/v1/backtests` — enqueue (control token). Jobs run in a worker
  task queue inside the existing process (bounded concurrency, default 1;
  backtests must never starve the live loop — worker runs at lower priority
  and is refused entirely while mode=LIVE unless `allow_backtest_in_live`).
- `GET /api/v1/backtests/{id}` — status + results
- `WS  /api/v1/stream/backtests` — progress events
- Candle data: served from local persistence; missing ranges fetched via the
  existing kline backfill with rate-limit budget separate from trading.
- Determinism: same (data, preset version, seed) → identical results;
  result JSON stores the data checksum so stale-data reruns are detectable.

### Results panel

Per run: trades, win rate, PF, net expectancy (R), avg/median R, max DD,
MAE/MFE distribution, rejection-reason histogram, equity curve, per-symbol
breakdown, cost breakdown (fees/spread model/funding).

**Compare mode** (the actual point): select 2+ runs → side-by-side metrics +
overlaid equity curves + "trades taken by A but rejected by B, with reasons".
That last table is where preset tuning decisions actually come from.

### A/B protocol integration

The strategy spec's variant protocol (A–D) maps directly: each variant is a
preset version; the Lab runs all four against the identical dataset and the
compare view answers "ship D or a single variant" per the pre-registered rule.

---

## 3. Safety rules (non-negotiable)

1. Preset edits never touch a live position's management; changes apply to
   NEW signals only, at next evaluation.
2. LIVE activation requires: completed backtest on that exact version +
   paper sample ≥ configured minimum + control token + confirm. All enforced
   server-side.
3. Overlays tighten-only; frozen keys rejected; class risk ceilings enforced.
4. Backtest results are labeled sanity-only everywhere they appear; they can
   gate activation (necessary) but never substitute for the paper evidence
   bar (PLAN §8).
5. Full audit trail: who changed what, when, from which version — the
   presets table is append-only.

## 4. Build order

1. Preset tables + resolution engine + provenance endpoint (backend only,
   config still file-driven as fallback) — tests: merge rules, tighten-only,
   frozen-key refusal, priority resolution.
2. Strategy Lab read UI (view/resolve/diff).
3. Edit + versioning + paper activation.
4. Backtest job runner + REST/WS + results panel.
5. Compare mode + A/B workflow.
6. Live activation flow (last, after kill-switch-grade review).
