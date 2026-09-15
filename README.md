# WeatherBuyEnd

Late-day Polymarket weather **BUY NO** bot for hard METAR-eliminated temperature buckets (HighTempTation-style sleeve), with a mobile ops dashboard. Phase-1: paper/mock by default; live PMXT taker orders behind explicit flags.

## What it does

1. Polls IEM ASOS/METAR per city station.
2. Tracks weather bucket markets + NO book (mock books by default; PMXT catalog when configured).
3. Gates entries with hard elim + ≤6h to local noon + NO price band `0.80–0.985`.
4. Sends **FOK/IOC taker BUY NO** (paper fills unless `LIVE_TRADING=true`).
5. Exposes kill / arm / sleeve / stake controls on a phone-first dashboard.

## Quick start (local)

```bash
cp .env.example .env
# optional: paste PMXT_API_KEY for catalog (still paper unless LIVE_TRADING=true)

# API + loop
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r engine/requirements.txt
export PYTHONPATH=engine
export MOCK_MARKETS=true TRADING_MODE=paper LIVE_TRADING=false
python -m weatherbuy
# → http://127.0.0.1:3847/health

# Dashboard (other terminal)
cd dashboard && npm install && npm run dev -- -p 3851
# → http://127.0.0.1:3851
```

Optional Redis: `redis-server` or `docker run -p 6379:6379 redis:7-alpine`. Engine falls back to an in-memory + JSON ledger if Redis is down.

## Docker / Coolify

### Option A — Dockerfile mode (default Coolify “Dockerfile” build)

Root `Dockerfile` builds the **engine + API** (paper by default). Coolify sets `PORT`; health check path: `/health`.

```bash
docker build -t weatherbuyend .
docker run --rm -p 3847:3847 -e PORT=3847 weatherbuyend
# → http://127.0.0.1:3847/health
```

In Coolify: Build Pack = **Dockerfile**, Dockerfile location = `/Dockerfile` (repo root), Port = `3847` (or whatever Coolify assigns via `PORT`).

### Option B — Compose mode (engine + dashboard + redis)

```bash
cp .env.example .env
docker compose up --build
```

| Service     | Port | Role                        |
|-------------|------|-----------------------------|
| `engine`    | 3847 | METAR + exec loop + FastAPI |
| `dashboard` | 3851 | Next.js mobile ops UI       |
| `redis`     | 6379 | Shared status / heartbeats  |

In Coolify: use **Docker Compose**, compose file `docker-compose.yml`. Inject secrets as env (`PMXT_API_KEY`, etc.) — never bake into the image. Set dashboard `NEXT_PUBLIC_API_URL` to the public engine URL.

## Live trading (opt-in)

Defaults are safe:

- `TRADING_MODE=paper`
- `LIVE_TRADING=false`
- `MOCK_MARKETS=true`

To enable live PMXT orders (tiny caps in `config/strategy.yaml`):

```env
TRADING_MODE=live
LIVE_TRADING=true
MOCK_MARKETS=false
PMXT_API_KEY=...
PMXT_WALLET_ADDRESS=...
```

Without both `TRADING_MODE=live` **and** `LIVE_TRADING=true`, orders stay paper.

## Strategy gates

From `config/strategy.yaml` (aligned with observed HighTempTation sleeve):

| Gate | Value |
|------|-------|
| Hard METAR elim | required |
| Hours to local noon | ≤ 6 |
| NO price | 0.80 – 0.985 |
| Min edge vs `p_no=0.99` | ≥ 0.015 |
| Order | FOK/IOC taker BUY NO |
| Hold | resolution (scalp exit = later phase) |

Cities: `config/cities.yaml` (filter with `CITY_ROLES`).

## API surface

- `GET /health` — Coolify health
- `GET /api/snapshot` — status, cities, positions, fills, controls
- `POST /api/controls/kill` `{ "reason": "manual" }`
- `POST /api/controls/arm`
- `POST /api/controls/sleeve` `{ "enabled": true }`
- `POST /api/controls/stake` `{ "multiplier": 1.0 }`

## Tests

```bash
source .venv/bin/activate
export PYTHONPATH=engine
pip install pytest
pytest engine/tests -q
```

## Layout

```
config/           cities + strategy
engine/           Python exec + FastAPI
dashboard/        Next.js ops UI
docker-compose.yml
.env.example
```

## Safety

- Never commit `.env` or API keys.
- Paper mode is the default path for Coolify first deploys.
- Global kill switch and METAR-staleness / daily-loss / venue-error circuit breakers are on the hot path.
