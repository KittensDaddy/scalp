"""Symbol -> shard assignment and rebalancing.

SCANNER_DASHBOARD_PLAN.md §D: "<=~200 streams per connection; Binance allows 1024
but keep headroom" and "MarketDataManager assigns symbols to shards, rebalances on
universe change, staggers reconnects." Rebalancing keeps existing assignments
stable — a universe change should move as few symbols (and therefore reconnect as
few shards) as possible, not redistribute everything from scratch.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ShardPlan:
    assignments: dict[int, list[str]] = field(default_factory=dict)

    def shard_of(self, symbol: str) -> int | None:
        for shard_id, symbols in self.assignments.items():
            if symbol in symbols:
                return shard_id
        return None

    @property
    def all_symbols(self) -> set[str]:
        return {s for symbols in self.assignments.values() for s in symbols}


def assign_shards(symbols: list[str], max_per_shard: int = 200) -> ShardPlan:
    """Initial assignment — deterministic (sorted) so it's reproducible across runs."""
    sorted_symbols = sorted(symbols)
    assignments: dict[int, list[str]] = {}
    for i in range(0, len(sorted_symbols), max_per_shard):
        shard_id = i // max_per_shard
        assignments[shard_id] = sorted_symbols[i : i + max_per_shard]
    return ShardPlan(assignments)


def rebalance_shards(
    previous: ShardPlan, new_symbols: set[str], max_per_shard: int = 200
) -> ShardPlan:
    """Symbols still in the universe keep their existing shard (no reconnect).
    Removed symbols simply drop out, freeing room. New symbols fill any shard with
    spare capacity before a new shard is created. Existing shards are never split
    or merged — minimizing churn is the whole point.
    """
    kept: dict[int, list[str]] = {
        shard_id: [s for s in symbols if s in new_symbols]
        for shard_id, symbols in previous.assignments.items()
    }
    already_placed = {s for symbols in kept.values() for s in symbols}
    to_place = sorted(new_symbols - already_placed)

    for symbol in to_place:
        placed = False
        for shard_id in sorted(kept):
            if len(kept[shard_id]) < max_per_shard:
                kept[shard_id].append(symbol)
                placed = True
                break
        if not placed:
            next_id = (max(kept) + 1) if kept else 0
            kept[next_id] = [symbol]

    kept = {shard_id: symbols for shard_id, symbols in kept.items() if symbols}
    return ShardPlan(kept)
