"""Order venue — paper fills or live Polymarket CLOB taker BUY NO."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from .config import Settings

logger = logging.getLogger(__name__)

OrderType = Literal["FOK", "IOC"]


def _allow_signature_type_1271() -> None:
    """py-clob-client 0.34 / py_order_utils only allow sig types 0–2. Polymarket.com deposit wallets use 3."""
    try:
        from py_order_utils.builders.order_builder import OrderBuilder as UtilsOrderBuilder
        from py_order_utils.model.signatures import EOA, POLY_GNOSIS_SAFE, POLY_PROXY
    except Exception:
        return
    if getattr(UtilsOrderBuilder._validate_inputs, "_poly1271", False):
        return

    def _validate_inputs(self, data) -> bool:  # noqa: ANN001
        st = data.signatureType
        return not (
            data.maker is None
            or data.tokenId is None
            or data.makerAmount is None
            or data.takerAmount is None
            or data.side is None
            or data.side not in {0, 1}
            or not str(data.feeRateBps).isnumeric()
            or int(data.feeRateBps) < 0
            or not str(data.nonce).isnumeric()
            or int(data.nonce) < 0
            or not str(data.expiration).isnumeric()
            or int(data.expiration) < 0
            or st is None
            or int(st) not in {int(EOA), int(POLY_PROXY), int(POLY_GNOSIS_SAFE), 3}
        )

    _validate_inputs._poly1271 = True  # type: ignore[attr-defined]
    UtilsOrderBuilder._validate_inputs = _validate_inputs
    logger.info("CLOB order builder allows signature_type=3 (POLY_1271)")


def _usdc_to_usd(raw: Any) -> float | None:
    """CLOB collateral is usually 6-decimal USDC integer; sometimes already USD."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        for key in ("balance", "amount", "usd", "usdc"):
            if key in raw:
                return _usdc_to_usd(raw[key])
        return None
    try:
        s = str(raw).strip().replace(",", "")
        if not s:
            return None
        val = float(s)
    except (TypeError, ValueError):
        return None
    if val < 0:
        return None
    # Raw 6-decimal units look like large integers ("12340000" → $12.34)
    if "." not in s and val >= 1000:
        val = val / 1_000_000.0
    return round(val, 2)


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
        self._clob = None
        self._resolved_sig = int(settings.poly_signature_type or 0)
        self._resolved_funder = (settings.poly_funder or "").strip() or None
        if settings.is_live and settings.has_poly_creds:
            self._clob = self._build_clob_client()

    def close(self) -> None:
        self._clob = None

    def _eoa_address(self) -> str | None:
        pk = (self.settings.poly_private_key or "").strip()
        if not pk:
            return None
        try:
            from eth_account import Account

            return Account.from_key(pk).address
        except Exception:
            logger.warning("Could not derive EOA from POLY_PRIVATE_KEY")
            return None

    def _lookup_proxy_wallet(self, eoa: str) -> str | None:
        """Public Gamma profile → Polymarket proxy/deposit wallet that holds USDC."""
        try:
            import httpx

            url = f"{self.settings.poly_gamma_url.rstrip('/')}/public-profile"
            r = httpx.get(url, params={"address": eoa}, timeout=15.0, follow_redirects=True)
            if r.status_code >= 400:
                logger.warning("public-profile HTTP %s for EOA lookup", r.status_code)
                return None
            data = r.json()
            if not isinstance(data, dict):
                return None
            proxy = data.get("proxyWallet") or data.get("proxy_wallet") or data.get("proxyAddress")
            if proxy and str(proxy).startswith("0x"):
                return str(proxy)
        except Exception:
            logger.warning("public-profile lookup failed", exc_info=True)
        return None

    def _build_clob_client(self) -> Any:
        from py_clob_client_v2.client import ClobClient

        pk = (self.settings.poly_private_key or "").strip()
        eoa = self._eoa_address()
        funder = (self.settings.poly_funder or "").strip() or None
        if not funder and eoa:
            funder = self._lookup_proxy_wallet(eoa)
            if funder:
                logger.info("CLOB auto-detected POLY_FUNDER from public-profile")

        sig = int(self.settings.poly_signature_type or 0)
        if funder and eoa and funder.lower() != eoa.lower() and sig == 0:
            # Current Polymarket.com deposit wallets need POLY_1271, not EOA.
            sig = 3
            logger.warning(
                "POLY_SIGNATURE_TYPE was 0 but funder != EOA; using signature_type=3 (deposit wallet)"
            )

        kwargs: dict[str, Any] = {
            "host": self.settings.poly_clob_host,
            "key": pk,
            "chain_id": int(self.settings.poly_chain_id),
            "signature_type": sig,
        }
        if funder:
            kwargs["funder"] = funder

        # L1: build without website L2 keys (those 401 if bound to another address).
        client = ClobClient(**kwargs)
        try:
            derived = client.create_or_derive_api_key()
            if derived is None:
                raise RuntimeError("create_or_derive_api_key returned None")
            client.set_api_creds(derived)
            logger.info("CLOB L2 creds derived from private key")
        except Exception:
            if self.settings.poly_api_key and self.settings.poly_api_secret and self.settings.poly_api_passphrase:
                from py_clob_client_v2.clob_types import ApiCreds

                logger.warning("CLOB cred derive failed; falling back to POLY_API_* from env")
                client.set_api_creds(
                    ApiCreds(
                        api_key=self.settings.poly_api_key,
                        api_secret=self.settings.poly_api_secret,
                        api_passphrase=self.settings.poly_api_passphrase,
                    )
                )
            else:
                raise

        logger.info(
            "CLOB client ready host=%s chain=%s sig_type=%s eoa=%s funder=%s",
            self.settings.poly_clob_host,
            self.settings.poly_chain_id,
            sig,
            eoa,
            funder,
        )
        self._resolved_sig = sig
        self._resolved_funder = funder
        return client

    def get_collateral(self) -> dict[str, Any]:
        """Live CLOB USDC collateral (not the paper BUDGET_USD). Never logs secrets."""
        out: dict[str, Any] = {
            "wallet_usd": None,
            "allowance_usd": None,
            "ok": False,
            "error": None,
            "sig_type": int(getattr(self, "_resolved_sig", self.settings.poly_signature_type) or 0),
            "funder_set": bool(getattr(self, "_resolved_funder", None) or self.settings.poly_funder),
        }
        if not self.settings.is_live:
            out["error"] = "not_live"
            return out
        if not self.settings.has_poly_creds:
            out["error"] = "missing_poly_creds"
            return out
        if self._clob is None:
            try:
                self._clob = self._build_clob_client()
            except Exception as e:
                out["error"] = f"clob_client:{type(e).__name__}"
                logger.exception("CLOB client build failed")
                return out
        try:
            from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams

            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            resp = self._clob.get_balance_allowance(params)
        except Exception as e:
            msg = str(e).replace("\n", " ")[:180]
            out["error"] = f"balance_fetch:{type(e).__name__}:{msg}"
            logger.warning("CLOB collateral fetch failed: %s", msg)
            return out
        if not isinstance(resp, dict):
            out["error"] = f"unexpected_balance_type:{type(resp).__name__}"
            return out
        out["wallet_usd"] = _usdc_to_usd(resp.get("balance"))
        allowance = resp.get("allowance")
        if allowance is None:
            allowances = resp.get("allowances")
            if isinstance(allowances, dict) and allowances:
                try:
                    allowance = min(_usdc_to_usd(v) or 0.0 for v in allowances.values())
                    out["allowance_usd"] = round(float(allowance), 2)
                except Exception:
                    allowance = None
            elif isinstance(allowances, list) and allowances:
                try:
                    allowance = min(_usdc_to_usd(v) or 0.0 for v in allowances)
                    out["allowance_usd"] = round(float(allowance), 2)
                except Exception:
                    allowance = None
        else:
            out["allowance_usd"] = _usdc_to_usd(allowance)
        if out["allowance_usd"] is not None and out["allowance_usd"] > 1_000_000_000:
            # uint256 max from CLOB means unlimited, not a real USD figure
            out["allowance_usd"] = None
        out["ok"] = out["wallet_usd"] is not None
        logger.info(
            "CLOB wallet usd=%s allowance=%s keys=%s sig_type=%s funder_set=%s",
            out["wallet_usd"],
            out["allowance_usd"],
            sorted(resp.keys()),
            out["sig_type"],
            out["funder_set"],
        )
        if out["ok"] and (out["wallet_usd"] or 0) <= 0:
            logger.warning(
                "CLOB wallet USDC is 0. If Polymarket.com shows a balance, set "
                "POLY_SIGNATURE_TYPE=3 and POLY_FUNDER to the profile proxy/deposit wallet."
            )
        return out

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
        neg_risk: bool = True,
        tick_size: str = "0.01",
    ) -> Fill:
        t0 = time.perf_counter()
        shares = size_usd / ask if ask > 0 else 0.0
        live = bool(self.settings.is_live)

        if live and (
            self.settings.mock_markets
            or not str(no_token_id or "")
            or str(no_token_id).startswith(("yes-", "no-", "mock"))
        ):
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
                latency_ms=(time.perf_counter() - t0) * 1000,
                ts=datetime.now(timezone.utc).isoformat(),
                status="rejected_mock_token",
                question=question,
                edge=edge,
            )

        if size_usd > depth_usd + 1e-6 and order_type == "FOK":
            # Thin book — not a venue outage. Caller should clip before submit.
            return Fill(
                fill_id=str(uuid.uuid4()),
                market_id=market_id,
                location_id=location_id,
                side="BUY_NO",
                price=ask,
                size_usd=0.0,
                shares=0.0,
                order_type=order_type,
                mode="paper" if not live else "live",
                latency_ms=(time.perf_counter() - t0) * 1000,
                ts=datetime.now(timezone.utc).isoformat(),
                status="rejected_depth",
                question=question,
                edge=edge,
            )

        if not live:
            logger.info(
                "PAPER FILL city=%s market=%s usd=%.2f ask=%.3f (not live — no CLOB post)",
                location_id,
                market_id[:18],
                size_usd,
                ask,
            )
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

        self.attempts += 1
        if not self.settings.has_poly_creds:
            self.errors += 1
            raise RuntimeError("LIVE_TRADING set but POLY_* CLOB credentials missing")

        if self._clob is None:
            try:
                self._clob = self._build_clob_client()
            except Exception as e:
                self.errors += 1
                logger.exception("CLOB client build failed")
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
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    ts=datetime.now(timezone.utc).isoformat(),
                    status=f"error:{type(e).__name__}",
                    question=question,
                    edge=edge,
                )

        try:
            return self._live_clob_buy_no(
                t0=t0,
                market_id=market_id,
                location_id=location_id,
                no_token_id=no_token_id,
                ask=ask,
                size_usd=size_usd,
                shares=shares,
                order_type=order_type,
                question=question,
                edge=edge,
                neg_risk=neg_risk,
                tick_size=tick_size,
            )
        except Exception as e:
            self.errors += 1
            logger.exception("CLOB BUY NO failed market=%s", market_id)
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
                latency_ms=(time.perf_counter() - t0) * 1000,
                ts=datetime.now(timezone.utc).isoformat(),
                status=f"error:{type(e).__name__}",
                question=question,
                edge=edge,
            )

    def _live_clob_buy_no(
        self,
        *,
        t0: float,
        market_id: str,
        location_id: str,
        no_token_id: str,
        ask: float,
        size_usd: float,
        shares: float,
        order_type: OrderType,
        question: str,
        edge: float | None,
        neg_risk: bool,
        tick_size: str,
    ) -> Fill:
        try:
            from py_clob_client_v2.clob_types import (
                MarketOrderArgsV2,
                OrderType as ClobOrderType,
                PartialCreateOrderOptions,
            )
            from py_clob_client_v2.order_builder.constants import BUY

            clob_type = ClobOrderType.FOK if order_type.upper() == "FOK" else ClobOrderType.FAK
            worst = min(0.99, max(0.01, float(ask) + 0.02))

            mo = MarketOrderArgsV2(
                token_id=str(no_token_id),
                amount=float(size_usd),
                side=BUY,
                price=worst,
                order_type=clob_type,
            )
            options = PartialCreateOrderOptions(
                tick_size=str(tick_size),
                neg_risk=bool(neg_risk),
            )
            logger.info(
                "CLOB SUBMIT BUY_NO market=%s token=%s usd=%.2f type=%s worst=%.3f client=v2",
                market_id[:18],
                str(no_token_id)[:16],
                size_usd,
                order_type,
                worst,
            )
            resp = self._clob.create_and_post_market_order(mo, options, clob_type)
        except TypeError:
            from py_clob_client_v2.clob_types import MarketOrderArgsV2, OrderType as ClobOrderType
            from py_clob_client_v2.order_builder.constants import BUY

            clob_type = ClobOrderType.FOK if order_type.upper() == "FOK" else ClobOrderType.FAK
            mo = MarketOrderArgsV2(
                token_id=str(no_token_id),
                amount=float(size_usd),
                side=BUY,
                order_type=clob_type,
            )
            logger.info(
                "CLOB SUBMIT BUY_NO market=%s token=%s usd=%.2f type=%s (v2 fallback)",
                market_id[:18],
                str(no_token_id)[:16],
                size_usd,
                order_type,
            )
            resp = self._clob.create_and_post_market_order(mo, order_type=clob_type)

        latency = (time.perf_counter() - t0) * 1000

        if not isinstance(resp, dict):
            resp = {"raw": resp}
        logger.info(
            "CLOB RESP market=%s status=%s keys=%s err=%s",
            market_id[:18],
            resp.get("status") or resp.get("orderStatus"),
            sorted(str(k) for k in resp.keys()),
            resp.get("errorMsg") or resp.get("error"),
        )
        status = str(resp.get("status") or resp.get("orderStatus") or "submitted")
        err = resp.get("errorMsg") or resp.get("error")
        if err or status.lower() in {"rejected", "canceled", "cancelled", "failed"}:
            logger.warning("CLOB order not filled: %s", resp)
            return Fill(
                fill_id=str(resp.get("orderID") or resp.get("id") or uuid.uuid4()),
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
                status=f"rejected:{status}",
                question=question,
                edge=edge,
            )

        fill_price = float(resp.get("price") or resp.get("avgPrice") or ask)
        fill_size = float(resp.get("size_matched") or resp.get("takingAmount") or shares)
        usd = float(resp.get("makingAmount") or size_usd)
        if fill_price > 0 and fill_size > 0 and abs(usd - size_usd) < 1e-9:
            try:
                usd = round(float(fill_size) * fill_price, 4)
            except Exception:
                usd = size_usd

        return Fill(
            fill_id=str(resp.get("orderID") or resp.get("id") or uuid.uuid4()),
            market_id=market_id,
            location_id=location_id,
            side="BUY_NO",
            price=fill_price,
            size_usd=round(usd, 2),
            shares=round(float(fill_size) if fill_size else shares, 4),
            order_type=order_type,
            mode="live",
            latency_ms=latency,
            ts=datetime.now(timezone.utc).isoformat(),
            status="filled" if status.lower() in {"matched", "filled", "live", "submitted"} else status,
            question=question,
            edge=edge,
        )
