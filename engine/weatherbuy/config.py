from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


CLOB_URL = "https://clob.polymarket.com"


def repo_root() -> Path:
    # engine/weatherbuy/config.py -> repo root
    return Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # Modes
    trading_mode: str = Field(default="paper", alias="TRADING_MODE")  # paper|live
    live_trading: bool = Field(default=False, alias="LIVE_TRADING")
    mock_markets: bool = Field(default=False, alias="MOCK_MARKETS")

    # Venue — market data and live orders always hit Polymarket CLOB
    pmxt_api_key: str | None = Field(default=None, alias="PMXT_API_KEY")
    pmxt_wallet_address: str | None = Field(default=None, alias="PMXT_WALLET_ADDRESS")
    pmxt_catalog_url: str = Field(default=CLOB_URL, alias="PMXT_CATALOG_URL")
    pmxt_trade_url: str = Field(default=CLOB_URL, alias="PMXT_TRADE_URL")
    clob_url: str = Field(default=CLOB_URL, alias="CLOB_URL")
    poly_private_key: str | None = Field(default=None, alias="POLY_PRIVATE_KEY")
    pmxt_private_key: str | None = Field(default=None, alias="PMXT_PRIVATE_KEY")
    clob_api_key: str | None = Field(default=None, alias="CLOB_API_KEY")
    clob_secret: str | None = Field(default=None, alias="CLOB_SECRET")
    clob_passphrase: str | None = Field(default=None, alias="CLOB_PASS_PHRASE")
    poly_signature_type: str | None = Field(default=None, alias="POLY_SIGNATURE_TYPE")
    polygon_rpc_url: str = Field(
        default="https://polygon-bor.publicnode.com", alias="POLYGON_RPC_URL"
    )

    # Infra
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=3847, alias="API_PORT")
    strategy_config: str = Field(default="config/strategy.yaml", alias="STRATEGY_CONFIG")
    cities_config: str = Field(default="config/cities.yaml", alias="CITIES_CONFIG")

    # Ops
    kill_switch_default: bool = Field(default=False, alias="KILL_SWITCH")
    city_roles: str = Field(default="paper,strict,metar", alias="CITY_ROLES")
    # Default operating budget (UI can override; persisted in ledger state)
    budget_usd: float | None = Field(default=None, alias="BUDGET_USD")

    @property
    def venue_url(self) -> str:
        return CLOB_URL

    @property
    def wallet_address(self) -> str | None:
        addr = (self.pmxt_wallet_address or "").strip()
        return addr or None

    @property
    def signing_key(self) -> str | None:
        key = (self.poly_private_key or self.pmxt_private_key or "").strip()
        return key or None

    @property
    def signature_type(self) -> int:
        raw = (self.poly_signature_type or "").strip()
        if raw:
            return int(raw)
        # Proxy/funder wallet → POLY_PROXY (email/magic). Override with POLY_SIGNATURE_TYPE=2 for browser Gnosis.
        return 1 if self.wallet_address else 0

    @property
    def is_live(self) -> bool:
        return self.trading_mode.lower() == "live" or bool(self.live_trading)

    @property
    def live_ready(self) -> bool:
        return self.is_live and bool(self.signing_key)


def load_yaml(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = repo_root() / p
    with p.open() as f:
        return yaml.safe_load(f) or {}


def load_strategy(settings: Settings | None = None) -> dict[str, Any]:
    s = settings or Settings()
    return load_yaml(s.strategy_config)


def load_cities(settings: Settings | None = None) -> list[dict[str, Any]]:
    s = settings or Settings()
    raw = load_yaml(s.cities_config)
    cities = list(raw.get("cities") or [])
    roles = {r.strip() for r in s.city_roles.split(",") if r.strip()}
    if roles:
        cities = [c for c in cities if str(c.get("role", "metar")) in roles]
    return cities


def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}
