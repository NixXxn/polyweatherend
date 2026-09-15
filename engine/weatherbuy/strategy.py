"""NO-eliminated gating — HighTempTation late BUY NO sleeve."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class NoElimDecision:
    ok: bool
    reason: str
    no_price: float | None = None
    p_no: float | None = None
    net_edge: float | None = None


def no_eliminated_cfg(strategy: dict[str, Any]) -> dict[str, Any]:
    raw = dict(strategy.get("no_eliminated") or {})
    return {
        "enabled": bool(raw.get("enabled", True)),
        "max_hours_to_noon": float(raw.get("max_hours_to_noon", 6.0)),
        "min_no_price": float(raw.get("min_no_price", 0.80)),
        "max_no_price": float(raw.get("max_no_price", 0.985)),
        "min_net_edge": float(raw.get("min_net_edge", 0.015)),
        "p_no_if_eliminated": float(raw.get("p_no_if_eliminated", 0.99)),
        "require_eliminated": bool(raw.get("require_eliminated", True)),
        "stake_mult": float(raw.get("stake_mult", 1.0)),
    }


def evaluate_no_eliminated(
    *,
    hours: float,
    eliminated: bool,
    no_price: float,
    cfg: dict[str, Any],
) -> NoElimDecision:
    if not cfg.get("enabled"):
        return NoElimDecision(False, "no_eliminated_disabled")
    if hours is None:
        return NoElimDecision(False, "hours_nan")
    # hours_to_noon: after noon is negative; window is hours <= max (includes after noon)
    # Also require we are not too early: hours > -24 implicitly via market day
    if float(hours) > float(cfg["max_hours_to_noon"]):
        return NoElimDecision(False, "outside_no_window", no_price=float(no_price))
    if cfg.get("require_eliminated", True) and not bool(eliminated):
        return NoElimDecision(False, "not_eliminated", no_price=float(no_price))
    try:
        px = float(no_price)
    except (TypeError, ValueError):
        return NoElimDecision(False, "bad_no_price")
    if not (0.0 < px < 1.0):
        return NoElimDecision(False, "bad_no_price")
    if px < float(cfg["min_no_price"]):
        return NoElimDecision(False, "no_price_low", no_price=px)
    if px > float(cfg["max_no_price"]):
        return NoElimDecision(False, "no_price_high", no_price=px)
    p_no = float(cfg["p_no_if_eliminated"])
    edge = p_no - px
    if edge < float(cfg["min_net_edge"]):
        return NoElimDecision(False, "net_edge_low", no_price=px, p_no=p_no, net_edge=edge)
    return NoElimDecision(True, "ok", no_price=px, p_no=p_no, net_edge=edge)


def stake_usd(strategy: dict[str, Any], *, edge: float | None = None) -> float:
    base = float(strategy.get("base_stake_usd", 10))
    mult = float((strategy.get("no_eliminated") or {}).get("stake_mult", 1.0))
    # Mild confidence bump when edge is large
    conf = 1.0
    if edge is not None and edge >= 0.05:
        conf = 1.5
    if edge is not None and edge >= 0.10:
        conf = 2.0
    return round(base * mult * conf, 2)
