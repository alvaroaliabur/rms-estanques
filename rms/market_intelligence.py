"""
AirROI — Market Intelligence for Colònia de Sant Jordi
v7.1: Real-time market data, comp set, occupancy, pacing

WHAT THIS GIVES US (that we didn't have before):
1. Market occupancy — how full is the ENTIRE market, not just us
2. Market ADR — real ADR from ALL properties, not just 8 competitors
3. Forward pacing — is the market booking ahead or behind vs LY
4. Booking lead time — how far ahead do guests actually book
5. Comp set with occupancy — not just their price, but how full they are
6. Future rates of competitors — 365 days of pricing data

API: AirROI (https://api.airroi.com)
Auth: X-API-KEY header
Cost: ~$0.60/day = ~$18/month
"""

import os
import logging
import requests
from datetime import date
from rms import config

log = logging.getLogger(__name__)

AIRROI_API_KEY = os.getenv("AIRROI_API_KEY", "")
AIRROI_BASE = "https://api.airroi.com"

# Colònia de Sant Jordi coordinates
PROPERTY_LAT = 39.3167
PROPERTY_LNG = 2.9889

# Market definition for AirROI
MARKET = {
    "country": "Spain",
    "region": "Balearic Islands",
    "locality": "ses Salines",
    "district": "Colònia de Sant Jordi",
}

# Cache to avoid redundant API calls within same day
_cache = {}
_cache_date = None


def _headers():
    return {"X-API-KEY": AIRROI_API_KEY, "Content-Type": "application/json"}


def _api_get(endpoint, params=None):
    """GET request to AirROI API."""
    try:
        resp = requests.get(
            f"{AIRROI_BASE}/{endpoint}",
            headers=_headers(),
            params=params,
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
        log.warning(f"  AirROI GET {endpoint}: {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        log.warning(f"  AirROI GET {endpoint}: {e}")
    return None


def _api_post(endpoint, payload):
    """POST request to AirROI API."""
    try:
        resp = requests.post(
            f"{AIRROI_BASE}/{endpoint}",
            headers=_headers(),
            json=payload,
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
        log.warning(f"  AirROI POST {endpoint}: {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        log.warning(f"  AirROI POST {endpoint}: {e}")
    return None


# ══════════════════════════════════════════
# 1. MARKET OCCUPANCY & ADR
# ══════════════════════════════════════════

def get_market_occupancy():
    """Get monthly occupancy rates for the market."""
    data = _api_post("markets/metrics/occupancy", {
        "market": MARKET,
        "num_months": 24,
    })
    if data:
        log.info(f"  📊 Market occupancy: {len(data.get('data', []))} months")
    return data


def get_market_adr():
    """Get monthly ADR for the market."""
    data = _api_post("markets/metrics/average-daily-rate", {
        "market": MARKET,
        "num_months": 24,
    })
    if data:
        log.info(f"  📊 Market ADR: {len(data.get('data', []))} months")
    return data


# ══════════════════════════════════════════
# 2. FORWARD PACING
# ══════════════════════════════════════════

def get_market_pacing():
    """Get forward-looking pacing data — is the market booking ahead or behind."""
    data = _api_post("markets/metrics/future/pacing", {
        "market": MARKET,
    })
    if data:
        log.info(f"  📊 Market pacing data received")
    return data


# ══════════════════════════════════════════
# 3. BOOKING LEAD TIME
# ══════════════════════════════════════════

def get_booking_lead_time():
    """Get how far ahead guests book in this market."""
    data = _api_post("markets/metrics/booking-lead-time", {
        "market": MARKET,
        "num_months": 12,
    })
    if data:
        log.info(f"  📊 Booking lead time data received")
    return data


# ══════════════════════════════════════════
# 4. COMP SET — Properties near us with performance data
# ══════════════════════════════════════════

def get_comp_set():
    """
    Find comparable properties within 2km radius.
    Returns properties with their occupancy, ADR, and revenue — 
    not just price like Apify.
    """
    data = _api_post("listings/search/radius", {
        "latitude": PROPERTY_LAT,
        "longitude": PROPERTY_LNG,
        "radius_miles": 2,
        "filter": {
            "room_type": {"eq": "entire_home"},
            "bedrooms": {"range": [1, 4]},
            "rating_overall": {"gte": 4.0},
        },
        "sort": {"ttm_revenue": "desc"},
        "pagination": {"page_size": 10, "offset": 0},
        "currency": "native",
    })
    
    if data and data.get("data"):
        listings = data["data"]
        log.info(f"  📊 Comp set: {len(listings)} propiedades encontradas")
        
        # Extract key metrics
        comp_metrics = []
        for l in listings:
            comp_metrics.append({
                "name": l.get("listing_title", "")[:50],
                "bedrooms": l.get("bedrooms", 0),
                "rating": l.get("rating_overall", 0),
                "ttm_adr": l.get("ttm_avg_rate", 0),
                "ttm_occ": l.get("ttm_occupancy", 0),
                "ttm_revenue": l.get("ttm_revenue", 0),
                "l90d_adr": l.get("l90d_avg_rate", 0),
                "l90d_occ": l.get("l90d_occupancy", 0),
            })
        
        return comp_metrics
    
    return None


# ══════════════════════════════════════════
# 5. COMPETITOR FUTURE RATES
# ══════════════════════════════════════════

def get_comp_future_rates(listing_id):
    """Get 365 days of future rates for a specific competitor listing."""
    data = _api_get("listings/future/rates", {"id": listing_id})
    return data


# ══════════════════════════════════════════
# 6. MARKET SUMMARY
# ══════════════════════════════════════════

def get_market_summary():
    """Get a complete summary of the market."""
    data = _api_post("markets/summary", {
        "market": MARKET,
    })
    if data:
        log.info(f"  📊 Market summary received")
    return data


# ══════════════════════════════════════════
# MAIN: Daily market intelligence update
# ══════════════════════════════════════════

def actualizar_market_intelligence():
    """
    Fetch all market data from AirROI.
    Called daily as part of the pricing pipeline.
    
    Updates config with fresh market data that the pricing
    engine uses for better decisions.
    """
    global _cache, _cache_date
    
    if not AIRROI_API_KEY:
        log.info("  No AIRROI_API_KEY — using static market data")
        return None
    
    today = date.today()
    
    # Only fetch once per day
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
    if occ and occ.get("data"):
        intelligence["occupancy"] = occ["data"]
        # Update config with fresh market occupancy
        _update_market_occ(occ["data"])
    
    # 3. ADR by month
    adr = get_market_adr()
    if adr and adr.get("data"):
        intelligence["adr"] = adr["data"]
        # Update ADR_PEER with real market data
        _update_market_adr(adr["data"])
    
    # 4. Forward pacing
    pacing = get_market_pacing()
    if pacing:
        intelligence["pacing"] = pacing
    
    # 5. Booking lead time
    lead_time = get_booking_lead_time()
    if lead_time:
        intelligence["lead_time"] = lead_time
    
    # 6. Comp set
    comp_set = get_comp_set()
    if comp_set:
        intelligence["comp_set"] = comp_set
        _log_comp_set_summary(comp_set)
    
    _cache = intelligence
    _cache_date = today
    
    log.info(f"  ✅ Market intelligence actualizada ({len(intelligence)} datasets)")
    return intelligence


def _update_market_occ(occ_data):
    """Update market occupancy in config for use by pricing engine."""
    # Store as market_occ_by_month for Claude API and forecast
    if not hasattr(config, 'MARKET_OCC'):
        config.MARKET_OCC = {}
    
    for entry in occ_data:
        month = entry.get("month")
        occ = entry.get("occupancy") or entry.get("value")
        if month and occ:
            config.MARKET_OCC[month] = occ


def _update_market_adr(adr_data):
    """Update ADR_PEER with real market data from AirROI."""
    for entry in adr_data:
        month = entry.get("month")
        adr = entry.get("adr") or entry.get("value")
        if month and adr and adr > 0:
            # Only update if we have a valid number
            old = config.COMP_SET["ADR_PEER"].get(month, 0)
            config.COMP_SET["ADR_PEER"][month] = round(adr)
            if old != round(adr):
                log.info(f"    ADR_PEER M{month}: {old}€ → {round(adr)}€ (AirROI)")


def _log_comp_set_summary(comp_set):
    """Log a summary of the comp set for visibility."""
    if not comp_set:
        return
    
    adrs = [c["ttm_adr"] for c in comp_set if c["ttm_adr"] > 0]
    occs = [c["ttm_occ"] for c in comp_set if c["ttm_occ"] > 0]
    
    if adrs:
        avg_adr = round(sum(adrs) / len(adrs))
        log.info(f"    Comp set ({len(comp_set)} props): ADR medio {avg_adr}€, "
                 f"Occ media {round(sum(occs)/len(occs)*100) if occs else 0}%")
    
    # Log top 5 competitors
    for c in comp_set[:5]:
        log.info(f"      {c['name'][:40]}: ADR {c['ttm_adr']}€, "
                 f"Occ {round(c['ttm_occ']*100) if c['ttm_occ'] else 0}%")


def check_and_update_market():
    """Called daily — fetches market intelligence."""
    return actualizar_market_intelligence()
