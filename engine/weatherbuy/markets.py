"""Market discovery + book quotes (Polymarket CLOB or mock)."""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .config import CLOB_URL, Settings
from .metar import DayState
from .strategy import polymarket_event_url

logger = logging.getLogger(__name__)

BUCKET_RE = re.compile(
    r"(?:highest|lowest|high|low|max|min).*?(?:temp|temperature).*?"
    r"(?:between\s+)?(-?\d+(?:\.\d+)?)\s*[°º]?\s*[CF]?\s*(?:-|to|–|—)\s*(-?\d+(?:\.\d+)?)",
    re.I,
)
RANGE_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*[-–—]\s*(-?\d+(?:\.\d+)?)\s*(?:[°º]\s*[CFcf]?|[CFcf]\b)",
)
OR_BELOW_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*[°º]?\s*[CFcf]?\s+or\s+(?:below|under)\b",
    re.I,
)
OR_ABOVE_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*[°º]?\s*[CFcf]?\s+or\s+(?:higher|above)\b",
    re.I,
)
SINGLE_TEMP_RE = re.compile(
    r"\bbe\s+(-?\d+(?:\.\d+)?)\s*[°º]?\s*[CFcf]?\s+on\b",
    re.I,
)
EVENT_SLUG_RE = re.compile(
    r"((?:highest|lowest)-temperature-in-[a-z0-9-]+-on-[a-z]+-\d+-\d{4})",
    re.I,
)

_SCAN_BACK_IDS = 35_000
_MAX_PAGES = 40
_BOOK_BATCH = 80


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
    yes_price: float | None = None
    no_price: float | None = None


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


def _kind_from_text(*parts: str) -> str:
    hay = " ".join(p or "" for p in parts).lower()
    if "highest" in hay or "high temperature" in hay or "max temp" in hay:
        return "highest"
    return "lowest"


def _parse_bucket(question: str, *, slug: str = "") -> tuple[str, float | None, float | None]:
    kind = _kind_from_text(question, slug)
    m = BUCKET_RE.search(question)
    if m:
        return kind, float(m.group(1)), float(m.group(2))
    m2 = RANGE_RE.search(question)
    if m2:
        return kind, float(m2.group(1)), float(m2.group(2))
    below = OR_BELOW_RE.search(question)
    if below:
        return kind, None, float(below.group(1))
    above = OR_ABOVE_RE.search(question)
    if above:
        return kind, float(above.group(1)), None
    single = SINGLE_TEMP_RE.search(question)
    if single:
        val = float(single.group(1))
        return kind, val, val
    return kind, None, None


def _city_slug_from_clob(slug: str, question: str, known: dict[str, Any]) -> str | None:
    hay = f"{slug} {question}".lower()
    for city in sorted(known, key=len, reverse=True):
        if f"temperature-in-{city}-on-" in hay or f"temperature-in-{city}-on-" in slug.lower():
            return city
    for city in known:
        if city.replace("-", " ") in hay or city in hay:
            return city
    return None


def _event_slug_from_clob(slug: str | None) -> str | None:
    if not slug:
        return None
    m = EVENT_SLUG_RE.search(slug)
    return m.group(1).lower() if m else slug


def _cursor_for_id(market_id: int) -> str:
    return base64.b64encode(f"id:{int(market_id)}".encode()).decode()


def _best_level(levels: Any) -> tuple[float | None, float]:
    """CLOB books: bids ascend, asks descend — best is the last level."""
    if not isinstance(levels, list) or not levels:
        return None, 0.0
    best = None
    depth = 0.0
    for lvl in levels:
        if not isinstance(lvl, dict):
            continue
        try:
            px = float(lvl.get("price") or lvl.get("p"))
            sz = float(lvl.get("size") or lvl.get("s") or 0)
        except (TypeError, ValueError):
            continue
        best = px
        depth += px * sz
    return best, depth


def _quote_from_clob_books(
    *,
    market_id: str,
    yes_book: dict[str, Any] | None,
    no_book: dict[str, Any] | None,
    yes_price: float | None = None,
    no_price: float | None = None,
) -> BookQuote:
    yes_book = yes_book or {}
    no_book = no_book or {}
    yes_bid, _ = _best_level(yes_book.get("bids"))
    yes_ask, _ = _best_level(yes_book.get("asks"))
    no_bid, _ = _best_level(no_book.get("bids"))
    no_ask, depth_no = _best_level(no_book.get("asks"))
    if no_ask is None and yes_bid is not None:
        no_ask = max(0.01, min(0.99, 1.0 - float(yes_bid)))
    if no_bid is None and yes_ask is not None:
        no_bid = max(0.01, min(0.99, 1.0 - float(yes_ask)))
    if no_ask is None and no_price is not None:
        no_ask = float(no_price)
    if no_bid is None and no_price is not None:
        no_bid = max(0.01, float(no_price) - 0.01)
    if yes_ask is None and yes_price is not None:
        yes_ask = float(yes_price)
    if yes_bid is None and yes_price is not None:
        yes_bid = max(0.01, float(yes_price) - 0.01)
    mid = None
    if no_ask is not None and no_bid is not None:
        mid = (float(no_ask) + float(no_bid)) / 2
    elif no_ask is not None:
        mid = float(no_ask)
    elif no_bid is not None:
        mid = float(no_bid)
    if depth_no <= 0 and no_ask is not None:
        depth_no = 150.0
    return BookQuote(
        market_id=market_id,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=no_bid,
        no_ask=no_ask,
        no_mid=mid,
        depth_no_usd=float(depth_no or 0),
        ts=datetime.now(timezone.utc).isoformat(),
    )


class MarketService:
    def __init__(self, settings: Settings, cities: list[dict[str, Any]]):
        self.settings = settings
        self.cities = cities
        self.by_slug = {c["polymarket_slug_city"]: c for c in cities}
        self.by_lid = {c["location_id"]: c for c in cities}
        self.markets: list[WeatherMarket] = []
        self.quotes: dict[str, BookQuote] = {}
        self._epoch = 0
        self._high_id: int | None = None
        self._client = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "WeatherBuyEnd/0.1", "Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def refresh_markets(self, force_new: bool = False) -> list[WeatherMarket]:
        if self.settings.mock_markets:
            if force_new:
                self._epoch += 1
            self.markets = self._mock_markets()
            return self.markets
        try:
            self.markets = self._fetch_clob_weather()
            if not self.markets:
                logger.warning("CLOB returned no weather markets; falling back to mock")
                self.markets = self._mock_markets()
        except Exception as e:
            logger.exception("CLOB catalog failed: %s", e)
            self.markets = self._mock_markets()
        return self.markets

    def _clob(self) -> str:
        return CLOB_URL.rstrip("/")

    def _markets_page(self, *, after_id: int | None = None, cursor: str | None = None) -> tuple[list[dict], str | None]:
        params: dict[str, str] = {}
        if cursor:
            params["next_cursor"] = cursor
        elif after_id is not None:
            params["next_cursor"] = _cursor_for_id(after_id)
        r = self._client.get(f"{self._clob()}/markets", params=params)
        r.raise_for_status()
        data = r.json()
        items = data.get("data") if isinstance(data, dict) else data
        if not isinstance(items, list):
            items = []
        nxt = data.get("next_cursor") if isinstance(data, dict) else None
        if nxt in (None, "", "LTE="):
            nxt = None
        return items, nxt

    def _discover_high_id(self) -> int:
        if self._high_id:
            items, _ = self._markets_page(after_id=self._high_id + 5_000)
            if not items:
                return self._high_id
            lo, hi = self._high_id, self._high_id + 500_000
        else:
            lo, hi = 2_000_000, 8_000_000
        while hi - lo > 1:
            mid = (lo + hi) // 2
            items, _ = self._markets_page(after_id=mid)
            if items:
                lo = mid
            else:
                hi = mid
        self._high_id = lo
        return lo

    def _fetch_clob_weather(self) -> list[WeatherMarket]:
        high = self._discover_high_id()
        start = max(1, high - _SCAN_BACK_IDS)
        min_day = (date.today() - timedelta(days=1)).isoformat()
        out: list[WeatherMarket] = []
        seen: set[str] = set()
        cursor: str | None = _cursor_for_id(start)
        pages = 0
        while cursor and pages < _MAX_PAGES:
            items, cursor = self._markets_page(cursor=cursor)
            pages += 1
            if not items:
                break
            for item in items:
                parsed = self._market_from_clob(item, min_day=min_day)
                if parsed is None or parsed.market_id in seen:
                    continue
                seen.add(parsed.market_id)
                out.append(parsed)
        logger.info("CLOB weather markets=%d pages=%d high_id=%s", len(out), pages, high)
        return out

    def _market_from_clob(self, item: dict[str, Any], *, min_day: str) -> WeatherMarket | None:
        if item.get("closed") or item.get("archived"):
            return None
        slug = str(item.get("market_slug") or item.get("slug") or "")
        q = str(item.get("question") or item.get("title") or "")
        hay = f"{slug} {q}".lower()
        if "temperature" not in hay and "temp" not in hay:
            return None
        city_slug = _city_slug_from_clob(slug, q, self.by_slug)
        if not city_slug or city_slug not in self.by_slug:
            return None
        city = self.by_slug[city_slug]
        kind, lo, hi = _parse_bucket(q, slug=slug)
        tokens = item.get("tokens") or []
        yes_id, no_id, yes_px, no_px = self._token_ids(item, tokens)
        mid = str(item.get("condition_id") or item.get("id") or item.get("market_id") or "")
        if not mid:
            return None
        end_raw = item.get("end_date_iso") or item.get("end_date") or item.get("endDate")
        end_date = str(end_raw)[:10] if end_raw else None
        if end_date and end_date < min_day:
            return None
        event_slug = _event_slug_from_clob(slug)
        pm_url = polymarket_event_url(
            city_slug=city_slug,
            kind=kind,
            end_date=end_date,
            event_slug=event_slug,
            market_id=mid,
        )
        return WeatherMarket(
            market_id=mid,
            question=q,
            city_slug=city_slug,
            location_id=city["location_id"],
            kind=kind,
            lo=lo,
            hi=hi,
            yes_token_id=yes_id,
            no_token_id=no_id,
            end_date=end_date,
            timezone=city["timezone"],
            temperature_unit=city.get("temperature_unit", "fahrenheit"),
            event_slug=event_slug,
            polymarket_url=pm_url,
            yes_price=yes_px,
            no_price=no_px,
        )

    def _token_ids(self, item: dict, tokens: Any) -> tuple[str, str, float | None, float | None]:
        yes_id = str(item.get("yes_token_id") or item.get("token1") or f"{item.get('condition_id') or item.get('id')}-YES")
        no_id = str(item.get("no_token_id") or item.get("token2") or f"{item.get('condition_id') or item.get('id')}-NO")
        yes_px = None
        no_px = None
        if isinstance(tokens, list) and tokens:
            for t in tokens:
                if not isinstance(t, dict):
                    continue
                name = str(t.get("outcome") or t.get("name") or "").lower()
                tid = str(t.get("token_id") or t.get("id") or "")
                px = t.get("price")
                try:
                    price = float(px) if px is not None else None
                except (TypeError, ValueError):
                    price = None
                if name in {"yes", "y"}:
                    yes_id = tid or yes_id
                    yes_px = price
                if name in {"no", "n"}:
                    no_id = tid or no_id
                    no_px = price
        return yes_id, no_id, yes_px, no_px

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

        books = self._fetch_clob_books(self.markets)
        for m in self.markets:
            yes_book = books.get(m.yes_token_id)
            no_book = books.get(m.no_token_id)
            if yes_book is None and no_book is None:
                quotes[m.market_id] = self._quote_from_prices(m)
            else:
                quotes[m.market_id] = _quote_from_clob_books(
                    market_id=m.market_id,
                    yes_book=yes_book,
                    no_book=no_book,
                    yes_price=m.yes_price,
                    no_price=m.no_price,
                )
        self.quotes = quotes
        return quotes

    def _quote_from_prices(self, m: WeatherMarket) -> BookQuote:
        return _quote_from_clob_books(
            market_id=m.market_id,
            yes_book=None,
            no_book=None,
            yes_price=m.yes_price,
            no_price=m.no_price,
        )

    def _fetch_clob_books(self, markets: list[WeatherMarket]) -> dict[str, dict[str, Any]]:
        token_ids: list[str] = []
        for m in markets:
            if m.yes_token_id:
                token_ids.append(m.yes_token_id)
            if m.no_token_id:
                token_ids.append(m.no_token_id)
        out: dict[str, dict[str, Any]] = {}
        for i in range(0, len(token_ids), _BOOK_BATCH):
            chunk = token_ids[i : i + _BOOK_BATCH]
            payload = [{"token_id": tid} for tid in chunk]
            try:
                r = self._client.post(f"{self._clob()}/books", json=payload)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                logger.debug("CLOB /books batch failed: %s", e)
                continue
            rows = data if isinstance(data, list) else data.get("data") or data.get("books") or []
            if not isinstance(rows, list):
                continue
            for book in rows:
                if not isinstance(book, dict):
                    continue
                tid = str(book.get("asset_id") or book.get("token_id") or "")
                if tid:
                    out[tid] = book
        return out

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
