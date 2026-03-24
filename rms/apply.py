"""
Apply Prices — Write prices to Beds24 via API
v7.1: Full implementation with duration discount slots

Replaces: aplicarPrecios_, aplicarPreciosFecha_

PRICE SLOTS in Beds24:
- price1: Standard rate (base price, what /prices/compare shows)
- price3: 6-night rate
- price4: 5-night rate  
- price5: 4-night rate
- price10: Weekly (7+ night) rate

DURATION DISCOUNTS:
Discounts compress as occupancy rises (scarce inventory = less discount).
At 75%+ occupancy, discounts shrink to minimum levels.

BEDS24 API:
- POST /properties/{id}/rooms/{roomId}/offer1/calendar
- Body: [{date, price1, price3, price4, price5, price10, minStay}]
- Must set both UPPER (8 units) and GROUND (1 unit) rooms
"""

import logging
from datetime import date
from rms import config
from rms.beds24 import api_post
from rms.utils import clamp

log = logging.getLogger(__name__)


# ══════════════════════════════════════════
# DURATION DISCOUNTS
# ══════════════════════════════════════════

# Dynamic discounts: compress as occupancy rises
DURATION_DISCOUNTS = {
    "4NOCHES": {"base": 0.82, "min": 0.90},    # 18% off at low occ → 10% off at high occ
    "5NOCHES": {"base": 0.75, "min": 0.85},    # 25% off → 15% off
    "6NOCHES": {"base": 0.68, "min": 0.80},    # 32% off → 20% off
    "SEMANAL":  {"base": 0.60, "min": 0.75},    # 40% off → 25% off
}

# Floor factors: duration floors can be lower than standard floor
DURATION_FLOOR_FACTOR = {
    "4NOCHES": 0.92,
    "5NOCHES": 0.85,
    "6NOCHES": 0.78,
    "SEMANAL":  0.70,
}

OCC_LOW = 0.30   # Below this → full discount
OCC_HIGH = 0.75  # Above this → minimum discount


def calc_duration_price(base_price, slot_name, occ, suelo):
    """
    Calculate duration-discounted price for a slot.
    
    Discount compresses as occupancy rises:
    - At 30% occ → base discount (e.g., -25% for 5NOCHES)
    - At 75% occ → min discount (e.g., -15% for 5NOCHES)
    - Between → linear interpolation
    
    Floor protection: each duration slot has its own floor
    (slightly lower than standard to allow discounts to show).
    """
    disc = DURATION_DISCOUNTS.get(slot_name)
    if not disc:
        return base_price
    
    # Interpolate discount factor based on occupancy
    if occ <= OCC_LOW:
        factor = disc["base"]
    elif occ >= OCC_HIGH:
        factor = disc["min"]
    else:
        ratio = (occ - OCC_LOW) / (OCC_HIGH - OCC_LOW)
        factor = disc["base"] + (disc["min"] - disc["base"]) * ratio
    
    price = round(base_price * factor)
    
    # Apply duration-specific floor
    floor_factor = DURATION_FLOOR_FACTOR.get(slot_name, 1.0)
    duration_floor = round(suelo * floor_factor)
    
    return max(price, duration_floor)


# ══════════════════════════════════════════
# APPLY TO BEDS24
# ══════════════════════════════════════════

def build_calendar_entry(result):
    """
    Build a single calendar entry for Beds24 API.
    
    Returns dict with date, price1, price3, price4, price5, price10, minStay.
    """
    d = result["date"]
    base = result["precioFinal"]
    suelo = result.get("suelo", 50)
    occ = result.get("occNow", 0)
    min_stay = result.get("minStay", 3)
    
    entry = {
        "date": d,
        "price1": base,                                              # Standard
        "price3": calc_duration_price(base, "6NOCHES", occ, suelo),  # 6-night
        "price4": calc_duration_price(base, "5NOCHES", occ, suelo),  # 5-night
        "price5": calc_duration_price(base, "4NOCHES", occ, suelo),  # 4-night
        "price10": calc_duration_price(base, "SEMANAL", occ, suelo), # Weekly
        "minStay": min_stay,
    }
    
    return entry


def aplicar_precios(results):
    """
    Apply all calculated prices to Beds24.
    
    Sets prices for both room types:
    - ROOM_UPPER (269521): 8 upper floor apartments
    - ROOM_GROUND (269520): 1 ground floor apartment
    
    Ground floor uses same prices but may have different minStay
    (controlled by GROUND_FLOOR_LOS config).
    """
    if config.DRY_RUN:
        log.info("  🔒 DRY RUN — precios NO aplicados")
        return {"applied": False, "reason": "DRY_RUN"}
    
    if not results:
        log.warning("  No results to apply")
        return {"applied": False, "reason": "no_results"}
    
    log.info(f"  Aplicando precios a Beds24 ({len(results)} fechas)...")
    
    # Build calendar entries
    calendar_upper = []
    calendar_ground = []
    
    for r in results:
        entry = build_calendar_entry(r)
        calendar_upper.append(entry)
        
        # Ground floor: same prices, but minStay may differ
        ground_entry = entry.copy()
        ground_los = config.GROUND_FLOOR_LOS
        if ground_los and ground_los.get("enabled"):
            # Ground floor can have lower minStay in some seasons
            sc = r.get("seasonCode", "M")
            if sc not in ground_los.get("temporadas_protegidas", []):
                occ = r.get("occNow", 0)
                if occ > ground_los.get("upper_occ_threshold", 0.75):
                    ground_entry["minStay"] = max(
                        ground_los.get("absolute_min", 2),
                        entry["minStay"] - 1
                    )
        calendar_ground.append(ground_entry)
    
    # Apply in batches of 60 days (Beds24 API limit)
    batch_size = 60
    errors = []
    
    for room_id, calendar, room_name in [
        (config.ROOM_UPPER, calendar_upper, "Upper"),
        (config.ROOM_GROUND, calendar_ground, "Ground"),
    ]:
        for i in range(0, len(calendar), batch_size):
            batch = calendar[i:i + batch_size]
            
            try:
                endpoint = f"properties/{config.PROPERTY_ID}/rooms/{room_id}/offer1/calendar"
                response = api_post(endpoint, batch)
                
                if response is None:
                    errors.append(f"{room_name} batch {i//batch_size + 1}: API error")
            except Exception as e:
                errors.append(f"{room_name} batch {i//batch_size + 1}: {e}")
    
    if errors:
        log.warning(f"  ⚠️ Errores aplicando: {'; '.join(errors)}")
        return {"applied": True, "errors": errors}
    
    log.info(f"  ✅ Precios aplicados: {len(results)} fechas × 2 rooms × 5 slots")
    return {"applied": True, "errors": []}
