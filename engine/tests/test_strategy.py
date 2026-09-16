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


def test_budget_ticket_scales_and_caps_deploy():
    from weatherbuy.strategy import budget_ticket_usd

    strat = {"base_stake_usd": 2, "bankroll_usd": 500}
    size, why = budget_ticket_usd(
        strat, budget_usd=500, open_notional=0, edge=0.03, max_deploy_frac=0.75
    )
    assert why == "ok"
    assert size == 2.0

    size2, _ = budget_ticket_usd(
        strat, budget_usd=1000, open_notional=0, edge=0.03, max_deploy_frac=0.75
    )
    assert size2 == 4.0  # 2× budget vs ref

    # Near 75% deploy cap — tiny remaining
    size3, why3 = budget_ticket_usd(
        strat, budget_usd=500, open_notional=374.5, edge=0.03, max_deploy_frac=0.75
    )
    assert why3 == "ok"
    assert size3 <= 0.5 + 1e-9 or size3 <= 500 * 0.75 - 374.5

    size4, why4 = budget_ticket_usd(
        strat, budget_usd=500, open_notional=375, edge=0.03, max_deploy_frac=0.75
    )
    assert size4 == 0.0
    assert why4 == "budget_fully_deployed"


def test_polymarket_url():
    url = polymarket_event_url(city_slug="nyc", kind="highest", end_date="2026-09-16")
    assert url.startswith("https://polymarket.com/event/")
    assert "nyc" in url
    assert "september-16-2026" in url
