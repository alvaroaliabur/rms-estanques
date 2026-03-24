"""
Apply Prices — Write prices to Beds24 via API
v7.1.1: Matches GAS behavior exactly

KEY RULES FROM GAS:
1. Not all price slots open in all seasons:
   - UA (Jul/Aug): Only price3 (6N) + price10 (weekly). MinStay=7, no short stays.
   - A (Jun/Sep): price4 (5N) + price3 (6N) + price10 (weekly).
   - MA (May/Oct): price5 (4N) + price4 + price3 + price10.
   - B/MB/M: All slots open (price1 + price5 + price4 + price3 + price10).
2. Closed slots get price 9999 (blocks that duration in Beds24).
3. Duration discounts compress as occupancy rises.
4. Ground floor (1 unit) can have different minStay in some conditions.
5. Beds24 API endpoint: inventory/rooms/calendar

BEDS24 API FORMAT:
POST /inventory/rooms/calendar
Body: [{roomId: 269521, calendar: [{from: "2026-07-01", to: "2026-07-01", price1: 9999, price3: 350, price10: 350, minStay: 7}]}]
"""

import logging
from rms import config
from rms.beds24 import api_post

log = logging.getLogger(__name__)


# ══════════════════════════════════════════
# SLOT OPENING BY SEASON
# ══════════════════════════════════════════

def get_open_slots(season_code):
    """
    Which price slots are open (bookable) for each season.
    Closed slots get price 9999 to block that duration.
    
    Matches GAS getSlotsBySeasonCode_ exactly.
    """
    if season_code == "UA":
        # Ultra Alta: only 6-night and weekly (minStay=7)
        return {"STANDARD": False, "4NOCHES": False, "5NOCHES": False, "6NOCHES": True, "SEMANAL": True}
    elif season_code == "A":
        # Alta: 5-night, 6-night, weekly
        return {"STANDARD": False, "4NOCHES": False, "5NOCHES": True, "6NOCHES": True, "SEMANAL": True}
    elif season_code == "MA":
        # Media-Alta: 4-night and above
        return {"STANDARD": False, "4NOCHES": True, "5NOCHES": True, "6NOCHES": True, "SEMANAL": True}
    else:
        # M, MB, B: all slots open
        return {"STANDARD": True, "4NOCHES": True, "5NOCHES": True, "6NOCHES": True, "SEMANAL": True}


# ══════════════════════════════════════════
# DURATION DISCOUNTS (dynamic)
# ══════════════════════════════════════════

DURATION_DISCOUNTS = {
    "4NOCHES": {"base": 0.82, "min": 0.90},
    "5NOCHES": {"base": 0.75, "min": 0.85},
    "6NOCHES": {"base": 0.68, "min": 0.80},
    "SEMANAL":  {"base": 0.60, "min": 0.75},
}

DURATION_FLOOR_FACTOR = {
    "4NOCHES": 0.92,
    "5NOCHES": 0.85,
    "6NOCHES": 0.78,
    "SEMANAL":  0.70,
}

OCC_LOW = 0.30
OCC_HIGH = 0.75

# Slot name → Beds24 field name
SLOT_TO_FIELD = {
    "STANDARD": "price1",
    "6NOCHES": "price3",
    "5NOCHES": "price4",
    "4NOCHES": "price5",
    "SEMANAL": "price10",
}


def calc_duration_price(base_price, slot_name, occ, suelo, days_out, season_code):
    """Calculate duration-discounted price for a slot."""
    disc = DURATION_DISCOUNTS.get(slot_name)
    if not disc:
        return base_price

    # In UA/A, duration slots use the same price (no discount)
    # Only B/MB/M/MA get duration discounts
    if season_code in ("UA", "A"):
        return base_price

    # Interpolate discount by occupancy
    if occ <= OCC_LOW:
        factor = disc["base"]
    elif occ >= OCC_HIGH:
        factor = disc["min"]
    else:
        ratio = (occ - OCC_LOW) / (OCC_HIGH - OCC_LOW)
        factor = disc["base"] + (disc["min"] - disc["base"]) * ratio

    # Modulate by days out (>90d: conservative, use min discount)
    if days_out is not None and days_out > 90:
        factor = disc["min"]  # Don't give big discounts far in advance
    elif days_out is not None and days_out > 30:
        # Blend between occ-based and min
        blend = (days_out - 30) / 60  # 0 at 30d, 1 at 90d
        factor = factor + (disc["min"] - factor) * blend

    price = round(base_price * factor)

    # Apply duration-specific floor
    floor_factor = DURATION_FLOOR_FACTOR.get(slot_name, 1.0)
    duration_floor = max(35, round(suelo * floor_factor))

    return max(price, duration_floor)


# ══════════════════════════════════════════
# BUILD CALENDAR ENTRY
# ══════════════════════════════════════════

def build_calendar_entry(result):
    """Build a single Beds24 calendar entry with all price slots."""
    d = result["date"]
    base = result["precioFinal"]
    suelo = result.get("suelo", 50)
    occ = result.get("occNow", 0)
    min_stay = result.get("minStay", 3)
    days_out = result.get("daysOut", 60)
    sc = result.get("seasonCode", "M")

    open_slots = get_open_slots(sc)

    entry = {"from": d, "to": d, "minStay": min_stay}

    for slot_name, field_name in SLOT_TO_FIELD.items():
        if open_slots.get(slot_name):
            if slot_name == "STANDARD":
                entry[field_name] = base
            else:
                entry[field_name] = calc_duration_price(base, slot_name, occ, suelo, days_out, sc)
        else:
            entry[field_name] = 9999  # Block this duration

    return entry


# ══════════════════════════════════════════
# GROUND FLOOR HANDLING
# ══════════════════════════════════════════

def get_ground_floor_minstay(result):
    """
    Ground floor (1 unit) can have different minStay.
    In protected seasons (A/UA) with low occupancy, keep default.
    Otherwise, can reduce by 1 to fill gaps.
    """
    sc = result.get("seasonCode", "M")
    min_stay = result.get("minStay", 3)
    occ = result.get("occNow", 0)

    gf = config.GROUND_FLOOR_LOS
    if not gf or not gf.get("enabled"):
        return min_stay

    protected = gf.get("temporadas_protegidas", ["A", "UA"])
    if sc in protected and occ < gf.get("upper_occ_threshold", 0.75):
        return min_stay  # Don't reduce in protected seasons with low occ

    # Allow reduction of 1 night, respecting absolute minimum
    return max(gf.get("absolute_min", 2), min_stay - 1)


# ══════════════════════════════════════════
# APPLY TO BEDS24
# ══════════════════════════════════════════

def aplicar_precios(results):
    """Apply all calculated prices to Beds24."""
    if config.DRY_RUN:
        log.info("  🔒 DRY RUN — precios NO aplicados")
        return {"applied": False, "reason": "DRY_RUN"}

    if not results:
        log.warning("  No results to apply")
        return {"applied": False, "reason": "no_results"}

    log.info(f"  Aplicando precios a Beds24 ({len(results)} fechas)...")

    # Build calendar for each room
    calendar_upper = []
    calendar_ground = []

    for r in results:
        # Upper floor entry (8 units)
        entry = build_calendar_entry(r)
        calendar_upper.append(entry)

        # Ground floor entry (1 unit) — same prices, possibly different minStay
        ground_entry = entry.copy()
        ground_entry["minStay"] = get_ground_floor_minstay(r)
        calendar_ground.append(ground_entry)

    # Send to Beds24 in batches of 30 (matching GAS behavior)
    batch_size = 30
    errors = []

    for room_id, calendar, room_name in [
        (config.ROOM_UPPER, calendar_upper, "Upper"),
        (config.ROOM_GROUND, calendar_ground, "Ground"),
    ]:
        for i in range(0, len(calendar), batch_size):
            batch = calendar[i:i + batch_size]
            try:
                payload = [{"roomId": room_id, "calendar": batch}]
                response = api_post("inventory/rooms/calendar", payload)
                log.info(f"  Room {room_name}: {batch[0]['from']} → {batch[-1]['from']} ({len(batch)} días)")
            except Exception as e:
                errors.append(f"{room_name} batch {i // batch_size + 1}: {e}")
                log.warning(f"  ❌ Room {room_name}: {str(e)[:100]}")

    if errors:
        log.warning(f"  ⚠️ {len(errors)} errores aplicando precios")
        return {"applied": True, "errors": errors}

    slot_count = sum(1 for r in results for s, o in get_open_slots(r.get("seasonCode", "M")).items() if o)
    log.info(f"  ✅ Precios aplicados: {len(results)} fechas × 2 rooms, {slot_count} slots activos")
    return {"applied": True, "errors": []}
