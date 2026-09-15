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
    app = create_app(settings, start_loop=True)
    uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_level="info")


if __name__ == "__main__":
    main()
