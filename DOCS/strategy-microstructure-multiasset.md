# A Comprehensive, Non-EMA Crypto Scalp Trading Research Framework

## Executive summary

The most important design change is to **stop treating "crypto scalping" as one strategy applied to different symbols**. BTC, ETH, liquid large-cap alts, thin small-caps, newly listed tokens, and manipulation-prone coins have materially different microstructure, information flow, liquidity, and execution risk. Research on limit-order books shows that queue imbalance, order flow, spread, and depth can carry short-horizon information, while cryptocurrency research also documents strong differences in price discovery, intraday liquidity, jumps, and manipulation across venues and assets.

Existing **CAEMS v2** (`strategy-caems.md`) is fundamentally a **1-minute/5-minute EMA-momentum strategy** built around EMA 12/48 and 20/50, ATR-normalized strength, relative volume, spread/cost gates, post-only maker entries, ATR/execution-floor stops, a fixed 1.35R target, breakeven logic, and a 15-minute time stop. The research framework below deliberately does **not** create eight variations of that same idea. EMA crossovers and ATR stops are excluded as primary alpha signals here. Retain only universal infrastructure ideas from CAEMS — cost gating, exchange-side protection, markouts, rejection logging, data-quality checks, and hard risk limits — because those are execution/risk-engine functions rather than the strategy itself, and are meant to be shared, not duplicated per strategy.

The proposed architecture is:

| Asset group | Primary signal family | Main indicator set | Typical hold |
|---|---|---|---:|
| **BTC** | Microstructure impulse | OFI + microprice + queue depletion | 2–10 sec |
| **ETH** | BTC→ETH lead/lag | Dynamic beta residual + lag gap + ETH flow | 10–60 sec |
| **Large-cap alts** | Relative-value reversion | BTC/ETH beta residual + VWAP + CVD | 1–8 min |
| **Mid-cap alts** | Liquidity-sweep reversal | Swing sweep + CVD divergence + depth refill | 30 sec–6 min |
| **Small-cap alts** | Compression breakout | Range compression + Donchian break + depth depletion | 1–10 min |
| **New hype/listings** | Opening-range discovery | Listing AVWAP + opening range + flow stabilization | 30 sec–8 min |
| **Sudden hype** | Volume-shock state machine | Seasonal volume z-score + CVD + price impact + OI | 15 sec–5 min |
| **Pump/dump candidates** | Defensive post-event failure | Manipulation-risk score + event VWAP failure | Prefer no trade; otherwise 30 sec–5 min |

This separation is intentional. BTC and ETH have sufficient liquidity to justify sub-second/order-book models; large alts are better suited to relative-value models; mid/small caps require structural liquidity signals; newly listed assets should be analyzed relative to **listing-time price discovery** rather than historical moving averages; sudden hype requires event detection; and suspected pump-and-dumps should be treated primarily as a **risk/avoidance class**, not an invitation to participate in manipulation. Regulators explicitly warn against participating in virtual-currency pump-and-dump schemes, particularly in thinly traded or newly issued tokens.

The central backtesting principle should be:

> **A signal is not an edge until it remains positive after the exact spread, queue/fill mechanics, fees, slippage, latency, partial fills, funding, and rejected/non-filled orders that would have occurred in production.**

That is especially important in crypto because exchange-level price discovery varies through time, high-frequency activity exhibits recurrent liquidity/volatility patterns, and extremely short-horizon strategies can lose their apparent edge through execution latency alone.

## Separation from CAEMS and definition of the trading universe

The strategy file already in this repo remains a separate strategy family:

`CAEMS = trend/momentum family`

The strategies below live under independent identifiers:

`OFI_BTC`, `ETH_LEADLAG`, `ALT_RESIDUAL`, `SWEEP_MID`, `COMPRESS_SMALL`, `LISTING_OR`, `VSHOCK`, and `PUMP_DEFENSIVE`.

That matters statistically. Combining an EMA strategy with a superficially different strategy that actually responds to the same underlying trend conditions gives less diversification than the strategy count suggests. The goal is to create **orthogonal sources of edge**: microstructure, cross-asset information diffusion, residual mean reversion, liquidity sweeps, volatility transitions, listing price discovery, event shocks, and manipulation detection.

For market-cap buckets, do not permanently hard-code symbols. CoinMarketCap and CoinGecko both expose ranked market-cap information through official APIs, while exchange APIs should remain the source of truth for actual tradability, tick size, lot size, launch status, depth and trades.

A practical point-in-time classification is:

| Group | Research definition |
|---|---|
| BTC | BTC only |
| ETH | ETH only |
| Large-cap alts | Market-cap rank 3–20, excluding stablecoins, wrapped representations and BTC/ETH |
| Mid-cap alts | Rank 21–100 |
| Small-cap alts | Rank 101–500, subject to liquidity eligibility |
| New hype | Venue age ≤7 days; high-risk subset ≤72 hours |
| Sudden hype | Venue age >7 days and real-time abnormal-volume detector triggered |
| Pump candidate | Manipulation/anomaly detector triggered; overlaps another capitalization bucket |

The ranking **must be reconstructed historically** in backtests. Selecting today's top-20 coins and backtesting them several years backward creates survivorship/look-ahead bias.

Market cap alone should never make a coin tradable. The second stage is a venue-liquidity filter:

```
Q_trade <= min(Q_risk, c_D * D_10bp, c_V * V_1m, Q_exchange)
```

where `D_10bp` is displayed executable depth within ±10 bps of mid, `V_1m` is trailing one-minute traded notional, and `c_D, c_V` shrink sharply as liquidity deteriorates.

These are reasonable **initial research defaults**, rather than universal market constants:

| Group | Equity risk/trade | Max % of 10-bp depth | Max % of trailing 1m volume | Gross leverage ceiling |
|---|---:|---:|---:|---:|
| BTC | 0.12% | 5.0% | 0.50% | 2.0x |
| ETH | 0.10% | 4.0% | 0.40% | 2.0x |
| Large alt | 0.08% | 3.0% | 0.30% | 1.5x |
| Mid alt | 0.06% | 2.0% | 0.20% | 1.25x |
| Small alt | 0.04% | 1.0% | 0.10% | 1.0x |
| New listing | 0.03% | 0.5% | 0.05% | 0.75x |
| Sudden hype | 0.03% | 0.5% | 0.05% | 0.75x |
| Pump candidate | 0–0.02% | 0.25% | 0.025% | 0.5x |

Position size remains stop-risk based:

```
N_risk = (E * r) / d_stop
```

where `E` is equity, `r` is group risk per trade and `d_stop` is the stop distance as a fraction of price. The liquidity caps above then override the result.

The lower limits for thin/event coins are intentional. Reported crypto volume can itself be unreliable — research has documented substantial wash-trading problems on some venues, and newer work on meme coins finds manipulation mechanisms including wash trading and liquidity-pool-driven artificial price inflation.

## Group-specific scalp strategies

### BTC — Order-Flow-Imbalance Microprice Impulse

BTC should be the most microstructure-heavy strategy, not another 1-minute trend strategy. Queue imbalance has been shown to contain information about the direction of subsequent mid-price changes; limit-order-book models such as DeepLOB demonstrate that the spatial and temporal configuration of book depth can be predictive.

Use event-level trades and L2 updates, sampled or aggregated at roughly **100 ms–1 second**.

Top-`k` book imbalance:

```
BI_k = (sum(B_i, i=1..k) - sum(A_i, i=1..k)) / (sum(B_i, i=1..k) + sum(A_i, i=1..k))
```

Microprice:

```
P_mu = (P_a*Q_b + P_b*Q_a) / (Q_a + Q_b)
```

where `P_a, P_b` are best ask/bid and `Q_a, Q_b` their queue sizes.

Standardized two-second OFI:

```
OFI_z = (OFI_2s - median(OFI_60s)) / (1.4826 * MAD(OFI_60s))
```

**Long entry:** all of the following:

`OFI_z >= +1.5`; microprice lies at least `0.15 * spread` above mid; aggressive-buy share during the most recent second >= 65%; top-five ask depth is declining rather than replenishing; current spread is no wider than the 60th percentile of its trailing 30-minute distribution.

Short is symmetric.

This signal is too short-lived to force maker entries. Prefer an **IOC/marketable-limit taker entry** only when:

```
E[delta_P_5s] > taker_fee + spread_cost + impact + safety_buffer
```

**Stop:** greater of `1.5 * current spread` or `0.8 * robust 10-second return sigma`.

**Take profit:** initially `1.2R`; additionally close immediately if `OFI_z` crosses zero and microprice flips against the position.

**Time stop:** 8 seconds.

**Position risk:** 0.12% equity, subject to BTC's depth/volume caps above.

The primary research question here is not whether OFI predicts direction — it often can — but whether the forecast remains large enough relative to fees and latency. Order-book research specifically identifies adverse selection and latency as central problems for high-frequency execution.

### ETH — Dynamic BTC-to-ETH Lead/Lag Residual

ETH should exploit information propagation rather than copying BTC's standalone OFI strategy. Crypto price discovery is not uniform across markets or exchanges, and research has found meaningful cross-cryptocurrency predictability, although even the **sign** of lead-lag relationships can vary. That means the relationship must be estimated rather than assumed permanently.

Dynamic hedge ratio via Kalman filter or exponentially weighted regression:

```
r_ETH_t = alpha_t + beta_t * r_BTC_t + epsilon_t
```

Three-second lag gap:

```
G_t = beta_t * r_BTC[t-3s,t] - r_ETH[t-3s,t]
```

Standardize `G` over the preceding 30–60 minutes.

**Long entry:** `G_z >= +1.5` (BTC's movement implies ETH has materially lagged); ETH aggressive-flow imbalance over the most recent 2 seconds is non-negative; BTC's one-second OFI has not reversed; ETH spread <= trailing 70th percentile.

**Short entry:** symmetric.

Crucially, enable the strategy only when the rolling walk-forward model confirms that BTC-leading/ETH-catching-up has the **same sign out of sample**. If the estimated relationship becomes negative or insignificant, disable rather than mechanically reversing every signal.

**Exit:** when `|G_z| <= 0.4` (expected convergence largely complete).

**Stop:** when `|G_z| >= 2.5` against the trade *and* BTC's initiating impulse reverses.

**Maximum hold:** 45 seconds.

**Minimum expected edge:** 1.5x estimated round-trip trading cost.

**Position risk:** 0.10% equity.

Useful supplementary features: ETH spot/perpetual basis, funding regime, BTC/ETH cross-venue price dispersion.

### Large-Cap Altcoins — BTC/ETH Beta-Residual VWAP Reversion

Liquid large alts are ideal candidates for a **market-neutral relative-value scalp**.

```
r_i = alpha_i + beta_BTC * r_BTC + beta_ETH * r_ETH + epsilon_i
```

via an online Kalman filter or robust rolling regression.

15-minute standardized cumulative residual:

```
Z_eps = (sum(eps) - median_6h(sum(eps))) / (1.4826 * MAD_6h(sum(eps)))
```

Also compute session VWAP and 30-second cumulative volume delta (CVD).

**Long:** residual `Z <= -2.0`, price at least `1.5` robust-sigma below session/rolling VWAP, and 30-second CVD has turned positive.

**Short:** residual `Z >= +2.0`, price stretched above VWAP, CVD rolls negative.

**Target:** first of VWAP touch or residual `|Z| <= 0.5`.

**Stop:** residual reaches `|Z| >= 3.0` against the trade or the asset makes a fresh idiosyncratic high/low with confirming CVD.

**Time stop:** 8 minutes.

**Signal timeframe:** 10-second features, 1-minute context.

**Position risk:** 0.08%.

The strategy should explicitly neutralize broad crypto movement — a strong common component exists in crypto trading/price formation, alongside meaningful segmentation across exchanges, so treating every alt price move as asset-specific information is dangerous.

### Mid-Cap Alts — Liquidity-Sweep Reclaim

Mid-caps should focus on **failed liquidity grabs** rather than continuous trend indicators.

Track the prior 15-minute high/low, aggressive trade CVD and top-five-level book depth.

Long setup:

1. Price trades beneath the previous 15-minute low by at least `max(8 bps, 3 * spread)`.
2. Within 30 seconds it returns above that old low.
3. Sell CVD makes a new low while price fails to continue lower: absorption/divergence.
4. Bid depth inside 10 bps recovers to at least 70% of its pre-sweep depth within five seconds.
5. Spread has returned below 1.5x its pre-event median.

Enter on the first post-reclaim trade through the previous low.

**Stop:** one current spread below the actual sweep low.

**TP1:** 1R, optional 30–50% reduction.

**Final target:** 1.8R or the midpoint of the pre-sweep 15-minute range, whichever comes first.

**Time stop:** six minutes.

Short setup mirrors the procedure above the previous 15-minute high.

**Position risk:** 0.06% equity.

The key feature is **depth recovery**. A wick by itself has almost no informational value; a wick followed by absorption, reclaim, and liquidity replenishment gives a testable microstructural hypothesis.

### Small-Cap Alts — Compression-to-Expansion Breakout

For small caps, traditional indicators often react too slowly relative to sudden liquidity changes. Use volatility compression and book depletion.

Calculate: 20-minute high/low channel; Parkinson or realized high-low volatility over 20 minutes; percentile of that volatility relative to the previous six hours; top-five-level depth; ten-second aggressive-trade imbalance.

A setup exists only when 20-minute volatility is below its trailing **35th percentile** and spread/depth have remained stable for at least five minutes.

**Long:** price trades at least two spreads above the 20-minute high; >=70% of ten-second aggressive notional is buyer-initiated; >=60% of the pre-breakout top-five ask depth has been consumed; the ask does not fully replenish within three seconds.

**Short:** symmetric.

**Stop:** back inside the old range by two spreads.

**TP:** 1.8R.

At +1R, tighten the invalidation level to the old breakout boundary rather than a CAEMS-style ATR/breakeven rule.

**Time stop:** eight minutes.

**Position risk:** 0.04%; no averaging down.

The performance driver is a transition from low realized volatility to a genuine order-flow-driven range expansion. The major danger is false breakout plus slippage, which is why depth consumption and replenishment matter more here than a generic volume threshold.

### New Hype Coins and Recent Listings — Opening-Range Anchored VWAP

A newly listed coin has insufficient history for a meaningful 20-, 50-, or 200-period trend model. The natural reference points are **listing time, opening range, and transaction-weighted price discovery**.

Do **nothing during the first 60 seconds**.

Establish a three-minute opening range, then calculate anchored VWAP from the first trade:

```
AVWAP_t = sum(P_j * V_j, j=0..t) / sum(V_j, j=0..t)
```

Long continuation setup requires:

- price above listing AVWAP;
- initial opening-range high has already been broken once;
- first pullback retraces to between AVWAP and the upper half of the opening range;
- 30-second aggressive buy/sell notional ratio >= 1.5;
- spread has fallen below 1.25x the median spread of minutes two through four;
- displayed depth within 20 bps is at least 100x proposed position notional.

Enter when price retakes the local 15-second high after the pullback.

**Stop:** beneath the pullback low or AVWAP by two spreads, whichever is farther.

**TP1:** 1R.

**TP2:** 2R or exit when 30-second aggressive flow turns net negative.

**Time stop:** eight minutes.

**Position risk:** 0.03%.

For DEX-originating/new-chain tokens, add an on-chain **eligibility layer**, not necessarily a directional alpha feature: holder concentration, mint/freeze authority, pool liquidity, large wallet inflows/outflows and liquidity removal.

For extremely new tokens, require pool/exchange liquidity at least **100x planned trade notional** and reject assets whose holder/concentration risk makes an ordinary stop unrealistic.

### Sudden-Hype Coins — Volume-Shock State Machine

A sudden hype coin is different from a recent listing: it has history, but abruptly enters a new state.

Crypto activity has measurable intraday/intraweek periodicity, so raw volume should be normalized against the appropriate time-of-week baseline rather than assuming every hour has the same expected activity.

Seasonally normalized 60-second notional-volume z-score:

```
Z_V = (V_60s - mu_dow_hour) / sigma_dow_hour
```

Trigger **event mode** when:

```
Z_V >= 5  AND  |Z_r_60s| >= 3
```

Then classify the event.

A **continuation long** requires aggressive-buy share >65%, positive price impact per unit traded notional, no immediate collapse in displayed bid depth and, for perpetual futures, 5-minute OI change >+0.5%.

Do **not** buy the vertical impulse. Wait for a 20–40% retracement of the impulse and enter when the ten-second high is retaken with flow still positive.

**Stop:** below the retracement low.

**Target:** 1.5R initially; exit earlier if volume shock decays below `Z_V=2` and CVD flips.

An **exhaustion/fade state** requires the opposite configuration: price makes a fresh extreme but CVD fails to confirm, open interest rolls over, and price loses the midpoint of the impulse. Model this state separately rather than mixing continuation and fade trades into the same statistics.

**Position risk:** 0.03% equity per event; impose one loss per symbol per event before a 10-minute cooldown.

### Pump-and-Dump Candidates — Detection First, Post-Failure Trading Only

This is not designed as a strategy for joining or inducing a pump. Coordinating or participating in manipulative pumping creates both extreme trading risk and potential legal problems. Regulators explicitly warn against participating in crypto pump-and-dumps, while empirical research finds these episodes can complete within minutes and exhibit identifiable pre-/post-event patterns.

Treat this as a **risk classifier**.

A research candidate can be flagged when several of these occur together:

```
|r_5m| > 4*sigma  AND  V_5m > 10x baseline
```

plus unusually high cancellation-to-trade activity, depth that appears and disappears without corresponding trades, concentrated ownership, abnormal trade-size distributions, or a major mismatch between reported volume and executable depth.

No long entry is permitted after the detector fires.

**The default action is: NO TRADE.**

An optional research-only post-collapse short may be tested only where a legitimate short instrument exists and depth is sufficient:

- initial pump has already rolled over;
- price closes beneath event-anchored VWAP;
- first attempt to reclaim event VWAP fails;
- 30-second CVD remains negative;
- spread has normalized;
- the intended trade is <=0.25% of 10-bp book depth.

Entry below the failed-reclaim candle/event low.

**Stop:** above the reclaim high.

Take 50% at 1.5R; final target is either 3R or the pre-event price region.

**Position risk:** no more than 0.02% equity.

A suspected pump should never receive increased leverage merely because the theoretical R:R appears attractive.

## Typical horizons

```
BTC          : 100ms-1s book events -> 2s OFI state -> 2-8s position
ETH          : 250ms-1s BTC/ETH data -> 3s lag gap -> 10-45s position
Large alts   : 10s flow/residuals -> 15m residual context -> 1-8m position
Mid alts     : liquidity sweep -> 5-30s reclaim confirmation -> 0.5-6m position
Small alts   : 20m compression -> seconds-level breakout confirmation -> 1-8m position
New listings : first 60s excluded -> 3m opening range -> 0.5-8m position
Sudden hype  : 60s shock detector -> 20-40% retracement -> seconds-5m position
Pump risk    : anomaly detected -> wait for full failure -> no trade or post-failure only
```

## Forecasting, feature engineering and backtesting design

The forecasting layer should not merely predict whether the next candle is green. The target must correspond to an **executable economic opportunity**.

For each signal timestamp `t`, simulate a realistic decision and network delay `L`, determine the fill that would have been available at `t+L`, and label the subsequent path relative to that fill.

Triple-barrier-style label:

```
y_t = +1  if net TP reached first
    = -1  if net SL reached first
    =  0  if time horizon reached first
```

where both barriers already include expected spread, fees and slippage.

Recommended labeling horizons:

| Group | Prediction horizons to test |
|---|---|
| BTC | 1s, 3s, 5s, 10s |
| ETH | 5s, 15s, 30s, 60s |
| Large alt | 30s, 1m, 3m, 5m |
| Mid alt | 30s, 1m, 3m, 6m |
| Small alt | 1m, 3m, 5m, 10m |
| New listing | 30s, 1m, 3m, 5m |
| Sudden hype | 15s, 30s, 1m, 3m |
| Pump failure | 30s, 1m, 3m, 5m |

Do not choose the horizon that looks best on the final test set. Establish candidate horizons in the research specification, tune on train/validation periods, and leave the final period untouched.

The feature library should be group-dependent (★ = relative importance):

| Feature family | BTC | ETH | Large | Mid | Small | Listing | Vol shock | Pump |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| OFI / L2 imbalance | ★★★ | ★★ | ★ | ★★ | ★★ | ★★ | ★★ | ★★ |
| Microprice | ★★★ | ★★ | | | | | | |
| BTC lead/lag | ★ | ★★★ | ★★ | ★ | ★ | ★ | ★ | ★ |
| Dynamic beta residual | | ★★★ | ★★★ | ★ | | | | |
| VWAP/AVWAP | | | ★★★ | ★ | | ★★★ | ★★ | ★★★ |
| CVD/aggressive flow | ★★ | ★★ | ★★★ | ★★★ | ★★ | ★★★ | ★★★ | ★★★ |
| Range compression | | | | ★ | ★★★ | | | |
| Depth refill/depletion | ★★★ | ★ | ★ | ★★★ | ★★★ | ★★ | ★★ | ★★★ |
| OI/funding | ★ | ★★ | ★ | ★ | | ★ | ★★★ | ★★ |
| On-chain concentration | | | | | ★ | ★★★ | ★ | ★★★ |
| Listing age | | | | | | ★★★ | ★ | ★ |
| Seasonal volume z-score | ★ | ★ | ★ | ★ | ★ | ★ | ★★★ | ★★★ |

Model stack should start simple:

- **Statistical models** — logistic regression for direction/probability, Kalman/state-space models for dynamic BTC/ETH and alt beta, ARX models for lead-lag, robust quantile regression for conditional future returns, Hawkes/event-intensity models for high-frequency trade/book-event clustering.
- **Machine learning** — begin with gradient-boosted trees (XGBoost, LightGBM, CatBoost) using carefully constructed microstructure features. Only BTC/ETH should initially justify expensive full-depth architectures such as CNN-LSTM/DeepLOB, since deep order-book models require enormous event data and are operationally harder to make latency-safe.
- **Manipulation/sudden-hype classification** — anomaly models in addition to supervised classifiers: Isolation Forest, robust covariance/Mahalanobis scores, autoencoder reconstruction error, or positive-unlabeled learning. Pump labels are intrinsically incomplete — a naive binary supervised model can learn the labeling process instead of manipulation itself.

Different lookbacks by signal family:

| Group | Fast feature window | Context window | Initial rolling model-training window |
|---|---|---|---|
| BTC | 100 ms–10 sec | 1–60 min | 30–60 days |
| ETH | 1–60 sec | 1–24 h | 60 days |
| Large | 10 sec–15 min | 6 h–7 d | 90–180 days |
| Mid | 5 sec–60 min | 1–7 d | 180 days pooled |
| Small | 10 sec–20 min | 6 h–30 d | 180–365 days pooled |
| Listings | seconds since listing | event age | previous 12–24 months of listings |
| Volume shock | 10 sec–5 min | 30-day seasonal baseline | 12–24 months of events |
| Pump | seconds–30 min | 7–90 d | all prior labeled events + controls |

Pooling is particularly important in small-cap and listing strategies because individual symbols have too little stable history.

Validation workflow must be fully chronological:

```
Raw trades / L2 / derivatives / on-chain
  -> Timestamp normalization
  -> Point-in-time symbol universe
  -> Reconstructed order books
  -> Feature store
  -> Signal / statistical / ML model
  -> Decision timestamp
  -> Inject measured latency
  -> Queue + fill simulator
  -> Fees / slippage / funding
  -> Net trade ledger
  -> Walk-forward validation
  -> Stress tests
  -> Composite score
  -> Threshold passed? --no--> Reject / redesign
                        --yes-> Paper trading -> Small-capital shadow/live
```

At minimum, conduct rolling walk-forward evaluation rather than random train/test splitting. Random shuffling permits future market regimes to leak into training and is inappropriate for a nonstationary time series.

A strong schedule: `60% expanding/rolling train -> 20% validation -> 20% untouched test`, followed by multiple walk-forward folds.

For event strategies, split **by event**, not rows. All observations from one listing or one pump episode must remain in the same fold, otherwise the model effectively sees later stages of an event while being evaluated on its beginning.

## Scoring, selection and strategy weighting

Economic evaluation should dominate predictive classification accuracy. A model with 55% directional accuracy that trades efficiently can be superior to a 65% model whose predictions arrive after the opportunity has vanished.

```
Sharpe = mean(r_d) / std(r_d) * sqrt(365)

MDD = max_t(1 - E_t / max_{s<=t}(E_s))

WR = N_net_winning_trades / N_closed_trades

Exp = P(win) * mean(W) - P(loss) * mean(L)     [net of fees]

WR_BE = mean(L) / (mean(W) + mean(L))          [break-even win rate]
```

Latency-adjusted P&L: reconstruct with assumed order arrival at `t_arrival = t_decision + L`. Use several latency scenarios and, ultimately, measured production p50/p90/p95.

```
LatencyRetention = PnL_at_p95_latency / PnL_low_latency_benchmark
```

A strategy whose P&L collapses when execution is delayed 100–250ms is fundamentally different from one whose edge survives seconds.

Practical 0–100 normalization:

```
S_Sharpe = 100 * clip((Sharpe - 0.5) / 1.5, 0, 1)
S_DD     = 100 * clip(1 - MDD / DD_cap, 0, 1)
S_WR     = clip(50 + 500 * (WR - WR_BE), 0, 100)
S_Exp    = 100 * clip(Exp_net_bps / C_round_trip_bps, 0, 1)
S_L      = 100 * clip((LatencyRetention - 0.40) / 0.50, 0, 1)
```

A 90% latency-retention strategy receives full latency credit; one retaining only 40% receives zero.

Weights differ by group:

| Group | Sharpe | Drawdown | Win-rate quality | Expectancy | Latency-adjusted P&L |
|---|---:|---:|---:|---:|---:|
| BTC | 25% | 15% | 10% | 20% | 30% |
| ETH | 25% | 15% | 10% | 20% | 30% |
| Large alt | 25% | 20% | 10% | 20% | 25% |
| Mid alt | 20% | 25% | 10% | 20% | 25% |
| Small alt | 15% | 30% | 10% | 20% | 25% |
| New listing | 10% | 30% | 10% | 20% | 30% |
| Sudden hype | 10% | 30% | 10% | 20% | 30% |
| Pump defensive | 5% | 40% | 5% | 20% | 30% |

```
Score_g = sum(w_g,m * S_m for m in metrics)
```

Drawdown caps for scoring should initially be approximately 8% for BTC/ETH, 10% large-cap, 12% mid-cap, 15% small-cap, 12% listing/hype and 8% for any pump-related system.

The composite score alone is **not enough**. Before scoring, impose hard rejection gates:

| Gate | Minimum requirement |
|---|---|
| Net expectancy | >0 after all costs |
| OOS Sharpe | >=1.0 |
| Latency retention | >=60% |
| Drawdown | Below group limit |
| Fee stress | Still non-negative with fees/slippage +25% |
| Concentration | No single day/event produces >25% of total OOS profit |
| Sample | >=500 OOS trades liquid groups; >=250 pooled trades/events for sparse groups |
| Stability | Positive in >=60% of independent walk-forward folds/event cohorts |
| Kill-switch realism | Simulated stale-book/outage scenarios do not create catastrophic loss |

For sparse new-listing strategies, "250" means pooled trades across independent listings, not 250 trades on one newly launched token.

Decision rubric:

| Composite | Decision |
|---:|---|
| >=75 | Eligible for paper -> very small live shadow deployment |
| 65–74 | Paper trade only; collect execution evidence |
| 55–64 | Research candidate; redesign before deployment |
| <55 | Reject |

If several variants survive within one group, do not simply select the highest historical return:

```
raw_i = max(Score_i - 60, 0)^2 / sigma_i
```

normalize the surviving `raw_i` values, then apply a correlation penalty — strategies with >0.70 correlation of daily net P&L should generally be treated as variants of the same risk source rather than independently allocated strategies.

The result should be **risk weighting, not capital weighting**. A $10,000 small-cap strategy position can carry more tail risk than a much larger BTC position.

## Data pipeline, execution simulation and implementation

The data architecture should be event-native from day one.

Binance exposes real-time trades, book tickers and depth updates; reconstruct a local order book by buffering WebSocket updates, obtaining a REST snapshot and applying sequence-numbered deltas. Bybit's WebSocket orderbook similarly publishes snapshots/deltas. Coinbase Advanced Trade exposes `level2`, market trades, ticker and status channels.

Recommended normalized event schema:

```
exchange
symbol
exchange_timestamp
local_receive_timestamp
sequence_id
event_type
trade_price
trade_size
aggressor_side
bid_px[1..N]
bid_qty[1..N]
ask_px[1..N]
ask_qty[1..N]
mark_price
index_price
funding_rate
open_interest
listing_time
data_quality_flags
```

Keep both exchange timestamp and local receive timestamp. Never overwrite one with the other — their difference is part of the latency/data-quality research.

For historical candles/trades, official venue endpoints should be the first choice. For L2 backtesting, ordinary OHLCV data is insufficient — either capture the exchange feed continuously or use a historical L2 vendor after validating its sequencing and timestamps. The live system and the backtest should consume the **same normalized event format**.

Taker execution simulated by walking the visible book after latency:

```
decision at t
  -> t_arrive = t + sampled_latency
  -> read reconstructed book at t_arrive
  -> consume ask/bid levels until quantity filled
  -> VWAP_fill = sum(price_i * qty_i) / sum(qty_i)
  -> charge taker fee
```

Maker simulation must be more conservative:

```
place limit
  -> estimate quantity ahead in queue
  -> process subsequent trades/cancels
  -> fill only when executable queue ahead is depleted
  -> allow partial fills
  -> cancel remainder at TTL
  -> record post-fill markout
```

Do not give a maker order a fill merely because the candle touched its price.

Round-trip cost model:

```
Cost_RT = fee_entry + fee_exit + spread + impact_entry + impact_exit + funding + adverseSelection
```

For an aggressive order of notional `Q`, estimate nonlinear impact empirically:

```
Impact(Q) = k * (Q / D_10bp)^alpha
```

Fit `k, alpha` separately by symbol, session and volatility regime rather than inventing a universal constant.

CAEMS's markout instrumentation remains valuable here even though the strategy signals are different — every strategy should record `+1s`, `+5s`, `+30s`, and strategy-horizon markouts by entry type, venue and signal bucket. The execution infrastructure is reusable even though the alpha engines are intentionally different.

## Comparison table

| Group / strategy | Performance driver | Indicator uniqueness | Liquidity requirement | Primary failure mode | Execution preference |
|---|---|---|---|---|---|
| BTC OFI | Immediate supply/demand imbalance | Microprice, OFI, queue depletion | Extremely high | Edge lost to latency/adverse selection | Taker/IOC |
| ETH lead-lag | Information diffusion from BTC | Dynamic beta, lag residual | Very high | Relationship changes sign/regime | Taker/marketable limit |
| Large-alt residual | Idiosyncratic deviation mean reverts | BTC/ETH beta + VWAP + CVD | High | "Residual" is real news, not noise | Maker or selective taker |
| Mid sweep reclaim | Stop/liquidity sweep fails | Sweep + absorption + depth refill | Medium-high | Sweep becomes genuine trend | Reclaim-triggered limit/taker |
| Small compression | Volatility expansion after compression | Realized-vol percentile + range + depletion | Medium | False breakout/slippage | Marketable limit |
| New listing OR | Opening price discovery | Listing AVWAP + opening range | Variable but must stabilize | No meaningful fair value / rug risk | Small taker |
| Sudden hype | Persistent abnormal flow | Seasonal volume shock + CVD + OI | Variable | Event reverses instantaneously | Small taker |
| Pump defensive | Collapse after manipulation fails | Anomaly + event VWAP failure | Must be adequate for short | Squeeze/manipulated book | Prefer no trade |

Primary data hierarchy:

1. **Execution truth: exchange-native feeds** — Binance/Coinbase Advanced Trade/Bybit V5 supply trades, BBO/L2 depth, instrument rules and actual order/execution telemetry.
2. **Derivatives context: exchange-native funding/OI/mark-price data** — take these fields directly from the specific trading venue whenever possible rather than inferring from third-party dashboards.
3. **Market-cap/universe classification: CoinMarketCap or CoinGecko** — appropriate for classification, not for reconstructing fills.
4. **On-chain data: native chain RPC wherever practical** — use vendor-indexed data only when the speed/complexity of running/indexing native nodes becomes operationally unreasonable.
5. **Research references: microstructure/market-quality literature** — useful for hypotheses, never a substitute for venue-specific cost-adjusted replay.

## Implementation sequence (research/build order for this track)

1. Keep CAEMS untouched as its own versioned EMA-momentum benchmark.
2. Build the common event/L2 replay and execution simulator before optimizing any of these new strategies.
3. Implement BTC OFI and large-alt residual reversion first — two very different edges, substantially better research conditions than illiquid hype coins.
4. Add ETH lead-lag and mid-cap sweep/reclaim.
5. Only after the execution simulator demonstrates realistic partial fills, impact and latency should small-cap breakout, listing and volume-shock strategies enter paper testing.
6. Run the pump detector primarily as a **trade-blocking/risk classifier**. A post-failure short remains optional and independently validated; it should never become a mechanism for chasing or joining coordinated pumps.

The resulting architecture asks a different market-structure question per group, instead of one "is the EMA trend strong enough to buy?" question applied everywhere:

- **BTC:** Is immediate displayed and executed order flow sufficiently imbalanced to move the next few ticks?
- **ETH:** Has BTC transmitted information that ETH has not yet incorporated?
- **Large alt:** Has the coin temporarily deviated from its BTC/ETH-implied fair move?
- **Mid alt:** Did a liquidity sweep fail and get absorbed?
- **Small alt:** Is a genuine liquidity-backed volatility expansion emerging from compression?
- **New listing:** Has initial price discovery stabilized enough for an opening-range/AVWAP continuation?
- **Sudden hype:** Is an abnormal-volume event continuing or exhausting?
- **Pump candidate:** Is this market so abnormal that the correct strategy is to stay out — and, only after a fully confirmed failure, is a tightly controlled post-event trade justified?
