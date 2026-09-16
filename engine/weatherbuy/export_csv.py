"""CSV export helpers for spreadsheet analysis."""

from __future__ import annotations

import csv
import io
from typing import Any, Iterable


TRADE_COLUMNS = [
    "type",
    "result",
    "ts",
    "fill_id",
    "market_id",
    "location_id",
    "city",
    "side",
    "price",
    "size_usd",
    "shares",
    "exit_price",
    "pnl_usd",
    "hold_sec",
    "edge",
    "mode",
    "order_type",
    "latency_ms",
    "status",
    "question",
    "reason",
    "budget_usd",
    "gains_usd",
    "open_notional",
    "deployable_usd",
]


def _row(values: dict[str, Any]) -> dict[str, Any]:
    return {k: values.get(k, "") for k in TRADE_COLUMNS}


def build_analysis_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    status = snapshot.get("status") or {}
    pnl = snapshot.get("pnl") or {}
    money_ctx = {
        "budget_usd": status.get("budget_usd", pnl.get("budget_usd")),
        "gains_usd": status.get("gains_usd", pnl.get("gains_usd", status.get("pnl_today"))),
        "open_notional": status.get("open_notional", pnl.get("open_notional")),
        "deployable_usd": status.get("deployable_usd", pnl.get("deployable_usd")),
    }

    for s in snapshot.get("settlements") or []:
        result = str(s.get("result") or "").lower()
        rows.append(
            _row(
                {
                    "type": "settlement",
                    "result": result or ("win" if float(s.get("pnl_usd") or 0) >= 0 else "loss"),
                    "ts": s.get("ts"),
                    "fill_id": s.get("fill_id") or s.get("settlement_id"),
                    "market_id": s.get("market_id"),
                    "location_id": s.get("location_id"),
                    "city": s.get("city"),
                    "side": s.get("side") or "BUY_NO",
                    "price": s.get("entry_price"),
                    "size_usd": s.get("size_usd"),
                    "shares": s.get("shares"),
                    "exit_price": s.get("exit_price"),
                    "pnl_usd": s.get("pnl_usd"),
                    "hold_sec": s.get("hold_sec"),
                    "edge": s.get("edge"),
                    "mode": s.get("mode"),
                    "status": s.get("status") or "settled",
                    "question": s.get("question"),
                    "reason": s.get("reason"),
                    **money_ctx,
                }
            )
        )

    settled_markets = {str(s.get("market_id")) for s in (snapshot.get("settlements") or [])}
    for f in snapshot.get("fills") or []:
        mid = str(f.get("market_id") or "")
        # Open fills that later settled are still useful as trade entries;
        # mark them as trade (entry). Settlements carry win/loss.
        rows.append(
            _row(
                {
                    "type": "trade",
                    "result": "open" if mid not in settled_markets else "entered",
                    "ts": f.get("ts"),
                    "fill_id": f.get("fill_id"),
                    "market_id": mid,
                    "location_id": f.get("location_id"),
                    "city": f.get("city") or f.get("location_id"),
                    "side": f.get("side") or "BUY_NO",
                    "price": f.get("price"),
                    "size_usd": f.get("size_usd"),
                    "shares": f.get("shares"),
                    "edge": f.get("edge"),
                    "mode": f.get("mode"),
                    "order_type": f.get("order_type"),
                    "latency_ms": f.get("latency_ms"),
                    "status": f.get("status"),
                    "question": f.get("question"),
                    **money_ctx,
                }
            )
        )

    for sk in snapshot.get("skips") or []:
        rows.append(
            _row(
                {
                    "type": "skip",
                    "result": "skipped",
                    "ts": sk.get("ts"),
                    "market_id": sk.get("market_id"),
                    "location_id": sk.get("location_id"),
                    "city": sk.get("city") or sk.get("location_id"),
                    "side": "BUY_NO",
                    "price": sk.get("no_price"),
                    "edge": sk.get("edge"),
                    "mode": sk.get("mode") or "paper",
                    "status": "skipped",
                    "question": sk.get("question"),
                    "reason": sk.get("reason"),
                    **money_ctx,
                }
            )
        )

    # Newest first for spreadsheet scanning
    rows.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    return rows


def rows_to_csv(rows: Iterable[dict[str, Any]], columns: list[str] | None = None) -> str:
    cols = columns or TRADE_COLUMNS
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in cols})
    return buf.getvalue()


def filter_rows(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    kind = kind.lower()
    if kind in {"all", "analysis"}:
        return rows
    if kind == "trades":
        return [r for r in rows if r.get("type") == "trade"]
    if kind == "skips":
        return [r for r in rows if r.get("type") == "skip"]
    if kind == "wins":
        return [r for r in rows if r.get("type") == "settlement" and r.get("result") == "win"]
    if kind == "losses":
        return [r for r in rows if r.get("type") == "settlement" and r.get("result") == "loss"]
    if kind == "settlements":
        return [r for r in rows if r.get("type") == "settlement"]
    return rows
