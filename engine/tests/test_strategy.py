"""Unit tests for NO-eliminated gates."""

from weatherbuy.strategy import evaluate_no_eliminated, no_eliminated_cfg


def test_ok_elim_window():
    cfg = no_eliminated_cfg({"no_eliminated": {"enabled": True}})
    d = evaluate_no_eliminated(hours=-1.0, eliminated=True, no_price=0.95, cfg=cfg)
    assert d.ok
    assert d.reason == "ok"
    assert d.net_edge is not None and d.net_edge > 0


def test_reject_not_eliminated():
    cfg = no_eliminated_cfg({"no_eliminated": {"enabled": True}})
    d = evaluate_no_eliminated(hours=-1.0, eliminated=False, no_price=0.95, cfg=cfg)
    assert not d.ok
    assert d.reason == "not_eliminated"


def test_reject_price_high():
    cfg = no_eliminated_cfg({"no_eliminated": {"enabled": True}})
    d = evaluate_no_eliminated(hours=-1.0, eliminated=True, no_price=0.995, cfg=cfg)
    assert not d.ok
    assert d.reason == "no_price_high"


def test_reject_outside_window():
    cfg = no_eliminated_cfg({"no_eliminated": {"enabled": True}})
    d = evaluate_no_eliminated(hours=8.0, eliminated=True, no_price=0.95, cfg=cfg)
    assert not d.ok
    assert d.reason == "outside_no_window"
