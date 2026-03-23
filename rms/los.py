"""
LOS Dinámico + Gap Detection.
Replaces: getMinStayDinamico_, detectGapsDinamico_
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


def detect_gaps_dinamico(otb):
    """Detect gaps in OTB for dynamic minStay and premium."""
    gaps = {}
    today = date.today()

    di = 0
    while di < 60:
        d = today + timedelta(days=di)
        date_str = fmt(d)
        reservadas = otb.get(date_str, 0)
        disponibles = config.TOTAL_UNITS - reservadas

        if disponibles < 1:
            di += 1
            continue

        # Count consecutive free nights
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
        }

        di += gap_length

    return gaps
