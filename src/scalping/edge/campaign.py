"""Assemble the PLAN §8 evidence bar from persisted campaign data.

`evidence_bar.evaluate_evidence_bar` is the pre-registered rule; this module is
the wiring that feeds it real numbers instead of hand-collected ones. Criteria
the paper phase cannot produce evidence for (§8.7 reconciliation across forced
restarts, §8.8 kill-switch end-to-end) are reported as *unverified* — they are
testnet ops steps, and reporting them any other way would let a paper campaign
appear to clear a bar it structurally cannot.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from scalping.accounting.markouts import MakerTakerDecision, decide_maker_vs_taker
from scalping.config.settings import EffectiveConfig
from scalping.edge.evidence_bar import EvidenceBarInputs, EvidenceBarReport, evaluate_evidence_bar
from scalping.monitoring.stats import percentile
from scalping.persistence.campaign_repo import (
    count_entry_attempts,
    load_markouts_by_entry_type,
    load_trade_r_multiples,
)
from scalping.persistence.protection_repo import load_recent_protection_ms


@dataclass(frozen=True)
class OpsAttestation:
    """§8.7 / §8.8 are procedures a human runs on testnet, not things the paper
    process can observe about itself. They default to unverified."""

    clean_restarts: int = 0
    clean_disconnects: int = 0
    kill_switch_verified: bool = False


@dataclass(frozen=True)
class CampaignEvidence:
    report: EvidenceBarReport
    maker_taker: MakerTakerDecision
    n_trades: int
    n_entry_attempts: int
    n_markouts: int
    protection_gap_p99_ms: float | None


async def build_campaign_evidence(
    session: AsyncSession,
    *,
    config: EffectiveConfig,
    ops: OpsAttestation | None = None,
    n_bootstrap: int = 2000,
    rng: random.Random | None = None,
) -> CampaignEvidence:
    ops = ops or OpsAttestation()

    trades = await load_trade_r_multiples(session)
    attempts = await count_entry_attempts(session)
    markouts = await load_markouts_by_entry_type(session)
    protection_samples = await load_recent_protection_ms(session)

    decision = decide_maker_vs_taker(
        maker_markouts_30s_bps=markouts.maker_30s_bps,
        taker_markouts_30s_bps=markouts.taker_30s_bps,
        fee_difference_bps=config.cost.taker_fee_bps - config.cost.maker_fee_bps,
    )

    gap_p99 = percentile(protection_samples, 99)
    inputs = EvidenceBarInputs(
        trade_r_multiples=trades,
        entry_attempts=attempts,
        # No protection samples yet means the gap is unmeasured, not fast. Feed
        # the criterion a value that fails rather than a flattering default.
        protection_gap_p99_ms=gap_p99 if gap_p99 is not None else float("inf"),
        maker_taker_resolved=decision.resolved,
        reconciliation_clean_restarts=ops.clean_restarts,
        reconciliation_clean_disconnects=ops.clean_disconnects,
        kill_switch_verified_end_to_end=ops.kill_switch_verified,
    )
    report = evaluate_evidence_bar(inputs, n_bootstrap=n_bootstrap, rng=rng)
    return CampaignEvidence(
        report=report,
        maker_taker=decision,
        n_trades=len(trades),
        n_entry_attempts=attempts,
        n_markouts=markouts.n,
        protection_gap_p99_ms=gap_p99,
    )
