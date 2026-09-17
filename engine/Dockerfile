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
ENV TRADING_MODE=paper
ENV LIVE_TRADING=false
ENV MOCK_MARKETS=false

RUN mkdir -p /app/data/ledger /app/logs

WORKDIR /app
EXPOSE 3847
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3847/health', timeout=4)"

CMD ["python", "-m", "weatherbuy"]
