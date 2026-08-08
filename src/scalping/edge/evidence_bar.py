"""The go-live evidence bar — PLAN_OF_ACTION.md §8, pre-registered before any
results exist. Implemented as a machine-checked report with PASS/FAIL per
criterion and the actual numbers, specifically so it cannot be bent to fit a
result after the fact: this module is the only place that gets to say "go".
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from scalping.edge.bootstrap import bootstrap_mean_ci
from scalping.risk.drawdown import DrawdownState


@dataclass(frozen=True)
class EvidenceBarInputs:
    trade_r_multiples: list[float]
    entry_attempts: int
    protection_gap_p99_ms: float
    maker_taker_resolved: bool
    reconciliation_clean_restarts: int
    reconciliation_clean_disconnects: int
    kill_switch_verified_end_to_end: bool


@dataclass(frozen=True)
class CriterionResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class EvidenceBarReport:
    criteria: list[CriterionResult]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.criteria)

    def summary(self) -> str:
        lines = [f"{'PASS' if c.passed else 'FAIL'}  {c.name}: {c.detail}" for c in self.criteria]
        lines.append(f"OVERALL: {'PASS' if self.passed else 'FAIL'}")
        return "\n".join(lines)


def _profit_factor(trades: list[float]) -> float | None:
    wins = sum(r for r in trades if r > 0)
    losses = -sum(r for r in trades if r < 0)
    if not trades:
        return None
    if losses == 0:
        return float("inf") if wins > 0 else None
    return wins / losses


def _max_drawdown_r(trades: list[float]) -> float:
    dd = DrawdownState()
    for r in trades:
        dd.record_trade(r)
    return dd.max_drawdown_r()


def evaluate_evidence_bar(
    inputs: EvidenceBarInputs, *, n_bootstrap: int = 2000, rng: random.Random | None = None
) -> EvidenceBarReport:
    trades = inputs.trade_r_multiples
    n = len(trades)
    criteria: list[CriterionResult] = []

    sample_ok = n >= 300 and inputs.entry_attempts >= 500
    criteria.append(
        CriterionResult(
            "sample_size", sample_ok,
            f"n={n} completed trades (need >=300), "
            f"entry_attempts={inputs.entry_attempts} (need >=500)",
        )
    )

    if trades:
        ci_low, ci_high = bootstrap_mean_ci(trades, n_resamples=n_bootstrap, rng=rng)
    else:
        ci_low, ci_high = (0.0, 0.0)
    expectancy_ok = ci_low > 0
    criteria.append(
        CriterionResult(
            "net_expectancy_positive", expectancy_ok,
            f"95% bootstrap CI on mean R = [{ci_low:.4f}, {ci_high:.4f}] "
            f"(must exclude zero, lower bound > 0)",
        )
    )

    pf = _profit_factor(trades)
    pf_ok = pf is not None and pf >= 1.15
    criteria.append(
        CriterionResult(
            "profit_factor", pf_ok,
            f"profit_factor={pf if pf is not None else 'n/a'} (need >= 1.15)",
        )
    )

    max_dd = _max_drawdown_r(trades)
    dd_ok = max_dd <= 6.0
    criteria.append(
        CriterionResult("max_drawdown", dd_ok, f"max_drawdown={max_dd:.2f}R (need <= 6R)")
    )

    gap_ok = inputs.protection_gap_p99_ms < 1500.0
    criteria.append(
        CriterionResult(
            "protection_gap", gap_ok,
            f"p99 t_protection = {inputs.protection_gap_p99_ms:.0f}ms (need < 1500ms)",
        )
    )

    criteria.append(
        CriterionResult(
            "maker_taker_decision", inputs.maker_taker_resolved,
            "resolved (default confirmed or switched)"
            if inputs.maker_taker_resolved
            else "not yet resolved by the pre-registered markout rule",
        )
    )

    reconcile_ok = (
        inputs.reconciliation_clean_restarts >= 3 and inputs.reconciliation_clean_disconnects >= 3
    )
    criteria.append(
        CriterionResult(
            "reconciliation", reconcile_ok,
            f"clean restarts={inputs.reconciliation_clean_restarts} (need >=3), "
            f"clean disconnects={inputs.reconciliation_clean_disconnects} (need >=3)",
        )
    )

    criteria.append(
        CriterionResult(
            "kill_switch_verified", inputs.kill_switch_verified_end_to_end,
            "verified end-to-end on testnet"
            if inputs.kill_switch_verified_end_to_end
            else "not verified",
        )
    )

    return EvidenceBarReport(criteria=criteria)
