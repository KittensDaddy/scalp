"""Settings helpers for run universe."""

from scalping.config.settings import Settings
from scalping.runtime.universe_refresh import universe_config_from_settings


def test_use_universe_auto_modes():
    assert Settings(run_symbols="auto").use_universe()
    assert Settings(run_symbols="universe").use_universe()
    assert Settings(run_symbols="*").use_universe()
    assert Settings(run_symbols="auto").symbols_list() == []


def test_explicit_symbols_list():
    s = Settings(run_symbols="btcusdt, ethusdt")
    assert not s.use_universe()
    assert s.symbols_list() == ["BTCUSDT", "ETHUSDT"]


def test_paper_pull_and_run_defaults():
    s = Settings()
    assert s.control_token == "paper-ctrl"
    assert s.dashboard_unkill_token == "paper-unkill"
    assert s.universe_max_symbols == 300
    assert s.universe_min_quote_volume_usdt == 100_000.0
    assert s.universe_max_spread_bps == 10.0
    assert s.universe_min_history_days == 0
    assert s.warm_registry is False


def test_universe_config_from_settings():
    s = Settings(
        universe_min_quote_volume_usdt=500_000,
        universe_max_spread_bps=8.0,
        universe_min_history_days=3,
    )
    cfg = universe_config_from_settings(s)
    assert cfg.min_quote_volume_usdt == 500_000
    assert cfg.max_spread_bps == 8.0
    assert cfg.min_history_days == 3
