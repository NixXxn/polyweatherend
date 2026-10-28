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
        "prefer_post_noon": bool(raw.get("prefer_post_noon", True)),
        "min_no_price": float(raw.get("min_no_price", 0.90)),
        "max_no_price": float(raw.get("max_no_price", 0.98)),
        "min_net_edge": float(raw.get("min_net_edge", 0.02)),
        "p_no_if_eliminated": float(raw.get("p_no_if_eliminated", 0.99)),
        "require_eliminated": bool(raw.get("require_eliminated", True)),
        "stake_mult": float(raw.get("stake_mult", 1.0)),
        "scalp_enabled": bool(raw.get("scalp_enabled", True)),
        "scalp_no_bid": float(raw.get("scalp_no_bid", 0.99)),
        "scalp_min_hold_sec": float(raw.get("scalp_min_hold_sec", 3.0)),
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
    # hours_to_noon: after noon is negative; window is hours <= max
    if float(hours) > float(cfg["max_hours_to_noon"]):
        return NoElimDecision(False, "outside_no_window", no_price=float(no_price))
    # Prefer post-noon entries (wallet median ≈ −1h); reject pre-noon when enabled
    if cfg.get("prefer_post_noon", True) and float(hours) > 0.0:
        return NoElimDecision(False, "before_noon", no_price=float(no_price))
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
    """Reference ticket at configured bankroll — never size up on weak elim."""
    base = float(strategy.get("base_stake_usd", 2))
    mult = float((strategy.get("no_eliminated") or {}).get("stake_mult", 1.0))
    conf = 1.0
    # Mild bump only on strong edge (solid elim residual); no 2× on weak
    if edge is not None and edge >= 0.06:
        conf = 1.25
    return round(base * mult * conf, 2)


def budget_ticket_usd(
    strategy: dict[str, Any],
    *,
    budget_usd: float,
    open_notional: float,
    edge: float | None = None,
    stake_multiplier: float = 1.0,
    max_deploy_frac: float = 0.75,
    max_per_fill_usd: float = 25.0,
    min_ticket_usd: float = 0.50,
) -> tuple[float, str]:
    """
    Size a ticket from budget with a 25% cash reserve.

    Max open notional = max_deploy_frac * budget (default 75%).
    Deployable = max(0, max_open - open_notional).
    Ticket scales with budget / reference bankroll and remaining capacity fraction.
    Hard-elim gates stay separate — this only sizes.
    """
    budget = max(0.0, float(budget_usd))
    if budget <= 0:
        return 0.0, "budget_zero"
    max_open = budget * float(max_deploy_frac)
    deployable = max(0.0, max_open - float(open_notional))
    if deployable < min_ticket_usd:
        return 0.0, "budget_fully_deployed"

    ref = float(strategy.get("bankroll_usd") or strategy.get("budget_usd") or 500.0)
    ref = max(ref, 1.0)
    base = stake_usd(strategy, edge=edge) * max(0.0, float(stake_multiplier))
    # Scale with configured budget vs reference bankroll
    scaled = base * (budget / ref)
    # Soft-scale with remaining deployable capacity (full size when book empty)
    rem_frac = deployable / max(max_open, 1e-9)
    size = scaled * max(0.35, min(1.0, rem_frac))
    size = min(size, deployable, float(max_per_fill_usd), max(budget * 0.05, min_ticket_usd))
    if size + 1e-9 < min_ticket_usd:
        if deployable + 1e-9 >= min_ticket_usd:
            size = min_ticket_usd
        else:
            return 0.0, "ticket_too_small"
    return round(size, 2), "ok"


def polymarket_event_url(
    *,
    city_slug: str,
    kind: str = "highest",
    end_date: str | None = None,
    event_slug: str | None = None,
    market_id: str | None = None,
) -> str:
    """Build a working Polymarket event URL for weather temp markets."""
    if event_slug:
        slug = str(event_slug).lstrip("/")
        if slug.startswith("event/"):
            slug = slug[len("event/") :]
        return f"https://polymarket.com/event/{slug}"
    day = None
    if end_date:
        try:
            day = datetime_from_iso_date(str(end_date)[:10])
        except ValueError:
            day = None
    if day is None:
        from datetime import date as date_cls

        day = date_cls.today()
    month = day.strftime("%B").lower()
    date_part = f"{month}-{day.day}-{day.year}"
    kind_word = "highest" if str(kind).lower().startswith("high") else "lowest"
    slug = f"{kind_word}-temperature-in-{city_slug}-on-{date_part}"
    # Non-mock condition IDs still deep-link via constructed city/day event
    _ = market_id
    return f"https://polymarket.com/event/{slug}"


def datetime_from_iso_date(s: str):
    from datetime import date

    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))
