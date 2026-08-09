"""ALT_RESIDUAL + multi-plugin StrategyRunner smoke tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import Candle, Side
from scalping.market_data.registry import SymbolStateRegistry
from scalping.scanner.runner import StrategyRunner, SymbolEvalContext
from scalping.scoring.features import FeatureRawInputs
from scalping.strategies.caems.engine import MarketQualityFlags, MarketSnapshot, RiskCostDecision
from scalping.strategies.microstructure.alt_residual import AltResidualStrategy
from scalping.strategies.microstructure.plugins import all_microstructure_strategies

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _snap(symbol: str, close: float = 100.0) -> MarketSnapshot:
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
        completed_quote_volume=2.0,
        volume_median_30=1.0,
        spread_bps=1.0,
        seconds_to_next_funding=1000.0,
        btc_strength=0.0,
    )


def _ctx(symbol: str, class_name: str, registry: SymbolStateRegistry) -> SymbolEvalContext:
    state = registry.get(symbol)
    assert state is not None

    def raw(side: Side) -> FeatureRawInputs:
        return FeatureRawInputs(
            side=side,
            entry_reference=100.0,
            btc_ema_fast_1m=None,
            btc_ema_slow_1m=None,
            spread_bps=1.0,
            expected_cost_bps=5.0,
            expected_edge_bps=20.0,
            liquidity_percentile=0.8,
            historical_edge_frac=0.0,
            confirmations_frac=0.5,
            stale=False,
            evaluated_at=NOW,
        )

    return SymbolEvalContext(
        symbol=symbol,
        symbol_class=class_name,
        state=state,
        snapshot=_snap(symbol),
        feature_raw_by_side={Side.LONG: raw(Side.LONG), Side.SHORT: raw(Side.SHORT)},
        flags=MarketQualityFlags(),
        risk_cost_by_side={
            Side.LONG: RiskCostDecision(risk_approved=True),
            Side.SHORT: RiskCostDecision(risk_approved=True),
        },
        preset=class_name,
    )


def test_alt_residual_rejects_wrong_class():
    strat = AltResidualStrategy()
    assert not strat.accepts_class("btc")
    assert strat.accepts_class("major_alt")


def test_runner_enabled_ids_filters_plugins():
    runner = StrategyRunner(enabled_ids={"caems_v2"})
    assert len(runner.strategies) == 1
    assert runner.strategies[0].strategy_id == "caems_v2"


def test_runner_includes_all_microstructure_by_default():
    runner = StrategyRunner()
    ids = {p.strategy_id for p in runner.strategies}
    assert "caems_v2" in ids
    assert "OFI_BTC" in ids
    assert "ALT_RESIDUAL" in ids
    assert len(all_microstructure_strategies()) == 8


def test_runner_one_row_per_symbol_with_multi_plugins():
    registry = SymbolStateRegistry(FrozenParams())
    for i in range(5):
        ts = NOW - timedelta(minutes=5 - i)
        registry.on_kline_1m_closed(
            Candle(
                symbol="BTCUSDT",
                timeframe="1m",
                open_time=ts,
                close_time=ts + timedelta(minutes=1),
                open=100,
                high=101,
                low=99,
                close=100.5,
                quote_volume=1,
            )
        )
    runner = StrategyRunner()
    result = runner.run_once(
        [_ctx("BTCUSDT", "btc", registry)],
        config=EffectiveConfig(),
        frozen=FrozenParams(),
        config_hash="h",
        evaluated_at=NOW,
    )
    assert len(result.delta.upserts) == 1
    row = result.delta.upserts[0]
    assert row.strategy
    assert row.preset == "btc"
