# WeatherBuyEnd **Live**

Live Polymarket CLOB version of the late-day weather **BUY NO** bot (hard METAR elimination sleeve). Same mobile ops dashboard + Coolify single-container deploy as `polyweatherend`, wired to official Polymarket credentials.

**Orders are taker-only** (FOK / FAK). No resting maker quotes.

## Required `.env` (Coolify secrets)

```bash
POLY_PRIVATE_KEY=0x...
POLY_API_KEY=...
POLY_API_SECRET=...
POLY_API_PASSPHRASE=...

# Optional if using Magic / proxy / deposit wallet (needed for almost all polymarket.com accounts)
POLY_SIGNATURE_TYPE=3   # 0=EOA, 1=Magic, 2=Gnosis/proxy, 3=deposit wallet
POLY_FUNDER=            # address on polymarket.com that holds USDC (not the EOA)

TRADING_MODE=live
LIVE_TRADING=true
MOCK_MARKETS=false
KILL_SWITCH=true        # start FLAT — Arm in the UI when ready
BUDGET_USD=500
```

Never commit `.env`. Rotate any key that was pasted into chat or tickets.

## What it does

1. Discovers weather temp buckets via **Gamma** (`gamma-api.polymarket.com`).
2. Quotes NO via public **CLOB** books (`clob.polymarket.com`).
3. Gates with hard METAR elim + post-noon + NO band `0.90–0.98`.
4. Sizes tickets from budget (max **75%** open / 25% cash reserve).
5. Sends **FOK taker BUY NO** through `py-clob-client` using your `POLY_*` creds.
6. Ops UI: Budget / Gains hero, Arm / Kill, CSV, Polymarket links.

## Coolify

- Repo: this GitHub repo · branch `main`
- Build Pack: **Dockerfile** · Port from `PORT`
- Health: `/health`
- Env: paste `POLY_*` + mode flags above (do **not** set `NEXT_PUBLIC_API_URL`)
- Persist `/app/data` volume for ledger / budget

Same-origin: `/` = UI, `/api/*` = API, `/health` = health.

## Local

```bash
cp .env.example .env   # fill POLY_* — never commit
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r engine/requirements.txt
export PYTHONPATH=engine
# smoke without live: MOCK_MARKETS=true LIVE_TRADING=false TRADING_MODE=paper
python -m weatherbuy
# → http://127.0.0.1:3847/
```

## Safety

- Default **KILL_SWITCH=true** → sleeve starts FLAT until you tap **Arm**.
- Paper path still works with `TRADING_MODE=paper` + `LIVE_TRADING=false` + `MOCK_MARKETS=true`.
- EOA wallets need USDC + allowance on Polygon for the exchange contracts.

## Stack

| Piece | Endpoint |
|-------|----------|
| Orders / books | `https://clob.polymarket.com` (`POLY_CLOB_HOST`) |
| Market discovery | `https://gamma-api.polymarket.com` (`POLY_GAMMA_URL`) |
| Auth | `POLY_PRIVATE_KEY` + `POLY_API_KEY` / `SECRET` / `PASSPHRASE` |

**No PMXT.** Catalog, books, and fills go through Polymarket CLOB + Gamma only.
