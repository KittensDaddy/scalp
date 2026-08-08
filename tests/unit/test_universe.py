from __future__ import annotations

from scalping.market_data.universe import (
    ExchangeSymbolInfo,
    UniverseConfig,
    diff_universe,
    evaluate_universe,
)


def _sym(symbol="BTCUSDT", quote="USDT", contract="PERPETUAL", status="TRADING") -> ExchangeSymbolInfo:
    return ExchangeSymbolInfo(symbol=symbol, quote_asset=quote, contract_type=contract, status=status)


def test_fully_eligible_symbol():
    entries = evaluate_universe(
        [_sym()], {"BTCUSDT": 50_000_000.0}, {"BTCUSDT": 1.0}, {"BTCUSDT": 30.0}, UniverseConfig()
    )
    assert entries[0].eligible is True
    assert entries[0].reasons == []
    assert all(entries[0].filters_passed.values())


def test_wrong_quote_asset_rejected():
    entries = evaluate_universe(
        [_sym(quote="BUSD")], {"BTCUSDT": 50_000_000.0}, {"BTCUSDT": 1.0}, {"BTCUSDT": 30.0},
        UniverseConfig(),
    )
    assert entries[0].eligible is False
    assert "NOT_ELIGIBLE_CONTRACT" in entries[0].reasons


def test_delivery_contract_rejected():
    entries = evaluate_universe(
        [_sym(contract="CURRENT_QUARTER")], {}, {}, {}, UniverseConfig()
    )
    assert entries[0].eligible is False
    assert "NOT_ELIGIBLE_CONTRACT" in entries[0].reasons


def test_non_trading_status_rejected():
    entries = evaluate_universe([_sym(status="BREAK")], {}, {}, {}, UniverseConfig())
    assert "NOT_ELIGIBLE_CONTRACT" in entries[0].reasons


def test_low_volume_rejected():
    entries = evaluate_universe(
        [_sym()], {"BTCUSDT": 1_000_000.0}, {"BTCUSDT": 1.0}, {"BTCUSDT": 30.0}, UniverseConfig()
    )
    assert entries[0].eligible is False
    assert "LOW_VOLUME" in entries[0].reasons


def test_wide_spread_rejected():
    entries = evaluate_universe(
        [_sym()], {"BTCUSDT": 50_000_000.0}, {"BTCUSDT": 10.0}, {"BTCUSDT": 30.0}, UniverseConfig()
    )
    assert entries[0].eligible is False
    assert "SPREAD_TOO_WIDE" in entries[0].reasons


def test_insufficient_history_rejected():
    entries = evaluate_universe(
        [_sym()], {"BTCUSDT": 50_000_000.0}, {"BTCUSDT": 1.0}, {"BTCUSDT": 2.0}, UniverseConfig()
    )
    assert entries[0].eligible is False
    assert "INSUFFICIENT_HISTORY" in entries[0].reasons


def test_missing_data_treated_as_failing():
    entries = evaluate_universe([_sym()], {}, {}, {}, UniverseConfig())
    assert entries[0].eligible is False
    assert set(entries[0].reasons) == {"LOW_VOLUME", "SPREAD_TOO_WIDE", "INSUFFICIENT_HISTORY"}


def test_multiple_reasons_all_recorded():
    entries = evaluate_universe(
        [_sym()], {"BTCUSDT": 1.0}, {"BTCUSDT": 10.0}, {"BTCUSDT": 1.0}, UniverseConfig()
    )
    assert set(entries[0].reasons) == {"LOW_VOLUME", "SPREAD_TOO_WIDE", "INSUFFICIENT_HISTORY"}


def test_diff_universe_detects_additions_and_removals():
    diff = diff_universe(previous_eligible={"BTCUSDT", "ETHUSDT"}, current_eligible={"BTCUSDT", "SOLUSDT"})
    assert diff.added == ["SOLUSDT"]
    assert diff.removed == ["ETHUSDT"]


def test_diff_universe_no_changes():
    diff = diff_universe(previous_eligible={"BTCUSDT"}, current_eligible={"BTCUSDT"})
    assert diff.added == []
    assert diff.removed == []
