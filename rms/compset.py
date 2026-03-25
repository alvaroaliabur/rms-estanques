"""
Comp Set — Apify scraping of Booking.com competitors
v7.2.1: Filter results to real comp set, 3 windows only, longer timeout

These are the REAL competitors from Booking.com peer group.
AirROI gives market-level data; Apify gives competitor-specific prices.

SCHEDULE: Wednesdays only
"""

import os
import time
import logging
import requests
from datetime import date, timedelta
from collections import defaultdict
from rms import config

log = logging.getLogger(__name__)

APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
APIFY_ACTOR = "voyager~booking-scraper"
APIFY_BASE = "https://api.apify.com/v2"

# The real competitors — used to FILTER scrape results
COMP_SET_NAMES_FILTER = [
    "apartamentos piza",
    "apartamentos lemar",
    "aparthotel isla de cabrera",
    "blue house",
    "apartamentos ibiza",
    "villa piccola",
    "edificio puerto",
    "apartamentos lago",
    "lavendel",
    "apartamento es trenc",
    "apartamento estándar",
    "edificio príncipe",
    "ses baules",
    "can vidal",
    "hotel isla de cabrera",
    "bluewater",
    "apartaments andreas",
    "apartaments posidonia",
]

# Only 3 windows — saves cost and covers short/medium/long term
SCRAPE_WINDOWS_DAYS = [7, 30, 60]

SCRAPE_PROFILES = {
    "DEFAULT": {"nights": 3, "adults": 2},
    "SUMMER": {"nights": 7, "adults": 2},
}

SUMMER_MONTHS = [6, 7, 8, 9]

MAX_WAIT_SECONDS = 180  # Increased from 120
POLL_INTERVAL = 5


def _is_comp_set(name):
    """Check if a property name matches our comp set."""
    if not name:
        return False
    name_lower = name.lower()
    # Exclude ourselves
    if "estanques" in name_lower:
        return False
    for comp in COMP_SET_NAMES_FILTER:
        if comp in name_lower:
            return True
    return False


def apify_run_and_wait(scrape_input):
    """Run Apify actor and wait for results."""
    if not APIFY_TOKEN:
        return None

    url = f"{APIFY_BASE}/acts/{APIFY_ACTOR}/runs?token={APIFY_TOKEN}"

    try:
        resp = requests.post(url, json=scrape_input, timeout=30)
        if resp.status_code != 201:
            log.warning(f"  Apify start failed: {resp.status_code}")
            return None
        run_data = resp.json().get("data", {})
        run_id = run_data.get("id")
        if not run_id:
            return None
    except Exception as e:
        log.warning(f"  Apify error: {e}")
        return None

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
        "maxResults": 30,
    }

    results = apify_run_and_wait(scrape_input)
    if not results:
        return []

    nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days

    parsed = []
    skipped = 0
    for r in results:
        name = r.get("name") or r.get("hotel_name") or "Desconocido"

        # FILTER: only keep comp set properties
        if not _is_comp_set(name):
            skipped += 1
            continue

        price = r.get("price") or r.get("room_price") or r.get("min_price") or 0
        parsed.append({
            "name": name,
            "checkIn": check_in,
            "checkOut": check_out,
            "price": price,
            "pricePerNight": round(price / nights) if price > 0 and nights > 0 else 0,
            "rating": r.get("rating", 0),
            "reviewCount": r.get("reviewCount", 0),
        })

    if skipped > 0:
        log.info(f"    Filtrado: {len(parsed)} comp set de {len(results)} total ({skipped} descartados)")

    return parsed


def actualizar_comp_set():
    """Full comp set update via Apify."""
    if not APIFY_TOKEN:
        log.info("  No APIFY_TOKEN — comp set not updated")
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

        log.info(f"  Scraping +{days_out}d ({ci_str}, {profile['nights']}n, {profile['adults']}a)...")
        results = scrape_comp_set(ci_str, co_str, profile["adults"])

        if results:
            prices = [r["pricePerNight"] for r in results if r["pricePerNight"] > 0]

            # Trimmed mean if enough data
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
                "details": results,
            })

            log.info(f"    +{days_out}d: ADR comp set = {adr_cs}€ ({len(prices)} props)")
            for r in results:
                if r["pricePerNight"] > 0:
                    log.info(f"      {r['name'][:30]}: {r['pricePerNight']}€/noche")

        time.sleep(3)

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
        old = config.COMP_SET["ADR_PEER"].get(month, 0)
        config.COMP_SET["ADR_PEER"][month] = avg_adr
        updated_months.append(f"M{month}: {old}→{avg_adr}€")

    log.info(f"  ✅ ADR_PEER actualizado: {', '.join(updated_months)}")

    return all_results


def check_and_update_comp_set():
    """Called daily — only runs on Wednesdays."""
    today = date.today()
    if today.weekday() != 2:
        return None
    return actualizar_comp_set()
