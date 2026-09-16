"""Risk limits + kill switches."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any


@dataclass
class RiskState:
    killed: bool = False
    sleeve_no_eliminated: bool = True
    stake_multiplier: float = 1.0
    day: str = field(default_factory=lambda: date.today().isoformat())
    markets_today: set[str] = field(default_factory=set)
    open_locations: set[str] = field(default_factory=set)
    daily_notional: float = 0.0
    daily_realized_pnl: float = 0.0
    kill_reason: str = ""

    def reset_if_new_day(self) -> None:
        today = date.today().isoformat()
        if today != self.day:
            self.day = today
            self.markets_today.clear()
            self.daily_notional = 0.0
            self.daily_realized_pnl = 0.0


class RiskGate:
    def __init__(self, strategy: dict[str, Any]):
        raw = dict(strategy.get("risk") or {})
        self.max_markets_per_day = int(raw.get("max_markets_per_day", 40))
        self.max_markets_concurrent = int(raw.get("max_markets_concurrent", 25))
        self.max_daily_notional_usd = float(raw.get("max_daily_notional_usd", 500))
        self.max_per_fill_usd = float(raw.get("max_per_fill_usd", 50))
        self.max_daily_loss_usd = float(raw.get("max_daily_loss_usd", 100))
        self.max_metar_age_minutes = float(raw.get("max_metar_age_minutes", 45))
        self.max_venue_error_rate = float(raw.get("max_venue_error_rate", 0.25))
        self.max_deploy_frac = float(raw.get("max_deploy_frac", 0.75))
        self.state = RiskState()

    def allow(
        self,
        *,
        market_id: str,
        location_id: str,
        size_usd: float,
        metar_age_minutes: float | None,
        venue_error_rate: float,
        already_open: bool,
        open_notional: float = 0.0,
        budget_usd: float | None = None,
    ) -> tuple[bool, str]:
        self.state.reset_if_new_day()
        if self.state.killed:
            return False, f"killed:{self.state.kill_reason or 'manual'}"
        if not self.state.sleeve_no_eliminated:
            return False, "sleeve_disabled"
        if already_open:
            return False, "already_open"
        if market_id in self.state.markets_today:
            return False, "already_traded_today"
        if len(self.state.markets_today) >= self.max_markets_per_day:
            return False, "max_markets_per_day"
        if len(self.state.open_locations) >= self.max_markets_concurrent and location_id not in self.state.open_locations:
            return False, "max_concurrent"
        if size_usd > self.max_per_fill_usd:
            return False, "max_per_fill"
        if self.state.daily_notional + size_usd > self.max_daily_notional_usd:
            return False, "max_daily_notional"
        if budget_usd is not None and budget_usd > 0:
            max_open = float(budget_usd) * self.max_deploy_frac
            if float(open_notional) + float(size_usd) > max_open + 1e-9:
                return False, "budget_deploy_cap"
        if self.state.daily_realized_pnl <= -abs(self.max_daily_loss_usd):
            self.kill("daily_loss")
            return False, "daily_loss"
        if metar_age_minutes is None or metar_age_minutes > self.max_metar_age_minutes:
            return False, "metar_stale"
        if venue_error_rate > self.max_venue_error_rate:
            self.kill("venue_error_rate")
            return False, "venue_error_rate"
        return True, "ok"

    def register_fill(self, market_id: str, location_id: str, size_usd: float) -> None:
        self.state.markets_today.add(market_id)
        self.state.open_locations.add(location_id)
        self.state.daily_notional += size_usd

    def kill(self, reason: str = "manual") -> None:
        self.state.killed = True
        self.state.kill_reason = reason

    def arm(self) -> None:
        self.state.killed = False
        self.state.kill_reason = ""

    def snapshot(self) -> dict[str, Any]:
        s = self.state
        return {
            "killed": s.killed,
            "kill_reason": s.kill_reason,
            "sleeve_no_eliminated": s.sleeve_no_eliminated,
            "stake_multiplier": s.stake_multiplier,
            "day": s.day,
            "markets_today": len(s.markets_today),
            "open_locations": len(s.open_locations),
            "daily_notional": round(s.daily_notional, 2),
            "daily_realized_pnl": round(s.daily_realized_pnl, 2),
            "limits": {
                "max_markets_per_day": self.max_markets_per_day,
                "max_markets_concurrent": self.max_markets_concurrent,
                "max_daily_notional_usd": self.max_daily_notional_usd,
                "max_per_fill_usd": self.max_per_fill_usd,
                "max_daily_loss_usd": self.max_daily_loss_usd,
                "max_metar_age_minutes": self.max_metar_age_minutes,
                "max_deploy_frac": self.max_deploy_frac,
            },
            "ts": datetime.now(timezone.utc).isoformat(),
        }
