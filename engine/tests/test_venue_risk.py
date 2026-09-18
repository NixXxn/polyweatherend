"""Venue error accounting must not flatten the sleeve on thin-book FOK misses."""

from weatherbuy.config import Settings
from weatherbuy.risk import RiskGate
from weatherbuy.venue import Venue


def _live_settings(**kwargs) -> Settings:
    base = dict(
        trading_mode="live",
        live_trading=True,
        mock_markets=False,
        poly_private_key=None,
    )
    base.update(kwargs)
    return Settings(**base)


def _buy(venue: Venue, **kwargs):
    args = dict(
        market_id="m1",
        location_id="nyc_lga",
        no_token_id="1234567890",
        ask=0.95,
        size_usd=10.0,
        order_type="FOK",
        depth_usd=50.0,
    )
    args.update(kwargs)
    return venue.buy_no_taker(**args)


def test_rejected_depth_is_not_a_venue_error():
    v = Venue(_live_settings())
    fill = _buy(v, depth_usd=1.0, size_usd=10.0)
    assert fill.status == "rejected_depth"
    assert fill.size_usd == 0.0
    assert v.attempts == 0
    assert v.errors == 0
    assert v.error_rate == 0.0


def test_mock_token_is_not_posted_live():
    v = Venue(_live_settings(mock_markets=True))
    fill = _buy(v, no_token_id="no-deadbeef")
    assert fill.status == "rejected_mock_token"
    assert v.attempts == 0
    assert v.errors == 0


def test_risk_ignores_error_rate_until_min_attempts():
    g = RiskGate(
        {
            "risk": {
                "max_venue_error_rate": 0.25,
                "min_venue_attempts": 8,
                "max_metar_age_minutes": 90,
            }
        }
    )
    ok, _ = g.allow(
        market_id="m1",
        location_id="nyc_lga",
        size_usd=2.0,
        metar_age_minutes=5.0,
        venue_error_rate=1.0,
        already_open=False,
        venue_attempts=1,
    )
    assert ok
    assert not g.state.killed

    ok2, why2 = g.allow(
        market_id="m2",
        location_id="miami_mia",
        size_usd=2.0,
        metar_age_minutes=5.0,
        venue_error_rate=1.0,
        already_open=False,
        venue_attempts=8,
    )
    assert not ok2
    assert why2 == "venue_error_rate"
    assert g.state.killed
