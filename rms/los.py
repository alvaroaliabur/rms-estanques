"""
LOS Dinámico + Gap Detection — v7.2
CHANGES:
  - Gap detection now works per room type (ground=1 unit, upper=8 units)
  - Ground floor has independent minStay from upper floor
  - detect_gaps_dinamico returns gaps keyed by date with per-type info
  - Expanded gap horizon from 60 to 90 days
"""

from datetime import date, timedelta
from rms import config
from rms.utils import fmt, parse_date, get_month


def get_min_stay_dinamico(fecha, occ_now, days_out, season_code, expected_occ, disponibles):
    """Calculate dynamic min stay based on occupancy, days out, season."""
    cfg = config.LOS_DINAMICO
    if not cfg or not cfg["enabled"]:
        return {"minStay": config.DEFAULT_MIN_STAY.get(season_code, 3),
                "premium": 1.0, "razon": "default", "reduccion": 0}

    default_min = config.DEFAULT_MIN_STAY.get(season_code, 3)
    absolute_min = cfg["ABSOLUTE_MIN"].get(season_code, 2)
    min_stay = default_min
    premium = 1.0
    razon = "default"

    # Step 1: Raise minStay if high demand
    occ_subir = cfg["OCC_SUBIR_MINSTAY"].get(season_code, 0.80)
    if occ_now >= occ_subir and days_out > 21 and disponibles >= 4:
        return {"minStay": min(8, default_min + 1),
                "premium": 1.0, "razon": "alta_demanda", "reduccion": 0}

    # Step 2: Find applicable tier
    occ_no_reducir = cfg["OCC_NO_REDUCIR"].get(season_code, 0.70)
    escalon = None
    for e in cfg["ESCALONES"]:
        if e["dias_min"] <= days_out <= e["dias_max"]:
            escalon = e
            break

    if not escalon:
        return {"minStay": max(absolute_min, min_stay),
                "premium": 1.0, "razon": "sin_escalon", "reduccion": 0}

    if escalon["requiere_occ_baja"] and occ_now >= occ_no_reducir:
        return {"minStay": max(absolute_min, min_stay),
                "premium": 1.0, "razon": f"occ_ok_{escalon['nombre']}", "reduccion": 0}

    # Apply reduction
    reduccion = escalon["reduccion"]
    occ_diff = occ_now - (expected_occ or 0.50)
    if occ_diff < -0.25 and reduccion > 0:
        reduccion += 1
        razon = f"{escalon['nombre']}_agresivo"
    else:
        razon = escalon["nombre"]

    min_stay = default_min - reduccion
    premium = escalon["precio_premium"]

    # Step 3: UA conservative
    if season_code == "UA" and reduccion > 0:
        if disponibles < 5:
            return {"minStay": default_min, "premium": 1.0,
                    "razon": "UA_conservador", "reduccion": 0}
        if default_min - min_stay > 2:
            min_stay = default_min - 2

    # Step 4: Clamp
    min_stay = max(absolute_min, min(8, min_stay))

    return {
        "minStay": min_stay,
        "premium": premium,
        "razon": razon,
        "reduccion": max(0, default_min - min_stay),
    }


# ══════════════════════════════════════════
# GAP DETECTION v7.2 — Per Room Type
# ══════════════════════════════════════════
#
# Two room types:
#   - UPPER (roomId 269521): 8 units, shared pool of availability
#   - GROUND (roomId 269520): 1 unit, independent availability
#
# For UPPER: we detect gaps in the aggregate OTB of 8 units.
#   A "gap" exists when ALL 8 units are booked on surrounding dates
#   but some units have a short window free. Since we don't have
#   per-unit booking data from the aggregate OTB, we use a proxy:
#   if disp_upper <= 2 on neighbors but disp_upper > 0 on the date,
#   it's likely a gap in one specific unit.
#
# For GROUND: we detect gaps by looking at the ground floor's own
#   bookings. Since it's 1 unit, any free stretch IS the gap.
#
# The OTB dict now needs to carry per-type availability.
# We add a parallel function that reads per-room-type OTB.

def detect_gaps_dinamico(otb, otb_by_type=None):
    """
    Detect gaps for dynamic minStay and premium.
    
    Args:
        otb: Standard OTB dict {date_str: total_units_booked}
        otb_by_type: Optional dict with per-type OTB:
            {"upper": {date_str: units_booked}, "ground": {date_str: units_booked}}
            If not provided, falls back to aggregate detection.
    
    Returns:
        Dict keyed by date_str with gap info including per-type details.
    """
    gaps = {}
    today = date.today()
    horizon = 90  # Extended from 60

    if otb_by_type:
        # ═══ NEW: Per-type gap detection ═══
        _detect_gaps_upper(gaps, otb_by_type.get("upper", {}), today, horizon)
        _detect_gaps_ground(gaps, otb_by_type.get("ground", {}), today, horizon)
    else:
        # Fallback: aggregate detection (old behavior)
        _detect_gaps_aggregate(gaps, otb, today, horizon)

    return gaps


def _detect_gaps_upper(gaps, otb_upper, today, horizon):
    """
    Detect gaps in upper floor (8 units).
    
    Strategy: Look for dates where 1-2 units are free but neighbors
    are heavily booked. This indicates a gap in specific units.
    """
    UPPER_UNITS = 8
    di = 0
    while di < horizon:
        d = today + timedelta(days=di)
        date_str = fmt(d)
        reservadas = otb_upper.get(date_str, 0)
        disponibles = UPPER_UNITS - reservadas

        if disponibles < 1:
            di += 1
            continue

        # Count consecutive nights with availability
        gap_length = 0
        for gdi in range(10):  # Extended scan to 10
            gd = today + timedelta(days=di + gdi)
            gd_str = fmt(gd)
            gd_disp = UPPER_UNITS - otb_upper.get(gd_str, 0)
            if gd_disp >= 1:
                gap_length += 1
            else:
                break

        if gap_length < 2 or gap_length > 7:
            di += max(1, gap_length)
            continue

        # Check if this is a real gap: are neighbors heavily booked?
        # Look at day before and day after the gap
        day_before = fmt(today + timedelta(days=max(0, di - 1)))
        day_after = fmt(today + timedelta(days=di + gap_length))
        disp_before = UPPER_UNITS - otb_upper.get(day_before, 0)
        disp_after = UPPER_UNITS - otb_upper.get(day_after, 0)

        # It's a meaningful gap if bookings are high around it
        is_surrounded = disp_before <= 2 or disp_after <= 2

        season_code = config.SEASON_CODE[d.month]
        default_ms = config.DEFAULT_MIN_STAY.get(season_code, 3)

        if gap_length < default_ms:
            # Gap shorter than minStay — MUST reduce or it's unsellable
            min_stay_gap = gap_length
            premium_gap = 1.20 if gap_length <= 2 else 1.12
        elif is_surrounded and gap_length <= default_ms + 1:
            # Gap barely fits minStay with tight neighbors
            min_stay_gap = gap_length
            premium_gap = 1.10
        elif season_code == "UA":
            min_stay_gap = gap_length
            premium_gap = 1.08
        else:
            min_stay_gap = default_ms
            premium_gap = 1.08 if di < 14 else 1.05

        # Fill ALL days of the gap with the same minStay.
        # Without this, only day 1 gets the reduced minStay;
        # days 2..N revert to default and the gap stays unsellable.
        gap_entry = {
            "gapLength": gap_length,
            "daysOut": di,
            "disponibles": disponibles,
            "minStayGap": min_stay_gap,
            "premiumGap": premium_gap,
            "roomType": "upper",
            "surrounded": is_surrounded,
        }
        for gdi in range(gap_length):
            gd_str = fmt(today + timedelta(days=di + gdi))
            gaps[gd_str] = {**gap_entry, "daysOut": di + gdi}

        di += gap_length


def _detect_gaps_ground(gaps, otb_ground, today, horizon):
    """
    Detect gaps in ground floor (1 unit).
    
    Since it's 1 unit, any free stretch is the actual gap.
    Ground floor has independent minStay (can be lower than upper).
    """
    GROUND_UNITS = 1
    gf_cfg = config.GROUND_FLOOR_LOS or {}
    gf_absolute_min = gf_cfg.get("absolute_min", 2)

    di = 0
    while di < horizon:
        d = today + timedelta(days=di)
        date_str = fmt(d)
        reservadas = otb_ground.get(date_str, 0)
        disponibles = GROUND_UNITS - reservadas

        if disponibles < 1:
            di += 1
            continue

        # Count consecutive free nights for ground floor
        gap_length = 0
        for gdi in range(14):  # Ground can have longer gaps
            gd = today + timedelta(days=di + gdi)
            gd_str = fmt(gd)
            gd_disp = GROUND_UNITS - otb_ground.get(gd_str, 0)
            if gd_disp >= 1:
                gap_length += 1
            else:
                break

        if gap_length < 2:
            # BUSINESS RULE: never accept 1-night stays anywhere.
            # Block both room types with minStay=9.
            gaps[date_str] = {
                "gapLength": 1,
                "daysOut": di,
                "disponibles": disponibles,
                "minStayGap": 9,
                "premiumGap": 1.0,
                "minStayGapGround": 9,
                "premiumGapGround": 1.0,
                "gapLengthGround": 1,
                "roomType": "ground",
                "surrounded": True,
            }
            di += 1
            continue

        season_code = config.SEASON_CODE[d.month]
        default_ms = config.DEFAULT_MIN_STAY.get(season_code, 3)

        # Ground floor: minStay = gap_length always.
        # The gap IS the constraint — never set minStay > gap_length
        # or the gap becomes unsellable.
        if gap_length < default_ms:
            min_stay_gap = max(gf_absolute_min, gap_length)
            premium_gap = 1.18 if gap_length <= 2 else 1.10
        else:
            # Gap fits default or longer — use default (not default-1)
            min_stay_gap = max(gf_absolute_min, default_ms)
            premium_gap = 1.05

        # Only add to gaps dict if it improves on existing entry
        # (upper floor might have already set a gap for this date)
        # Fill ALL days of the gap for ground floor too.
        for gdi in range(gap_length):
            gd = today + timedelta(days=di + gdi)
            gd_str = fmt(gd)
            existing = gaps.get(gd_str)
            if existing:
                # Merge: keep upper info, add ground info
                existing["minStayGapGround"] = min_stay_gap
                existing["premiumGapGround"] = premium_gap
                existing["gapLengthGround"] = gap_length
            else:
                gaps[gd_str] = {
                    "gapLength": gap_length,
                    "daysOut": di + gdi,
                    "disponibles": disponibles,
                    "minStayGap": min_stay_gap,
                    "premiumGap": premium_gap,
                    "minStayGapGround": min_stay_gap,
                    "premiumGapGround": premium_gap,
                    "gapLengthGround": gap_length,
                    "roomType": "ground",
                    "surrounded": True,
                }

        di += gap_length


def _detect_gaps_aggregate(gaps, otb, today, horizon):
    """Fallback: original aggregate gap detection."""
    di = 0
    while di < horizon:
        d = today + timedelta(days=di)
        date_str = fmt(d)
        reservadas = otb.get(date_str, 0)
        disponibles = config.TOTAL_UNITS - reservadas

        if disponibles < 1:
            di += 1
            continue

        gap_length = 0
        for gdi in range(8):
            gd = today + timedelta(days=di + gdi)
            gd_str = fmt(gd)
            gd_disp = config.TOTAL_UNITS - otb.get(gd_str, 0)
            if gd_disp >= 1:
                gap_length += 1
            else:
                break

        if gap_length < 2 or gap_length > 7:
            di += max(1, gap_length)
            continue

        season_code = config.SEASON_CODE[d.month]
        default_ms = config.DEFAULT_MIN_STAY.get(season_code, 3)

        if gap_length < default_ms:
            min_stay_gap = gap_length
            premium_gap = 1.20 if gap_length == 2 else 1.10
        elif season_code == "UA":
            min_stay_gap = gap_length
            premium_gap = 1.08
        else:
            min_stay_gap = default_ms
            premium_gap = 1.08 if di < 14 else 1.05

        gaps[date_str] = {
            "gapLength": gap_length,
            "daysOut": di,
            "disponibles": disponibles,
            "minStayGap": min_stay_gap,
            "premiumGap": premium_gap,
            "roomType": "aggregate",
            "surrounded": False,
        }

        di += gap_length
