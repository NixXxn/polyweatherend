"""Order venue — paper fills by default; live PMXT behind flags."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from .config import Settings

logger = logging.getLogger(__name__)

OrderType = Literal["FOK", "IOC"]


@dataclass
class Fill:
    fill_id: str
    market_id: str
    location_id: str
    side: str  # BUY_NO
    price: float
    size_usd: float
    shares: float
    order_type: str
    mode: str  # paper | live
    latency_ms: float
    ts: str
    status: str
    question: str = ""
    edge: float | None = None


class Venue:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.errors = 0
        self.attempts = 0
        self._client = httpx.Client(timeout=15.0, follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    @property
    def error_rate(self) -> float:
        if self.attempts == 0:
            return 0.0
        return self.errors / self.attempts

    def buy_no_taker(
        self,
        *,
        market_id: str,
        location_id: str,
        no_token_id: str,
        ask: float,
        size_usd: float,
        order_type: OrderType = "FOK",
        question: str = "",
        edge: float | None = None,
        depth_usd: float = 100.0,
    ) -> Fill:
        t0 = time.perf_counter()
        self.attempts += 1
        shares = size_usd / ask if ask > 0 else 0.0

        if size_usd > depth_usd + 1e-6 and order_type == "FOK":
            self.errors += 1
            return Fill(
                fill_id=str(uuid.uuid4()),
                market_id=market_id,
                location_id=location_id,
                side="BUY_NO",
                price=ask,
                size_usd=0.0,
                shares=0.0,
                order_type=order_type,
                mode="paper" if not self.settings.is_live else "live",
                latency_ms=(time.perf_counter() - t0) * 1000,
                ts=datetime.now(timezone.utc).isoformat(),
                status="rejected_depth",
                question=question,
                edge=edge,
            )

        if not self.settings.is_live:
            return Fill(
                fill_id=f"paper-{uuid.uuid4().hex[:12]}",
                market_id=market_id,
                location_id=location_id,
                side="BUY_NO",
                price=ask,
                size_usd=round(size_usd, 2),
                shares=round(shares, 4),
                order_type=order_type,
                mode="paper",
                latency_ms=(time.perf_counter() - t0) * 1000,
                ts=datetime.now(timezone.utc).isoformat(),
                status="filled",
                question=question,
                edge=edge,
            )

        # Live PMXT path
        if not self.settings.pmxt_api_key:
            self.errors += 1
            raise RuntimeError("LIVE_TRADING set but PMXT_API_KEY missing")

        try:
            payload = {
                "token_id": no_token_id,
                "side": "BUY",
                "type": order_type,
                "price": ask,
                "size": shares,
                "amount_usd": size_usd,
            }
            url = f"{self.settings.pmxt_trade_url.rstrip('/')}/v0/orders"
            headers = {
                "Authorization": f"Bearer {self.settings.pmxt_api_key}",
                "Content-Type": "application/json",
            }
            if self.settings.pmxt_wallet_address:
                headers["X-Wallet-Address"] = self.settings.pmxt_wallet_address
            r = self._client.post(url, headers=headers, json=payload)
            latency = (time.perf_counter() - t0) * 1000
            if r.status_code >= 400:
                self.errors += 1
                logger.error("PMXT order failed %s: %s", r.status_code, r.text[:300])
                return Fill(
                    fill_id=str(uuid.uuid4()),
                    market_id=market_id,
                    location_id=location_id,
                    side="BUY_NO",
                    price=ask,
                    size_usd=0.0,
                    shares=0.0,
                    order_type=order_type,
                    mode="live",
                    latency_ms=latency,
                    ts=datetime.now(timezone.utc).isoformat(),
                    status=f"error_{r.status_code}",
                    question=question,
                    edge=edge,
                )
            data = r.json() if r.content else {}
            return Fill(
                fill_id=str(data.get("id") or data.get("order_id") or uuid.uuid4()),
                market_id=market_id,
                location_id=location_id,
                side="BUY_NO",
                price=float(data.get("price") or ask),
                size_usd=float(data.get("amount_usd") or size_usd),
                shares=float(data.get("size") or shares),
                order_type=order_type,
                mode="live",
                latency_ms=latency,
                ts=datetime.now(timezone.utc).isoformat(),
                status=str(data.get("status") or "submitted"),
                question=question,
                edge=edge,
            )
        except Exception:
            self.errors += 1
            raise
