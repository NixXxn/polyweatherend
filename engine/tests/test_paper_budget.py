"""Paper bankroll must compound settlement PnL and survive process restart."""

from weatherbuy.config import Settings
from weatherbuy.loop import ExecEngine


def _paper_settings(**kwargs) -> Settings:
    base = dict(
        TRADING_MODE="paper",
        LIVE_TRADING=False,
        MOCK_MARKETS=True,
        KILL_SWITCH=False,
        BUDGET_USD=500,
    )
    base.update(kwargs)
    return Settings(**base)


def _engine(tmp_path, monkeypatch, settings=None) -> ExecEngine:
    strat = {
        "bankroll_usd": 500,
        "base_stake_usd": 2,
        "paths": {"ledger_dir": str(tmp_path)},
        "paper": {"settle_after_sec": 1, "scalp_enabled": False, "mock_metar_on_failure": True},
        "risk": {"max_deploy_frac": 0.75},
        "no_eliminated": {"scalp_enabled": False},
    }
    monkeypatch.setattr("weatherbuy.loop.load_strategy", lambda settings=None: strat)
    monkeypatch.setattr("weatherbuy.loop.load_cities", lambda settings=None: [])
    return ExecEngine(settings or _paper_settings())


def _open_pos(**kwargs) -> dict:
    pos = {
        "market_id": "m1",
        "location_id": "nyc_lga",
        "city": "nyc",
        "entry_price": 0.95,
        "size_usd": 19.0,
        "shares": 20.0,
        "opened_at": "2020-01-01T00:00:00+00:00",
        "kind": "highest",
        "lo": 50,
        "hi": 51,
        "entry_elim": True,
        "mode": "paper",
        "fill_id": "f1",
        "question": "Highest temperature in nyc: 50-51",
    }
    pos.update(kwargs)
    return pos


def test_paper_budget_compounds_win(tmp_path, monkeypatch):
    eng = _engine(tmp_path, monkeypatch)
    assert eng._cash_budget() == 500.0
    eng._open["m1"] = _open_pos()
    eng._settle_paper()
    # exit 1.0 on honored elim → pnl = (1-0.95)*20 = 1.0
    assert eng._wins == 1
    assert eng._cash_budget() == 501.0
    eng._publish()
    assert eng.store.snapshot()["status"]["budget_usd"] == 501.0
    assert eng.store.snapshot()["status"]["equity_usd"] == 501.0


def test_paper_budget_survives_restart(tmp_path, monkeypatch):
    eng = _engine(tmp_path, monkeypatch)
    eng._open["m1"] = _open_pos()
    eng._settle_paper()
    eng._publish()
    cash = eng._cash_budget()
    assert cash == 501.0
    eng.stop()

    eng2 = _engine(tmp_path, monkeypatch)
    assert eng2._cash_budget() == 501.0
    assert eng2._wins == 1
    assert eng2.risk.state.daily_realized_pnl == 1.0
    eng2._publish()
    assert eng2.store.snapshot()["status"]["budget_usd"] == 501.0


def test_set_budget_is_new_mark_not_double_count(tmp_path, monkeypatch):
    eng = _engine(tmp_path, monkeypatch)
    eng._open["m1"] = _open_pos()
    eng._settle_paper()
    assert eng._cash_budget() == 501.0
    eng.set_budget(800)
    assert eng._cash_budget() == 800.0
    eng.stop()
    eng2 = _engine(tmp_path, monkeypatch)
    assert eng2._cash_budget() == 800.0


def test_snapshot_has_restored_stats_before_loop(tmp_path, monkeypatch):
    eng = _engine(tmp_path, monkeypatch)
    eng._open["m1"] = _open_pos()
    eng._settle_paper()
    eng._publish(force=True)
    eng.stop()

    eng2 = _engine(tmp_path, monkeypatch)
    snap = eng2.store.snapshot()["status"]
    assert snap["wins"] == 1
    assert snap["gains_usd"] == 1.0
    assert snap["budget_usd"] == 501.0


def test_live_boot_keeps_paper_ledger_stats(tmp_path, monkeypatch):
    eng = _engine(tmp_path, monkeypatch)
    eng._open["m1"] = _open_pos()
    eng._settle_paper()
    eng._publish(force=True)
    eng.stop()

    live = _engine(
        tmp_path,
        monkeypatch,
        settings=_paper_settings(TRADING_MODE="live", LIVE_TRADING=True, MOCK_MARKETS=False),
    )
    snap = live.store.snapshot()["status"]
    assert live._wins == 1
    assert snap["wins"] == 1
    assert snap["gains_usd"] == 1.0


def test_heartbeat_does_not_rewrite_unchanged_state(tmp_path, monkeypatch):
    eng = _engine(tmp_path, monkeypatch)
    eng._open["m1"] = _open_pos()
    eng._settle_paper()
    eng._publish(force=True)
    writes = eng.store.persist_writes
    eng._publish()
    eng._publish()
    eng._publish()
    assert eng.store.persist_writes == writes


def test_arm_survives_kill_switch_restart(tmp_path, monkeypatch):
    eng = _engine(tmp_path, monkeypatch, settings=_paper_settings(KILL_SWITCH=True))
    assert eng.risk.state.killed
    eng.arm()
    assert not eng.risk.state.killed
    eng.stop()

    eng2 = _engine(tmp_path, monkeypatch, settings=_paper_settings(KILL_SWITCH=True))
    assert not eng2.risk.state.killed
    assert eng2.store.snapshot()["status"]["armed"] is True


def test_empty_poly_signature_type_does_not_crash(monkeypatch):
    monkeypatch.setenv("POLY_SIGNATURE_TYPE", "")
    monkeypatch.setenv("POLY_CHAIN_ID", "")
    monkeypatch.setenv("BUDGET_USD", "")
    s = Settings()
    assert s.poly_signature_type == 0
    assert s.poly_chain_id == 137
    assert s.budget_usd is None


def test_paper_loss_reduces_budget(tmp_path, monkeypatch):
    eng = _engine(tmp_path, monkeypatch)
    # still_elim False → exit 0, lose full entry
    eng._day_states["nyc_lga"] = type("S", (), {"tmax_so_far": 40.0, "tmin_so_far": 40.0})()
    eng._open["m1"] = _open_pos(entry_elim=True, lo=50, hi=51, kind="highest")
    eng._settle_paper()
    assert eng._losses == 1
    # pnl = (0-0.95)*20 = -19 → budget 481
    assert eng._cash_budget() == 481.0
