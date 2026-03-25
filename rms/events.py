"""
Events — v7.2
CHANGES:
  - get_vacaciones_factor now actually reads from vacaciones cache
  - Connected to vacaciones.py module properly
  - No longer a stub returning 1.0
"""

import logging
from datetime import date, timedelta
from rms.utils import fmt

log = logging.getLogger(__name__)


def _easter(year):
    """Compute Easter Sunday for a given year."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def build_events():
    """Generate all automatic events for current and next year."""
    today = date.today()
    events = []

    for y in [today.year, today.year + 1]:
        pascua = _easter(y)
        dom_ramos = pascua - timedelta(days=7)
        events.append({
            "name": f"Semana Santa {y}",
            "from": fmt(dom_ramos - timedelta(days=1)),
            "to": fmt(pascua + timedelta(days=1)),
            "factor": 1.30, "minStayOverride": 5, "floorOverride": 160,
        })

        festivos = [
            {"name": "Año Nuevo", "m": 1, "d": 1, "factor": 1.25, "minStay": 4, "rB": 1, "rA": 1, "floor": 160},
            {"name": "Reyes", "m": 1, "d": 6, "factor": 1.15, "rB": 1, "rA": 0, "floor": 130},
            {"name": "Día del Trabajo", "m": 5, "d": 1, "factor": 1.10, "rB": 0, "rA": 0},
            {"name": "Asunción", "m": 8, "d": 15, "factor": 1.10, "rB": 1, "rA": 1},
            {"name": "Fiesta Nacional", "m": 10, "d": 12, "factor": 1.15, "rB": 1, "rA": 0},
            {"name": "Todos los Santos", "m": 11, "d": 1, "factor": 1.10, "rB": 0, "rA": 0},
            {"name": "Constitución", "m": 12, "d": 6, "factor": 1.20, "rB": 0, "rA": 0},
            {"name": "Inmaculada", "m": 12, "d": 8, "factor": 1.20, "rB": 0, "rA": 0},
            {"name": "Navidad", "m": 12, "d": 25, "factor": 1.25, "minStay": 4, "rB": 1, "rA": 1, "floor": 160},
        ]

        for f in festivos:
            fecha = date(y, f["m"], f["d"])
            dow = fecha.weekday()  # 0=Mon
            fr = fecha - timedelta(days=f["rB"])
            to = fecha + timedelta(days=f["rA"])
            puente = ""
            if dow == 3:  # Thursday
                to = fecha + timedelta(days=2)
                puente = " (puente)"
            if dow == 1:  # Tuesday
                fr = fecha - timedelta(days=2)
                puente = " (puente)"

            ev = {"name": f"{f['name']}{puente} {y}", "from": fmt(fr), "to": fmt(to), "factor": f["factor"]}
            if f.get("minStay"):
                ev["minStayOverride"] = f["minStay"]
            if f.get("floor"):
                ev["floorOverride"] = f["floor"]
            events.append(ev)

        # Puente Constitución-Inmaculada
        d6 = date(y, 12, 6).weekday()
        if d6 in (3, 2):
            events.append({"name": f"Puente Constitución-Inmaculada {y}",
                          "from": f"{y}-12-05", "to": f"{y}-12-09", "factor": 1.20, "minStayOverride": 3})

        # Nochevieja
        events.append({"name": f"Nochevieja {y}",
                       "from": f"{y}-12-30", "to": f"{y+1}-01-02", "factor": 1.25, "minStayOverride": 4, "floorOverride": 160})

        # Local events
        events.append({"name": f"Dia Illes Balears {y}", "from": f"{y}-02-28", "to": f"{y}-03-02", "factor": 1.05})
        events.append({"name": f"Sant Joan {y}", "from": f"{y}-06-22", "to": f"{y}-06-25", "factor": 1.15})
        events.append({"name": f"Pico agosto inicio {y}", "from": f"{y}-07-31", "to": f"{y}-08-03", "factor": 1.10})

    # Filter to pricing horizon
    horizon = today + timedelta(days=365)
    events = [e for e in events if e["to"] >= fmt(today) and e["from"] <= fmt(horizon)]

    return events


def get_event_factor(date_str, events):
    """Get event factor for a given date."""
    best = {"factor": 1.0, "name": None, "minStay": None, "floorOverride": None}

    for ev in events:
        if ev["from"] <= date_str <= ev["to"]:
            if ev["factor"] > best["factor"]:
                best["factor"] = ev["factor"]
                best["name"] = ev["name"]
            ms = ev.get("minStayOverride")
            if ms and (not best["minStay"] or ms > best["minStay"]):
                best["minStay"] = ms
            fl = ev.get("floorOverride")
            if fl and (not best["floorOverride"] or fl > best["floorOverride"]):
                best["floorOverride"] = fl

    return best


# ══════════════════════════════════════════
# SCHOOL HOLIDAYS — Connected to vacaciones.py
# ══════════════════════════════════════════

_vacaciones_cache = None


def load_vacaciones_cache():
    """Load school holidays data from vacaciones module."""
    global _vacaciones_cache
    try:
        from rms.vacaciones import get_cached_vacaciones
        _vacaciones_cache = get_cached_vacaciones()
        if _vacaciones_cache:
            log.info(f"  Vacaciones cache loaded: {len(_vacaciones_cache)} dates with boost")
    except Exception as e:
        log.warning(f"  Could not load vacaciones cache: {e}")
        _vacaciones_cache = {}


def get_vacaciones_factor(date_str):
    """
    Get school holiday factor for a date.
    
    Returns a factor >= 1.0 based on how many school holiday
    markets (DE, NL, UK) overlap on this date.
    
    The vacaciones module pre-computes a dict:
        {date_str: {"factor": 1.08, "markets": ["DE", "NL"]}}
    """
    global _vacaciones_cache

    # Lazy load on first call
    if _vacaciones_cache is None:
        load_vacaciones_cache()

    if not _vacaciones_cache:
        return 1.0

    entry = _vacaciones_cache.get(date_str)
    if entry:
        return entry.get("factor", 1.0)

    return 1.0
