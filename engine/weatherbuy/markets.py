"""Market discovery + book quotes (Gamma catalog + Polymarket CLOB)."""

from __future__ import annotations

import calendar
import hashlib
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .config import Settings
from .metar import DayState, hours_to_local_noon
from .strategy import polymarket_event_url

logger = logging.getLogger(__name__)

# Hard cap so a bad Gamma parse cannot stall the live loop on tens of thousands of books.
MAX_LIVE_MARKETS = 1200
QUOTE_WORKERS = 12

BUCKET_RE = re.compile(
    r"(?:highest|lowest|high|low|max|min).*?(?:temp|temperature).*?"
    r"(?:between\s+)?(-?\d+(?:\.\d+)?)\s*[°º]?\s*[CF]?\s*(?:-|to|–|—)\s*(-?\d+(?:\.\d+)?)",
    re.I,
)
CITY_SLUG_RE = re.compile(r"([a-z0-9-]+)", re.I)
EVENT_DATE_RE = re.compile(
    r"on[- ](?P<month>[a-z]+)[- ](?P<day>\d{1,2})(?:st|nd|rd|th)?[- ,]*(?P<year>\d{4})",
    re.I,
)
MONTH_NUM = {calendar.month_name[i].lower(): i for i in range(1, 13)}
MONTH_NUM.update({calendar.month_abbr[i].lower(): i for i in range(1, 13)})


@dataclass
class WeatherMarket:
    market_id: str
    question: str
    city_slug: str
    location_id: str
    kind: str  # highest | lowest
    lo: float | None
    hi: float | None
    yes_token_id: str
    no_token_id: str
    end_date: str | None = None
    timezone: str = "UTC"
    temperature_unit: str = "fahrenheit"
    event_slug: str | None = None
    polymarket_url: str | None = None
    neg_risk: bool = True
    tick_size: str = "0.01"


@dataclass
class BookQuote:
    market_id: str
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None
    no_mid: float | None
    depth_no_usd: float
    ts: str


@dataclass
class CityStatus:
    location_id: str
    city_slug: str
    icao: str
    station: str
    timezone: str
    badge: str  # ELIM | WATCH | BLOCKED | IDLE
    hours_to_noon: float | None
    tmax_so_far: float | None
    tmin_so_far: float | None
    metar_age_minutes: float | None
    eliminated: bool
    best_no: float | None
    edge: float | None
    markets: int
    reason: str = ""


def parse_event_date(*texts: str | None) -> date | None:
    """Parse 'on September 17, 2026' / slug 'on-september-17-2026' from Gamma fields."""
    blob = " ".join(str(t) for t in texts if t)
    if not blob:
        return None
    m = EVENT_DATE_RE.search(blob.replace("_", "-"))
    if not m:
        return None
    month = MONTH_NUM.get(m.group("month").lower())
    if not month:
        return None
    try:
        return date(int(m.group("year")), month, int(m.group("day")))
    except ValueError:
        return None


def is_temperature_question(question: str) -> bool:
    q = question.lower()
    return "temperature" in q or "°" in question


def city_local_trade_dates(tz_name: str, now: datetime | None = None) -> set[date]:
    now = now or datetime.now(timezone.utc)
    try:
        local = now.astimezone(ZoneInfo(tz_name)).date()
    except Exception:
        local = now.date()
    return {local - timedelta(days=1), local, local + timedelta(days=1)}


def _parse_bucket(question: str) -> tuple[str, float | None, float | None]:
    q = question.lower()
    kind = "highest" if ("highest" in q or "high temperature" in q or "max temp" in q) else "lowest"
    m = BUCKET_RE.search(question)
    if not m:
        # fallback: "72-73°F" style
        m2 = re.search(r"(-?\d+(?:\.\d+)?)\s*[-–—]\s*(-?\d+(?:\.\d+)?)\s*[°º]?\s*[CF]?", question)
        if m2:
            return kind, float(m2.group(1)), float(m2.group(2))
        return kind, None, None
    return kind, float(m.group(1)), float(m.group(2))


class MarketService:
    def __init__(self, settings: Settings, cities: list[dict[str, Any]]):
        self.settings = settings
        self.cities = cities
        self.by_slug = {c["polymarket_slug_city"]: c for c in cities}
        self.by_lid = {c["location_id"]: c for c in cities}
        self.markets: list[WeatherMarket] = []
        self.quotes: dict[str, BookQuote] = {}
        self._epoch = 0
        self._client = httpx.Client(timeout=30.0, follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    def refresh_markets(self, force_new: bool = False) -> list[WeatherMarket]:
        if self.settings.mock_markets:
            if force_new:
                self._epoch += 1
            self.markets = self._mock_markets()
            return self.markets
        # Live path: Gamma discovery + CLOB books/orders only
        try:
            self.markets = self._fetch_gamma_weather()
            by_city: dict[str, list[WeatherMarket]] = {}
            for m in self.markets:
                by_city.setdefault(m.location_id, []).append(m)
            capped: list[WeatherMarket] = []
            per_city = 24
            for rows in by_city.values():
                capped.extend(rows[:per_city])
            if len(capped) != len(self.markets):
                logger.info(
                    "Gamma per-city cap %d → %d markets (%d cities)",
                    len(self.markets),
                    len(capped),
                    len(by_city),
                )
            self.markets = capped
            if len(self.markets) > MAX_LIVE_MARKETS:
                logger.error(
                    "Gamma matched %d markets — capping to %d",
                    len(self.markets),
                    MAX_LIVE_MARKETS,
                )
                self.markets = self.markets[:MAX_LIVE_MARKETS]
            if self.markets:
                return self.markets
            logger.warning("Gamma returned no matched weather markets")
        except Exception as e:
            logger.exception("Gamma catalog failed: %s", e)
        logger.warning(
            "No Gamma weather markets found. "
            "Check POLY_GAMMA_URL / city slugs, or set MOCK_MARKETS=true for local paper."
        )
        self.markets = []
        return self.markets

    def _fetch_gamma_weather(self) -> list[WeatherMarket]:
        """Discover today's temperature bucket markets via Polymarket Gamma API."""
        base = self.settings.poly_gamma_url.rstrip("/")
        out: list[WeatherMarket] = []
        seen: set[str] = set()
        skipped = {"not_temp": 0, "city": 0, "date": 0, "closed": 0, "tokens": 0}

        def add_item(item: dict, city: dict, slug: str, event_slug: str | None = None) -> None:
            m = self._gamma_to_market(item, city, slug, event_slug=event_slug, skipped=skipped)
            if m and m.market_id not in seen:
                seen.add(m.market_id)
                out.append(m)

        for slug, city in self.by_slug.items():
            # Direct event slug for today (and tomorrow) — primary live path
            try:
                local = datetime.now(ZoneInfo(city["timezone"])).date()
                days = [local]
                for day in days:
                    month = day.strftime("%B").lower()
                    for kind in ("highest", "lowest"):
                        event_slug = f"{kind}-temperature-in-{slug}-on-{month}-{day.day}-{day.year}"
                        r = self._client.get(
                            f"{base}/events", params={"slug": event_slug}, timeout=15.0
                        )
                        if r.status_code >= 400:
                            continue
                        data = r.json()
                        events = data if isinstance(data, list) else [data]
                        for ev in events:
                            if not isinstance(ev, dict):
                                continue
                            nested = ev.get("markets") or []
                            if nested:
                                for item in nested:
                                    if isinstance(item, dict):
                                        add_item(item, city, slug, event_slug=event_slug)
                            else:
                                add_item(ev, city, slug, event_slug=event_slug)
            except Exception as e:
                logger.debug("gamma event slug fail %s: %s", slug, e)

            # Narrow search fallback — still city+date gated in _gamma_to_market
            queries = [
                f"highest temperature in {slug.replace('-', ' ')}",
                f"lowest temperature in {slug.replace('-', ' ')}",
            ]
            for q in queries:
                try:
                    r = self._client.get(
                        f"{base}/public-search",
                        params={"q": q, "limit_per_type": 8},
                        timeout=20.0,
                    )
                    if r.status_code >= 400:
                        continue
                    data = r.json()
                    items = self._gamma_items(data)
                    for item in items:
                        add_item(item, city, slug)
                except Exception as e:
                    logger.debug("gamma query fail %s: %s", q, e)

        logger.info(
            "Gamma weather markets matched: %d skipped=%s cities=%d",
            len(out),
            skipped,
            len(self.by_slug),
        )
        return out

    def _gamma_items(self, data: Any) -> list[dict]:
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if not isinstance(data, dict):
            return []
        # Prefer events (public-search) over a top-level markets dump.
        for key in ("events", "markets", "data"):
            raw = data.get(key)
            if isinstance(raw, list):
                out: list[dict] = []
                for row in raw:
                    if not isinstance(row, dict):
                        continue
                    nested = [m for m in (row.get("markets") or []) if isinstance(m, dict)]
                    if nested:
                        parent_slug = row.get("slug") or row.get("ticker")
                        for m in nested:
                            if parent_slug and not m.get("eventSlug") and not m.get("event_slug"):
                                m = {**m, "eventSlug": parent_slug}
                            out.append(m)
                    elif "question" in row or "clobTokenIds" in row or "tokens" in row:
                        out.append(row)
                return out
        return []

    def _gamma_to_market(
        self,
        item: dict,
        city: dict,
        slug: str,
        event_slug: str | None = None,
        skipped: dict[str, int] | None = None,
    ) -> WeatherMarket | None:
        def bump(reason: str) -> None:
            if skipped is not None:
                skipped[reason] = skipped.get(reason, 0) + 1

        if item.get("closed") is True or item.get("active") is False:
            bump("closed")
            return None
        q = str(item.get("question") or item.get("title") or "")
        if not is_temperature_question(q):
            bump("not_temp")
            return None
        matched = self._match_city_slug(q, item)
        if matched is None and event_slug and slug.replace("_", "-") in str(event_slug).replace("_", "-"):
            matched = slug
        if matched is None:
            bump("city")
            return None
        if matched != slug:
            if matched not in self.by_slug:
                bump("city")
                return None
            city = self.by_slug[matched]
            slug = matched
        ev = event_slug or item.get("slug") or item.get("eventSlug") or item.get("event_slug")
        ev_date = parse_event_date(q, str(ev) if ev else None, item.get("endDate"), item.get("end_date"))
        allowed = city_local_trade_dates(city.get("timezone") or "UTC")
        if ev_date is None or ev_date not in allowed:
            bump("date")
            return None
        kind, lo, hi = _parse_bucket(q)
        yes_id, no_id = self._gamma_token_ids(item)
        if not yes_id or not no_id or yes_id.startswith("None"):
            bump("tokens")
            return None
        mid = str(item.get("conditionId") or item.get("condition_id") or item.get("id") or "")
        if not mid:
            return None
        end_date = item.get("endDate") or item.get("end_date")
        tick = str(item.get("minimum_tick_size") or item.get("orderPriceMinTickSize") or "0.01")
        neg = item.get("negRisk")
        if neg is None:
            neg = item.get("neg_risk")
        if neg is None:
            neg = True
        return WeatherMarket(
            market_id=mid,
            question=q,
            city_slug=slug,
            location_id=city["location_id"],
            kind=kind,
            lo=lo,
            hi=hi,
            yes_token_id=yes_id,
            no_token_id=no_id,
            end_date=str(end_date)[:10] if end_date else None,
            timezone=city["timezone"],
            temperature_unit=city.get("temperature_unit", "fahrenheit"),
            event_slug=str(ev) if ev else None,
            polymarket_url=polymarket_event_url(
                city_slug=slug,
                kind=kind,
                end_date=str(end_date)[:10] if end_date else None,
                event_slug=str(ev) if ev else None,
                market_id=mid,
            ),
            neg_risk=bool(neg),
            tick_size=tick,
        )

    def _gamma_token_ids(self, item: dict) -> tuple[str, str]:
        yes_id, no_id = "", ""
        # clobTokenIds often JSON string "[yes, no]"
        raw = item.get("clobTokenIds") or item.get("clob_token_ids")
        if isinstance(raw, str):
            try:
                import json

                arr = json.loads(raw)
                if isinstance(arr, list) and len(arr) >= 2:
                    yes_id, no_id = str(arr[0]), str(arr[1])
            except Exception:
                pass
        elif isinstance(raw, list) and len(raw) >= 2:
            yes_id, no_id = str(raw[0]), str(raw[1])
        tokens = item.get("tokens") or []
        if isinstance(tokens, list):
            for t in tokens:
                if not isinstance(t, dict):
                    continue
                name = str(t.get("outcome") or t.get("name") or "").lower()
                tid = str(t.get("token_id") or t.get("tokenId") or "")
                if name in {"yes", "y"} and tid:
                    yes_id = tid
                if name in {"no", "n"} and tid:
                    no_id = tid
        outcomes = item.get("outcomes")
        if (not yes_id or not no_id) and isinstance(outcomes, str):
            try:
                import json

                names = json.loads(outcomes)
                ids_raw = item.get("clobTokenIds")
                ids = json.loads(ids_raw) if isinstance(ids_raw, str) else ids_raw
                if isinstance(names, list) and isinstance(ids, list) and len(names) == len(ids):
                    for name, tid in zip(names, ids):
                        n = str(name).lower()
                        if n == "yes":
                            yes_id = str(tid)
                        if n == "no":
                            no_id = str(tid)
            except Exception:
                pass
        return yes_id, no_id

    def _match_city_slug(self, question: str, item: dict) -> str | None:
        hay = " ".join(
            [
                question.lower(),
                str(item.get("slug") or "").lower(),
                str(item.get("event_slug") or "").lower(),
                str(item.get("eventSlug") or "").lower(),
            ]
        )
        hay_norm = re.sub(r"[^a-z0-9]+", " ", hay)
        aliases = {
            "nyc": ("new york city", "new york"),
        }
        # Longest slug first so 'new-york-city' wins over 'york'
        for slug in sorted(self.by_slug, key=len, reverse=True):
            needle = slug.replace("-", " ")
            if re.search(rf"(?:^|[\s\-_/,]){re.escape(slug)}(?:$|[\s\-_/,])", hay):
                return slug
            if re.search(rf"(?:^|\s){re.escape(needle)}(?:$|\s)", hay_norm):
                return slug
            for alias in aliases.get(slug, ()):
                if re.search(rf"(?:^|\s){re.escape(alias)}(?:$|\s)", hay_norm):
                    return slug
        return None

    def _mock_markets(self) -> list[WeatherMarket]:
        """Synthetic buckets near each city's timezone for paper/shadow testing."""
        out: list[WeatherMarket] = []
        now = datetime.now(timezone.utc)
        for city in self.cities[:20]:  # keep mock loop light
            slug = city["polymarket_slug_city"]
            lid = city["location_id"]
            local = now.astimezone(ZoneInfo(city["timezone"]))
            day = local.date().isoformat()
            # Three buckets: below / at / above a placeholder — elim can hit the low ones
            for i, (lo, hi) in enumerate([(50, 51), (60, 61), (70, 71)] if city.get("temperature_unit", "").startswith("f") else [(10, 11), (20, 21), (30, 31)]):
                mid = f"mock-{lid}-{day}-{self._epoch}-{i}"
                h = hashlib.sha1(mid.encode()).hexdigest()[:12]
                pm_url = polymarket_event_url(
                    city_slug=slug, kind="highest", end_date=day, market_id=mid
                )
                out.append(
                    WeatherMarket(
                        market_id=mid,
                        question=f"Highest temperature in {slug} on {day}: {lo}-{hi}°",
                        city_slug=slug,
                        location_id=lid,
                        kind="highest",
                        lo=float(lo),
                        hi=float(hi),
                        yes_token_id=f"yes-{h}",
                        no_token_id=f"no-{h}",
                        end_date=day,
                        timezone=city["timezone"],
                        temperature_unit=city.get("temperature_unit", "fahrenheit"),
                        polymarket_url=pm_url,
                    )
                )
        return out

    def refresh_quotes(self, day_states: dict[str, DayState]) -> dict[str, BookQuote]:
        quotes: dict[str, BookQuote] = {}
        if self.settings.mock_markets:
            for m in self.markets:
                quotes[m.market_id] = self._mock_quote(m, day_states.get(m.location_id))
            self.quotes = quotes
            return quotes

        host = self.settings.poly_clob_host.rstrip("/")
        fails = 0
        t0 = datetime.now(timezone.utc)
        local = threading.local()

        def client() -> httpx.Client:
            c = getattr(local, "http", None)
            if c is None:
                local.http = httpx.Client(timeout=8.0, follow_redirects=True)
                c = local.http
            return c

        def one(m: WeatherMarket) -> tuple[str, BookQuote, bool]:
            try:
                return m.market_id, self._fetch_clob_quote(m, http=client()), False
            except Exception as e:
                logger.debug("CLOB book fail %s @ %s: %s", m.market_id[:18], host, e)
                empty = BookQuote(
                    market_id=m.market_id,
                    yes_bid=None,
                    yes_ask=None,
                    no_bid=None,
                    no_ask=None,
                    no_mid=None,
                    depth_no_usd=0.0,
                    ts=datetime.now(timezone.utc).isoformat(),
                )
                return m.market_id, empty, True

        workers = min(QUOTE_WORKERS, max(1, len(self.markets)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(one, m) for m in self.markets]
            for fut in as_completed(futs):
                mid, quote, failed = fut.result()
                quotes[mid] = quote
                if failed:
                    fails += 1

        elapsed_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
        priced = sum(1 for q in quotes.values() if q.no_ask is not None or q.no_mid is not None)
        logger.info(
            "CLOB quotes markets=%d priced=%d fail=%d elapsed_ms=%.0f",
            len(self.markets),
            priced,
            fails,
            elapsed_ms,
        )
        self.quotes = quotes
        return quotes

    def _fetch_clob_quote(self, m: WeatherMarket, http: httpx.Client | None = None) -> BookQuote:
        """Public CLOB book for NO token (and YES for complement) at clob.polymarket.com."""
        host = self.settings.poly_clob_host.rstrip("/")
        http = http or self._client
        no_ask = no_bid = yes_ask = yes_bid = None
        depth = 0.0
        sides = (("no", m.no_token_id),)
        if not m.no_token_id:
            sides = (("yes", m.yes_token_id),)
        for side_name, tid in sides:
            if not tid or str(tid).startswith(("yes-", "no-")):
                continue
            r = http.get(f"{host}/book", params={"token_id": tid}, timeout=8.0)
            if r.status_code >= 400:
                raise RuntimeError(f"CLOB book HTTP {r.status_code} for {tid[:16]}…")
            book = r.json()
            asks = book.get("asks") or []
            bids = book.get("bids") or []
            best_ask = min(float(a["price"]) for a in asks) if asks else None
            best_bid = max(float(b["price"]) for b in bids) if bids else None
            if side_name == "no":
                no_ask, no_bid = best_ask, best_bid
                if asks:
                    depth = sum(
                        float(a.get("size") or 0) * float(a.get("price") or 0) for a in asks[:5]
                    )
            else:
                yes_ask, yes_bid = best_ask, best_bid
        if no_ask is None and yes_bid is not None:
            no_ask = max(0.01, min(0.99, 1.0 - float(yes_bid)))
        if no_bid is None and yes_ask is not None:
            no_bid = max(0.01, min(0.99, 1.0 - float(yes_ask)))
        mid = None
        if no_ask is not None and no_bid is not None:
            mid = (float(no_ask) + float(no_bid)) / 2
        elif no_ask is not None:
            mid = float(no_ask)
        return BookQuote(
            market_id=m.market_id,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            no_mid=mid,
            depth_no_usd=float(depth or 50),
            ts=datetime.now(timezone.utc).isoformat(),
        )

    def _mock_quote(self, m: WeatherMarket, st: DayState | None) -> BookQuote:
        # Elim residual YES ~2–10¢ ⇒ NO in densest wallet band ~0.90–0.97
        eliminated = False
        if st and st.tmax_so_far is not None and m.hi is not None and m.kind == "highest":
            eliminated = st.tmax_so_far > m.hi
        if st and st.tmin_so_far is not None and m.lo is not None and m.kind == "lowest":
            eliminated = st.tmin_so_far < m.lo
        if eliminated:
            digest = int(hashlib.sha1(m.market_id.encode()).hexdigest()[:8], 16)
            # Spread across 0.90–0.969 (avoid defaulting to 1–2¢ residual wins)
            no_ask = 0.90 + (digest % 70) / 1000.0
            yes_ask = max(0.01, min(0.12, 1.0 - no_ask))
        else:
            yes_ask = 0.45
            no_ask = 0.55
        no_bid = max(0.01, no_ask - 0.008)
        return BookQuote(
            market_id=m.market_id,
            yes_bid=max(0.01, yes_ask - 0.02),
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            no_mid=(no_ask + no_bid) / 2,
            depth_no_usd=150.0,
            ts=datetime.now(timezone.utc).isoformat(),
        )