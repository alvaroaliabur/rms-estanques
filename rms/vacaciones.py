"""
Vacaciones Escolares — OpenHolidays API Integration
v7.2: Added get_cached_vacaciones() for events.py integration

CONCEPT:
When German/Dutch/UK schools are on holiday, demand for Mallorca
increases. We detect this automatically and boost prices proportionally
to how many source markets are simultaneously on holiday.

COUNTRIES & WEIGHTS (based on booking origin data):
- DE (Germany): 40% of bookings → weight 0.40
- NL (Netherlands): 25% → weight 0.25
- UK (United Kingdom): 20% → weight 0.20

BOOST CALCULATION:
- Sum weights of countries currently on school holiday
- Multiply by MAX_BOOST to get the factor
- Example: DE + NL on holiday = (0.40 + 0.25) × 0.20 = +13% boost

API: OpenHolidays (https://openholidaysapi.org) — free, no auth needed
"""

import logging
import requests
from datetime import date, timedelta
from collections import defaultdict
from rms import config

log = logging.getLogger(__name__)

# ══════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════

OPENHOLIDAYS_BASE = "https://openholidaysapi.org"

SOURCE_MARKETS = {
    "DE": {"weight": 0.40, "name": "Alemania"},
    "NL": {"weight": 0.25, "name": "Países Bajos"},
    "GB": {"weight": 0.20, "name": "Reino Unido"},
}

MAX_BOOST = 0.20  # +20%

_holiday_cache = {}
_holiday_cache_detailed = {}  # NEW: includes market info for events.py
_cache_date = None


# ══════════════════════════════════════════
# API CALLS
# ══════════════════════════════════════════

def fetch_subdivisions(country_code):
    try:
        url = f"{OPENHOLIDAYS_BASE}/Subdivisions?countryIsoCode={country_code}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        log.debug(f"  Subdivisions {country_code}: {e}")
    return []


def fetch_school_holidays(country_code, valid_from, valid_to, subdivision_code=None):
    params = {
        "countryIsoCode": country_code,
        "validFrom": valid_from,
        "validTo": valid_to,
        "languageIsoCode": "EN",
    }
    if subdivision_code:
        params["subdivisionCode"] = subdivision_code

    try:
        url = f"{OPENHOLIDAYS_BASE}/SchoolHolidays"
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        log.debug(f"  Holidays {country_code}/{subdivision_code}: {e}")
    return []


def extract_name(holiday):
    names = holiday.get("name", [])
    for n in names:
        if n.get("language") == "EN":
            return n.get("text", "Holiday")
    if names:
        return names[0].get("text", "Holiday")
    return "Holiday"


# ══════════════════════════════════════════
# HOLIDAY DATA PROCESSING
# ══════════════════════════════════════════

def download_all_holidays(valid_from, valid_to):
    all_holidays = []
    for country_code, market_info in SOURCE_MARKETS.items():
        weight = market_info["weight"]
        log.info(f"  Descargando vacaciones {country_code}...")
        try:
            holidays = fetch_school_holidays(country_code, valid_from, valid_to)
            for h in holidays:
                start = h.get("startDate", "")
                end = h.get("endDate", "")
                if start and end:
                    all_holidays.append({
                        "country": country_code,
                        "name": extract_name(h),
                        "start": start,
                        "end": end,
                        "weight": weight,
                        "subdivision": h.get("subdivisions", [{}])[0].get("code", "") if h.get("subdivisions") else "",
                    })
            log.info(f"    {country_code}: {len(holidays)} períodos")
        except Exception as e:
            log.warning(f"    {country_code}: error — {e}")
    return all_holidays


def compute_daily_multipliers(holidays, valid_from, valid_to):
    """
    For each date, calculate vacation boost AND track which markets are active.
    Returns: (multipliers, detailed)
        multipliers: {date_str: float}  (for backward compat)
        detailed: {date_str: {"factor": float, "markets": [str]}}  (for events.py)
    """
    date_coverage = defaultdict(set)
    for h in holidays:
        try:
            start = date.fromisoformat(h["start"])
            end = date.fromisoformat(h["end"])
            country = h["country"]
            sub = h.get("subdivision", "")
            current = start
            while current <= end:
                date_coverage[current.isoformat()].add((country, sub))
                current += timedelta(days=1)
        except (ValueError, KeyError):
            continue

    multipliers = {}
    detailed = {}
    d = date.fromisoformat(valid_from)
    end_d = date.fromisoformat(valid_to)

    while d <= end_d:
        ds = d.isoformat()
        entries = date_coverage.get(ds, set())
        if entries:
            countries_on_holiday = set(c for c, _ in entries)
            total_weight = sum(
                SOURCE_MARKETS[c]["weight"]
                for c in countries_on_holiday
                if c in SOURCE_MARKETS
            )
            boost = 1.0 + total_weight * MAX_BOOST
            if boost > 1.01:
                multipliers[ds] = round(boost, 3)
                detailed[ds] = {
                    "factor": round(boost, 3),
                    "markets": sorted(countries_on_holiday),
                }
        d += timedelta(days=1)

    return multipliers, detailed


# ══════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════

def actualizar_vacaciones():
    """Download school holidays and compute daily multipliers."""
    global _holiday_cache, _holiday_cache_detailed, _cache_date

    log.info("══ VACACIONES ESCOLARES ══")
    today = date.today()
    valid_from = today.isoformat()
    valid_to = (today + timedelta(days=365)).isoformat()

    holidays = download_all_holidays(valid_from, valid_to)
    if not holidays:
        log.warning("  No holiday data retrieved — keeping existing cache")
        return _holiday_cache

    multipliers, detailed = compute_daily_multipliers(holidays, valid_from, valid_to)

    _holiday_cache = multipliers
    _holiday_cache_detailed = detailed
    _cache_date = today

    dates_with_boost = len(multipliers)
    if dates_with_boost > 0:
        avg_boost = sum(multipliers.values()) / len(multipliers)
        max_boost_date = max(multipliers, key=multipliers.get)
        log.info(f"  ✅ {dates_with_boost} días con boost vacacional "
                 f"(media +{(avg_boost-1)*100:.1f}%, max +{(multipliers[max_boost_date]-1)*100:.1f}% el {max_boost_date})")
    else:
        log.info("  Sin períodos vacacionales en el horizonte")

    return multipliers


def get_vacaciones_factor(date_str):
    """Get the vacation multiplier for a specific date."""
    global _holiday_cache, _cache_date
    today = date.today()
    if not _cache_date or (today - _cache_date).days > 30:
        try:
            actualizar_vacaciones()
        except Exception as e:
            log.debug(f"  Vacation refresh failed: {e}")
    return _holiday_cache.get(date_str, 1.0)


def get_cached_vacaciones():
    """
    Return the detailed vacation cache for events.py integration.
    
    Returns: {date_str: {"factor": 1.08, "markets": ["DE", "NL"]}}
    
    Called by events.py load_vacaciones_cache() on first use.
    If cache is empty, triggers a refresh.
    """
    global _holiday_cache_detailed, _cache_date
    today = date.today()
    if not _cache_date or (today - _cache_date).days > 30 or not _holiday_cache_detailed:
        try:
            actualizar_vacaciones()
        except Exception as e:
            log.warning(f"  get_cached_vacaciones refresh failed: {e}")
    return _holiday_cache_detailed


def check_and_update_vacaciones():
    """Called daily — refreshes cache if needed."""
    global _cache_date
    today = date.today()
    if not _cache_date or (today - _cache_date).days > 30:
        return actualizar_vacaciones()
    return None
