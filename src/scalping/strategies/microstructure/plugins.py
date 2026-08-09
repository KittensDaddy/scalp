"""Live microstructure strategies — best-effort proxies from bookTicker + 1m candles.

Maps DOCS/strategy-microstructure-multiasset.md families onto available feeds.
Missing L2/CVD/OI gates are omitted (not fabricated). Signals are real accept/reject.
"""

from __future__ import annotations

from datetime import datetime

from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import RejectionReason, Side, SignalCandidate, StrategyEvaluation
from scalping.market_data.registry import SymbolState
from scalping.strategies.caems.engine import MarketQualityFlags, MarketSnapshot, RiskCostDecision
from scalping.strategies.microstructure.common import (
    beta_residual_z,
    candle_closes,
    common_gates,
    entry_price,
    make_signal_at,
    reject,
    returns_from_closes,
    robust_z,
)


def _gate(
    *,
    side: Side,
    snapshot: MarketSnapshot,
    config: EffectiveConfig,
    flags: MarketQualityFlags,
    risk_cost: RiskCostDecision,
    evaluated_at: datetime,
    config_hash: str,
) -> tuple[StrategyEvaluation, None] | None:
    reason = common_gates(
        side=side, snapshot=snapshot, config=config, flags=flags, risk_cost=risk_cost
    )
    if reason is None:
        return None
    return reject(
        symbol=snapshot.symbol,
        side=side,
        evaluated_at=evaluated_at,
        config_hash=config_hash,
        reason=reason,
    )


class OfiBtcStrategy:
    """BTC top-of-book OFI + microprice impulse (bookTicker proxy for L2 OFI)."""

    strategy_id = "OFI_BTC"
    strategy_version = "OFI_BTC"

    def accepts_class(self, symbol_class: str) -> bool:
        return symbol_class == "btc"

    def evaluate(
        self,
        *,
        side: Side,
        snapshot: MarketSnapshot,
        state: SymbolState,
        config: EffectiveConfig,
        frozen: FrozenParams,
        config_hash: str,
        evaluated_at: datetime,
        flags: MarketQualityFlags,
        risk_cost: RiskCostDecision,
        symbol_class: str,
        btc_snapshot: MarketSnapshot | None = None,
    ) -> tuple[StrategyEvaluation, SignalCandidate | None]:
        blocked = _gate(
            side=side, snapshot=snapshot, config=config, flags=flags,
            risk_cost=risk_cost, evaluated_at=evaluated_at, config_hash=config_hash,
        )
        if blocked:
            return blocked
        bt = state.last_book_ticker
        if bt is None:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        ofi_z = state.book_micro.ofi_z()
        imb = state.book_micro.imbalance()
        premium = state.book_micro.microprice_premium_spreads(bt)
        spread_pct = state.book_micro.spread_percentile(bt.spread_bps)
        if ofi_z is None or premium is None or imb is None:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        if spread_pct is not None and spread_pct > 0.60:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.SPREAD_TOO_WIDE,
            )
        long_ok = side is Side.LONG and ofi_z >= 1.5 and premium >= 0.15 and imb > 0.0
        short_ok = side is Side.SHORT and ofi_z <= -1.5 and premium <= -0.15 and imb < 0.0
        if not (long_ok or short_ok):
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DEAD_BAND_TOO_SMALL,
                strength=abs(ofi_z),
            )
        entry = entry_price(state, snapshot)
        stop_dist = max(1.5 * (bt.ask_price - bt.bid_price), entry * 0.0004)
        return make_signal_at(
            strategy_id=self.strategy_id, symbol=snapshot.symbol, side=side,
            entry=entry, evaluated_at=evaluated_at, config_hash=config_hash,
            strength=abs(ofi_z), stop_dist=stop_dist, tp_r=1.2,
        )


class EthLeadlagStrategy:
    """ETH catch-up to BTC via 1m residual lag gap (proxy for 3s lead/lag)."""

    strategy_id = "ETH_LEADLAG"
    strategy_version = "ETH_LEADLAG"

    def accepts_class(self, symbol_class: str) -> bool:
        return symbol_class == "eth"

    def evaluate(
        self,
        *,
        side: Side,
        snapshot: MarketSnapshot,
        state: SymbolState,
        config: EffectiveConfig,
        frozen: FrozenParams,
        config_hash: str,
        evaluated_at: datetime,
        flags: MarketQualityFlags,
        risk_cost: RiskCostDecision,
        symbol_class: str,
        btc_snapshot: MarketSnapshot | None = None,
    ) -> tuple[StrategyEvaluation, SignalCandidate | None]:
        blocked = _gate(
            side=side, snapshot=snapshot, config=config, flags=flags,
            risk_cost=risk_cost, evaluated_at=evaluated_at, config_hash=config_hash,
        )
        if blocked:
            return blocked
        if btc_snapshot is None:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        # Need BTC candle history via closes on ETH side: use snapshot returns from
        # eth state + btc_snapshot single bar is not enough — runner passes btc_snapshot
        # only. Use eth candles and approximate BTC move from btc_strength + close path
        # stored when we have paired updates via shared residual on last closes.
        eth_closes = candle_closes(state.candles_1m)
        if len(eth_closes) < 45:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        btc_closes = self._btc_closes
        if len(btc_closes) < 45:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        n = min(len(eth_closes), len(btc_closes))
        eth_r = returns_from_closes(eth_closes[-n:])
        btc_r = returns_from_closes(btc_closes[-n:])
        m = min(len(eth_r), len(btc_r))
        if m < 40:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        # Gap G = beta*r_btc - r_eth (positive => ETH lagged a BTC up-move)
        mean_b = sum(btc_r[-m:]) / m
        mean_e = sum(eth_r[-m:]) / m
        var_b = sum((x - mean_b) ** 2 for x in btc_r[-m:]) / m
        if var_b <= 1e-18:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        cov = sum(
            (e - mean_e) * (b - mean_b) for e, b in zip(eth_r[-m:], btc_r[-m:], strict=True)
        ) / m
        beta = cov / var_b
        gaps = [beta * b - e for e, b in zip(eth_r[-m:], btc_r[-m:], strict=True)]
        g_z = robust_z(gaps)
        if g_z is None:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        long_ok = side is Side.LONG and g_z >= 1.5
        short_ok = side is Side.SHORT and g_z <= -1.5
        if not (long_ok or short_ok):
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DEAD_BAND_TOO_SMALL,
                strength=abs(g_z),
            )
        entry = entry_price(state, snapshot)
        stop_dist = max(snapshot.atr14_1m * 0.5, entry * 0.001)
        return make_signal_at(
            strategy_id=self.strategy_id, symbol=snapshot.symbol, side=side,
            entry=entry, evaluated_at=evaluated_at, config_hash=config_hash,
            strength=abs(g_z), stop_dist=stop_dist, tp_r=1.2,
        )

    def __init__(self) -> None:
        self._btc_closes: list[float] = []

    def seed_btc_closes(self, closes: list[float]) -> None:
        if len(closes) >= len(self._btc_closes):
            self._btc_closes = list(closes[-120:])

    def note_btc_close(self, close: float) -> None:
        if self._btc_closes and self._btc_closes[-1] == close:
            return
        self._btc_closes.append(close)
        if len(self._btc_closes) > 120:
            self._btc_closes = self._btc_closes[-120:]


class AltResidualStrategy:
    """Large/mid alt residual reversion vs BTC (1m)."""

    strategy_id = "ALT_RESIDUAL"
    strategy_version = "ALT_RESIDUAL"

    def __init__(self, *, z_entry: float = 2.0, min_bars: int = 40) -> None:
        self.z_entry = z_entry
        self.min_bars = min_bars
        self._btc_closes: list[float] = []
        self._alt_closes: dict[str, list[float]] = {}
        self._last_key: dict[str, datetime | None] = {}

    def accepts_class(self, symbol_class: str) -> bool:
        return symbol_class in {"major_alt", "mid_alt"}

    def seed_btc_closes(self, closes: list[float]) -> None:
        if len(closes) >= len(self._btc_closes):
            self._btc_closes = list(closes[-120:])

    def note_btc_close(self, close: float, close_time: datetime | None = None) -> None:
        if self._btc_closes and self._btc_closes[-1] == close:
            return
        self._btc_closes.append(close)
        if len(self._btc_closes) > 120:
            self._btc_closes = self._btc_closes[-120:]

    def evaluate(
        self,
        *,
        side: Side,
        snapshot: MarketSnapshot,
        state: SymbolState,
        config: EffectiveConfig,
        frozen: FrozenParams,
        config_hash: str,
        evaluated_at: datetime,
        flags: MarketQualityFlags,
        risk_cost: RiskCostDecision,
        symbol_class: str,
        btc_snapshot: MarketSnapshot | None = None,
    ) -> tuple[StrategyEvaluation, SignalCandidate | None]:
        blocked = _gate(
            side=side, snapshot=snapshot, config=config, flags=flags,
            risk_cost=risk_cost, evaluated_at=evaluated_at, config_hash=config_hash,
        )
        if blocked:
            return blocked
        if btc_snapshot is None:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        key = state.last_kline_1m_close_time
        series = self._alt_closes.setdefault(snapshot.symbol, [])
        if self._last_key.get(snapshot.symbol) != key:
            series.append(snapshot.completed_close)
            if len(series) > 120:
                self._alt_closes[snapshot.symbol] = series[-120:]
                series = self._alt_closes[snapshot.symbol]
            self._last_key[snapshot.symbol] = key
            # keep btc series in sync once per bar from snapshot
            if not self._btc_closes or self._btc_closes[-1] != btc_snapshot.completed_close:
                self.note_btc_close(btc_snapshot.completed_close)

        alt_r = returns_from_closes(series)
        btc_r = returns_from_closes(self._btc_closes)
        z = beta_residual_z(alt_r, btc_r, min_bars=self.min_bars)
        if z is None:
            # Prefer candles_1m if strategy state cold after restart mid-warm
            alt_r2 = returns_from_closes(candle_closes(state.candles_1m))
            z = beta_residual_z(alt_r2, btc_r, min_bars=self.min_bars)
        if z is None:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        long_ok = side is Side.LONG and z <= -self.z_entry
        short_ok = side is Side.SHORT and z >= self.z_entry
        if not (long_ok or short_ok):
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DEAD_BAND_TOO_SMALL,
                strength=abs(z),
            )
        entry = entry_price(state, snapshot)
        stop_dist = max(snapshot.atr14_1m, entry * 0.002)
        return make_signal_at(
            strategy_id=self.strategy_id, symbol=snapshot.symbol, side=side,
            entry=entry, evaluated_at=evaluated_at, config_hash=config_hash,
            strength=abs(z), stop_dist=stop_dist, tp_r=1.35,
        )


class SweepMidStrategy:
    """Mid-cap liquidity-sweep reclaim on 1m (15-bar high/low)."""

    strategy_id = "SWEEP_MID"
    strategy_version = "SWEEP_MID"

    def accepts_class(self, symbol_class: str) -> bool:
        return symbol_class == "mid_alt"

    def evaluate(
        self,
        *,
        side: Side,
        snapshot: MarketSnapshot,
        state: SymbolState,
        config: EffectiveConfig,
        frozen: FrozenParams,
        config_hash: str,
        evaluated_at: datetime,
        flags: MarketQualityFlags,
        risk_cost: RiskCostDecision,
        symbol_class: str,
        btc_snapshot: MarketSnapshot | None = None,
    ) -> tuple[StrategyEvaluation, SignalCandidate | None]:
        blocked = _gate(
            side=side, snapshot=snapshot, config=config, flags=flags,
            risk_cost=risk_cost, evaluated_at=evaluated_at, config_hash=config_hash,
        )
        if blocked:
            return blocked
        candles = list(state.candles_1m)
        if len(candles) < 16:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        window = candles[-16:-1]
        last = candles[-1]
        prior_low = min(c.low for c in window)
        prior_high = max(c.high for c in window)
        spread_frac = snapshot.spread_bps / 10_000.0
        pad = max(0.0008, 3 * spread_frac) * last.close
        vol_ok = last.quote_volume >= 1.3 * max(snapshot.volume_median_30, 1e-9)
        if side is Side.LONG:
            swept = last.low <= prior_low - pad
            reclaimed = last.close > prior_low
            ok = swept and reclaimed and vol_ok
            sweep_ext = prior_low - last.low
        else:
            swept = last.high >= prior_high + pad
            reclaimed = last.close < prior_high
            ok = swept and reclaimed and vol_ok
            sweep_ext = last.high - prior_high
        if not ok:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.PRICE_CONFIRMATION_FAILED,
            )
        entry = entry_price(state, snapshot)
        stop_dist = max(sweep_ext + (last.close * spread_frac), entry * 0.001)
        return make_signal_at(
            strategy_id=self.strategy_id, symbol=snapshot.symbol, side=side,
            entry=entry, evaluated_at=evaluated_at, config_hash=config_hash,
            strength=min(5.0, sweep_ext / max(entry * 0.001, 1e-12)),
            stop_dist=stop_dist, tp_r=1.8,
        )


class CompressSmallStrategy:
    """Small-cap / thin compression breakout (20-bar range)."""

    strategy_id = "COMPRESS_SMALL"
    strategy_version = "COMPRESS_SMALL"

    def accepts_class(self, symbol_class: str) -> bool:
        return symbol_class in {"low_liquidity", "meme"}

    def evaluate(
        self,
        *,
        side: Side,
        snapshot: MarketSnapshot,
        state: SymbolState,
        config: EffectiveConfig,
        frozen: FrozenParams,
        config_hash: str,
        evaluated_at: datetime,
        flags: MarketQualityFlags,
        risk_cost: RiskCostDecision,
        symbol_class: str,
        btc_snapshot: MarketSnapshot | None = None,
    ) -> tuple[StrategyEvaluation, SignalCandidate | None]:
        blocked = _gate(
            side=side, snapshot=snapshot, config=config, flags=flags,
            risk_cost=risk_cost, evaluated_at=evaluated_at, config_hash=config_hash,
        )
        if blocked:
            return blocked
        candles = list(state.candles_1m)
        if len(candles) < 60:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        ranges = [(c.high - c.low) / c.close for c in candles if c.close > 0]
        if len(ranges) < 60:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        recent = ranges[-20:]
        hist = ranges[-60:]
        recent_med = sorted(recent)[len(recent) // 2]
        hist_sorted = sorted(hist)
        p35 = hist_sorted[int(0.35 * (len(hist_sorted) - 1))]
        if recent_med > p35:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.BAR_RANGE_ABNORMAL,
            )
        window = candles[-20:]
        hi = max(c.high for c in window)
        lo = min(c.low for c in window)
        last = candles[-1]
        pad = 2 * (snapshot.spread_bps / 10_000.0) * last.close
        vol_ok = last.quote_volume >= 1.5 * max(snapshot.volume_median_30, 1e-9)
        if side is Side.LONG:
            ok = last.close >= hi + pad and vol_ok
        else:
            ok = last.close <= lo - pad and vol_ok
        if not ok:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.PRICE_CONFIRMATION_FAILED,
            )
        entry = entry_price(state, snapshot)
        stop_dist = max(abs(entry - (lo if side is Side.LONG else hi)), entry * 0.002)
        return make_signal_at(
            strategy_id=self.strategy_id, symbol=snapshot.symbol, side=side,
            entry=entry, evaluated_at=evaluated_at, config_hash=config_hash,
            strength=2.0 + (last.quote_volume / max(snapshot.volume_median_30, 1e-9)),
            stop_dist=stop_dist, tp_r=1.8,
        )


class ListingOrStrategy:
    """New listing opening-range + AVWAP continuation (1m proxy)."""

    strategy_id = "LISTING_OR"
    strategy_version = "LISTING_OR"

    def accepts_class(self, symbol_class: str) -> bool:
        return symbol_class == "new_listing"

    def evaluate(
        self,
        *,
        side: Side,
        snapshot: MarketSnapshot,
        state: SymbolState,
        config: EffectiveConfig,
        frozen: FrozenParams,
        config_hash: str,
        evaluated_at: datetime,
        flags: MarketQualityFlags,
        risk_cost: RiskCostDecision,
        symbol_class: str,
        btc_snapshot: MarketSnapshot | None = None,
    ) -> tuple[StrategyEvaluation, SignalCandidate | None]:
        blocked = _gate(
            side=side, snapshot=snapshot, config=config, flags=flags,
            risk_cost=risk_cost, evaluated_at=evaluated_at, config_hash=config_hash,
        )
        if blocked:
            return blocked
        candles = list(state.candles_1m)
        # Skip first bar after warm; need >= 4 minutes of history
        if len(candles) < 5:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        or_bars = candles[:3]
        or_high = max(c.high for c in or_bars)
        or_low = min(c.low for c in or_bars)
        # Anchored VWAP from available history
        num = sum(((c.high + c.low + c.close) / 3) * c.quote_volume for c in candles)
        den = sum(c.quote_volume for c in candles)
        if den <= 0:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        avwap = num / den
        last = candles[-1]
        broke_or = any(c.high > or_high for c in candles[3:])
        mid_or = 0.5 * (or_high + or_low)
        if side is Side.LONG:
            ok = (
                last.close > avwap
                and broke_or
                and mid_or <= last.close <= or_high
                and last.close > candles[-2].high
            )
        else:
            broke_or_dn = any(c.low < or_low for c in candles[3:])
            ok = (
                last.close < avwap
                and broke_or_dn
                and or_low <= last.close <= mid_or
                and last.close < candles[-2].low
            )
        if not ok:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.PRICE_CONFIRMATION_FAILED,
            )
        entry = entry_price(state, snapshot)
        stop_dist = max(abs(entry - avwap), entry * 0.002)
        return make_signal_at(
            strategy_id=self.strategy_id, symbol=snapshot.symbol, side=side,
            entry=entry, evaluated_at=evaluated_at, config_hash=config_hash,
            strength=2.5, stop_dist=stop_dist, tp_r=2.0,
        )


class VShockStrategy:
    """Sudden volume-shock continuation after partial retrace."""

    strategy_id = "VSHOCK"
    strategy_version = "VSHOCK"

    def accepts_class(self, symbol_class: str) -> bool:
        return symbol_class in {"hype_alt", "meme", "major_alt", "mid_alt"}

    def evaluate(
        self,
        *,
        side: Side,
        snapshot: MarketSnapshot,
        state: SymbolState,
        config: EffectiveConfig,
        frozen: FrozenParams,
        config_hash: str,
        evaluated_at: datetime,
        flags: MarketQualityFlags,
        risk_cost: RiskCostDecision,
        symbol_class: str,
        btc_snapshot: MarketSnapshot | None = None,
    ) -> tuple[StrategyEvaluation, SignalCandidate | None]:
        blocked = _gate(
            side=side, snapshot=snapshot, config=config, flags=flags,
            risk_cost=risk_cost, evaluated_at=evaluated_at, config_hash=config_hash,
        )
        if blocked:
            return blocked
        candles = list(state.candles_1m)
        if len(candles) < 40:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        vols = [c.quote_volume for c in candles]
        rets = returns_from_closes(candle_closes(candles))
        z_v = robust_z(vols)
        z_r = robust_z(rets) if rets else None
        if z_v is None or z_r is None:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        if not (z_v >= 3.0 and abs(z_r) >= 2.0):
            # Slightly looser than doc's 5/3 so paper can fire on 1m proxies
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.LOW_VOLUME,
                strength=max(z_v, abs(z_r)),
            )
        # Impulse from last 5 bars; require 20-40% retrace then reclaim
        impulse = candles[-6:-1]
        last = candles[-1]
        i_low = min(c.low for c in impulse)
        i_high = max(c.high for c in impulse)
        height = i_high - i_low
        if height <= 0:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DEAD_BAND_TOO_SMALL,
            )
        if side is Side.LONG and z_r > 0:
            retrace = (i_high - last.low) / height
            ok = 0.2 <= retrace <= 0.5 and last.close > candles[-2].high
        elif side is Side.SHORT and z_r < 0:
            retrace = (last.high - i_low) / height
            ok = 0.2 <= retrace <= 0.5 and last.close < candles[-2].low
        else:
            ok = False
        if not ok:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.PRICE_CONFIRMATION_FAILED,
                strength=z_v,
            )
        entry = entry_price(state, snapshot)
        stop_dist = max(height * 0.35, entry * 0.002)
        return make_signal_at(
            strategy_id=self.strategy_id, symbol=snapshot.symbol, side=side,
            entry=entry, evaluated_at=evaluated_at, config_hash=config_hash,
            strength=z_v, stop_dist=stop_dist, tp_r=1.5,
        )


class PumpDefensiveStrategy:
    """Pump detector — default no-trade; optional post-failure short only."""

    strategy_id = "PUMP_DEFENSIVE"
    strategy_version = "PUMP_DEFENSIVE"

    def accepts_class(self, symbol_class: str) -> bool:
        return symbol_class in {"meme", "hype_alt", "new_listing"}

    def evaluate(
        self,
        *,
        side: Side,
        snapshot: MarketSnapshot,
        state: SymbolState,
        config: EffectiveConfig,
        frozen: FrozenParams,
        config_hash: str,
        evaluated_at: datetime,
        flags: MarketQualityFlags,
        risk_cost: RiskCostDecision,
        symbol_class: str,
        btc_snapshot: MarketSnapshot | None = None,
    ) -> tuple[StrategyEvaluation, SignalCandidate | None]:
        blocked = _gate(
            side=side, snapshot=snapshot, config=config, flags=flags,
            risk_cost=risk_cost, evaluated_at=evaluated_at, config_hash=config_hash,
        )
        if blocked:
            return blocked
        candles = list(state.candles_1m)
        if len(candles) < 30:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DATA_UNAVAILABLE,
            )
        # 5-bar return and volume vs baseline
        c5 = candles[-5:]
        r5 = (c5[-1].close - c5[0].open) / c5[0].open if c5[0].open > 0 else 0.0
        rets = returns_from_closes(candle_closes(candles[:-5] or candles))
        sigma = None
        if len(rets) >= 20:
            ztmp = robust_z([*rets, r5])
            sigma = abs(r5) / max(abs(ztmp), 1e-9) if ztmp else None
        vols = [c.quote_volume for c in candles]
        if len(vols) > 10:
            baseline = sorted(vols[:-5])[len(vols[:-5]) // 2]
        else:
            baseline = snapshot.volume_median_30
        v5 = sum(c.quote_volume for c in c5)
        pump = abs(r5) > 0.04 and v5 > 8 * max(baseline, 1e-9)
        if not pump:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.DEAD_BAND_TOO_SMALL,
            )
        # Default: no long participation
        if side is Side.LONG:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.SYMBOL_DISABLED,
                strength=abs(r5) * 100,
            )
        # Post-failure short: price rolled over below event VWAP midpoint
        event = candles[-8:]
        num = sum(((c.high + c.low + c.close) / 3) * c.quote_volume for c in event)
        den = sum(c.quote_volume for c in event) or 1.0
        evwap = num / den
        last = candles[-1]
        peak = max(c.high for c in event)
        failed_reclaim = (
            last.close < evwap and last.high < peak and last.close < candles[-2].close
        )
        if not failed_reclaim:
            return reject(
                symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                config_hash=config_hash, reason=RejectionReason.PRICE_CONFIRMATION_FAILED,
                strength=abs(r5) * 100,
            )
        entry = entry_price(state, snapshot)
        stop_dist = max(peak - entry, entry * 0.003)
        _ = sigma
        return make_signal_at(
            strategy_id=self.strategy_id, symbol=snapshot.symbol, side=side,
            entry=entry, evaluated_at=evaluated_at, config_hash=config_hash,
            strength=abs(r5) * 50, stop_dist=stop_dist, tp_r=1.5,
        )


def all_microstructure_strategies() -> list:
    return [
        OfiBtcStrategy(),
        EthLeadlagStrategy(),
        AltResidualStrategy(),
        SweepMidStrategy(),
        CompressSmallStrategy(),
        ListingOrStrategy(),
        VShockStrategy(),
        PumpDefensiveStrategy(),
    ]
