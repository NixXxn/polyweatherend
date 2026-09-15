"""IEM ASOS / METAR ingest for hard bucket elimination."""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

IEM_ASOS = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"


@dataclass
class DayState:
    local_day: str
    last_temp: float | None
    tmax_so_far: float | None
    tmin_so_far: float | None
    obs_utc: datetime | None
    obs_age_minutes: float | None
    n_obs: int
    station: str


def parse_temp_c_from_metar(metar: str) -> Optional[float]:
    if not metar:
        return None
    m = re.search(r"\bT([01])(\d{3})([01])(\d{3})\b", metar)
    if m:
        sign = -1 if m.group(1) == "1" else 1
        return sign * int(m.group(2)) / 10.0
    m2 = re.search(r"\b(M?\d{1,2})/(M?\d{1,2})\b", metar)
    if m2:
        raw = m2.group(1)
        try:
            return -float(raw[1:]) if raw.startswith("M") else float(raw)
        except ValueError:
            return None
    return None


def c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def f_to_native(temp_f: float, unit: str) -> float:
    if unit.lower().startswith("c"):
        return (temp_f - 32.0) * 5.0 / 9.0
    return temp_f


def fetch_asos_recent(station: str, *, hours: int = 36, timeout: float = 60.0) -> list[dict[str, Any]]:
    """Fetch recent ASOS obs for an IEM station id (e.g. LGA, MIA)."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=max(2, hours // 24 + 1))
    ets = end + timedelta(days=1)
    params = [
        ("station", station),
        ("data", "tmpf"),
        ("data", "metar"),
        ("year1", str(start.year)),
        ("month1", str(start.month)),
        ("day1", str(start.day)),
        ("year2", str(ets.year)),
        ("month2", str(ets.month)),
        ("day2", str(ets.day)),
        ("tz", "UTC"),
        ("format", "onlycomma"),
        ("latlon", "no"),
        ("elev", "no"),
        ("missing", "null"),
        ("trace", "null"),
        ("direct", "yes"),
        ("report_type", "1"),
        ("report_type", "2"),
    ]
    url = IEM_ASOS + "?" + urlencode(params)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        text = r.text.strip()
    if not text or "station,valid" not in text.split("\n", 1)[0]:
        return []
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        valid = row.get("valid")
        if not valid:
            continue
        try:
            obs = datetime.fromisoformat(valid.replace("Z", "+00:00"))
            if obs.tzinfo is None:
                obs = obs.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        tmpf: float | None = None
        raw = (row.get("tmpf") or "").strip()
        if raw and raw.lower() not in {"null", "m", "none"}:
            try:
                tmpf = float(raw)
            except ValueError:
                tmpf = None
        if tmpf is None:
            c = parse_temp_c_from_metar(row.get("metar") or "")
            if c is not None:
                tmpf = c_to_f(c)
        if tmpf is None:
            continue
        rows.append({"station": station, "valid_utc": obs, "tmpf": tmpf, "metar": row.get("metar")})
    rows.sort(key=lambda x: x["valid_utc"])
    return rows


def day_state(
    obs: list[dict[str, Any]],
    *,
    tz_name: str,
    unit: str,
    station: str,
    asof: datetime | None = None,
    target_date_local: str | None = None,
) -> DayState:
    asof = asof or datetime.now(timezone.utc)
    if asof.tzinfo is None:
        asof = asof.replace(tzinfo=timezone.utc)
    tz = ZoneInfo(tz_name)
    local_day = target_date_local or asof.astimezone(tz).date().isoformat()

    day_rows = []
    for row in obs:
        if row["valid_utc"] > asof:
            continue
        if row["valid_utc"].astimezone(tz).date().isoformat() != local_day:
            continue
        day_rows.append(row)

    if not day_rows:
        return DayState(
            local_day=local_day,
            last_temp=None,
            tmax_so_far=None,
            tmin_so_far=None,
            obs_utc=None,
            obs_age_minutes=None,
            n_obs=0,
            station=station,
        )

    temps_f = [float(r["tmpf"]) for r in day_rows]
    temps_n = [f_to_native(t, unit) for t in temps_f]
    last = day_rows[-1]
    age = (asof - last["valid_utc"]).total_seconds() / 60.0
    return DayState(
        local_day=local_day,
        last_temp=temps_n[-1],
        tmax_so_far=max(temps_n),
        tmin_so_far=min(temps_n),
        obs_utc=last["valid_utc"],
        obs_age_minutes=age,
        n_obs=len(day_rows),
        station=station,
    )


def hours_to_local_noon(tz_name: str, asof: datetime | None = None) -> float:
    """Hours until local noon today (negative = after noon)."""
    asof = asof or datetime.now(timezone.utc)
    if asof.tzinfo is None:
        asof = asof.replace(tzinfo=timezone.utc)
    tz = ZoneInfo(tz_name)
    local = asof.astimezone(tz)
    noon = local.replace(hour=12, minute=0, second=0, microsecond=0)
    return (noon - local).total_seconds() / 3600.0


def is_eliminated_highest(*, tmax_so_far: float | None, lo: float | None, hi: float | None) -> bool:
    """Hard elim for highest-temp range buckets: running max already above bucket hi."""
    if tmax_so_far is None or hi is None:
        return False
    return float(tmax_so_far) > float(hi)


def is_eliminated_lowest(*, tmin_so_far: float | None, lo: float | None, hi: float | None) -> bool:
    """Hard elim for lowest-temp range: running min already below bucket lo."""
    if tmin_so_far is None or lo is None:
        return False
    return float(tmin_so_far) < float(lo)


def mock_day_state(city: dict[str, Any], *, tmax: float | None = None) -> DayState:
    """Synthetic METAR day-state for paper/demo when IEM is rate-limited."""
    from zoneinfo import ZoneInfo
    now = datetime.now(timezone.utc)
    tz = ZoneInfo(city.get("timezone") or "UTC")
    local_day = now.astimezone(tz).date().isoformat()
    unit = (city.get("temperature_unit") or "fahrenheit").lower()
    # Default tmax high enough to eliminate low mock buckets (50-51 / 60-61)
    if tmax is None:
        tmax = 88.0 if unit.startswith("f") else 32.0
    station = city.get("iem_station") or city.get("icao", "")[-3:]
    return DayState(
        local_day=local_day,
        last_temp=float(tmax) - 1.0,
        tmax_so_far=float(tmax),
        tmin_so_far=float(tmax) - 10.0,
        obs_utc=now,
        obs_age_minutes=2.0,
        n_obs=12,
        station=station,
    )
