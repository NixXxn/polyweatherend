"""Live Polymarket wallet cash + position value (public RPC / Data API)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from .config import Settings

logger = logging.getLogger(__name__)

DATA_API = "https://data-api.polymarket.com"
PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
USDCE = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
_DECIMALS = 6
_BALANCE_OF = "70a08231"


@dataclass
class WalletSnapshot:
    address: str | None
    pusd: float = 0.0
    usdce: float = 0.0
    usdc: float = 0.0
    cash_usd: float = 0.0
    positions_usd: float = 0.0
    equity_usd: float = 0.0
    error: str | None = None


def hex_uint(value: str | None) -> int:
    if not value:
        return 0
    s = str(value).strip()
    if s.startswith("0x") or s.startswith("0X"):
        s = s[2:]
    if not s:
        return 0
    return int(s, 16)


def units_to_usd(raw: int, decimals: int = _DECIMALS) -> float:
    return round(raw / (10**decimals), 6)


def _pad_address(addr: str) -> str:
    return addr.lower().replace("0x", "").zfill(64)


def erc20_balance_calldata(wallet: str) -> str:
    return "0x" + _BALANCE_OF + _pad_address(wallet)


def fetch_wallet(settings: Settings, client: httpx.Client | None = None) -> WalletSnapshot:
    addr = settings.wallet_address
    if not addr:
        return WalletSnapshot(address=None, error="wallet_address_missing")
    own = client is None
    http = client or httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": "WeatherBuyEnd/0.1"})
    try:
        pusd = _erc20_balance(http, settings.polygon_rpc_url, PUSD, addr)
        usdce = _erc20_balance(http, settings.polygon_rpc_url, USDCE, addr)
        usdc = _erc20_balance(http, settings.polygon_rpc_url, USDC, addr)
        positions = _positions_value(http, addr)
        cash = pusd + usdce + usdc
        return WalletSnapshot(
            address=addr,
            pusd=pusd,
            usdce=usdce,
            usdc=usdc,
            cash_usd=round(cash, 2),
            positions_usd=round(positions, 2),
            equity_usd=round(cash + positions, 2),
        )
    except Exception as e:
        logger.warning("wallet fetch failed: %s", e)
        return WalletSnapshot(address=addr, error=str(e)[:200])
    finally:
        if own:
            http.close()


def _erc20_balance(http: httpx.Client, rpc: str, token: str, wallet: str) -> float:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": token, "data": erc20_balance_calldata(wallet)}, "latest"],
    }
    r = http.post(rpc, json=payload)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(str(data["error"])[:180])
    return units_to_usd(hex_uint(data.get("result")))


def _positions_value(http: httpx.Client, wallet: str) -> float:
    r = http.get(f"{DATA_API}/value", params={"user": wallet})
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list) and data:
        return float(data[0].get("value") or 0)
    if isinstance(data, dict):
        return float(data.get("value") or 0)
    return 0.0
