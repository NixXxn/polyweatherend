# WeatherBuyEnd

Late-day Polymarket weather **BUY NO** bot for hard METAR-eliminated temperature buckets (HighTempTation-style sleeve), with a mobile ops dashboard. Phase-1: paper by default; live CLOB taker orders behind explicit flags.

## What it does

1. Polls IEM ASOS/METAR per city station.
2. Tracks weather bucket markets + NO book from **`https://clob.polymarket.com`** (mock books only if `MOCK_MARKETS=true`).
3. Gates entries with **hard METAR elim only**, post-noon preference (≤6h to noon), NO band `0.90–0.98` with min edge.
4. **Budget-aware sizing:** tickets scale with operating budget; max **75%** of budget may be open at once (25% cash reserve). Set budget from the ops UI or `BUDGET_USD`.
5. Scalp-or-hold: optional SELL NO near `0.99` when the book marks up; else hold-to-resolve.
6. Sends **FOK/IOC taker BUY NO** (paper fills unless `LIVE_TRADING=true`).
7. Mobile ops dashboard: hero **Budget / Gains**, kill / arm / sleeve / stake, city status, Polymarket links, CSV export.

## Quick start (local)

```bash
cp .env.example .env
# optional: paste PMXT_API_KEY for live CLOB orders (still paper unless LIVE_TRADING=true)

# API + loop
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r engine/requirements.txt
export PYTHONPATH=engine
export MOCK_MARKETS=false TRADING_MODE=paper LIVE_TRADING=false
python -m weatherbuy
# → http://127.0.0.1:3847/health

# Dashboard (other terminal)
cd dashboard && npm install && npm run dev -- -p 3851
# → http://127.0.0.1:3851
```

Optional Redis: `redis-server` or `docker run -p 6379:6379 redis:7-alpine`. Engine falls back to an in-memory + JSON ledger if Redis is down.

## Docker / Coolify

### Option A — Dockerfile mode (recommended for Coolify)

Root `Dockerfile` is a **multi-stage** build: Next.js ops UI + Python engine/API in **one container / one PORT**.

- `/` → mobile ops dashboard (HTML)
- `/api/*`, `/health`, `/docs` → FastAPI
- Browser calls are **same-origin** (`/api/...`) — do **not** set `NEXT_PUBLIC_API_URL` in Coolify for this mode

```bash
docker build -t weatherbuyend .
docker run --rm -p 3847:3847 -e PORT=3847 weatherbuyend
# → http://127.0.0.1:3847/          (ops UI)
# → http://127.0.0.1:3847/health    (JSON)
```

In Coolify: Build Pack = **Dockerfile**, Dockerfile = `/Dockerfile`, Port = Coolify `PORT` (or `3847`). Health path: `/health`.

### Option B — Compose mode (engine + dashboard + redis)

```bash
cp .env.example .env
docker compose up --build
```

| Service     | Port | Role                        |
|-------------|------|-----------------------------|
| `engine`    | 3847 | API + UI (same image)       |
| `dashboard` | 3851 | Optional separate Next UI   |
| `redis`     | 6379 | Shared status / heartbeats  |

For a **separate** dashboard service, set `NEXT_PUBLIC_API_URL` to the public engine URL. The unified Dockerfile image does not need it.

### Local split (engine + `next dev`)

```bash
# terminal 1
PYTHONPATH=engine python -m weatherbuy
# terminal 2
cd dashboard && NEXT_PUBLIC_API_URL=http://127.0.0.1:3847 npm run dev
```


## Live trading (opt-in)

Defaults are safe:

- `TRADING_MODE=paper`
- `LIVE_TRADING=false`
- `MOCK_MARKETS=false`

To enable live CLOB orders (tiny caps in `config/strategy.yaml`):

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
