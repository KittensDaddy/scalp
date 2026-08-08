from __future__ import annotations

from scalping.domain.models import Side
from scalping.execution.ports import ExchangeOpenAlgoOrder, ExchangePosition
from scalping.execution.reconcile import LocalPositionRecord, reconcile


class FakePort:
    def __init__(self, positions: list[ExchangePosition], algo_orders: dict[str, list[ExchangeOpenAlgoOrder]]):
        self._positions = positions
        self._algo_orders = algo_orders

    async def get_open_positions(self):
        return self._positions

    async def get_open_algo_orders(self, symbol):
        return self._algo_orders.get(symbol, [])


async def test_clean_reconciliation():
    port = FakePort(
        positions=[ExchangePosition("BTCUSDT", Side.LONG, 1.0)],
        algo_orders={
            "BTCUSDT": [
                ExchangeOpenAlgoOrder("BTCUSDT", "STOP_MARKET"),
                ExchangeOpenAlgoOrder("BTCUSDT", "TAKE_PROFIT_MARKET"),
            ]
        },
    )
    expected = [LocalPositionRecord("BTCUSDT", Side.LONG, 1.0)]
    report = await reconcile(port, expected)
    assert report.clean is True


async def test_naked_position_detected():
    port = FakePort(
        positions=[ExchangePosition("BTCUSDT", Side.LONG, 1.0)],
        algo_orders={"BTCUSDT": [ExchangeOpenAlgoOrder("BTCUSDT", "STOP_MARKET")]},  # missing TP
    )
    expected = [LocalPositionRecord("BTCUSDT", Side.LONG, 1.0)]
    report = await reconcile(port, expected)
    assert report.clean is False
    assert report.mismatches[0].kind == "naked_position"
    assert "take_profit" in report.mismatches[0].detail


async def test_unexpected_exchange_position_detected():
    port = FakePort(positions=[ExchangePosition("ETHUSDT", Side.SHORT, 2.0)], algo_orders={})
    report = await reconcile(port, expected=[])
    assert report.clean is False
    assert report.mismatches[0].kind == "unexpected_exchange_position"


async def test_missing_exchange_position_detected():
    port = FakePort(positions=[], algo_orders={})
    expected = [LocalPositionRecord("BTCUSDT", Side.LONG, 1.0)]
    report = await reconcile(port, expected)
    assert report.clean is False
    assert report.mismatches[0].kind == "missing_exchange_position"


async def test_quantity_mismatch_detected():
    port = FakePort(
        positions=[ExchangePosition("BTCUSDT", Side.LONG, 1.5)],
        algo_orders={"BTCUSDT": [
            ExchangeOpenAlgoOrder("BTCUSDT", "STOP_MARKET"),
            ExchangeOpenAlgoOrder("BTCUSDT", "TAKE_PROFIT_MARKET"),
        ]},
    )
    expected = [LocalPositionRecord("BTCUSDT", Side.LONG, 1.0)]
    report = await reconcile(port, expected)
    assert report.clean is False
    assert report.mismatches[0].kind == "unexpected_exchange_position"


async def test_multiple_symbols_all_clean():
    port = FakePort(
        positions=[
            ExchangePosition("BTCUSDT", Side.LONG, 1.0),
            ExchangePosition("ETHUSDT", Side.SHORT, 2.0),
        ],
        algo_orders={
            "BTCUSDT": [
                ExchangeOpenAlgoOrder("BTCUSDT", "STOP_MARKET"),
                ExchangeOpenAlgoOrder("BTCUSDT", "TAKE_PROFIT_MARKET"),
            ],
            "ETHUSDT": [
                ExchangeOpenAlgoOrder("ETHUSDT", "STOP_MARKET"),
                ExchangeOpenAlgoOrder("ETHUSDT", "TAKE_PROFIT_MARKET"),
            ],
        },
    )
    expected = [
        LocalPositionRecord("BTCUSDT", Side.LONG, 1.0),
        LocalPositionRecord("ETHUSDT", Side.SHORT, 2.0),
    ]
    report = await reconcile(port, expected)
    assert report.clean is True
