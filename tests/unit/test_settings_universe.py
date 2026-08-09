"""Settings helpers for run universe."""

from scalping.config.settings import Settings


def test_use_universe_auto_modes():
    assert Settings(run_symbols="auto").use_universe()
    assert Settings(run_symbols="universe").use_universe()
    assert Settings(run_symbols="*").use_universe()
    assert Settings(run_symbols="auto").symbols_list() == []


def test_explicit_symbols_list():
    s = Settings(run_symbols="btcusdt, ethusdt")
    assert not s.use_universe()
    assert s.symbols_list() == ["BTCUSDT", "ETHUSDT"]
