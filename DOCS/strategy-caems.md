# CAEMS v2 — Cost-Aware EMA Momentum Scalp

## Concept

A deliberate, minimal EMA-momentum scalp. The edge is only trusted if it
survives a strict cost gate. No extra indicators are added.

**v2 changes (2026-08-09):** entry-location condition, strength upper bound,
strengthened volume gate, breakeven stop move, candle-quality and funding
sanity checks, maker-fill markout instrumentation, per-symbol deadband.
EMA periods and TP ratio are deliberately UNCHANGED — do not tune them until
paper MAE/MFE data exists (see "Frozen parameters").

## Timeframes

- Signal: **1m** candles (completed only).
- Regime: **5m** candles (completed only).

## Indicators

| Indicator | Period | Notes |
|---|---|---|
| EMA fast 1m | 12 | price EMA |
| EMA slow 1m | 48 | price EMA |
| EMA fast 5m | 20 | price EMA |
| EMA slow 5m | 50 | price EMA |
| ATR (1m) | 14 | for stop + strength normalization |
| Volume | 30 bars | rolling median of prior 30 completed 1m quote-volumes |

## Strength

```
strength = (EMA12_1m - EMA48_1m) / ATR14_1m
```

Logged on **every evaluation** (signals AND rejections) so per-symbol
thresholds can later be fitted from persisted data instead of guessed.

## LONG entry (all conditions)

1. Regime: `EMA20_5m > EMA50_5m`
2. Momentum: `EMA12_1m > EMA48_1m`
3. Deadband: `strength >= strength_min` (default 0.20, **per-symbol config**)
4. Strength cap: `strength <= strength_max` (default 1.50, per-symbol) —
   extreme 1m readings are climactic, not initiating; do not chase.
5. Confirmation: `completed_close > EMA12_1m`
6. **Entry location: `completed_close <= EMA12_1m + entry_max_atr * ATR14_1m`**
   (default `entry_max_atr = 0.5`) — forbids buying far above the mean after a
   vertical bar, which passes every other condition and is the worst entry of
   the set.
7. Volume: `completed_quote_volume >= rvol_min * median(30 bars)`
   (default `rvol_min = 1.3`; the old `>= 1.0*median` passed ~half of all bars
   by construction and filtered nothing).
8. **Candle quality: `last_bar_range <= bar_range_max_atr * ATR14_1m`**
   (default 3.0) — a news spike satisfies every trend condition while ATR14
   has not caught up, making the stop structurally too tight.
9. **Funding proximity: no entries within `funding_blackout_s` (default 120 s)
   of the funding timestamp** — mark-price behavior and forced flows around
   funding pollute 1m signals.
10. Spread: `spread_bps <= 2.0` (configurable, per-symbol)
11. Risk gate approved (sizing, caps, drawdown, daily/weekly loss)
12. Cost gate: `expected_gross_edge >= cost_edge_multiplier * round_trip_cost`

**Reserved (multi-symbol phase, off by default):** BTC veto — for non-BTC
symbols, reject longs when BTC 1m `strength <= -btc_veto_threshold`
(symmetric for shorts). The symbol's own 5m regime does not protect an alt
long from a BTC dump. Config: `btc_veto_enabled`, `btc_veto_threshold` (0.30).

## SHORT entry

Symmetric, all conditions mirrored (only when the venue supports shorting —
always true on Binance USDT-M futures).

## Exit logic

- **Stop loss**: `max(atr_stop, execution_floor)` where
  `execution_floor = 3*spread + 2*slippage_buffer` (all price-unit).
- **Take profit**: `1.35 R`, where `R = entry - stop` distance. **Frozen.**
- **Breakeven move (new)**: when unrealized reaches `be_trigger_r` (default
  1.0R), amend the exchange-side algo stop to `entry + be_offset` (default
  offset = round-trip cost in price units, so a stop-out is a true scratch,
  not a small loss). One amendment only; never move the stop away from price.
  Rationale: with a slow structural reversal exit and a fast hard stop there
  was nothing in between, and this TP/stop geometry constantly produces
  "+1.2R then full stop" outcomes. Config-gated (`be_enabled`, default ON in
  paper for A/B measurement — see Validation).
- **Time stop**: 15 minutes, by wall-clock elapsed time.
- **Reversal exit**: for longs, exit on `strength < -strength_min`
  (symmetric for shorts).
- Risk engine may force exits independently.

## Order flow (default)

1. Post-only maker entry at best bid (long) / best ask (short).
2. TTL 3s.
3. If partially filled, cancel remainder.
4. Re-evaluate with current book/signal/risk/cost.
5. Convert to taker only if `remaining_edge > taker_cost + safety_buffer`.
6. Otherwise abandon.
7. After fill: place exchange-side protective stop + take-profit; entry is
   not considered protected until both are ACKed (see plan §protection gap).

### Adverse-selection instrumentation (new, mandatory from day one)

Maker-at-bid entry on a momentum signal is structurally adversely selected:
fills are biased toward micro-reversals, misses toward the trades that work
instantly. Whether the maker fee saving survives that bias is an empirical
question. Accounting must record per entry attempt:

- outcome: `MAKER_FILL | PARTIAL | TAKER_CONVERT | ABANDONED`
- non-fill rate per symbol/session
- **markout**: mid-price at +5 s and +30 s after fill minus fill price,
  in bps and in R, split by fill type

**Decision rule (pre-registered):** after ≥300 entry attempts in paper, if
maker fills show 30 s markout worse than taker-convert fills by more than the
maker/taker fee difference, switch default entry to
`taker-if-spread <= taker_spread_max_bps` and re-run the cost gate with taker
fees. Do not decide this from intuition.

## Position sizing

```
stop_fraction = |entry - stop| / entry
risk_notional = equity * risk_per_trade / stop_fraction
size = min(risk_notional, depth_cap, volume_cap, leverage_cap, exchange_cap)
```

Default `risk_per_trade = 0.15%`. Leverage cap default `2x`.

## Frozen parameters (do not tune before evidence)

`EMA 12/48, 20/50`, `ATR 14`, `TP 1.35R`, `time stop 15m`. These are the most
overfittable knobs. They stay fixed until ≥300 paper trades produce MAE/MFE
distributions; any change is then a **new strategy version** (caems_v3)
validated independently, never a silent edit.

## Validation protocol for v2 changes

Each new rule is tested **one at a time** against the same replay dataset,
attributing expectancy change to a single rule:

| Variant | Change vs v1 |
|---|---|
| A | entry-location condition only |
| B | breakeven move only |
| C | rvol_min 1.3 only |
| D | A+B+C combined |

Ship the combination only if D ≥ best single variant on net expectancy with
non-overlapping harm on drawdown. Strength cap, candle quality, and funding
blackout are safety rails, not edge claims — they ship without A/B but their
rejection counts are monitored (if any fires >20% of the time, its threshold
is re-examined).

## Configuration defaults

See `src/scalping/config/settings.py` (the single source of truth). All values
are configurable; nothing is hard-coded in strategy code. New keys:
`strength_max`, `entry_max_atr`, `rvol_min`, `bar_range_max_atr`,
`funding_blackout_s`, `be_enabled`, `be_trigger_r`, `be_offset_mode`,
`btc_veto_enabled`, `btc_veto_threshold`, `taker_spread_max_bps`.

## Rejection reasons

Persisted for research: `NO_5M_TREND`, `DEAD_BAND_TOO_SMALL`,
`STRENGTH_TOO_EXTREME`, `PRICE_CONFIRMATION_FAILED`, `ENTRY_TOO_EXTENDED`,
`LOW_VOLUME`, `BAR_RANGE_ABNORMAL`, `FUNDING_BLACKOUT`, `SPREAD_TOO_WIDE`,
`BTC_REGIME_VETO`, `COST_TOO_HIGH`, `EXPECTED_EDGE_TOO_LOW`, `RISK_LIMIT`,
`DRAW_DOWN_LIMIT`, `STALE_MARKET_DATA`, `INVALID_BOOK`, `SYMBOL_DISABLED`,
`LIQUIDITY_TOO_LOW`, `KILL_SWITCH`, `SHORTS_DISABLED`.
