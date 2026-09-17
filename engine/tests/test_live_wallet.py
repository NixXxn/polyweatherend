"""Wallet helpers and live venue guards."""

from weatherbuy.config import Settings
from weatherbuy.venue import Venue
from weatherbuy.wallet import erc20_balance_calldata, hex_uint, units_to_usd


def _settings(**kw) -> Settings:
    defaults = dict(
        trading_mode="paper",
        live_trading=False,
        mock_markets=False,
        poly_private_key="",
        pmxt_private_key="",
        pmxt_wallet_address="",
        pmxt_api_key="",
    )
    defaults.update(kw)
    return Settings(_env_file=None, **defaults)


def test_hex_uint_and_units():
    assert hex_uint("0xe3f763") == 0xE3F763
    assert units_to_usd(1_000_000) == 1.0
    assert units_to_usd(0) == 0.0


def test_balance_of_calldata():
    data = erc20_balance_calldata("0x56687bf447db6ffa42ffe2204a05edaa20f55839")
    assert data.startswith("0x70a08231")
    assert data.endswith("56687bf447db6ffa42ffe2204a05edaa20f55839")


def test_trading_mode_live_is_enough():
    s = _settings(trading_mode="live", live_trading=False)
    assert s.is_live
    assert not s.live_ready


def test_live_without_key_does_not_paper_fill():
    s = _settings(trading_mode="live", live_trading=True)
    v = Venue(s)
    try:
        fill = v.buy_no_taker(
            market_id="m1",
            location_id="nyc",
            no_token_id="1",
            ask=0.95,
            size_usd=2.0,
            depth_usd=100.0,
        )
        assert fill.mode == "live"
        assert fill.status == "error_missing_signing_key"
        assert fill.size_usd == 0.0
        assert not str(fill.fill_id).startswith("paper-")
    finally:
        v.close()


def test_paper_still_paper_fills():
    s = _settings(trading_mode="paper", live_trading=False)
    v = Venue(s)
    try:
        fill = v.buy_no_taker(
            market_id="m1",
            location_id="nyc",
            no_token_id="1",
            ask=0.95,
            size_usd=2.0,
            depth_usd=100.0,
        )
        assert fill.mode == "paper"
        assert fill.status == "filled"
        assert fill.size_usd == 2.0
        assert str(fill.fill_id).startswith("paper-")
    finally:
        v.close()
