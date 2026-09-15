"""Entry point: Uvicorn API + background exec loop."""

from __future__ import annotations

import logging
import os

import uvicorn

from weatherbuy.api import create_app
from weatherbuy.config import Settings


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    settings = Settings()
    # Coolify / PaaS inject PORT; prefer it over API_PORT when set.
    port = int(os.getenv("PORT") or settings.api_port)
    host = os.getenv("API_HOST") or settings.api_host
    settings.api_port = port
    settings.api_host = host
    app = create_app(settings, start_loop=True)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
