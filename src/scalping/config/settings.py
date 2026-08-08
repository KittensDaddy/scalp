"""Single source of truth for runtime configuration.

Every strategy/gate/risk/execution key referenced by `DOCS/strategy-caems.md` and
`DOCS/caems_presets.yaml` lives here, typed and defaulted. Nothing is hard-coded in
strategy code — a preset or per-symbol override only ever changes values defined on
this model. Frozen strategy parameters (see `frozen.py`) are intentionally NOT present
on this model; they cannot be set through config at all.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from scalping.config.frozen import FrozenParams, reject_frozen_keys


class GateConfig(BaseModel):
    """CAEMS v2 entry-gate thresholds — every key is per-symbol overridable."""

    model_config = ConfigDict(extra="forbid")

    strength_min: float = 0.20
    strength_max: float = 1.50
    entry_max_atr: float = 0.50
    rvol_min: float = 1.3
    bar_range_max_atr: float = 3.0
    funding_blackout_s: int = 120
    spread_max_bps: float = 2.0
    spread_stability_60s_bps: float = 2.0

    btc_veto_enabled: bool = False
    btc_veto_threshold: float = 0.30
    require_btc_strength_min: float | None = None

    taker_spread_max_bps: float = 2.0


class ExitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    be_enabled: bool = True
    be_trigger_r: float = 1.0
    be_offset_mode: Literal["round_trip_cost"] = "round_trip_cost"

    slippage_buffer: float = 0.0  # price-unit; venue/symbol calibrated
    exec_floor_max_stop_frac: float = 0.5


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_per_trade_pct: float = 0.15
    leverage_cap: float = 2.0
    depth_size_frac: float = 0.15
    volume_cap_frac: float = 0.10
    exchange_cap_frac: float = 1.0

    daily_loss_cap_r: float = 3.0
    weekly_loss_cap_r: float = 6.0
    max_positions_total: int = 3
    max_positions_in_class: int = 1
    max_positions_per_correlation_group: int = 99  # permissive default; tighten per group

    risk_per_trade_multiplier: float = 1.0  # overlay hook (e.g. high_funding: 0.75)


class CostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_edge_multiplier: float = 1.5
    taker_fee_bps: float = 5.0
    maker_fee_bps: float = 2.0
    safety_buffer_bps: float = 1.0


class SymbolMeta(BaseModel):
    """Universe / listing metadata used by preset resolution, not by CAEMS rules."""

    model_config = ConfigDict(extra="forbid")

    min_listing_age_days: int = 0
    shorts_enabled: bool = True
    disabled: bool = False
    disabled_reason: str | None = None
    observe_only: bool = False


class EffectiveConfig(BaseModel):
    """The fully-resolved configuration a symbol trades under.

    `defaults <- class_preset <- overlays <- per_symbol_override`, per
    DASHBOARD_STRATEGY_LAB.md §1. Frozen params are attached read-only from
    `FrozenParams` and are never part of the merge.
    """

    model_config = ConfigDict(extra="forbid")

    frozen: FrozenParams = Field(default_factory=FrozenParams)
    gates: GateConfig = Field(default_factory=GateConfig)
    exits: ExitConfig = Field(default_factory=ExitConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    cost: CostConfig = Field(default_factory=CostConfig)
    symbol_meta: SymbolMeta = Field(default_factory=SymbolMeta)

    protection_timeout_ms: int = 2000

    def config_hash(self) -> str:
        """Deterministic hash persisted with every signal/rejection/trade.

        Excludes nothing — the hash must change if any effective value changes,
        including frozen params (a caems_v3 bump changes `frozen.strategy_version`).
        """
        payload = self.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Settings(BaseSettings):
    """Process-level settings: secrets, endpoints, and the config default stack.

    Loaded from environment variables (prefix `SCALPING_`) and an optional `.env`
    file. Never logged or repr'd with secret values — see `scalping.monitoring.logging`
    for the redaction filter this model is designed to work with.
    """

    model_config = SettingsConfigDict(
        env_prefix="SCALPING_",
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    environment: Literal["backtest", "replay", "paper", "testnet", "live"] = "paper"

    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_rest_base: str = "https://fapi.binance.com"
    binance_testnet_rest_base: str = "https://demo-fapi.binance.com"
    binance_ws_base: str = "wss://fstream.binance.com"

    database_url: str = "sqlite+aiosqlite:///./data/scalping.db"

    control_token: str = ""
    dashboard_unkill_token: str = ""

    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8000
    dashboard_cors_origin: str = "http://localhost:5173"

    defaults: EffectiveConfig = Field(default_factory=EffectiveConfig)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "Settings(<redacted>)"

    __str__ = __repr__


def get_settings() -> Settings:
    return Settings()


__all__ = [
    "CostConfig",
    "EffectiveConfig",
    "ExitConfig",
    "GateConfig",
    "RiskConfig",
    "Settings",
    "SymbolMeta",
    "get_settings",
    "reject_frozen_keys",
]
