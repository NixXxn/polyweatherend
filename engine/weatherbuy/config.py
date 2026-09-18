from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def repo_root() -> Path:
    # engine/weatherbuy/config.py -> repo root
    return Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Modes
    trading_mode: str = Field(default="live", alias="TRADING_MODE")  # paper|live
    live_trading: bool = Field(default=True, alias="LIVE_TRADING")
    mock_markets: bool = Field(default=False, alias="MOCK_MARKETS")

    # Polymarket CLOB + Gamma
    poly_private_key: str | None = Field(default=None, alias="POLY_PRIVATE_KEY")
    poly_api_key: str | None = Field(default=None, alias="POLY_API_KEY")
    poly_api_secret: str | None = Field(default=None, alias="POLY_API_SECRET")
    poly_api_passphrase: str | None = Field(default=None, alias="POLY_API_PASSPHRASE")
    poly_signature_type: int = Field(default=0, alias="POLY_SIGNATURE_TYPE")
    poly_funder: str | None = Field(default=None, alias="POLY_FUNDER")
    poly_clob_host: str = Field(default="https://clob.polymarket.com", alias="POLY_CLOB_HOST")
    poly_chain_id: int = Field(default=137, alias="POLY_CHAIN_ID")
    poly_gamma_url: str = Field(default="https://gamma-api.polymarket.com", alias="POLY_GAMMA_URL")

    # Infra
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=3847, alias="API_PORT")
    strategy_config: str = Field(default="config/strategy.yaml", alias="STRATEGY_CONFIG")
    cities_config: str = Field(default="config/cities.yaml", alias="CITIES_CONFIG")

    # Ops
    kill_switch_default: bool = Field(default=True, alias="KILL_SWITCH")
    city_roles: str = Field(default="paper,strict,metar", alias="CITY_ROLES")
    budget_usd: float | None = Field(default=None, alias="BUDGET_USD")

    @property
    def is_live(self) -> bool:
        return self.trading_mode.lower() == "live" and self.live_trading

    @property
    def has_poly_creds(self) -> bool:
        # L2 API keys can be derived from the private key at runtime.
        return bool(self.poly_private_key)


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
