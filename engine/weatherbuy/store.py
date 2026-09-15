"""Redis + local JSON ledger for positions / fills / status."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import repo_root
from .venue import Fill

logger = logging.getLogger(__name__)

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore


class Store:
    def __init__(self, redis_url: str, ledger_dir: str | Path = "data/ledger"):
        self._lock = threading.RLock()
        self.ledger_dir = Path(ledger_dir)
        if not self.ledger_dir.is_absolute():
            self.ledger_dir = repo_root() / self.ledger_dir
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.fills_path = self.ledger_dir / "fills.jsonl"
        self.skips_path = self.ledger_dir / "skips.jsonl"
        self.settlements_path = self.ledger_dir / "settlements.jsonl"
        self.state_path = self.ledger_dir / "state.json"

        self._memory: dict[str, Any] = {
            "status": {},
            "cities": [],
            "positions": [],
            "fills": [],
            "skips": [],
            "settlements": [],
            "controls": {},
            "pnl": {"realized": 0.0, "unrealized": 0.0, "today": 0.0},
        }
        self._r = None
        if redis is not None:
            try:
                self._r = redis.Redis.from_url(redis_url, decode_responses=True)
                self._r.ping()
            except Exception as e:
                logger.warning("Redis unavailable (%s); using in-memory store", e)
                self._r = None

        self._load_local()

    def _load_local(self) -> None:
        if self.state_path.exists():
            try:
                self._memory.update(json.loads(self.state_path.read_text()))
            except Exception:
                logger.exception("Failed to load state.json")
        if self.fills_path.exists():
            fills = []
            for line in self.fills_path.read_text().splitlines()[-200:]:
                try:
                    fills.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            self._memory["fills"] = fills
        self._memory["skips"] = self._read_jsonl(self.skips_path, 400)
        self._memory["settlements"] = self._read_jsonl(self.settlements_path, 300)


    def _read_jsonl(self, path: Path, n: int) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text().splitlines()[-n:]:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def _persist(self) -> None:
        payload = {
            "status": self._memory.get("status", {}),
            "cities": self._memory.get("cities", []),
            "positions": self._memory.get("positions", []),
            "controls": self._memory.get("controls", {}),
            "pnl": self._memory.get("pnl", {}),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.state_path.write_text(json.dumps(payload, indent=2))
        if self._r:
            try:
                self._r.set("weatherbuy:state", json.dumps(payload))
                self._r.set("weatherbuy:cities", json.dumps(self._memory.get("cities", [])))
                self._r.set("weatherbuy:fills", json.dumps(self._memory.get("fills", [])[-50:]))
            except Exception as e:
                logger.debug("redis write failed: %s", e)

    def set_status(self, status: dict[str, Any]) -> None:
        with self._lock:
            self._memory["status"] = status
            self._persist()

    def set_cities(self, cities: list[dict[str, Any]]) -> None:
        with self._lock:
            self._memory["cities"] = cities
            self._persist()

    def set_controls(self, controls: dict[str, Any]) -> None:
        with self._lock:
            self._memory["controls"] = controls
            self._persist()

    def set_pnl(self, pnl: dict[str, Any]) -> None:
        with self._lock:
            self._memory["pnl"] = pnl
            self._persist()

    def set_positions(self, positions: list[dict[str, Any]]) -> None:
        with self._lock:
            self._memory["positions"] = positions
            self._persist()

    def append_fill(self, fill: Fill | dict[str, Any]) -> None:
        row = asdict(fill) if isinstance(fill, Fill) else dict(fill)
        with self._lock:
            fills = list(self._memory.get("fills") or [])
            fills.append(row)
            self._memory["fills"] = fills[-200:]
            with self.fills_path.open("a") as f:
                f.write(json.dumps(row) + "\n")
            self._persist()


    def append_skip(self, skip: dict[str, Any]) -> None:
        with self._lock:
            skips = list(self._memory.get("skips") or [])
            skips.append(skip)
            self._memory["skips"] = skips[-400:]
            with self.skips_path.open("a") as f:
                f.write(json.dumps(skip) + "\n")

    def append_settlement(self, settlement: dict[str, Any]) -> None:
        with self._lock:
            rows = list(self._memory.get("settlements") or [])
            rows.append(settlement)
            self._memory["settlements"] = rows[-300:]
            with self.settlements_path.open("a") as f:
                f.write(json.dumps(settlement) + "\n")
            self._persist()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": self._memory.get("status", {}),
                "cities": self._memory.get("cities", []),
                "positions": self._memory.get("positions", []),
                "fills": list(self._memory.get("fills") or [])[-80:][::-1],
                "skips": list(self._memory.get("skips") or [])[-80:][::-1],
                "settlements": list(self._memory.get("settlements") or [])[-80:][::-1],
                "controls": self._memory.get("controls", {}),
                "pnl": self._memory.get("pnl", {}),
            }

    def ping(self) -> dict[str, Any]:
        redis_ok = False
        if self._r:
            try:
                redis_ok = bool(self._r.ping())
            except Exception:
                redis_ok = False
        return {"redis": redis_ok, "ledger_dir": str(self.ledger_dir)}
