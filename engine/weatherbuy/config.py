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
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    def is_live(self) -> bool:
        return self.trading_mode.lower() == "live" and self.live_trading


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
