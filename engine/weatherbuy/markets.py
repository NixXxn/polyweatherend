"""Market discovery + book quotes (PMXT catalog or mock)."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .config import Settings
from .metar import DayState, hours_to_local_noon

logger = logging.getLogger(__name__)

BUCKET_RE = re.compile(
    r"(?:highest|lowest|high|low|max|min).*?(?:temp|temperature).*?"
    r"(?:between\s+)?(-?\d+(?:\.\d+)?)\s*[°º]?\s*[CF]?\s*(?:-|to|–|—)\s*(-?\d+(?:\.\d+)?)",
    re.I,
)
CITY_SLUG_RE = re.compile(r"([a-z0-9-]+)", re.I)


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
        if self.settings.mock_markets or not self.settings.pmxt_api_key:
            if force_new:
                self._epoch += 1
            self.markets = self._mock_markets()
            return self.markets
        try:
            self.markets = self._fetch_pmxt_weather()
            if not self.markets:
                logger.warning("PMXT returned no weather markets; falling back to mock")
                self.markets = self._mock_markets()
        except Exception as e:
            logger.exception("PMXT catalog failed: %s", e)
            self.markets = self._mock_markets()
        return self.markets

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.pmxt_api_key}"}

    def _fetch_pmxt_weather(self) -> list[WeatherMarket]:
        # Hosted catalog — keep query broad; filter client-side
        url = f"{self.settings.pmxt_catalog_url.rstrip('/')}/v0/markets"
        params = {"limit": 200, "q": "temperature"}
        r = self._client.get(url, headers=self._headers(), params=params)
        if r.status_code >= 400:
            logger.warning("PMXT markets HTTP %s: %s", r.status_code, r.text[:200])
            return []
        data = r.json()
        items = data if isinstance(data, list) else data.get("markets") or data.get("data") or []
        out: list[WeatherMarket] = []
        for item in items:
            q = str(item.get("question") or item.get("title") or "")
            if "temp" not in q.lower() and "°" not in q:
                continue
            kind, lo, hi = _parse_bucket(q)
            slug = self._match_city_slug(q, item)
            if not slug or slug not in self.by_slug:
                continue
            city = self.by_slug[slug]
            tokens = item.get("tokens") or item.get("outcomes") or []
            yes_id, no_id = self._token_ids(item, tokens)
            mid = str(item.get("id") or item.get("condition_id") or item.get("market_id"))
            out.append(
                WeatherMarket(
                    market_id=mid,
                    question=q,
                    city_slug=slug,
                    location_id=city["location_id"],
                    kind=kind,
                    lo=lo,
                    hi=hi,
                    yes_token_id=yes_id,
                    no_token_id=no_id,
                    end_date=item.get("end_date") or item.get("endDate"),
                    timezone=city["timezone"],
                    temperature_unit=city.get("temperature_unit", "fahrenheit"),
                )
            )
        return out

    def _match_city_slug(self, question: str, item: dict) -> str | None:
        hay = " ".join(
            [
                question.lower(),
                str(item.get("slug") or ""),
                str(item.get("event_slug") or ""),
            ]
        )
        for slug in self.by_slug:
            if slug.replace("-", " ") in hay or slug in hay:
                return slug
        return None

    def _token_ids(self, item: dict, tokens: Any) -> tuple[str, str]:
        yes_id = str(item.get("yes_token_id") or item.get("token1") or f"{item.get('id')}-YES")
        no_id = str(item.get("no_token_id") or item.get("token2") or f"{item.get('id')}-NO")
        if isinstance(tokens, list) and len(tokens) >= 2:
            for t in tokens:
                name = str(t.get("outcome") or t.get("name") or "").lower()
                tid = str(t.get("token_id") or t.get("id") or "")
                if name in {"yes", "y"}:
                    yes_id = tid or yes_id
                if name in {"no", "n"}:
                    no_id = tid or no_id
        return yes_id, no_id

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
                    )
                )
        return out

    def refresh_quotes(self, day_states: dict[str, DayState]) -> dict[str, BookQuote]:
        quotes: dict[str, BookQuote] = {}
        for m in self.markets:
            if self.settings.mock_markets or not self.settings.pmxt_api_key:
                quotes[m.market_id] = self._mock_quote(m, day_states.get(m.location_id))
            else:
                try:
                    quotes[m.market_id] = self._fetch_quote(m)
                except Exception as e:
                    logger.debug("quote fail %s: %s", m.market_id, e)
                    quotes[m.market_id] = self._mock_quote(m, day_states.get(m.location_id))
        self.quotes = quotes
        return quotes

    def _fetch_quote(self, m: WeatherMarket) -> BookQuote:
        url = f"{self.settings.pmxt_catalog_url.rstrip('/')}/v0/markets/{m.market_id}/book"
        r = self._client.get(url, headers=self._headers())
        if r.status_code >= 400:
            raise RuntimeError(f"book {r.status_code}")
        data = r.json()
        yes_ask = _best(data, "yes", "ask")
        yes_bid = _best(data, "yes", "bid")
        no_ask = _best(data, "no", "ask")
        no_bid = _best(data, "no", "bid")
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
            depth_no_usd=float(data.get("depth_no_usd") or 200),
            ts=datetime.now(timezone.utc).isoformat(),
        )

    def _mock_quote(self, m: WeatherMarket, st: DayState | None) -> BookQuote:
        # If eliminated, quote stale residual YES (~3–12¢) so NO sits in 0.88–0.97 band
        eliminated = False
        if st and st.tmax_so_far is not None and m.hi is not None and m.kind == "highest":
            eliminated = st.tmax_so_far > m.hi
        if eliminated:
            yes_ask = 0.05
            no_ask = 0.95
        else:
            yes_ask = 0.45
            no_ask = 0.55
        return BookQuote(
            market_id=m.market_id,
            yes_bid=max(0.01, yes_ask - 0.02),
            yes_ask=yes_ask,
            no_bid=max(0.01, no_ask - 0.02),
            no_ask=no_ask,
            no_mid=no_ask - 0.01,
            depth_no_usd=150.0,
            ts=datetime.now(timezone.utc).isoformat(),
        )


def _best(data: dict, side: str, book_side: str) -> float | None:
    key = f"{side}_{book_side}"
    if key in data and data[key] is not None:
        return float(data[key])
    books = data.get("books") or data.get("orderbook") or {}
    side_book = books.get(side) or {}
    levels = side_book.get(f"{book_side}s") or side_book.get(book_side) or []
    if levels:
        lvl = levels[0]
        if isinstance(lvl, dict):
            return float(lvl.get("price") or lvl.get("p"))
        if isinstance(lvl, (list, tuple)) and lvl:
            return float(lvl[0])
    return None
