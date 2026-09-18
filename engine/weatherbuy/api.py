"""FastAPI ops API + optional static ops dashboard (same PORT for Coolify)."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings, repo_root
from .export_csv import TRADE_COLUMNS, build_analysis_rows, filter_rows, rows_to_csv
from .loop import ExecEngine

logger = logging.getLogger(__name__)

engine: ExecEngine | None = None

# Paths reserved for API / docs — never fall through to SPA.
_API_PREFIXES = ("api/", "health", "docs", "redoc", "openapi.json")


class KillBody(BaseModel):
    reason: str = "manual"


class SleeveBody(BaseModel):
    enabled: bool = True


class StakeBody(BaseModel):
    multiplier: float = Field(ge=0.0, le=5.0)


class BudgetBody(BaseModel):
    budget_usd: float = Field(ge=10.0, le=1_000_000.0)


def _resolve_ui_dir() -> Path | None:
    env = os.getenv("WEATHERBUY_UI_DIR")
    candidates = []
    if env:
        candidates.append(Path(env))
    root = repo_root()
    candidates.extend(
        [
            root / "ui",
            root / "dashboard" / "out",
            Path("/app/ui"),
        ]
    )
    for p in candidates:
        if (p / "index.html").is_file():
            return p
    return None


def _mount_dashboard(app: FastAPI) -> None:
    ui_dir = _resolve_ui_dir()
    if ui_dir is None:
        logger.warning("No static dashboard found; / will 404 until UI is built")
        return

    next_dir = ui_dir / "_next"
    if next_dir.is_dir():
        app.mount("/_next", StaticFiles(directory=next_dir), name="next_assets")

    index = ui_dir / "index.html"

    @app.get("/")
    async def spa_root() -> FileResponse:
        return FileResponse(index)

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        lowered = full_path.lstrip("/").lower()
        if lowered.startswith(_API_PREFIXES) or lowered in {"docs", "redoc", "openapi.json"}:
            raise HTTPException(404, "Not Found")

        candidate = ui_dir / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        # Next export with trailingSlash: try directory index
        as_dir = ui_dir / full_path / "index.html"
        if as_dir.is_file():
            return FileResponse(as_dir)
        htmlish = ui_dir / f"{full_path}.html"
        if htmlish.is_file():
            return FileResponse(htmlish)
        return FileResponse(index)

    logger.info("Serving ops dashboard from %s", ui_dir)


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
            "live_clob": bool(status.get("live_clob")),
            "poly_creds": require_engine().settings.has_poly_creds,
            "mock_markets": bool(status.get("mock_markets")),
            "redis": ping.get("redis"),
            "last_metar_ts": status.get("last_metar_ts"),
            "last_book_ts": status.get("last_book_ts"),
            "markets": status.get("markets_tracked"),
            "budget_usd": status.get("budget_usd"),
            "wallet_usd": status.get("wallet_usd"),
            "gains_usd": status.get("gains_usd"),
            "ui": _resolve_ui_dir() is not None,
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

    @app.post("/api/controls/budget")
    def api_budget(body: BudgetBody) -> dict[str, Any]:
        eng = require_engine()
        try:
            eng.set_budget(body.budget_usd)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return eng.store.snapshot()["controls"]

    # Mount UI last so /api and /health win route matching.
    _mount_dashboard(app)
    return app
