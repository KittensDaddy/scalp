"""Universe refresh merge/rank helpers."""

from scalping.runtime.universe_refresh import merge_universe


def test_merge_keeps_protected_and_reports_diff():
    next_syms, added, removed = merge_universe(
        previous=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        ranked=["BTCUSDT", "ETHUSDT", "XRPUSDT", "DOGEUSDT"],
        protect={"SOLUSDT"},  # open trade — must stay
        max_symbols=4,
    )
    assert "SOLUSDT" in next_syms
    assert "XRPUSDT" in next_syms or "DOGEUSDT" in next_syms
    assert "XRPUSDT" in added or "DOGEUSDT" in added
    # SOL kept even if not in ranked liquidity list
    assert "SOLUSDT" not in removed


def test_merge_caps_without_dropping_protect():
    next_syms, _, _ = merge_universe(
        previous=["A", "B"],
        ranked=["C", "D", "E"],
        protect={"A"},
        max_symbols=2,
    )
    assert "A" in next_syms
    assert len(next_syms) <= 2
