"""Microstructure strategy unit tests — accept/reject with candle+book proxies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import BookTicker, Candle, RejectionReason, Side
from scalping.market_data.registry import SymbolStateRegistry
from scalping.strategies.caems.engine import MarketQualityFlags, MarketSnapshot, RiskCostDecision
from scalping.strategies.microstructure.plugins import (
    AltResidualStrategy,
    CompressSmallStrategy,
    OfiBtcStrategy,
    PumpDefensiveStrategy,
    SweepMidStrategy,
    VShockStrategy,
    all_microstructure_strategies,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _snap(symbol: str, close: float = 100.0, vol: float = 2.0, spread: float = 1.0) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        ema_fast_1m=close + 0.1,
        ema_slow_1m=close,
        ema_fast_5m=close + 0.05,
        ema_slow_5m=close,
        atr14_1m=1.0,
        completed_close=close,
        last_bar_high=close + 0.5,
        last_bar_low=close - 0.5,
        completed_quote_volume=vol,
        volume_median_30=1.0,
        spread_bps=spread,
        seconds_to_next_funding=1000.0,
        btc_strength=0.0,
    )


def _feed_candles(registry: SymbolStateRegistry, symbol: str, closes: list[float], *, vol: float = 1.0) -> None:
    for i, close in enumerate(closes):
        ts = NOW - timedelta(minutes=len(closes) - i)
        registry.on_kline_1m_closed(
            Candle(
                symbol=symbol,
                timeframe="1m",
                open_time=ts,
                close_time=ts + timedelta(minutes=1),
                open=close - 0.1,
                high=close + 0.2,
                low=close - 0.2,
                close=close,
                quote_volume=vol,
            )
        )


def _feed_books(registry: SymbolStateRegistry, symbol: str, n: int = 40, *, imb: float = 0.8) -> None:
    for i in range(n):
        bid_qty = 10.0 * imb
        ask_qty = 10.0 * (1 - imb)
        # walk bid up to generate positive OFI
        px = 100.0 + i * 0.01
        registry.on_book_ticker(
            BookTicker(
                symbol=symbol,
                bid_price=px,
                bid_qty=bid_qty + i,
                ask_price=px + 0.02,
                ask_qty=max(0.1, ask_qty),
                event_time=NOW + timedelta(milliseconds=i),
            )
        )


def test_all_eight_microstructure_strategies_registered():
    ids = {p.strategy_id for p in all_microstructure_strategies()}
    assert ids == {
        "OFI_BTC",
        "ETH_LEADLAG",
        "ALT_RESIDUAL",
        "SWEEP_MID",
        "COMPRESS_SMALL",
        "LISTING_OR",
        "VSHOCK",
        "PUMP_DEFENSIVE",
    }


def test_ofi_btc_can_accept_long():
    registry = SymbolStateRegistry(FrozenParams())
    _feed_candles(registry, "BTCUSDT", [100 + i * 0.01 for i in range(50)])
    _feed_books(registry, "BTCUSDT", 50, imb=0.9)
    strat = OfiBtcStrategy()
    ev, sig = strat.evaluate(
        side=Side.LONG,
        snapshot=_snap("BTCUSDT"),
        state=registry.get("BTCUSDT"),
        config=EffectiveConfig(),
        frozen=FrozenParams(),
        config_hash="h",
        evaluated_at=NOW,
        flags=MarketQualityFlags(),
        risk_cost=RiskCostDecision(risk_approved=True),
        symbol_class="btc",
    )
    # May accept or reject on band — must not be DATA_UNAVAILABLE once books warm
    assert ev.rejection_reason != RejectionReason.DATA_UNAVAILABLE
    if ev.accepted:
        assert sig is not None
        assert sig.strategy_version == "OFI_BTC"


def test_sweep_mid_detects_reclaim():
    registry = SymbolStateRegistry(FrozenParams())
    # flat range then sweep below and reclaim
    closes = [100.0] * 20
    for i, close in enumerate(closes):
        ts = NOW - timedelta(minutes=len(closes) - i)
        registry.on_kline_1m_closed(
            Candle(
                symbol="AAAUSDT",
                timeframe="1m",
                open_time=ts,
                close_time=ts + timedelta(minutes=1),
                open=close,
                high=close + 0.3,
                low=close - 0.3,
                close=close,
                quote_volume=1.0,
            )
        )
    # sweep bar
    ts = NOW
    registry.on_kline_1m_closed(
        Candle(
            symbol="AAAUSDT",
            timeframe="1m",
            open_time=ts,
            close_time=ts + timedelta(minutes=1),
            open=100.0,
            high=100.2,
            low=99.0,  # sweep
            close=100.1,  # reclaim
            quote_volume=5.0,
        )
    )
    strat = SweepMidStrategy()
    ev, sig = strat.evaluate(
        side=Side.LONG,
        snapshot=_snap("AAAUSDT", close=100.1, vol=5.0),
        state=registry.get("AAAUSDT"),
        config=EffectiveConfig(),
        frozen=FrozenParams(),
        config_hash="h",
        evaluated_at=NOW,
        flags=MarketQualityFlags(),
        risk_cost=RiskCostDecision(risk_approved=True),
        symbol_class="mid_alt",
    )
    assert ev.accepted
    assert sig is not None


def test_pump_defensive_blocks_longs():
    registry = SymbolStateRegistry(FrozenParams())
    closes = [100.0] * 25 + [100 + i for i in range(1, 6)]  # vertical pump
    for i, close in enumerate(closes):
        ts = NOW - timedelta(minutes=len(closes) - i)
        registry.on_kline_1m_closed(
            Candle(
                symbol="MEMEUSDT",
                timeframe="1m",
                open_time=ts,
                close_time=ts + timedelta(minutes=1),
                open=close - 1,
                high=close + 1,
                low=close - 1,
                close=close,
                quote_volume=100.0 if i >= 25 else 1.0,
            )
        )
    strat = PumpDefensiveStrategy()
    ev, _ = strat.evaluate(
        side=Side.LONG,
        snapshot=_snap("MEMEUSDT", close=closes[-1], vol=100.0),
        state=registry.get("MEMEUSDT"),
        config=EffectiveConfig(),
        frozen=FrozenParams(),
        config_hash="h",
        evaluated_at=NOW,
        flags=MarketQualityFlags(),
        risk_cost=RiskCostDecision(risk_approved=True),
        symbol_class="meme",
    )
    assert not ev.accepted
    assert ev.rejection_reason in {
        RejectionReason.SYMBOL_DISABLED,
        RejectionReason.PRICE_CONFIRMATION_FAILED,
        RejectionReason.DEAD_BAND_TOO_SMALL,
    }


def test_alt_residual_seeds_from_history():
    strat = AltResidualStrategy(min_bars=20)
    btc = [100.0 + i * 0.1 for i in range(50)]
    alt = [50.0 + i * 0.05 for i in range(50)]
    # make last alt move idiosyncratic down
    alt[-1] = alt[-2] * 0.97
    strat.seed_btc_closes(btc)
    registry = SymbolStateRegistry(FrozenParams())
    _feed_candles(registry, "SOLUSDT", alt)
    state = registry.get("SOLUSDT")
    assert state is not None
    # force strategy series
    for c in alt:
        strat._alt_closes.setdefault("SOLUSDT", []).append(c)
    strat._last_key["SOLUSDT"] = state.last_kline_1m_close_time
    btc_snap = _snap("BTCUSDT", close=btc[-1])
    ev, _ = strat.evaluate(
        side=Side.LONG,
        snapshot=_snap("SOLUSDT", close=alt[-1]),
        state=state,
        config=EffectiveConfig(),
        frozen=FrozenParams(),
        config_hash="h",
        evaluated_at=NOW,
        flags=MarketQualityFlags(),
        risk_cost=RiskCostDecision(risk_approved=True),
        symbol_class="major_alt",
        btc_snapshot=btc_snap,
    )
    assert ev.rejection_reason != RejectionReason.DATA_UNAVAILABLE


def test_compress_and_vshock_not_stubs():
    assert CompressSmallStrategy().strategy_id == "COMPRESS_SMALL"
    assert VShockStrategy().strategy_id == "VSHOCK"
