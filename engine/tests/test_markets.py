"""CLOB market parsing + quote helpers."""

from weatherbuy.config import CLOB_URL, Settings
from weatherbuy.markets import (
    _city_slug_from_clob,
    _event_slug_from_clob,
    _parse_bucket,
    _quote_from_clob_books,
)


def test_parse_between_range():
    kind, lo, hi = _parse_bucket(
        "Will the lowest temperature in New York City be between 56-57°F on September 19?"
    )
    assert kind == "lowest"
    assert lo == 56
    assert hi == 57


def test_parse_or_below():
    kind, lo, hi = _parse_bucket(
        "Will the highest temperature in Dallas be 89°F or below on September 19?"
    )
    assert kind == "highest"
    assert lo is None
    assert hi == 89


def test_parse_or_higher():
    kind, lo, hi = _parse_bucket(
        "Will the lowest temperature in Jinan be 22°C or higher on September 17?"
    )
    assert kind == "lowest"
    assert lo == 22
    assert hi is None


def test_parse_single_degree():
    kind, lo, hi = _parse_bucket("Will the lowest temperature in Jinan be 13°C on September 17?")
    assert kind == "lowest"
    assert lo == 13
    assert hi == 13


def test_city_and_event_slug_from_clob():
    known = {"nyc": {}, "hong-kong": {}, "dallas": {}}
    slug = "lowest-temperature-in-nyc-on-september-19-2026-56-57f"
    assert _city_slug_from_clob(slug, "Will the lowest temperature in New York City be between 56-57°F?", known) == "nyc"
    assert _city_slug_from_clob(
        "highest-temperature-in-hong-kong-on-september-19-2026-32c",
        "highest temperature in Hong Kong",
        known,
    ) == "hong-kong"
    assert _event_slug_from_clob(slug) == "lowest-temperature-in-nyc-on-september-19-2026"


def test_quote_uses_last_clob_level_and_complement():
    yes_book = {
        "bids": [{"price": "0.02", "size": "10"}, {"price": "0.035", "size": "5"}],
        "asks": [{"price": "0.08", "size": "4"}, {"price": "0.04", "size": "2"}],
    }
    no_book = {"bids": [{"price": "0.90", "size": "8"}, {"price": "0.93", "size": "3"}], "asks": []}
    q = _quote_from_clob_books(
        market_id="m1",
        yes_book=yes_book,
        no_book=no_book,
        yes_price=0.035,
        no_price=0.965,
    )
    assert q.yes_bid == 0.035
    assert q.yes_ask == 0.04
    assert q.no_bid == 0.93
    assert q.no_ask == 0.965  # 1 - yes_bid when NO asks empty
    assert q.depth_no_usd == 150.0


def test_settings_always_use_clob_host():
    s = Settings(pmxt_catalog_url="https://api.pmxt.dev", clob_url="https://example.invalid")
    assert s.venue_url == "https://clob.polymarket.com"
    assert CLOB_URL == "https://clob.polymarket.com"


def test_clob_time_endpoint():
    import httpx

    r = httpx.get(f"{CLOB_URL}/time", timeout=15, headers={"User-Agent": "WeatherBuyEnd/0.1"})
    assert r.status_code == 200
    assert r.text.strip().isdigit()
