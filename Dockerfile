# WeatherBuyEnd — Coolify default image (Dockerfile build mode)
# Builds the paper/live exec engine + FastAPI ops API.
# Coolify injects PORT; health is /health on that port.
#
# Full stack (redis + dashboard): use docker-compose.yml in Coolify Compose mode.

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY engine/requirements.txt /app/engine/requirements.txt
RUN pip install --no-cache-dir -r /app/engine/requirements.txt

COPY config /app/config
COPY engine /app/engine

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/engine
ENV API_HOST=0.0.0.0
ENV API_PORT=3847
ENV PORT=3847
ENV TRADING_MODE=paper
ENV LIVE_TRADING=false
ENV MOCK_MARKETS=true
ENV CITY_ROLES=paper,strict

RUN mkdir -p /app/data/ledger /app/logs

WORKDIR /app
EXPOSE 3847

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import os,urllib.request; p=os.environ.get('PORT') or os.environ.get('API_PORT') or '3847'; urllib.request.urlopen(f'http://127.0.0.1:{p}/health', timeout=4)"

CMD ["python", "-m", "weatherbuy"]
