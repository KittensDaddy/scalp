"""Expected message/response shapes from PLAN_OF_ACTION.md §2's fact table.

Kept separate from the self-check runner (P6) so the shape checks themselves are
pure functions, unit-testable without any network access — the self-check runner
just calls these against real responses at startup.
"""

from __future__ import annotations

from typing import Any


class ShapeMismatch(Exception):
    pass


def check_book_ticker_shape(msg: dict[str, Any]) -> None:
    required = {"s", "b", "B", "a", "A"}  # symbol, bid, bidQty, ask, askQty
    missing = required - msg.keys()
    if missing:
        raise ShapeMismatch(f"bookTicker message missing fields: {sorted(missing)}")


def check_kline_shape(msg: dict[str, Any]) -> None:
    if "k" not in msg:
        raise ShapeMismatch("kline message missing 'k' payload")
    k = msg["k"]
    required = {"t", "T", "o", "h", "l", "c", "q", "x"}  # x = is_closed
    missing = required - k.keys()
    if missing:
        raise ShapeMismatch(f"kline payload missing fields: {sorted(missing)}")


def check_user_stream_shape(msg: dict[str, Any]) -> None:
    if "e" not in msg:
        raise ShapeMismatch("user stream message missing event type field 'e'")


def check_algo_order_ack_shape(resp: dict[str, Any]) -> None:
    required = {"algoId", "symbol", "algoType"}
    missing = required - resp.keys()
    if missing:
        raise ShapeMismatch(f"algoOrder response missing fields: {sorted(missing)}")
