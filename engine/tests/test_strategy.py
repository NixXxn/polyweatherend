"""Unit tests for NO-eliminated gates."""

from weatherbuy.strategy import evaluate_no_eliminated, no_eliminated_cfg, polymarket_event_url, stake_usd


def _cfg(**overrides):
    return no_eliminated_cfg({"no_eliminated": {"enabled": True, **overrides}})


def test_ok_elim_post_noon():
    cfg = _cfg()
    d = evaluate_no_eliminated(hours=-1.0, eliminated=True, no_price=0.95, cfg=cfg)
    assert d.ok
    assert d.reason == "ok"
    assert d.net_edge is not None and d.net_edge >= 0.02


def test_reject_not_eliminated():
    cfg = _cfg()
    d = evaluate_no_eliminated(hours=-1.0, eliminated=False, no_price=0.95, cfg=cfg)
    assert not d.ok
    assert d.reason == "not_eliminated"


def test_reject_price_high():
    cfg = _cfg()
    d = evaluate_no_eliminated(hours=-1.0, eliminated=True, no_price=0.995, cfg=cfg)
    assert not d.ok
    assert d.reason == "no_price_high"


def test_reject_price_below_dense_band():
    cfg = _cfg()
    d = evaluate_no_eliminated(hours=-1.0, eliminated=True, no_price=0.85, cfg=cfg)
    assert not d.ok
    assert d.reason == "no_price_low"


def test_reject_outside_window():
    cfg = _cfg()
    d = evaluate_no_eliminated(hours=8.0, eliminated=True, no_price=0.95, cfg=cfg)
    assert not d.ok
    assert d.reason == "outside_no_window"


def test_reject_before_noon_when_prefer_post():
    cfg = _cfg(prefer_post_noon=True)
    d = evaluate_no_eliminated(hours=2.0, eliminated=True, no_price=0.95, cfg=cfg)
    assert not d.ok
    assert d.reason == "before_noon"


def test_allow_before_noon_when_prefer_off():
    cfg = _cfg(prefer_post_noon=False)
    d = evaluate_no_eliminated(hours=2.0, eliminated=True, no_price=0.95, cfg=cfg)
    assert d.ok


def test_reject_net_edge_low():
    cfg = _cfg(min_net_edge=0.02, p_no_if_eliminated=0.99)
    # 0.975 → edge 0.015 < 0.02
    d = evaluate_no_eliminated(hours=-1.0, eliminated=True, no_price=0.975, cfg=cfg)
    assert not d.ok
    assert d.reason == "net_edge_low"


def test_small_stake_no_weak_bump():
    assert stake_usd({"base_stake_usd": 2}, edge=0.03) == 2.0
    assert stake_usd({"base_stake_usd": 2}, edge=0.07) == 2.5


def test_polymarket_url():
    url = polymarket_event_url(city_slug="nyc", kind="highest", end_date="2026-09-16")
    assert url.startswith("https://polymarket.com/event/")
    assert "nyc" in url
    assert "september-16-2026" in url
