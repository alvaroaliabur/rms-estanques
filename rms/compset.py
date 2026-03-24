"""
Comp Set — Apify scraping of competitor prices
v7.1: Full implementation for Python/Railway

Replaces: actualizarCompSetApify_, scrapearCompSet_, buildApifyADRByMonth_

PROCESS:
1. Run Apify booking-scraper actor with competitor URLs
2. Wait for results
3. Parse prices, calculate ADR per month
4. Update config.COMP_SET.ADR_PEER
5. Store historical data for trend analysis

SCHEDULE:
- Weekly (every Wednesday, matching GAS behavior)
- Can also run on demand
"""

import os
import time
import logging
import requests
from datetime import date, timedelta
from collections import defaultdict
from rms import config

log = logging.getLogger(__name__)

# ══════════════════════════════════════════
# APIFY CONFIG
# ══════════════════════════════════════════

APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
APIFY_ACTOR = "dtrber~booking-scraper"
APIFY_BASE = "https://api.apify.com/v2"

COMP_SET_URLS = [
    "https://www.booking.com/hotel/es/apartamentos-piza.es.html",
    "https://www.booking.com/hotel/es/apartamentos-lemar-colonia-de-sant-jordi.es.html",
    "https://www.booking.com/hotel/es/aparthotelisladecabrera.es.html",
    "https://www.booking.com/hotel/es/blue-house-mallorca.es.html",
    "https://www.booking.com/hotel/es/apartamentos-ibiza-colonia-de-sant-jordi1.es.html",
    "https://www.booking.com/hotel/es/villa-piccola-by-cassai.es.html",
    "https://www.booking.com/hotel/es/apartamentos-cala-figuera-cala-figuera.es.html",
    "https://www.booking.com/hotel/es/carrer-de-l-esglesia-1.es.html",
]

COMP_SET_NAMES = [
    "Apartamentos Piza", "Apartamentos Lemar", "Aparthotel Isla de Cabrera",
    "Blue House Mallorca", "Apartamentos Ibiza", "Villa Piccola by Cassai",
    "Apartamentos Cala Figuera", "Apartamentos Villa Sirena",
]

# Scrape windows: days ahead to check
SCRAPE_WINDOWS_DAYS = [7, 14, 30, 45]

SCRAPE_PROFILES = {
    "DEFAULT": {"nights": 3, "adults": 2},
    "SUMMER": {"nights": 7, "adults": 4},
}

SUMMER_MONTHS = [6, 7, 8, 9]
MAX_WAIT_SECONDS = 120
POLL_INTERVAL = 5


# ══════════════════════════════════════════
# APIFY API CALLS
# ══════════════════════════════════════════

def apify_run_and_wait(scrape_input):
    """Run Apify actor and wait for results."""
    if not APIFY_TOKEN:
        log.warning("  No APIFY_TOKEN configured — comp set not updated")
        return None
    
    # Start actor run
    url = f"{APIFY_BASE}/acts/{APIFY_ACTOR}/runs?token={APIFY_TOKEN}"
    try:
        resp = requests.post(url, json=scrape_input, timeout=30)
        if resp.status_code != 201:
            log.warning(f"  Apify start failed: {resp.status_code}")
            return None
        
        run_data = resp.json().get("data", {})
        run_id = run_data.get("id")
        if not run_id:
            log.warning("  Apify: no run ID returned")
            return None
    except Exception as e:
        log.warning(f"  Apify error: {e}")
        return None
    
    # Poll for completion
    elapsed = 0
    while elapsed < MAX_WAIT_SECONDS:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        
        try:
            status_url = f"{APIFY_BASE}/actor-runs/{run_id}?token={APIFY_TOKEN}"
            status_resp = requests.get(status_url, timeout=15)
            status_data = status_resp.json().get("data", {})
            status = status_data.get("status")
            
            if status == "SUCCEEDED":
                dataset_id = status_data.get("defaultDatasetId")
                if not dataset_id:
                    return None
                
                data_url = f"{APIFY_BASE}/datasets/{dataset_id}/items?token={APIFY_TOKEN}&format=json"
                data_resp = requests.get(data_url, timeout=30)
                if data_resp.status_code == 200:
                    return data_resp.json()
                return None
            
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                log.warning(f"  Apify run {status}")
                return None
        except Exception:
            continue
    
    log.warning(f"  Apify timeout after {MAX_WAIT_SECONDS}s")
    return None


def scrape_comp_set(check_in, check_out, adults=2):
    """Scrape competitor prices for a specific date range."""
    scrape_input = {
        "search": "Colònia de Sant Jordi",
        "checkIn": check_in,
        "checkOut": check_out,
        "adults": adults,
        "rooms": 1,
        "currency": "EUR",
        "language": "es",
        "propertyUrls": COMP_SET_URLS,
        "maxResults": 10,
    }
    
    results = apify_run_and_wait(scrape_input)
    if not results:
        return []
    
    nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
    parsed = []
    
    for r in results:
        price = r.get("price") or r.get("room_price") or r.get("min_price") or 0
        parsed.append({
            "name": r.get("name") or r.get("hotel_name") or "Desconocido",
            "checkIn": check_in,
            "checkOut": check_out,
            "price": price,
            "pricePerNight": round(price / nights) if price > 0 and nights > 0 else 0,
            "rating": r.get("rating", 0),
            "reviewCount": r.get("reviewCount", 0),
        })
    
    return parsed


# ══════════════════════════════════════════
# MAIN: Update Comp Set
# ══════════════════════════════════════════

# In-memory storage for comp set history (persists during Railway service lifetime)
_comp_set_history = []

def actualizar_comp_set():
    """
    Full comp set update: scrape all windows, calculate ADR by month,
    update config.COMP_SET.ADR_PEER.
    
    Should run weekly (Wednesdays).
    """
    if not APIFY_TOKEN:
        log.info("  Comp set: no APIFY_TOKEN, using static ADR_PEER")
        return None
    
    log.info("══ COMP SET APIFY ══")
    
    today = date.today()
    all_results = []
    
    for days_out in SCRAPE_WINDOWS_DAYS:
        ci = today + timedelta(days=days_out)
        ci_month = ci.month
        is_summer = ci_month in SUMMER_MONTHS
        
        profile = SCRAPE_PROFILES["SUMMER"] if is_summer else SCRAPE_PROFILES["DEFAULT"]
        co = ci + timedelta(days=profile["nights"])
        
        ci_str = ci.isoformat()
        co_str = co.isoformat()
        
        log.info(f"  Scraping +{days_out}d ({ci_str} → {co_str})...")
        results = scrape_comp_set(ci_str, co_str, profile["adults"])
        
        if results:
            prices = [r["pricePerNight"] for r in results if r["pricePerNight"] > 0]
            
            # Trimmed mean (remove outliers)
            if len(prices) >= 4:
                prices.sort()
                prices = prices[1:-1]
            
            adr_cs = round(sum(prices) / len(prices)) if prices else 0
            
            all_results.append({
                "checkIn": ci_str,
                "daysOut": days_out,
                "month": ci_month,
                "adrCompSet": adr_cs,
                "numProps": len(prices),
            })
            
            log.info(f"    +{days_out}d: ADR comp set = {adr_cs}€ ({len(prices)} props)")
        
        time.sleep(3)  # Rate limiting between scrapes
    
    if not all_results:
        log.warning("  No comp set data retrieved")
        return None
    
    # Update ADR_PEER by month
    by_month = defaultdict(list)
    for r in all_results:
        if r["adrCompSet"] > 0:
            by_month[r["month"]].append(r["adrCompSet"])
    
    updated_months = []
    for month, adrs in by_month.items():
        avg_adr = round(sum(adrs) / len(adrs))
        config.COMP_SET["ADR_PEER"][month] = avg_adr
        updated_months.append(f"M{month}={avg_adr}€")
    
    log.info(f"  ✅ ADR_PEER actualizado: {', '.join(updated_months)}")
    
    # Store in history
    _comp_set_history.append({
        "date": today.isoformat(),
        "results": all_results,
    })
    
    return all_results


def check_and_update_comp_set():
    """Called daily — only runs on Wednesdays."""
    today = date.today()
    if today.weekday() != 2:  # Wednesday = 2
        return None
    return actualizar_comp_set()
