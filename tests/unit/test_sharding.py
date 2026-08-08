from __future__ import annotations

from scalping.market_data.sharding import assign_shards, rebalance_shards


def test_assign_shards_respects_max_per_shard():
    symbols = [f"SYM{i}" for i in range(450)]
    plan = assign_shards(symbols, max_per_shard=200)
    assert len(plan.assignments) == 3
    assert all(len(syms) <= 200 for syms in plan.assignments.values())
    assert plan.all_symbols == set(symbols)


def test_assign_shards_deterministic():
    symbols = [f"SYM{i}" for i in range(250)]
    a = assign_shards(symbols, max_per_shard=200)
    b = assign_shards(symbols, max_per_shard=200)
    assert a == b


def test_rebalance_keeps_unchanged_symbols_on_same_shard():
    plan = assign_shards([f"SYM{i}" for i in range(10)], max_per_shard=5)
    original_shard_of_sym0 = plan.shard_of("SYM0")
    new_plan = rebalance_shards(plan, new_symbols=set(plan.all_symbols), max_per_shard=5)
    assert new_plan.shard_of("SYM0") == original_shard_of_sym0


def test_rebalance_drops_removed_symbols():
    plan = assign_shards(["A", "B", "C"], max_per_shard=5)
    new_plan = rebalance_shards(plan, new_symbols={"A", "B"}, max_per_shard=5)
    assert new_plan.all_symbols == {"A", "B"}


def test_rebalance_adds_new_symbols_to_shard_with_room():
    plan = assign_shards(["A", "B"], max_per_shard=5)
    new_plan = rebalance_shards(plan, new_symbols={"A", "B", "C"}, max_per_shard=5)
    assert new_plan.shard_of("C") == new_plan.shard_of("A")  # same shard, room available


def test_rebalance_creates_new_shard_when_full():
    plan = assign_shards(["A", "B"], max_per_shard=2)  # shard 0 full
    new_plan = rebalance_shards(plan, new_symbols={"A", "B", "C"}, max_per_shard=2)
    assert new_plan.shard_of("C") != new_plan.shard_of("A")


def test_rebalance_drops_empty_shards():
    plan = assign_shards(["A"], max_per_shard=1)
    new_plan = rebalance_shards(plan, new_symbols=set(), max_per_shard=1)
    assert new_plan.assignments == {}


def test_rebalance_minimizes_churn_vs_full_reassignment():
    """The point of rebalancing: removing one symbol from a large universe must
    not move every other symbol to a different shard."""
    symbols = [f"SYM{i}" for i in range(400)]
    plan = assign_shards(symbols, max_per_shard=200)
    reduced = set(symbols) - {"SYM399"}
    new_plan = rebalance_shards(plan, new_symbols=reduced, max_per_shard=200)
    for s in reduced:
        assert new_plan.shard_of(s) == plan.shard_of(s)
