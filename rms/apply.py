"""
Apply Prices — v7.2.2
CHANGES from v7.2:
  - v7.2.2: Ground floor pricing +10% premium over upper floor
    Ground floor = acceso jardín, terraza privada, producto premium.
    Applied at the price level, not as a multiplier on the final price.
  - Ground floor minStay fully independent from upper floor
  - Uses minStayGround from pricing results (gap-aware)
  - Modest duration discount for 14+ nights in UA (5% when days_out > 60)
"""

import logging
from rms import config
from rms.beds24 import api_post

log = logging.getLogger(__name__)

# ══════════════════════════════════════════
# GROUND FLOOR PREMIUM
# ══════════════════════════════════════════
GROUND_FLOOR_PREMIUM = 1.10  # +10% sobre Upper Floor


# ══════════════════════════════════════════
# SLOT OPENING BY SEASON
# ══════════════════════════════════════════

def get_open_slots(season_code):
    """
    Slots abiertos por temporada. Alineados con DEFAULT_MIN_STAY.

    UA/A  (minStay=5): STANDARD + 5N + 6N + 7N. Sin 4N — nunca menos de 5 noches.
          STANDARD con minStay=5 acepta exactamente 5n al precio base.
          5N/6N/7N son tarifas con descuento para esas duraciones.
    MA/M  (minStay=3): Todo abierto, máxima flexibilidad.
    B/MB  (minStay=2): Todo abierto, llenar.
    """
    if season_code == "UA":
        # minStay=5. STANDARD acepta 5n. 5N/6N/7N con descuento contenido.
        # 4NOCHES cerrado: nunca menos de 5 noches en julio/agosto.
        return {"STANDARD": True, "4NOCHES": False, "5NOCHES": True, "6NOCHES": True, "SEMANAL": True}
    elif season_code == "A":
        # minStay=5. Igual que UA — jun/sep mismo criterio.
        return {"STANDARD": True, "4NOCHES": False, "5NOCHES": True, "6NOCHES": True, "SEMANAL": True}
    elif season_code in ("MA", "M"):
        # minStay=3. Todo abierto, flexibilidad máxima.
        return {"STANDARD": True, "4NOCHES": True, "5NOCHES": True, "6NOCHES": True, "SEMANAL": True}
    else:
        # B/MB: minStay=2. Todo abierto, llenar.
        return {"STANDARD": True, "4NOCHES": True, "5NOCHES": True, "6NOCHES": True, "SEMANAL": True}


# ══════════════════════════════════════════
# DURATION DISCOUNTS (dynamic)
# ══════════════════════════════════════════

DURATION_DISCOUNTS = {
    "4NOCHES": {"base": 0.82, "min": 0.90},
    "5NOCHES": {"base": 0.75, "min": 0.85},
    "6NOCHES": {"base": 0.68, "min": 0.80},
    "SEMANAL": {"base": 0.60, "min": 0.75},
}

DURATION_FLOOR_FACTOR = {
    "4NOCHES": 0.92,
    "5NOCHES": 0.85,
    "6NOCHES": 0.78,
    "SEMANAL": 0.70,
}

OCC_LOW = 0.30
OCC_HIGH = 0.75

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

    # UA/A: escala progresiva — más noches = más descuento por noche.
    # Pero el revenue TOTAL sube con las noches.
    # 5N: -3%  → precio/noche casi igual, pequeño incentivo
    # 6N: -6%  → descuento apreciable para semana completa
    # 7N: -10% → descuento real para bloquear semana entera
    # Revenue total: 5N < 6N < 7N siempre ✅
    if season_code in ("UA", "A"):
        if slot_name == "5NOCHES":
            return max(round(base_price * 0.97), round(suelo * 0.87))
        if slot_name == "6NOCHES":
            return max(round(base_price * 0.94), round(suelo * 0.82))
        if slot_name == "SEMANAL":
            return max(round(base_price * 0.90), round(suelo * 0.78))
        return base_price

    # B/MB/M/MA: full dynamic discounts
    if occ <= OCC_LOW:
        factor = disc["base"]
    elif occ >= OCC_HIGH:
        factor = disc["min"]
    else:
        ratio = (occ - OCC_LOW) / (OCC_HIGH - OCC_LOW)
        factor = disc["base"] + (disc["min"] - disc["base"]) * ratio

    # Modulate by days out
    if days_out is not None and days_out > 90:
        factor = disc["min"]
    elif days_out is not None and days_out > 30:
        blend = (days_out - 30) / 60
        factor = factor + (disc["min"] - factor) * blend

    price = round(base_price * factor)
    floor_factor = DURATION_FLOOR_FACTOR.get(slot_name, 1.0)
    duration_floor = max(35, round(suelo * floor_factor))
    return max(price, duration_floor)


# ══════════════════════════════════════════
# BUILD CALENDAR ENTRY
# ══════════════════════════════════════════

def build_calendar_entry(result, room_type="upper"):
    """
    Build a single Beds24 calendar entry with all price slots.

    room_type: "upper" or "ground"
    - "ground" gets +10% premium on all prices (GROUND_FLOOR_PREMIUM)
    - "ground" uses independent minStay (minStayGround from results)
    """
    d = result["date"]
    base = result["precioFinal"]
    suelo = result.get("suelo", 50)
    occ = result.get("occNow", 0)
    days_out = result.get("daysOut", 60)
    sc = result.get("seasonCode", "M")
    techo = result.get("techo", 9999)

    # Ground floor: +10% premium, clamped by ceiling
    if room_type == "ground":
        base = min(round(base * GROUND_FLOOR_PREMIUM), techo)
        suelo = round(suelo * GROUND_FLOOR_PREMIUM)

    # Pick minStay based on room type
    if room_type == "ground":
        min_stay = result.get("minStayGround", result.get("minStay", 3))
    else:
        min_stay = result.get("minStay", 3)

    open_slots = get_open_slots(sc)

    entry = {"from": d, "to": d, "minStay": min_stay}

    for slot_name, field_name in SLOT_TO_FIELD.items():
        if open_slots.get(slot_name):
            if slot_name == "STANDARD":
                entry[field_name] = base
            else:
                entry[field_name] = calc_duration_price(base, slot_name, occ, suelo, days_out, sc)
        else:
            entry[field_name] = 9999

    return entry


# ══════════════════════════════════════════
# GROUND FLOOR HANDLING
# ══════════════════════════════════════════

def get_ground_floor_minstay(result):
    """
    Ground floor (1 unit) has independent minStay.

    v7.2: Now uses minStayGround from results if available (set by
    gap detection). Falls back to reducing upper minStay by 1.
    """
    # If gap detection already set a specific ground minStay, use it
    if result.get("gapOverrideGround") and result.get("minStayGround"):
        return result["minStayGround"]

    sc = result.get("seasonCode", "M")
    min_stay = result.get("minStay", 3)
    occ = result.get("occNow", 0)
    gf = config.GROUND_FLOOR_LOS

    if not gf or not gf.get("enabled"):
        return min_stay

    protected = gf.get("temporadas_protegidas", ["A", "UA"])
    if sc in protected and occ < gf.get("upper_occ_threshold", 0.75):
        return min_stay

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

    calendar_upper = []
    calendar_ground = []

    for r in results:
        # Upper floor: 8 units — uses minStay from results
        entry_upper = build_calendar_entry(r, room_type="upper")
        calendar_upper.append(entry_upper)

        # Ground floor: 1 unit — +10% premium + independent minStay
        entry_ground = build_calendar_entry(r, room_type="ground")
        # Override minStay if not already set by gap detection
        if not r.get("gapOverrideGround"):
            entry_ground["minStay"] = get_ground_floor_minstay(r)
        calendar_ground.append(entry_ground)

    # Send to Beds24 in batches of 30
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
                log.info(f"    Room {room_name}: {batch[0]['from']} → {batch[-1]['from']} ({len(batch)} días)")
            except Exception as e:
                errors.append(f"{room_name} batch {i // batch_size + 1}: {e}")
                log.warning(f"    ❌ Room {room_name}: {str(e)[:100]}")

    if errors:
        log.warning(f"  ⚠️ {len(errors)} errores aplicando precios")
        return {"applied": True, "errors": errors}

    # Count ground floor dates with different minStay than upper
    diff_minstay = sum(1 for u, g in zip(calendar_upper, calendar_ground) if u["minStay"] != g["minStay"])
    diff_price = sum(1 for u, g in zip(calendar_upper, calendar_ground) if u.get("price1", 0) != g.get("price1", 0))
    if diff_minstay > 0:
        log.info(f"  🏠 Ground floor: {diff_minstay} fechas con minStay diferente al upper")
    log.info(f"  🏠 Ground floor: +10% premium aplicado en {diff_price} fechas")

    slot_count = sum(1 for r in results for s, o in get_open_slots(r.get("seasonCode", "M")).items() if o)
    log.info(f"  ✅ Precios aplicados: {len(results)} fechas × 2 rooms, {slot_count} slots activos")
    return {"applied": True, "errors": []}
