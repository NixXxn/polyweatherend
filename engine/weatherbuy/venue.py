"""Order venue — paper fills by default; signed live CLOB orders behind flags."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from .config import CLOB_URL, Settings

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
        self._clob = None
        self._clob_error: str | None = None

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
            return self._fill(
                market_id=market_id,
                location_id=location_id,
                ask=ask,
                size_usd=0.0,
                shares=0.0,
                order_type=order_type,
                status="rejected_depth",
                question=question,
                edge=edge,
                t0=t0,
            )

        if not self.settings.is_live:
            return self._fill(
                market_id=market_id,
                location_id=location_id,
                ask=ask,
                size_usd=round(size_usd, 2),
                shares=round(shares, 4),
                order_type=order_type,
                status="filled",
                question=question,
                edge=edge,
                t0=t0,
                fill_id=f"paper-{uuid.uuid4().hex[:12]}",
            )

        clob = self._clob_client()
        if clob is None:
            self.errors += 1
            return self._fill(
                market_id=market_id,
                location_id=location_id,
                ask=ask,
                size_usd=0.0,
                shares=0.0,
                order_type=order_type,
                status="error_missing_signing_key",
                question=question,
                edge=edge,
                t0=t0,
            )

        try:
            from py_clob_client_v2 import MarketOrderArgs, OrderType as ClobOrderType, Side

            clob_type = ClobOrderType.FOK if str(order_type).upper() == "FOK" else ClobOrderType.FAK
            resp = clob.create_and_post_market_order(
                MarketOrderArgs(
                    token_id=str(no_token_id),
                    amount=float(size_usd),
                    side=Side.BUY,
                    price=float(ask),
                    order_type=clob_type,
                ),
                order_type=clob_type,
            )
            data = resp if isinstance(resp, dict) else {}
            status = str(data.get("status") or data.get("orderStatus") or "submitted")
            oid = str(data.get("orderID") or data.get("orderId") or data.get("id") or uuid.uuid4())
            return self._fill(
                market_id=market_id,
                location_id=location_id,
                ask=float(data.get("price") or ask),
                size_usd=float(data.get("amount_usd") or size_usd),
                shares=float(data.get("size") or shares),
                order_type=order_type,
                status=status.lower(),
                question=question,
                edge=edge,
                t0=t0,
                fill_id=oid,
            )
        except Exception as e:
            self.errors += 1
            logger.exception("CLOB live order failed: %s", e)
            return self._fill(
                market_id=market_id,
                location_id=location_id,
                ask=ask,
                size_usd=0.0,
                shares=0.0,
                order_type=order_type,
                status="error_clob_order",
                question=question,
                edge=edge,
                t0=t0,
            )

    def _clob_client(self):
        if self._clob is not None:
            return self._clob
        key = self.settings.signing_key
        if not key:
            self._clob_error = "POLY_PRIVATE_KEY missing — live orders cannot be signed"
            logger.error(self._clob_error)
            return None
        try:
            from py_clob_client_v2 import ApiCreds, ClobClient

            creds = None
            if self.settings.clob_api_key and self.settings.clob_secret and self.settings.clob_passphrase:
                creds = ApiCreds(
                    api_key=self.settings.clob_api_key,
                    api_secret=self.settings.clob_secret,
                    api_passphrase=self.settings.clob_passphrase,
                )
            kwargs: dict[str, Any] = {
                "host": CLOB_URL,
                "chain_id": 137,
                "key": key,
                "signature_type": self.settings.signature_type,
            }
            if self.settings.wallet_address:
                kwargs["funder"] = self.settings.wallet_address
            if creds:
                kwargs["creds"] = creds
            client = ClobClient(**kwargs)
            if creds is None:
                derived = client.create_or_derive_api_key()
                kwargs["creds"] = derived
                client = ClobClient(**kwargs)
            self._clob = client
            logger.info(
                "CLOB live client ready funder=%s sig_type=%s",
                self.settings.wallet_address,
                self.settings.signature_type,
            )
            return self._clob
        except Exception as e:
            self._clob_error = str(e)[:200]
            logger.exception("CLOB client init failed: %s", e)
            return None

    def _fill(
        self,
        *,
        market_id: str,
        location_id: str,
        ask: float,
        size_usd: float,
        shares: float,
        order_type: str,
        status: str,
        question: str,
        edge: float | None,
        t0: float,
        fill_id: str | None = None,
    ) -> Fill:
        live = self.settings.is_live
        return Fill(
            fill_id=fill_id or str(uuid.uuid4()),
            market_id=market_id,
            location_id=location_id,
            side="BUY_NO",
            price=ask,
            size_usd=size_usd,
            shares=shares,
            order_type=order_type,
            mode="live" if live else "paper",
            latency_ms=(time.perf_counter() - t0) * 1000,
            ts=datetime.now(timezone.utc).isoformat(),
            status=status,
            question=question,
            edge=edge,
        )
