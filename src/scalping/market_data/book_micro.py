"""BookTicker-driven microstructure feature buffer (OFI / microprice / spread)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from scalping.domain.models import BookTicker


def _robust_z(values: list[float]) -> float | None:
    if len(values) < 8:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    med = ordered[mid] if len(ordered) % 2 else 0.5 * (ordered[mid - 1] + ordered[mid])
    abs_dev = sorted(abs(v - med) for v in values)
    mad = abs_dev[mid] if len(abs_dev) % 2 else 0.5 * (abs_dev[mid - 1] + abs_dev[mid])
    scale = 1.4826 * mad
    if scale <= 1e-18:
        return None
    return (values[-1] - med) / scale


@dataclass
class BookMicroFeatures:
    """Top-of-book Cont-style OFI proxy + microprice/spread history."""

    last_bid: float | None = None
    last_ask: float | None = None
    last_bid_qty: float | None = None
    last_ask_qty: float | None = None
    ofi_events: deque[float] = field(default_factory=lambda: deque(maxlen=240))
    ofi_cum_window: deque[float] = field(default_factory=lambda: deque(maxlen=60))
    spreads: deque[float] = field(default_factory=lambda: deque(maxlen=180))
    imbalances: deque[float] = field(default_factory=lambda: deque(maxlen=120))
    _cum_ofi: float = 0.0

    def on_book(self, bt: BookTicker) -> None:
        if bt.bid_price <= 0 or bt.ask_price <= 0:
            return
        spread = bt.spread_bps
        if spread is not None and spread >= 0:
            self.spreads.append(spread)
        denom = bt.bid_qty + bt.ask_qty
        if denom > 0:
            self.imbalances.append((bt.bid_qty - bt.ask_qty) / denom)

        if (
            self.last_bid is None
            or self.last_ask is None
            or self.last_bid_qty is None
            or self.last_ask_qty is None
        ):
            self.last_bid = bt.bid_price
            self.last_ask = bt.ask_price
            self.last_bid_qty = bt.bid_qty
            self.last_ask_qty = bt.ask_qty
            return

        e = 0.0
        if bt.bid_price >= self.last_bid:
            e += bt.bid_qty
        if bt.bid_price <= self.last_bid:
            e -= self.last_bid_qty
        if bt.ask_price <= self.last_ask:
            e -= bt.ask_qty
        if bt.ask_price >= self.last_ask:
            e += self.last_ask_qty

        self.ofi_events.append(e)
        self._cum_ofi += e
        self.ofi_cum_window.append(self._cum_ofi)

        self.last_bid = bt.bid_price
        self.last_ask = bt.ask_price
        self.last_bid_qty = bt.bid_qty
        self.last_ask_qty = bt.ask_qty

    def ofi_z(self) -> float | None:
        if len(self.ofi_cum_window) < 20:
            return None
        xs = list(self.ofi_events)[-60:]
        if len(xs) < 20:
            return None
        return _robust_z(xs)

    def imbalance(self) -> float | None:
        if not self.imbalances:
            return None
        return self.imbalances[-1]

    def spread_percentile(self, current: float) -> float | None:
        if len(self.spreads) < 20:
            return None
        below = sum(1 for s in self.spreads if s <= current)
        return below / len(self.spreads)

    def microprice_premium_spreads(self, bt: BookTicker) -> float | None:
        mid = bt.mid
        spread = bt.ask_price - bt.bid_price
        if spread <= 0 or mid <= 0:
            return None
        denom = bt.bid_qty + bt.ask_qty
        if denom <= 0:
            return None
        micro = (bt.ask_price * bt.bid_qty + bt.bid_price * bt.ask_qty) / denom
        return (micro - mid) / spread
