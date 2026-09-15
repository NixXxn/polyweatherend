"""ULL decision loop: METAR → elim gate → taker BUY NO (+ paper settle / skips)."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from .config import Settings, load_cities, load_strategy
from .markets import CityStatus, MarketService
from .metar import (
    day_state,
    fetch_asos_recent,
    hours_to_local_noon,
    is_eliminated_highest,
    is_eliminated_lowest,
    mock_day_state,
)
from .risk import RiskGate
from .store import Store
from .strategy import evaluate_no_eliminated, no_eliminated_cfg, stake_usd
from .venue import Venue

logger = logging.getLogger(__name__)


class ExecEngine:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.strategy = load_strategy(self.settings)
        self.cities = load_cities(self.settings)
        self.no_cfg = no_eliminated_cfg(self.strategy)
        self.store = Store(
            self.settings.redis_url,
            self.strategy.get("paths", {}).get("ledger_dir", "data/ledger"),
        )
        self.risk = RiskGate(self.strategy)
        if self.settings.kill_switch_default:
            self.risk.kill("env_default")
        self.markets = MarketService(self.settings, self.cities)
        self.venue = Venue(self.settings)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._asos_cache: dict[str, list] = {}
        self._day_states: dict[str, Any] = {}
        self._open: dict[str, dict[str, Any]] = {}
        self._last_metar_ts: str | None = None
        self._last_book_ts: str | None = None
        self._tick = 0
        self._started = datetime.now(timezone.utc).isoformat()
        paper = dict(self.strategy.get("paper") or {})
        self._paper_settle_sec = float(paper.get("settle_after_sec", 35))
        self._rotate_sec = float(paper.get("rotate_markets_sec", 70))
        self._last_rotate = 0.0
        self._wins = 0
        self._losses = 0
        self._use_mock_metar = bool(paper.get("mock_metar_on_failure", True))

    def start_background(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.run_forever, name="exec-loop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.markets.close()
        self.venue.close()

    def run_forever(self) -> None:
        loop = self.strategy.get("loop") or {}
        metar_every = float(loop.get("metar_poll_sec", 30))
        book_every = float(loop.get("book_poll_sec", 5))
        market_every = float(loop.get("market_refresh_sec", 120))
        last_metar = 0.0
        last_book = 0.0
        last_markets = 0.0
        logger.info(
            "ExecEngine started mode=%s live=%s mock=%s cities=%d",
            self.settings.trading_mode,
            self.settings.is_live,
            self.settings.mock_markets,
            len(self.cities),
        )
        self.markets.refresh_markets()
        self._publish()
        while not self._stop.is_set():
            now = time.time()
            try:
                rotate = self.settings.mock_markets and (now - self._last_rotate >= self._rotate_sec)
                if now - last_markets >= market_every or rotate:
                    self.markets.refresh_markets(force_new=rotate)
                    last_markets = now
                    if rotate:
                        self._last_rotate = now
                if now - last_metar >= metar_every:
                    self._refresh_metar()
                    last_metar = now
                if now - last_book >= book_every:
                    self.markets.refresh_quotes(self._day_states)
                    self._last_book_ts = datetime.now(timezone.utc).isoformat()
                    self._settle_paper()
                    self._decide_and_trade()
                    last_book = now
                self._publish()
            except Exception:
                logger.exception("loop error")
            self._stop.wait(0.5)

    def _refresh_metar(self) -> None:
        def one(city: dict[str, Any]) -> tuple[str, Any | None, str | None]:
            station = city.get("iem_station") or city.get("icao", "")[-3:]
            lid = city["location_id"]
            try:
                obs = fetch_asos_recent(station, hours=36, timeout=25.0)
                st = day_state(
                    obs,
                    tz_name=city["timezone"],
                    unit=city.get("temperature_unit", "fahrenheit"),
                    station=station,
                )
                if st.obs_age_minutes is None and self._use_mock_metar:
                    return lid, (obs, mock_day_state(city)), "empty_obs_mock"
                return lid, (obs, st), None
            except Exception as e:
                if self._use_mock_metar and not self.settings.is_live:
                    return lid, ([], mock_day_state(city)), f"mock:{e}"
                return lid, None, str(e)

        workers = 3 if self.settings.mock_markets else 4
        with ThreadPoolExecutor(max_workers=min(workers, max(2, len(self.cities)))) as pool:
            futs = [pool.submit(one, city) for city in self.cities]
            for fut in as_completed(futs):
                lid, payload, err = fut.result()
                if err and not (err.startswith("mock") or err == "empty_obs_mock"):
                    logger.warning("METAR %s failed: %s", lid, err)
                if payload is None:
                    continue
                obs, st = payload
                self._asos_cache[lid] = obs
                self._day_states[lid] = st
                if err and err.startswith("mock"):
                    logger.info("METAR %s using mock fallback", lid)
        self._last_metar_ts = datetime.now(timezone.utc).isoformat()

    def _skip(
        self,
        *,
        city: dict[str, Any],
        market: Any,
        reason: str,
        no_price: float | None = None,
        edge: float | None = None,
    ) -> None:
        self.store.append_skip(
            {
                "skip_id": f"skip-{uuid.uuid4().hex[:10]}",
                "ts": datetime.now(timezone.utc).isoformat(),
                "market_id": getattr(market, "market_id", None),
                "location_id": city["location_id"],
                "city": city.get("polymarket_slug_city"),
                "reason": reason,
                "no_price": no_price,
                "edge": edge,
                "question": getattr(market, "question", ""),
                "mode": "live" if self.settings.is_live else "paper",
            }
        )

    def _decide_and_trade(self) -> None:
        self._tick += 1
        city_rows: list[dict[str, Any]] = []
        by_lid: dict[str, list] = {}
        for m in self.markets.markets:
            by_lid.setdefault(m.location_id, []).append(m)

        for city in self.cities:
            lid = city["location_id"]
            st = self._day_states.get(lid)
            hours = hours_to_local_noon(city["timezone"])
            markets = by_lid.get(lid, [])
            best_no = None
            best_edge = None
            eliminated_any = False
            badge = "IDLE"
            reason = "no_markets"

            for m in markets:
                q = self.markets.quotes.get(m.market_id)
                no_px = (q.no_ask if q and q.no_ask is not None else None) or (q.no_mid if q else None)
                elim = False
                if st:
                    if m.kind == "highest":
                        elim = is_eliminated_highest(tmax_so_far=st.tmax_so_far, lo=m.lo, hi=m.hi)
                    else:
                        elim = is_eliminated_lowest(tmin_so_far=st.tmin_so_far, lo=m.lo, hi=m.hi)
                eliminated_any = eliminated_any or elim

                if no_px is None:
                    continue
                decision = evaluate_no_eliminated(
                    hours=hours,
                    eliminated=elim,
                    no_price=float(no_px),
                    cfg=self.no_cfg,
                )
                if decision.net_edge is not None and (best_edge is None or decision.net_edge > best_edge):
                    best_edge = decision.net_edge
                    best_no = decision.no_price

                if decision.ok:
                    badge = "ELIM"
                    reason = "ok"
                    self._try_enter(city, m, q, decision, st)
                elif elim and hours <= self.no_cfg["max_hours_to_noon"]:
                    if badge != "ELIM":
                        badge = "WATCH"
                        reason = decision.reason
                    if decision.reason not in {"already_open", "already_traded_today"}:
                        self._skip(
                            city=city,
                            market=m,
                            reason=decision.reason,
                            no_price=float(no_px),
                            edge=decision.net_edge,
                        )
                elif hours <= self.no_cfg["max_hours_to_noon"]:
                    if badge == "IDLE":
                        badge = "WATCH"
                        reason = decision.reason
                else:
                    reason = decision.reason

            if self.risk.state.killed:
                badge = "BLOCKED"
                reason = f"killed:{self.risk.state.kill_reason}"

            row = CityStatus(
                location_id=lid,
                city_slug=city["polymarket_slug_city"],
                icao=city.get("icao", ""),
                station=city.get("iem_station", ""),
                timezone=city["timezone"],
                badge=badge,
                hours_to_noon=round(hours, 2),
                tmax_so_far=None if not st else st.tmax_so_far,
                tmin_so_far=None if not st else st.tmin_so_far,
                metar_age_minutes=None if not st else st.obs_age_minutes,
                eliminated=eliminated_any,
                best_no=best_no,
                edge=best_edge,
                markets=len(markets),
                reason=reason,
            )
            city_rows.append(asdict(row))

        self.store.set_cities(city_rows)

    def _try_enter(self, city: dict, market, quote, decision, st) -> None:
        if market.market_id in self._open:
            self._skip(
                city=city,
                market=market,
                reason="already_open",
                no_price=decision.no_price,
                edge=decision.net_edge,
            )
            return
        size = stake_usd(self.strategy, edge=decision.net_edge) * self.risk.state.stake_multiplier
        ask = float(quote.no_ask or quote.no_mid or decision.no_price)
        age = None if not st else st.obs_age_minutes
        # Paper/mock: don't stall on slightly stale IEM ages
        if not self.settings.is_live and age is not None and age > self.risk.max_metar_age_minutes:
            age = max(0.0, self.risk.max_metar_age_minutes - 1.0)
        ok, why = self.risk.allow(
            market_id=market.market_id,
            location_id=city["location_id"],
            size_usd=size,
            metar_age_minutes=age,
            venue_error_rate=self.venue.error_rate,
            already_open=market.market_id in self._open,
        )
        if not ok:
            self._skip(
                city=city,
                market=market,
                reason=why,
                no_price=decision.no_price,
                edge=decision.net_edge,
            )
            return
        fill = self.venue.buy_no_taker(
            market_id=market.market_id,
            location_id=city["location_id"],
            no_token_id=market.no_token_id,
            ask=ask,
            size_usd=size,
            order_type=str((self.strategy.get("execution") or {}).get("order_type", "FOK")),
            question=market.question,
            edge=decision.net_edge,
            depth_usd=float(quote.depth_no_usd or 0),
        )
        self.store.append_fill(fill)
        if fill.status in {"filled", "submitted"}:
            self.risk.register_fill(market.market_id, city["location_id"], fill.size_usd)
            pos = {
                "market_id": market.market_id,
                "location_id": city["location_id"],
                "city": city["polymarket_slug_city"],
                "side": "BUY_NO",
                "entry_price": fill.price,
                "size_usd": fill.size_usd,
                "shares": fill.shares,
                "mode": fill.mode,
                "opened_at": fill.ts,
                "question": market.question,
                "status": "open",
                "mark_no": ask,
                "unrealized_pnl": 0.0,
                "edge": decision.net_edge,
                "fill_id": fill.fill_id,
                "kind": market.kind,
                "lo": market.lo,
                "hi": market.hi,
            }
            self._open[market.market_id] = pos

    def _settle_paper(self) -> None:
        if self.settings.is_live:
            return
        now = datetime.now(timezone.utc)
        done: list[str] = []
        for mid, pos in list(self._open.items()):
            try:
                opened = datetime.fromisoformat(str(pos["opened_at"]).replace("Z", "+00:00"))
            except Exception:
                opened = now
            hold = (now - opened).total_seconds()
            if hold < self._paper_settle_sec:
                continue
            st = self._day_states.get(pos["location_id"])
            still_elim = False
            if st is not None:
                if pos.get("kind") == "lowest":
                    still_elim = is_eliminated_lowest(
                        tmin_so_far=st.tmin_so_far, lo=pos.get("lo"), hi=pos.get("hi")
                    )
                else:
                    still_elim = is_eliminated_highest(
                        tmax_so_far=st.tmax_so_far, lo=pos.get("lo"), hi=pos.get("hi")
                    )
            exit_price = 1.0 if still_elim else 0.0
            pnl = (exit_price - float(pos["entry_price"])) * float(pos["shares"])
            result = "win" if pnl >= 0 else "loss"
            if result == "win":
                self._wins += 1
            else:
                self._losses += 1
            self.risk.state.daily_realized_pnl += pnl
            self.risk.state.open_locations.discard(pos["location_id"])
            self.store.append_settlement(
                {
                    "settlement_id": f"set-{uuid.uuid4().hex[:10]}",
                    "ts": now.isoformat(),
                    "fill_id": pos.get("fill_id"),
                    "market_id": mid,
                    "location_id": pos["location_id"],
                    "city": pos.get("city"),
                    "side": "BUY_NO",
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_price,
                    "size_usd": pos["size_usd"],
                    "shares": pos["shares"],
                    "pnl_usd": round(pnl, 4),
                    "hold_sec": round(hold, 1),
                    "edge": pos.get("edge"),
                    "mode": pos.get("mode", "paper"),
                    "status": "settled",
                    "result": result,
                    "question": pos.get("question"),
                    "reason": "still_eliminated" if still_elim else "bucket_survived",
                }
            )
            done.append(mid)
        for mid in done:
            self._open.pop(mid, None)

    def _publish(self) -> None:
        positions = []
        unreal = 0.0
        for mid, pos in self._open.items():
            q = self.markets.quotes.get(mid)
            mark = float(q.no_mid or q.no_bid or pos["entry_price"]) if q else pos["entry_price"]
            upnl = (mark - pos["entry_price"]) * pos["shares"]
            positions.append({**pos, "mark_no": mark, "unrealized_pnl": round(upnl, 4)})
            unreal += upnl

        worst_age = None
        for st in self._day_states.values():
            if st.obs_age_minutes is None:
                continue
            worst_age = st.obs_age_minutes if worst_age is None else max(worst_age, st.obs_age_minutes)

        snap = self.store.snapshot()
        status = {
            "armed": not self.risk.state.killed and self.risk.state.sleeve_no_eliminated,
            "killed": self.risk.state.killed,
            "kill_reason": self.risk.state.kill_reason,
            "mode": "live" if self.settings.is_live else "paper",
            "mock_markets": self.settings.mock_markets or not self.settings.pmxt_api_key,
            "open_no_count": len(positions),
            "pnl_today": round(self.risk.state.daily_realized_pnl + unreal, 2),
            "realized_pnl": round(self.risk.state.daily_realized_pnl, 2),
            "unrealized_pnl": round(unreal, 2),
            "wins": self._wins,
            "losses": self._losses,
            "metar_age_worst_min": None if worst_age is None else round(worst_age, 1),
            "last_metar_ts": self._last_metar_ts,
            "last_book_ts": self._last_book_ts,
            "venue_error_rate": round(self.venue.error_rate, 3),
            "tick": self._tick,
            "started_at": self._started,
            "markets_tracked": len(self.markets.markets),
            "cities_tracked": len(self.cities),
            "fills_count": len(snap.get("fills") or []),
            "skips_count": len(snap.get("skips") or []),
            "settlements_count": len(snap.get("settlements") or []),
        }
        self.store.set_status(status)
        self.store.set_positions(positions)
        self.store.set_pnl(
            {
                "realized": status["realized_pnl"],
                "unrealized": status["unrealized_pnl"],
                "today": status["pnl_today"],
                "wins": self._wins,
                "losses": self._losses,
            }
        )
        self.store.set_controls(
            {
                **self.risk.snapshot(),
                "trading_mode": status["mode"],
                "live_trading_flag": self.settings.live_trading,
            }
        )

    def kill(self, reason: str = "manual") -> None:
        self.risk.kill(reason)
        self._publish()

    def arm(self) -> None:
        self.risk.arm()
        self._publish()

    def set_sleeve(self, enabled: bool) -> None:
        self.risk.state.sleeve_no_eliminated = bool(enabled)
        self._publish()

    def set_stake_mult(self, mult: float) -> None:
        self.risk.state.stake_multiplier = max(0.0, min(5.0, float(mult)))
        self._publish()
