from __future__ import annotations

from datetime import UTC, datetime

from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import RejectionReason, Side
from scalping.market_data.registry import SymbolStateRegistry
from scalping.scanner.cooldowns import CooldownManager
from scalping.scanner.runner import StrategyRunner, SymbolEvalContext
from scalping.scanner.service import ScannerService
from scalping.scoring.features import FeatureRawInputs
from scalping.strategies.caems.engine import MarketQualityFlags, MarketSnapshot, RiskCostDecision

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _baseline_snapshot(symbol="BTCUSDT") -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol, ema_fast_1m=101.0, ema_slow_1m=100.0, ema_fast_5m=51.0, ema_slow_5m=50.0,
        atr14_1m=1.0, completed_close=101.3, last_bar_high=101.5, last_bar_low=100.5,
        completed_quote_volume=2.0, volume_median_30=1.0, spread_bps=1.0,
        seconds_to_next_funding=1000.0, btc_strength=0.0,
    )


def _feature_raw(**overrides) -> FeatureRawInputs:
    defaults = dict(
        side=Side.LONG, entry_reference=101.3, btc_ema_fast_1m=None, btc_ema_slow_1m=None,
        spread_bps=1.0, expected_cost_bps=5.0, expected_edge_bps=20.0,
        liquidity_percentile=0.8, historical_edge_frac=0.0, confirmations_frac=0.5,
        stale=False, evaluated_at=NOW,
    )
    defaults.update(overrides)
    return FeatureRawInputs(**defaults)


def _context(symbol="BTCUSDT") -> SymbolEvalContext:
    registry = SymbolStateRegistry(FrozenParams())
    # a couple of book/kline updates so the SymbolState exists (score features
    # degrade gracefully to 0 when indicators aren't ready, which is fine here —
    # this test exercises the runner's orchestration, not feature accuracy).
    from datetime import timedelta

    from scalping.domain.models import Candle

    candle = Candle(
        symbol=symbol, timeframe="1m", open_time=NOW, close_time=NOW + timedelta(minutes=1),
        open=100.0, high=101.5, low=100.5, close=101.3, quote_volume=2.0,
    )
    registry.on_kline_1m_closed(candle)
    state = registry.get(symbol)

    return SymbolEvalContext(
        symbol=symbol, symbol_class="btc", state=state, snapshot=_baseline_snapshot(symbol),
        feature_raw_by_side={
            Side.LONG: _feature_raw(side=Side.LONG),
            Side.SHORT: _feature_raw(side=Side.SHORT),
        },
        flags=MarketQualityFlags(),
        risk_cost_by_side={
            Side.LONG: RiskCostDecision(risk_approved=True),
            Side.SHORT: RiskCostDecision(risk_approved=True),
        },
    )


def test_run_once_publishes_one_row_per_symbol():
    runner = StrategyRunner()
    result = runner.run_once(
        [_context("BTCUSDT")], config=EffectiveConfig(), frozen=FrozenParams(),
        config_hash="h", evaluated_at=NOW,
    )
    assert len(result.delta.upserts) == 1
    assert result.delta.upserts[0].symbol == "BTCUSDT"


def test_run_once_accepted_row_has_score_and_breakdown():
    runner = StrategyRunner()
    result = runner.run_once(
        [_context("BTCUSDT")], config=EffectiveConfig(), frozen=FrozenParams(),
        config_hash="h", evaluated_at=NOW,
    )
    row = result.delta.upserts[0]
    assert row.accepted is True
    assert row.side == Side.LONG  # baseline snapshot favors LONG
    assert row.breakdown is not None
    assert row.score > 0


def test_run_once_respects_cooldown():
    cooldowns = CooldownManager()
    cooldowns.set("symbol", "BTCUSDT", "RISK_LIMIT", NOW.replace(hour=13))
    runner = StrategyRunner(cooldowns=cooldowns)
    result = runner.run_once(
        [_context("BTCUSDT")], config=EffectiveConfig(), frozen=FrozenParams(),
        config_hash="h", evaluated_at=NOW,
    )
    row = result.delta.upserts[0]
    assert row.accepted is False
    assert row.score == 0.0


def test_run_once_picks_best_side_between_long_and_short():
    runner = StrategyRunner()
    result = runner.run_once(
        [_context("BTCUSDT")], config=EffectiveConfig(), frozen=FrozenParams(),
        config_hash="h", evaluated_at=NOW, sides=(Side.LONG, Side.SHORT),
    )
    row = result.delta.upserts[0]
    # baseline snapshot is LONG-favorable; SHORT should fail regime/momentum and
    # score lower (0), so LONG must win
    assert row.side == Side.LONG


def test_run_once_uses_shared_scanner_service_for_ranking():
    scanner = ScannerService()
    runner = StrategyRunner(scanner=scanner)
    runner.run_once(
        [_context("BTCUSDT")], config=EffectiveConfig(), frozen=FrozenParams(),
        config_hash="h", evaluated_at=NOW,
    )
    snapshot = scanner.snapshot()
    assert snapshot.rows[0].symbol == "BTCUSDT"


def test_rejected_symbol_carries_reason():
    runner = StrategyRunner()
    ctx = _context("ETHUSDT")
    # force rejection via kill switch flag
    from dataclasses import replace

    ctx = replace(ctx, flags=MarketQualityFlags(kill_switch_engaged=True))
    result = runner.run_once(
        [ctx], config=EffectiveConfig(), frozen=FrozenParams(), config_hash="h", evaluated_at=NOW,
    )
    row = result.delta.upserts[0]
    assert row.accepted is False
    assert row.rejection_reason == RejectionReason.KILL_SWITCH


def test_run_once_publishes_developing_setup_for_near_trigger_rejection():
    from dataclasses import replace

    from scalping.scanner.developing import NearTriggerConfig

    # feature-based score under this fixture's un-warmed indicators lands well below
    # the default 70±20 threshold band, so use a threshold matched to the fixture's
    # actual score (13.75) rather than tuning the fixture to hit a default threshold
    # that assumes fully warmed indicator state.
    runner = StrategyRunner(
        near_trigger=NearTriggerConfig(
            score_threshold=15.0, score_delta=10.0, min_score=0.0
        )
    )
    ctx = _context("SOLUSDT")
    # only the spread condition fails -> one missing condition
    ctx = replace(ctx, snapshot=replace(ctx.snapshot, spread_bps=5.0))
    runner.run_once(
        [ctx], config=EffectiveConfig(), frozen=FrozenParams(), config_hash="h", evaluated_at=NOW,
    )
    snapshot = runner.developing.snapshot()
    assert snapshot.seq == 1
    setups = [s for s in snapshot.setups if s.symbol == "SOLUSDT"]
    assert len(setups) == 1
    assert setups[0].missing_conditions == ["spread"]


def test_run_once_no_developing_setup_when_symbol_accepted():
    runner = StrategyRunner()
    runner.run_once(
        [_context("BTCUSDT")], config=EffectiveConfig(), frozen=FrozenParams(),
        config_hash="h", evaluated_at=NOW,
    )
    snapshot = runner.developing.snapshot()
    # LONG accepts in this fixture — never listed as developing for that side.
    assert not any(s.side is Side.LONG for s in snapshot.setups)