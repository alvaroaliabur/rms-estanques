"""
Apply prices to Beds24 — writes calendar data via API.
Replaces: aplicarPrecios_, getSlotsBySeasonCode_, getDynamicDurationDiscount_,
          getGroundFloorPremium_, readGroundFloorOTB_, detectGroundFloorGaps_
"""

import time
import logging
from datetime import date, timedelta
from rms import config
from rms.beds24 import api_post, api_get_all
from rms.utils import fmt, parse_date, is_weekend

log = logging.getLogger(__name__)


def get_slots_by_season(sc):
    if sc == "UA":
        return {"STANDARD": False, "4NOCHES": False, "5NOCHES": False, "6NOCHES": True, "SEMANAL": True}
    if sc == "A":
        return {"STANDARD": False, "4NOCHES": False, "5NOCHES": True, "6NOCHES": True, "SEMANAL": True}
    if sc == "MA":
        return {"STANDARD": False, "4NOCHES": True, "5NOCHES": True, "6NOCHES": True, "SEMANAL": True}
    return {"STANDARD": True, "4NOCHES": True, "5NOCHES": True, "6NOCHES": True, "SEMANAL": True}


def get_dynamic_duration_discount(slot_name, occupancy, days_out, season_code):
    dyn = config.DURATION_DISCOUNTS_DYNAMIC.get(slot_name)
    if not dyn:
        return config.DURATION_DISCOUNTS.get(slot_name, 1)

    if days_out is None:
        days_out = 60

    # Discount by occupancy
    if occupancy <= config.DURATION_DISCOUNT_OCC_LOW:
        disc = dyn["base"]
    elif occupancy >= config.DURATION_DISCOUNT_OCC_HIGH:
        disc = dyn["min"]
    else:
        disc = dyn["base"] + (dyn["min"] - dyn["base"]) * (
            (occupancy - config.DURATION_DISCOUNT_OCC_LOW) /
            (config.DURATION_DISCOUNT_OCC_HIGH - config.DURATION_DISCOUNT_OCC_LOW)
        )

    # Modulate by days out
    if days_out > 90:
        if season_code in ("UA", "A"):
            return dyn["min"] + (1 - dyn["min"]) * 0.4
        return dyn["min"]
    elif days_out > 30:
        urgency_pct = (90 - days_out) / 60
        return dyn["min"] + (disc - dyn["min"]) * urgency_pct
    elif days_out > 14:
        return disc
    else:
        extra_urgency = (14 - days_out) / 14
        extra_discount = dyn["base"] - 0.05 * extra_urgency
        return min(disc, extra_discount)


def get_ground_floor_premium(result):
    sc = result.get("seasonCode", "M")
    days_out = result.get("daysOut", 90)
    premiums = {"UA": 1.08, "A": 1.07, "MA": 1.06, "M": 1.05, "MB": 1.03, "B": 1.02}
    bp = premiums.get(sc, 1.05)

    if days_out <= 7:
        bp = 1.00 + (bp - 1.00) * 0.25
    elif days_out <= 14:
        bp = 1.00 + (bp - 1.00) * 0.50
    elif days_out <= 21:
        bp = 1.00 + (bp - 1.00) * 0.75
    return bp


def read_ground_floor_otb():
    """Read GroundFloor-specific OTB."""
    today = date.today()
    end = today + timedelta(days=config.PRICING_HORIZON)

    all_bks = api_get_all("bookings", {
        "arrivalFrom": fmt(today), "departureTo": fmt(end),
        "propertyId": config.PROPERTY_ID, "roomId": config.ROOM_GROUND,
    })
    active = api_get_all("bookings", {
        "departureFrom": fmt(today), "arrivalTo": fmt(today),
        "propertyId": config.PROPERTY_ID, "roomId": config.ROOM_GROUND,
    })
    if active:
        all_bks.extend(active)

    from rms.otb import es_cancelada
    otb = {}
    seen = set()
    for b in all_bks:
        if not b.get("arrival") or not b.get("departure"):
            continue
        if es_cancelada(b):
            continue
        bid = b.get("id")
        if bid in seen:
            continue
        seen.add(bid)
        if b.get("roomId") and b["roomId"] != config.ROOM_GROUND:
            continue

        ci = parse_date(b["arrival"])
        co = parse_date(b["departure"])
        d = max(ci, today)
        while d < co:
            if d > end:
                break
            otb[fmt(d)] = 1
            d += timedelta(days=1)

    log.info(f"  GroundFloor OTB: {len(otb)} fechas con reserva")
    return otb


def detect_ground_floor_gaps(gf_otb):
    """Detect gaps in GroundFloor bookings."""
    today = date.today()
    gaps = {}
    di = 0

    while di < config.PRICING_HORIZON:
        d = today + timedelta(days=di)
        ds = fmt(d)
        if gf_otb.get(ds):
            di += 1
            continue

        # Count gap length
        gap_start = ds
        gap_dates = []
        gap_len = 0
        while di + gap_len < config.PRICING_HORIZON and gap_len <= 30:
            gd = today + timedelta(days=di + gap_len)
            gds = fmt(gd)
            if gf_otb.get(gds):
                break
            gap_dates.append(gds)
            gap_len += 1

        if 2 <= gap_len <= 30:
            sc = config.SEASON_CODE[d.month]
            default_ms = config.DEFAULT_MIN_STAY.get(sc, 3)
            if gap_len < default_ms:
                ms_gap = gap_len
                prem = 1.15 if gap_len == 2 else 1.08
            else:
                ms_gap = default_ms
                prem = 1.00

            for gds in gap_dates:
                gaps[gds] = {
                    "gapLength": gap_len, "gapStart": gap_start,
                    "minStayGap": ms_gap, "premiumGap": prem,
                }

        di += max(1, gap_len)

    return gaps


def aplicar_precios(results):
    """Apply calculated prices to Beds24 calendar."""
    if config.DRY_RUN:
        log.info("  DRY RUN — prices not applied")
        return

    # GroundFloor OTB + gaps
    gf_otb = {}
    gf_gaps = {}
    if config.GROUND_FLOOR_LOS["enabled"]:
        gf_otb = read_ground_floor_otb()
        gf_gaps = detect_ground_floor_gaps(gf_otb)

    calendar_updates = {config.ROOM_UPPER: [], config.ROOM_GROUND: []}

    for r in results:
        std_price = r["precioFinal"]
        open_slots = get_slots_by_season(r["seasonCode"])
        seasonal_floor = r.get("seasonalFloor", r["suelo"])

        # Build price slots
        price_slots = {}
        price_slots[config.PRICE_SLOTS["STANDARD"]] = std_price if open_slots["STANDARD"] else 9999

        apply_dd = r["seasonCode"] in ("B", "MB", "M", "MA")
        for slot_name in ("4NOCHES", "5NOCHES", "6NOCHES", "SEMANAL"):
            slot_key = config.PRICE_SLOTS[slot_name]
            if open_slots[slot_name]:
                if apply_dd:
                    sp = round(std_price * get_dynamic_duration_discount(
                        slot_name, r.get("occNow", 0), r.get("daysOut"), r["seasonCode"]))
                else:
                    sp = std_price
                dur_floor = seasonal_floor
                if config.DURATION_FLOOR_FACTOR.get(slot_name):
                    dur_floor = max(35, round(seasonal_floor * config.DURATION_FLOOR_FACTOR[slot_name]))
                if sp < dur_floor:
                    sp = dur_floor
                price_slots[slot_key] = sp
            else:
                price_slots[slot_key] = 9999

        # Ground floor premium
        gp = get_ground_floor_premium(r)
        upper_slots = dict(price_slots)
        ground_slots = {k: (9999 if v == 9999 else round(v * gp)) for k, v in price_slots.items()}

        # Upper floor entry
        entry_upper = {"from": r["date"], "to": r["date"], "minStay": r["minStay"]}
        entry_upper.update(upper_slots)
        calendar_updates[config.ROOM_UPPER].append(entry_upper)

        # Ground floor minStay
        ground_ms = config.DEFAULT_MIN_STAY.get(r["seasonCode"], 3)
        gf_gap = gf_gaps.get(r["date"])
        if gf_gap and config.GROUND_FLOOR_LOS["enabled"]:
            gf_cfg = config.GROUND_FLOOR_LOS
            es_protegida = r["seasonCode"] in gf_cfg["temporadas_protegidas"]
            reducir = True
            if es_protegida and (r.get("occNow", 0) < gf_cfg["upper_occ_threshold"]) and not r.get("eventName"):
                reducir = False
            if reducir:
                ground_ms = max(gf_cfg["absolute_min"], gf_gap["minStayGap"])

        entry_ground = {"from": r["date"], "to": r["date"], "minStay": ground_ms}
        entry_ground.update(ground_slots)
        calendar_updates[config.ROOM_GROUND].append(entry_ground)

    # Send to Beds24 in batches
    for room_id, updates in calendar_updates.items():
        for start in range(0, len(updates), 30):
            batch = updates[start:start + 30]
            try:
                api_post("inventory/rooms/calendar", [{"roomId": room_id, "calendar": batch}])
                log.info(f"  Room {room_id}: {batch[0]['from']} → {batch[-1]['from']} ({len(batch)} días)")
            except Exception as e:
                log.error(f"  ❌ Room {room_id}: {str(e)[:100]}")
            time.sleep(0.5)
