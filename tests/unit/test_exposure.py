from __future__ import annotations

from scalping.config.settings import RiskConfig
from scalping.domain.models import RejectionReason, Side
from scalping.risk.engine import RiskEngine, RiskRequest
from scalping.risk.exposure import ExposureLimiter


def test_exposure_limiter_tracks_open_count():
    limiter = ExposureLimiter()
    limiter.on_opened("btc_beta")
    limiter.on_opened("btc_beta")
    assert limiter.open_count("btc_beta") == 2


def test_exposure_limiter_within_limit():
    limiter = ExposureLimiter()
    limiter.on_opened("btc_beta")
    assert limiter.within_limit("btc_beta", max_positions=2) is True
    limiter.on_opened("btc_beta")
    assert limiter.within_limit("btc_beta", max_positions=2) is False


def test_exposure_limiter_closed_frees_slot():
    limiter = ExposureLimiter()
    limiter.on_opened("btc_beta")
    limiter.on_closed("btc_beta")
    assert limiter.open_count("btc_beta") == 0


def _request(**overrides) -> RiskRequest:
    defaults = dict(
        symbol="SOLUSDT", symbol_class="major_alt", side=Side.LONG, entry=100.0, stop=99.0,
        equity=10_000.0, available_depth=1_000_000.0, bar_volume=1_000_000.0,
        exchange_max_notional=1_000_000.0, correlation_group="btc_beta",
    )
    defaults.update(overrides)
    return RiskRequest(**defaults)


def test_risk_engine_blocks_on_correlation_group_cap():
    engine = RiskEngine()
    engine.on_position_opened("major_alt", correlation_group="btc_beta")
    engine.on_position_opened("meme", correlation_group="btc_beta")  # different class, same group
    cfg = RiskConfig(max_positions_total=10, max_positions_in_class=5, max_positions_per_correlation_group=2)
    approval = engine.evaluate(_request(), cfg)
    assert approval.approved is False
    assert approval.reason == RejectionReason.RISK_LIMIT


def test_risk_engine_allows_when_correlation_group_none():
    engine = RiskEngine()
    engine.on_position_opened("major_alt", correlation_group="btc_beta")
    engine.on_position_opened("meme", correlation_group="btc_beta")
    cfg = RiskConfig(max_positions_total=10, max_positions_in_class=5, max_positions_per_correlation_group=1)
    approval = engine.evaluate(_request(correlation_group=None), cfg)
    assert approval.approved is True


def test_risk_engine_correlation_group_freed_on_close():
    engine = RiskEngine()
    engine.on_position_opened("major_alt", correlation_group="btc_beta")
    engine.on_position_closed("major_alt", correlation_group="btc_beta")
    cfg = RiskConfig(max_positions_total=10, max_positions_in_class=5, max_positions_per_correlation_group=1)
    approval = engine.evaluate(_request(), cfg)
    assert approval.approved is True
