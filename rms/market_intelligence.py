"""
AirROI — Market Intelligence for Colònia de Sant Jordi
v7.2.1: Fixed _update_market_adr to NOT overwrite ADR_PEER

Market-level data (not competitor-specific — that's Apify's job).
AirROI tells us about the WHOLE MARKET. Apify tells us about our 8 competitors.

SCHEDULE: Wednesdays (same day as Apify comp set)
COST: ~$1.10/week = ~$5/month
"""

import os
import logging
import requests
from datetime import date
from rms import config

log = logging.getLogger(__name__)

AIRROI_API_KEY = os.getenv("AIRROI_API_KEY", "")
AIRROI_BASE = "https://api.airroi.com"

PROPERTY_LAT = 39.3167
PROPERTY_LNG = 2.9889

# Market definition — verified working with AirROI
MARKET = {
    "country": "Spain",
    "region": "Balearic Islands",
    "locality": "ses Salines",
    "district": "Colònia de Sant Jordi",
}

_cache = {}
_cache_date = None


def _headers():
    return {"X-API-KEY": AIRROI_API_KEY, "Content-Type": "application/json"}


def _api_get(endpoint, params=None):
    try:
        resp = requests.get(f"{AIRROI_BASE}/{endpoint}", headers=_headers(), params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        log.warning(f"  AirROI GET {endpoint}: {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        log.warning(f"  AirROI GET {endpoint}: {e}")
    return None


def _api_post(endpoint, payload):
    try:
        resp = requests.post(f"{AIRROI_BASE}/{endpoint}", headers=_headers(), json=payload, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        log.warning(f"  AirROI POST {endpoint}: {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        log.warning(f"  AirROI POST {endpoint}: {e}")
    return None


# ══════════════════════════════════════════
# MARKET METRICS
# ══════════════════════════════════════════

def _airroi_enabled():
    """Check if AirROI is enabled in config."""
    return getattr(config, 'AIRROI_ENABLED', True)


def get_market_occupancy():
    if not _airroi_enabled():
        return None
    data = _api_post("markets/metrics/occupancy", {"market": MARKET, "num_months": 24})
    if data:
        results = data.get("results", [])
        log.info(f"  📊 Market occupancy: {len(results)} months")
    return data

def get_market_adr():
    data = _api_post("markets/metrics/average-daily-rate", {"market": MARKET, "num_months": 24})
    if data:
        results = data.get("results", [])
        log.info(f"  📊 Market ADR: {len(results)} months")
    return data

def get_market_pacing():
    data = _api_post("markets/metrics/future/pacing", {"market": MARKET})
    if data:
        log.info(f"  📊 Market pacing data received")
    return data

def get_booking_lead_time():
    data = _api_post("markets/metrics/booking-lead-time", {"market": MARKET, "num_months": 12})
    if data:
        log.info(f"  📊 Booking lead time data received")
    return data

def get_market_summary():
    data = _api_post("markets/summary", {"market": MARKET})
    if data:
        log.info(f"  📊 Market summary received")
    return data


# ══════════════════════════════════════════
# COMP SET (AirROI — market-level, not peer group)
# ══════════════════════════════════════════

def get_comp_set():
    """Find comparable properties within 2 miles. Filtered for apartments (1-2 bed, 2-5 guests)."""
    data = _api_post("listings/search/radius", {
        "latitude": PROPERTY_LAT,
        "longitude": PROPERTY_LNG,
        "radius_miles": 2,
        "filter": {
            "room_type": {"eq": "entire_home"},
            "bedrooms": {"range": [1, 2]},
            "guests": {"range": [2, 5]},
            "rating_overall": {"gte": 4.0},
        },
        "sort": {"ttm_revenue": "desc"},
        "pagination": {"page_size": 10, "offset": 0},
        "currency": "native",
    })

    if data and data.get("results"):
        listings = data["results"]
        log.info(f"  📊 AirROI comp set: {len(listings)} propiedades (apartamentos 1-2hab, 2-5pax)")

        comp_metrics = []
        for l in listings:
            info = l.get("listing_info", {})
            perf = l.get("performance_metrics", {})
            loc = l.get("location_info", {})
            prop = l.get("property_details", {})
            ratings = l.get("ratings", {})

            comp_metrics.append({
                "name": info.get("listing_name", "")[:50],
                "bedrooms": prop.get("bedrooms", 0),
                "guests": prop.get("guests", 0),
                "rating": ratings.get("rating_overall", 0),
                "ttm_adr": perf.get("ttm_avg_rate", 0),
                "ttm_occ": perf.get("ttm_occupancy", 0),
                "ttm_revenue": perf.get("ttm_revenue", 0),
                "l90d_adr": perf.get("l90d_avg_rate", 0),
                "l90d_occ": perf.get("l90d_occupancy", 0),
            })

        return comp_metrics
    return None


# ══════════════════════════════════════════
# MAIN: Weekly market intelligence update
# ══════════════════════════════════════════

def actualizar_market_intelligence():
    """Fetch all market data from AirROI. Runs weekly on Wednesdays."""
    global _cache, _cache_date

    if not AIRROI_API_KEY:
        log.info("  No AIRROI_API_KEY — using static market data")
        return None

    today = date.today()

    if _cache_date == today and _cache:
        log.info("  Market intelligence cache vigente")
        return _cache

    log.info("══ MARKET INTELLIGENCE (AirROI) ══")

    intelligence = {}

    # 1. Market summary
    summary = get_market_summary()
    if summary:
        intelligence["summary"] = summary

    # 2. Occupancy by month
    occ = get_market_occupancy()
    if occ and occ.get("results"):
        intelligence["occupancy"] = occ["results"]
        _update_market_occ(occ["results"])

    # 3. ADR by month
    adr = get_market_adr()
    if adr and adr.get("results"):
        intelligence["adr"] = adr["results"]
        _update_market_adr(adr["results"])

    # 4. Forward pacing
    pacing = get_market_pacing()
    if pacing:
        intelligence["pacing"] = pacing

    # 5. Booking lead time
    lead_time = get_booking_lead_time()
    if lead_time:
        intelligence["lead_time"] = lead_time

    # 6. AirROI comp set (apartments only)
    comp_set = get_comp_set()
    if comp_set:
        intelligence["comp_set"] = comp_set
        _log_comp_set_summary(comp_set)

    _cache = intelligence
    _cache_date = today

    log.info(f"  ✅ Market intelligence actualizada ({len(intelligence)} datasets)")
    return intelligence


def _update_market_occ(occ_data):
    """Store market occupancy for pricing engine."""
    if not hasattr(config, 'MARKET_OCC'):
        config.MARKET_OCC = {}
    for entry in occ_data:
        d = entry.get("date", "")
        occ = entry.get("avg") or entry.get("occupancy") or entry.get("value")
        if d and occ:
            month = int(d[5:7])
            config.MARKET_OCC[month] = occ
            log.info(f"    Market occ M{month}: {round(occ*100)}%")


def _update_market_adr(adr_data):
    """Store market-wide ADR separately. Does NOT overwrite ADR_PEER.
    
    ADR_PEER is for direct competitors (Apify scraping).
    MARKET_ADR is for the whole market (AirROI) — used as context only.
    """
    if not hasattr(config, 'MARKET_ADR'):
        config.MARKET_ADR = {}
    for entry in adr_data:
        d = entry.get("date", "")
        adr = entry.get("avg") or entry.get("adr") or entry.get("value")
        if d and adr and adr > 0:
            month = int(d[5:7])
            config.MARKET_ADR[month] = round(adr)
            log.info(f"    Market ADR M{month}: {round(adr)}€ (AirROI — referencia, NO comp set)")


def _log_comp_set_summary(comp_set):
    if not comp_set:
        return
    adrs = [c["ttm_adr"] for c in comp_set if c["ttm_adr"] > 0]
    occs = [c["ttm_occ"] for c in comp_set if c["ttm_occ"] > 0]
    if adrs:
        avg_adr = round(sum(adrs) / len(adrs))
        avg_occ = round(sum(occs) / len(occs) * 100) if occs else 0
        log.info(f"    AirROI comp set ({len(comp_set)} props): ADR medio {avg_adr}€, Occ media {avg_occ}%")
    for c in comp_set[:5]:
        occ_pct = round(c['ttm_occ'] * 100) if c['ttm_occ'] else 0
        log.info(f"      {c['name'][:40]}: {c['bedrooms']}hab {c['guests']}pax, ADR {c['ttm_adr']}€, Occ {occ_pct}%")


def check_and_update_market():
    """Called daily — only fetches on Wednesdays. Uses cache other days."""
    global _cache
    today = date.today()

    if _cache:
        log.info("  Market intelligence cache vigente")
        return _cache

    if today.weekday() != 2:
        log.info("  AirROI: no es miércoles, usando datos existentes")
        return None

    return actualizar_market_intelligence()
