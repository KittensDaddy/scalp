"""SymbolClassResolver — YAML routing rules from caems_presets.yaml."""

from __future__ import annotations

from pathlib import Path

from scalping.config.class_resolver import (
    SymbolClassResolver,
    SymbolFacts,
    volume_ranks_from_tickers,
)
from scalping.config.presets import load_presets_yaml
from scalping.config.settings import EffectiveConfig

DOCS = Path(__file__).resolve().parents[2] / "DOCS" / "caems_presets.yaml"


def test_docs_routing_priority():
    presets = load_presets_yaml(DOCS)
    r = SymbolClassResolver(presets)
    assert r.resolve(SymbolFacts("BTCUSDT")).class_name == "btc"
    assert r.resolve(SymbolFacts("ETHUSDT")).class_name == "eth"
    assert r.resolve(SymbolFacts("SOLUSDT", quote_volume_rank=5)).class_name == "major_alt"
    assert r.resolve(SymbolFacts("AAAUSDT", quote_volume_rank=40)).class_name == "mid_alt"
    assert r.resolve(SymbolFacts("ZZZUSDT", quote_volume_rank=90)).class_name == "low_liquidity"
    assert r.resolve(SymbolFacts("DOGEUSDT", quote_volume_rank=8)).class_name == "meme"


def test_disabled_observe_only_on_low_liquidity():
    presets = load_presets_yaml(DOCS)
    r = SymbolClassResolver(presets, defaults=EffectiveConfig())
    resolved = r.resolve(SymbolFacts("ILLIQUSDT", quote_volume_rank=99))
    assert resolved.class_name == "low_liquidity"
    assert resolved.config.symbol_meta.disabled is True
    assert resolved.config.symbol_meta.observe_only is True
    assert resolved.config.symbol_meta.disabled_reason == "LIQUIDITY_TOO_LOW"


def test_major_alt_stricter_spread_than_defaults():
    presets = load_presets_yaml(DOCS)
    r = SymbolClassResolver(presets)
    cfg = r.resolve(SymbolFacts("SOLUSDT", quote_volume_rank=3)).config
    assert cfg.gates.spread_max_bps == 1.8
    assert cfg.risk.risk_per_trade_pct == 0.12


def test_volume_ranks_from_tickers():
    ranks = volume_ranks_from_tickers(
        [
            {"symbol": "BTCUSDT", "quoteVolume": "100"},
            {"symbol": "ETHUSDT", "quoteVolume": "50"},
            {"symbol": "SOLUSDT", "quoteVolume": "200"},
        ]
    )
    assert ranks["SOLUSDT"] == 1
    assert ranks["BTCUSDT"] == 2
    assert ranks["ETHUSDT"] == 3
