from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scalping.exchanges.base.errors import SelfCheckFailed
from scalping.exchanges.binance.selfcheck import require_passed, run_self_check
from scalping.exchanges.binance.ws import StreamCategory

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


async def _good_ack() -> dict:
    return {"algoId": 1, "symbol": "BTCUSDT", "algoType": "STOP_MARKET"}


def _good_samples() -> dict:
    return {
        StreamCategory.PUBLIC: {"s": "BTCUSDT", "b": "1", "B": "1", "a": "1", "A": "1"},
        StreamCategory.MARKET: {
            "k": {"t": 1, "T": 2, "o": "1", "h": "1", "l": "1", "c": "1", "q": "1", "x": True}
        },
        StreamCategory.PRIVATE: {"e": "ORDER_TRADE_UPDATE"},
    }


async def test_all_checks_pass():
    result = await run_self_check(
        environment="testnet", place_and_cancel_algo_order=_good_ack,
        sample_messages=_good_samples(), now=NOW,
    )
    assert result.passed is True
    assert len(result.steps) == 4
    require_passed(result)  # must not raise


async def test_algo_order_failure_fails_whole_check():
    async def bad_ack() -> dict:
        raise RuntimeError("connection refused")

    result = await run_self_check(
        environment="testnet", place_and_cancel_algo_order=bad_ack,
        sample_messages=_good_samples(), now=NOW,
    )
    assert result.passed is False
    step = next(s for s in result.steps if s.name == "algo_order_submit_cancel")
    assert step.passed is False
    assert "connection refused" in step.detail


async def test_algo_ack_wrong_shape_fails():
    async def wrong_shape_ack() -> dict:
        return {"algoId": 1}  # missing symbol, algoType

    result = await run_self_check(
        environment="testnet", place_and_cancel_algo_order=wrong_shape_ack,
        sample_messages=_good_samples(), now=NOW,
    )
    assert result.passed is False


async def test_missing_ws_sample_message_fails_that_category():
    samples = _good_samples()
    del samples[StreamCategory.PRIVATE]
    result = await run_self_check(
        environment="testnet", place_and_cancel_algo_order=_good_ack,
        sample_messages=samples, now=NOW,
    )
    assert result.passed is False
    step = next(s for s in result.steps if s.name == "ws_shape_private")
    assert step.passed is False


async def test_malformed_bookticker_fails_only_public_step():
    samples = _good_samples()
    samples[StreamCategory.PUBLIC] = {"s": "BTCUSDT"}  # missing bid/ask fields
    result = await run_self_check(
        environment="testnet", place_and_cancel_algo_order=_good_ack,
        sample_messages=samples, now=NOW,
    )
    assert result.passed is False
    steps_by_name = {s.name: s for s in result.steps}
    assert steps_by_name["ws_shape_public"].passed is False
    assert steps_by_name["ws_shape_market"].passed is True
    assert steps_by_name["ws_shape_private"].passed is True


def test_require_passed_raises_on_failure():
    from scalping.exchanges.binance.selfcheck import SelfCheckResult, SelfCheckStepResult

    result = SelfCheckResult(
        checked_at=NOW, environment="testnet", passed=False,
        steps=[SelfCheckStepResult("ws_shape_public", False, "boom")],
    )
    with pytest.raises(SelfCheckFailed, match="ws_shape_public"):
        require_passed(result)


def test_require_passed_noop_on_success():
    from scalping.exchanges.binance.selfcheck import SelfCheckResult

    result = SelfCheckResult(checked_at=NOW, environment="testnet", passed=True, steps=[])
    require_passed(result)  # must not raise
