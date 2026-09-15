"""FastAPI ops API for the mobile dashboard."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .config import Settings
from .export_csv import TRADE_COLUMNS, build_analysis_rows, filter_rows, rows_to_csv
from .loop import ExecEngine

logger = logging.getLogger(__name__)

engine: ExecEngine | None = None


class KillBody(BaseModel):
    reason: str = "manual"


class SleeveBody(BaseModel):
    enabled: bool = True


class StakeBody(BaseModel):
    multiplier: float = Field(ge=0.0, le=5.0)


def create_app(settings: Settings | None = None, start_loop: bool = True) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global engine
        engine = ExecEngine(settings)
        if start_loop:
            engine.start_background()
        logger.info("API up on %s:%s", settings.api_host, settings.api_port)
        yield
        if engine:
            engine.stop()

    app = FastAPI(title="WeatherBuyEnd", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def require_engine() -> ExecEngine:
        if engine is None:
            raise HTTPException(503, "engine not ready")
        return engine

    @app.get("/health")
    def health() -> dict[str, Any]:
        eng = require_engine()
        snap = eng.store.snapshot()
        ping = eng.store.ping()
        status = snap.get("status") or {}
        return {
            "ok": True,
            "mode": status.get("mode"),
            "armed": status.get("armed"),
            "redis": ping.get("redis"),
            "last_metar_ts": status.get("last_metar_ts"),
            "last_book_ts": status.get("last_book_ts"),
            "markets": status.get("markets_tracked"),
        }

    @app.get("/api/status")
    def api_status() -> dict[str, Any]:
        return require_engine().store.snapshot()["status"]

    @app.get("/api/snapshot")
    def api_snapshot() -> dict[str, Any]:
        return require_engine().store.snapshot()

    @app.get("/api/cities")
    def api_cities() -> list[dict[str, Any]]:
        return require_engine().store.snapshot()["cities"]

    @app.get("/api/positions")
    def api_positions() -> list[dict[str, Any]]:
        return require_engine().store.snapshot()["positions"]

    @app.get("/api/fills")
    def api_fills() -> list[dict[str, Any]]:
        return require_engine().store.snapshot()["fills"]

    @app.get("/api/pnl")
    def api_pnl() -> dict[str, Any]:
        return require_engine().store.snapshot()["pnl"]

    @app.get("/api/controls")
    def api_controls() -> dict[str, Any]:
        return require_engine().store.snapshot()["controls"]

    @app.get("/api/skips")
    def api_skips() -> list[dict[str, Any]]:
        return require_engine().store.snapshot().get("skips") or []

    @app.get("/api/settlements")
    def api_settlements() -> list[dict[str, Any]]:
        return require_engine().store.snapshot().get("settlements") or []

    @app.get("/api/export")
    def api_export(kind: str = "all") -> Response:
        """Spreadsheet export: kind=all|trades|skips|wins|losses|settlements."""
        snap = require_engine().store.snapshot()
        rows = filter_rows(build_analysis_rows(snap), kind)
        body = rows_to_csv(rows, TRADE_COLUMNS)
        filename = f"weatherbuyend-{kind}.csv"
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/controls/kill")
    def api_kill(body: KillBody) -> dict[str, Any]:
        eng = require_engine()
        eng.kill(body.reason)
        return eng.store.snapshot()["controls"]

    @app.post("/api/controls/arm")
    def api_arm() -> dict[str, Any]:
        eng = require_engine()
        eng.arm()
        return eng.store.snapshot()["controls"]

    @app.post("/api/controls/sleeve")
    def api_sleeve(body: SleeveBody) -> dict[str, Any]:
        eng = require_engine()
        eng.set_sleeve(body.enabled)
        return eng.store.snapshot()["controls"]

    @app.post("/api/controls/stake")
    def api_stake(body: StakeBody) -> dict[str, Any]:
        eng = require_engine()
        eng.set_stake_mult(body.multiplier)
        return eng.store.snapshot()["controls"]

    return app
