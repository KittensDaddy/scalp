"""Map symbols → CAEMS class presets from `caems_presets.yaml` routing rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scalping.config.presets import ClassPreset, resolve_effective_config
from scalping.config.settings import EffectiveConfig

# YAML footer priority: btc > eth > meme > hype > major > mid > new > low
_CLASS_PRIORITY = (
    "btc",
    "eth",
    "meme",
    "hype_alt",
    "major_alt",
    "mid_alt",
    "new_listing",
    "low_liquidity",
)

DEFAULT_MEME_BASES = frozenset(
    {
        "DOGE", "SHIB", "PEPE", "WIF", "BONK", "FLOKI", "MEME", "BRETT",
        "NEIRO", "PNUT", "GOAT", "ACT", "TRUMP", "MELANIA", "FARTCOIN",
    }
)


@dataclass
class SymbolFacts:
    """Point-in-time facts used only for class routing (not CAEMS signal geometry)."""

    symbol: str
    quote_volume_rank: int | None = None  # 1 = highest 24h quote volume
    listing_age_days: float | None = None
    tags: set[str] = field(default_factory=set)
    volume_surge_ratio: float | None = None  # current / 30d median; None = unknown


@dataclass(frozen=True)
class ResolvedSymbolPreset:
    class_name: str
    preset: ClassPreset
    config: EffectiveConfig


class SymbolClassResolver:
    def __init__(
        self,
        presets: dict[str, ClassPreset],
        *,
        defaults: EffectiveConfig | None = None,
        meme_bases: frozenset[str] | set[str] | None = None,
    ) -> None:
        self.presets = presets
        self.defaults = defaults or EffectiveConfig()
        self.meme_bases = frozenset(b.upper() for b in (meme_bases or DEFAULT_MEME_BASES))

    def resolve(self, facts: SymbolFacts) -> ResolvedSymbolPreset:
        name = self.classify(facts)
        preset = self.presets[name]
        config = resolve_effective_config(self.defaults, preset, overlays=[])
        return ResolvedSymbolPreset(class_name=name, preset=preset, config=config)

    def classify(self, facts: SymbolFacts) -> str:
        """Exactly one class; first match in YAML priority order wins."""
        for name in _CLASS_PRIORITY:
            preset = self.presets.get(name)
            if preset is None or preset.overlay:
                continue
            if self._matches(preset, facts):
                return name
        # Fallback: treat unknown as low_liquidity if present, else mid_alt
        if "low_liquidity" in self.presets:
            return "low_liquidity"
        return next(n for n in _CLASS_PRIORITY if n in self.presets)

    def _matches(self, preset: ClassPreset, facts: SymbolFacts) -> bool:
        if preset.symbols_match:
            return facts.symbol.upper() in {s.upper() for s in preset.symbols_match}

        rule: dict[str, Any] = preset.universe_rule or {}
        if not rule:
            return False

        if "tag" in rule:
            tag = str(rule["tag"]).lower()
            if tag == "meme":
                base = facts.symbol.upper().removesuffix("USDT").removesuffix("USDC")
                return tag in {t.lower() for t in facts.tags} or base in self.meme_bases
            return tag in {t.lower() for t in facts.tags}

        if "volume_surge_ratio_min" in rule:
            # v1: skip hype until surge ratio is known
            if facts.volume_surge_ratio is None:
                return False
            if facts.volume_surge_ratio < float(rule["volume_surge_ratio_min"]):
                return False
            min_rank = rule.get("min_quote_volume_rank")
            if min_rank is None:
                return True
            return (
                facts.quote_volume_rank is not None
                and facts.quote_volume_rank >= int(min_rank)
            )

        if "listing_age_days_max" in rule:
            if facts.listing_age_days is None:
                return False
            return facts.listing_age_days <= float(rule["listing_age_days_max"])

        rank = facts.quote_volume_rank
        if rank is None:
            return False
        rmin = rule.get("quote_volume_rank_min")
        rmax = rule.get("quote_volume_rank_max")
        if rmin is not None and rank < int(rmin):
            return False
        if rmax is not None and rank > int(rmax):
            return False
        exclude = {str(x) for x in (rule.get("exclude_presets") or [])}
        # exclude_presets is documentary for major_alt (btc/eth already matched earlier)
        _ = exclude
        return rmin is not None or rmax is not None


def volume_ranks_from_tickers(tickers: list[dict]) -> dict[str, int]:
    """symbol → rank (1 = highest quoteVolume)."""
    scored: list[tuple[str, float]] = []
    for t in tickers:
        sym = t.get("symbol")
        if not sym:
            continue
        try:
            vol = float(t.get("quoteVolume", 0.0))
        except (TypeError, ValueError):
            vol = 0.0
        scored.append((sym, vol))
    scored.sort(key=lambda x: -x[1])
    return {sym: i + 1 for i, (sym, _) in enumerate(scored)}
