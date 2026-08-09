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
from pathlib import Path
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
    max_positions_total: int = 10
    max_positions_in_class: int = 3
    max_positions_per_correlation_group: int = 99  # permissive default; tighten per group

    risk_per_trade_multiplier: float = 1.0  # overlay hook (e.g. high_funding: 0.75)


class CostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_edge_multiplier: float = 1.5
    taker_fee_bps: float = 5.0
    maker_fee_bps: float = 2.0
    safety_buffer_bps: float = 1.0


class CooldownConfig(BaseModel):
    """How long a symbol sits out after a trade or a feed interruption.

    `StrategyRunner` has always *checked* cooldowns; these are the durations the
    runtime now sets them for. Losses cool down longer than wins: re-entering the
    same symbol immediately after a stop-out is how one adverse regime turns into
    a cluster of correlated losses.
    """

    model_config = ConfigDict(extra="forbid")

    post_trade_s: float = 60.0
    post_loss_s: float = 300.0
    api_reconnect_s: float = 30.0


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
    cooldowns: CooldownConfig = Field(default_factory=CooldownConfig)
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

    # Outbound HTTP(S) proxy for Binance REST (+ optional WS). Webshare example:
    #   SCALPING_HTTP_PROXY=http://USER-rotate:PASS@p.webshare.io:80
    # Or many direct proxies (comma/newline); one is picked sticky per process:
    #   SCALPING_HTTP_PROXIES=http://u:p@1.2.3.4:80,http://u:p@5.6.7.8:80
    http_proxy: str = ""
    http_proxies: str = ""

    database_url: str = "sqlite+aiosqlite:///./data/scalping.db"

    # Paper defaults so `scalping --run` works after pull without exporting env.
    # Override in .env for anything beyond local/miniserver paper soak.
    control_token: str = "paper-ctrl"
    dashboard_unkill_token: str = "paper-unkill"

    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8000
    # Built dashboard (`cd frontend && npm run build`) served by the API itself.
    # Empty → auto-detect `frontend/dist` in the repo. Serving it same-origin is
    # what makes a headless miniserver reachable over one port with no Vite
    # process and no CORS involved at all.
    dashboard_static_dir: str = ""
    # Comma-separated browser origins allowed to call the API (CORS).
    # LAN example: http://192.168.1.10:5173,http://localhost:5173
    dashboard_cors_origin: str = "http://localhost:5173"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    calibration_min_samples: int = 30
    paper_min_trades_for_live: int = 50
    # "auto" = liquid USDT-perp universe from Binance (see market_data/universe.py).
    # Or a comma list, e.g. "BTCUSDT,ETHUSDT".
    run_symbols: str = "auto"
    universe_max_symbols: int = 300
    # Liquidity floor for auto-universe (USDT 24h quote volume).
    # ~$100k + 10bps spread ≈ 300 names; raise for a tighter liquid set.
    universe_min_quote_volume_usdt: float = 100_000.0
    universe_max_spread_bps: float = 10.0
    # 0 = skip per-symbol kline history REST probes (avoids Binance IP bans).
    universe_min_history_days: int = 0
    # How often to rebuild the liquid watchlist when run_symbols=auto.
    # Scanner score still re-ranks every tick inside that watchlist.
    universe_refresh_hours: float = 4.0
    # REST candle backfill before WS. Default off — indicators fill from live
    # kline_1m streams (avoids Binance IP bans on large universes).
    warm_registry: bool = False
    paper_equity: float = 10_000.0
    # GTX maker entry TTL, per strategy-caems.md §Order flow step 2. Must stay
    # long enough for the book to actually move against a resting order —
    # sub-second values make maker fills impossible and turn the whole campaign
    # into a taker-only sample.
    paper_entry_ttl_s: float = 3.0
    # Offsets at which post-fill markouts are sampled (adverse-selection rule).
    markout_short_s: float = 5.0
    markout_long_s: float = 30.0
    # Empty → DOCS/caems_presets.yaml (repo root). Per-pair class routing for --run.
    presets_path: str = ""
    # Comma list of strategy_ids. Empty → caems_v2 + ALT_RESIDUAL + microstructure stubs.
    enabled_strategies: str = ""

    defaults: EffectiveConfig = Field(default_factory=EffectiveConfig)

    def static_dir(self) -> Path | None:
        """Directory of the built dashboard, or None when it hasn't been built.

        Checked against several layouts because the answer decides whether the
        dashboard appears at all: an explicit override, the repo root relative to
        this file (editable install), and the working directory (non-editable
        install, where `__file__` lives under site-packages).
        """
        if self.dashboard_static_dir:
            explicit = Path(self.dashboard_static_dir).expanduser()
            return explicit if (explicit / "index.html").is_file() else None
        candidates = [
            Path(__file__).resolve().parents[3] / "frontend" / "dist",
            Path.cwd() / "frontend" / "dist",
        ]
        for candidate in candidates:
            if (candidate / "index.html").is_file():
                return candidate
        return None

    def use_universe(self) -> bool:
        return self.run_symbols.strip().lower() in {"auto", "universe", "*"}

    def symbols_list(self) -> list[str]:
        if self.use_universe():
            return []
        return [s.strip().upper() for s in self.run_symbols.split(",") if s.strip()]

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "Settings(<redacted>)"

    __str__ = __repr__


def get_settings() -> Settings:
    return Settings()


__all__ = [
    "CooldownConfig",
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
