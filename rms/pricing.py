"""
RMS v7.3 Pricing Engine — Conservative Direct Multipliers

KEY CHANGE from v7.2:
  v7.2 put all signals into forecast (only moved virtual availability).
  Result: 18/31 July days stuck at SUELO. Prices didn't move.

  v7.3 adds CONSERVATIVE direct multipliers to the price:
  - fOTB, fPickup, fPace move the actual price, not just forecast
  - BUT with tighter clamps than old GAS to prevent price explosions:
    * Individual factor: 0.90 - 1.15 (GAS was 0.85 - 1.25)
    * fTotal: 0.85 - 1.25 (GAS was 0.70 - 1.50)
    * Urgency: max 1.5x (GAS was 2.5x)
  - EBSA (early booking signal) gives additional upside when pace is strong
  - Boost UA preserved for scarcity pricing

  Net effect: prices can move +/- 25% from Capa A base instead of 0%.
  Still clamped by floors/ceilings as final safety net.

GOAL: cada mes factura más que el año anterior. No pasarnos, no quedarnos cortos.
"""

import logging
from datetime import date, timedelta
from rms import config
from rms.utils import fmt, clamp, is_weekend, get_month, days_until, add_days
from rms.otb import (
    fetch_historical_bookings, build_fill_curves, calc_pickup, calc_pace,
    read_current_prices, get_expected_occ, get_segment_key,
    read_otb_by_type,
)
from rms.los import get_min_stay_dinamico, detect_gaps_dinamico
from rms.events import get_event_factor, get_vacaciones_factor

log = logging.getLogger(__name__)


# ══════════════════════════════════════════
# SEGMENT HELPERS
# ══════════════════════════════════════════

def get_demand_segment(d):
    if isinstance(d, str):
        from rms.utils import parse_date
        d = parse_date(d)
    m = d.month
    dt = "WE" if d.weekday() in (4, 5) else "WD"
    return f"{m}-{dt}"


def get_season_code(d):
    if isinstance(d, str):
        from rms.utils import parse_date
        d = parse_date(d)
    return config.SEASON_CODE[d.month]


# ══════════════════════════════════════════
# v7.3 DIRECT MULTIPLIER CONFIG
# Conservative clamps to prevent price explosions
# ══════════════════════════════════════════

# Sensitivities by season — from GAS production, proven in 2025
SENS_BY_SEASON = {
    "UA": {"OTB": 0.35, "PICKUP": 0.25, "PACE": 0.00},
    "A":  {"OTB": 0.30, "PICKUP": 0.20, "PACE": 0.10},
    "MA": {"OTB": 0.35, "PICKUP": 0.20, "PACE": 0.35},
    "M":  {"OTB": 0.40, "PICKUP": 0.25, "PACE": 0.50},
    "MB": {"OTB": 0.40, "PICKUP": 0.25, "PACE": 0.50},
    "B":  {"OTB": 0.40, "PICKUP": 0.25, "PACE": 0.50},
}

# v7.3: TIGHTER than GAS to prevent cascading explosions
FACTOR_IND_MIN = 0.90   # GAS was 0.85
FACTOR_IND_MAX = 1.15   # GAS was 1.25
FACTOR_TOTAL_MIN = 0.85  # GAS was 0.70
FACTOR_TOTAL_MAX = 1.25  # GAS was 1.50

# Urgency: how much signals amplify close to arrival
# v7.3: capped at 1.5 (GAS went to 2.5 which caused explosions)
URGENCY_MULTIPLIERS = {45: 1.0, 30: 1.2, 14: 1.5, 7: 1.5}

# Boost UA: extra push when few units left in July/August
BOOST_UA = {1: 1.20, 2: 1.12, 3: 1.06, 4: 1.03, 5: 1.00}


# ══════════════════════════════════════════
# EBSA — Early Booking Signal Advantage
# Post-clamp boost when pace is ahead of historical
# ══════════════════════════════════════════

EBSA_CONFIG = {
    "enabled": True,
    "SENS_EBSA": 0.12,
    "LEAD_TIME_CURVE": [
        {"dias": 0, "peso": 0.00},
        {"dias": 7, "peso": 0.00},
        {"dias": 14, "peso": 0.50},
        {"dias": 30, "peso": 1.00},
        {"dias": 60, "peso": 1.50},
        {"dias": 90, "peso": 1.80},
        {"dias": 120, "peso": 2.20},
        {"dias": 180, "peso": 2.80},
        {"dias": 270, "peso": 3.20},
        {"dias": 365, "peso": 3.50},
    ],
    "FACTOR_MIN": 0.90,   # v7.3: was 0.85 in GAS
    "FACTOR_MAX": 1.25,   # v7.3: was 1.35 in GAS
    "MIN_EXPECTED_OCC": 0.02,
    "SENS_BY_SEASON": {
        "B": 0.15, "MB": 0.14, "M": 0.12,
        "MA": 0.10, "A": 0.08, "UA": 0.06,
    },
}


def _interpolate_lead_time(days_out, curve):
    if days_out <= curve[0]["dias"]:
        return curve[0]["peso"]
    if days_out >= curve[-1]["dias"]:
        return curve[-1]["peso"]
    for i in range(len(curve) - 1):
        lo, hi = curve[i], curve[i + 1]
        if lo["dias"] <= days_out <= hi["dias"]:
            pct = (days_out - lo["dias"]) / (hi["dias"] - lo["dias"])
            return lo["peso"] + (hi["peso"] - lo["peso"]) * pct
    return 1.0


def get_ebsa(days_out, occ_actual, occ_esperada, season_code):
    """Early Booking Signal Advantage — boost when pace ahead of expected."""
    cfg = EBSA_CONFIG
    if not cfg["enabled"]:
        return 1.0

    occ_esp_adj = occ_esperada
    if days_out > 120:
        scale = max(0.05, 1.0 - (days_out - 120) / (365 - 120) * 0.95)
        occ_esp_adj = occ_esperada * scale

    if occ_esp_adj is None:
        return 1.0
    occ_esp = max(occ_esp_adj, cfg["MIN_EXPECTED_OCC"])
    pace_ratio = occ_actual / occ_esp if occ_esp > 0 else 1.0

    # At >90 days, only boost (don't penalize)
    if days_out > 90 and pace_ratio < 1.0:
        return 1.0
    if abs(pace_ratio - 1.0) < 0.05:
        return 1.0

    lead_weight = _interpolate_lead_time(days_out, cfg["LEAD_TIME_CURVE"])
    if lead_weight <= 0.01:
        return 1.0

    sens = cfg["SENS_BY_SEASON"].get(season_code, cfg["SENS_EBSA"])
    f_ebsa = 1 + (pace_ratio - 1) * sens * lead_weight
    f_ebsa = clamp(cfg["FACTOR_MIN"], f_ebsa, cfg["FACTOR_MAX"])
    return round(f_ebsa, 3)


# ══════════════════════════════════════════
# UNCONSTRAINED DEMAND ESTIMATION
# ══════════════════════════════════════════

UNCONSTRAINED_DEMAND = {
    "enabled": True,
    "occ_threshold": 0.85,
    "max_uplift": 1.25,
    "max_disp_affected": 3,
    "method": "proportional",
}

SEGMENT_OCC_HIST = {
    "1-WD": 27.8, "1-WE": 35.8,
    "2-WD": 87.2, "2-WE": 90.3,
    "3-WD": 91.9, "3-WE": 84.0,
    "4-WD": 92.4, "4-WE": 88.9,
    "5-WD": 87.3, "5-WE": 92.2,
    "6-WD": 87.4, "6-WE": 93.1,
    "7-WD": 94.2, "7-WE": 90.3,
    "8-WD": 94.2, "8-WE": 94.4,
    "9-WD": 89.9, "9-WE": 94.4,
    "10-WD": 88.9, "10-WE": 86.4,
    "11-WD": 85.7, "11-WE": 86.4,
    "12-WD": 42.0, "12-WE": 48.6,
}


def get_unconstrained_uplift(segment, disponibles):
    cfg = UNCONSTRAINED_DEMAND
    if not cfg["enabled"]:
        return 1.0
    if disponibles > cfg["max_disp_affected"]:
        return 1.0
    occ_hist = SEGMENT_OCC_HIST.get(segment, 0) / 100.0
    if occ_hist < cfg["occ_threshold"]:
        return 1.0
    p_turnaway = (occ_hist - cfg["occ_threshold"]) / (1 - cfg["occ_threshold"])
    p_turnaway = min(p_turnaway, 1.0)
    scarcity = {1: 1.0, 2: 0.60, 3: 0.30}
    scarcity_factor = scarcity.get(disponibles, 0.0)
    uplift = 1.0 + p_turnaway * scarcity_factor * (cfg["max_uplift"] - 1.0)
    return round(min(uplift, cfg["max_uplift"]), 3)


# ══════════════════════════════════════════
# MARKET FACTOR — Uses AirROI data
# ══════════════════════════════════════════

def get_market_factor(date_str):
    if not hasattr(config, 'MARKET_OCC') or not config.MARKET_OCC:
        return 1.0
    month = int(date_str[5:7])
    market_occ = config.MARKET_OCC.get(month)
    if not market_occ:
        return 1.0
    seg = f"{month}-WD"
    our_occ = SEGMENT_OCC_HIST.get(seg, 50) / 100.0
    diff = market_occ - our_occ
    if diff > 0.10:
        return min(1.10, 1.0 + diff * 0.5)
    elif diff < -0.10:
        return max(0.95, 1.0 + diff * 0.3)
    return 1.0


# ══════════════════════════════════════════
# MODULE 1: FORECAST (secondary — virtual availability)
# ══════════════════════════════════════════

def forecast(fecha, fill_curves, pace_data, pickup_data, otb, events):
    """
    Forecast provides virtual availability for Capa A lookup.
    Main price movement now comes from direct multipliers in execute().
    """
    cfg = config.V7["FORECAST"]
    date_str = fmt(fecha)
    seg_key = get_segment_key(fecha)
    days_out = days_until(fecha)
    season_code = get_season_code(fecha)

    occ_esperada = get_expected_occ(fill_curves, seg_key, days_out)
    demanda_base = occ_esperada * config.TOTAL_UNITS

    reservadas = otb.get(date_str, 0)
    disponibles = config.TOTAL_UNITS - reservadas
    occ_actual = reservadas / config.TOTAL_UNITS

    # Pace adjustment (for forecast)
    ajuste_pace = 1.0
    pace_ratio_raw = 0.0
    if pace_data and date_str in pace_data:
        otb_ly = pace_data[date_str]
        if otb_ly > 0.05:
            pace_ratio_raw = occ_actual / otb_ly
            ajuste_pace = clamp(cfg["PACE_MIN"], 1.0 + (pace_ratio_raw - 1.0) * cfg["PACE_SENS"], cfg["PACE_MAX"])
            if days_out > 90:
                ajuste_pace = 1.0 + (ajuste_pace - 1.0) * 0.5

    # Pickup adjustment (for forecast)
    ajuste_pickup = 1.0
    pickup_real = 0
    pickup_esperado = 0
    if pickup_data and date_str in pickup_data:
        pickup_real = pickup_data[date_str]
        exp_occ_7ago = get_expected_occ(fill_curves, seg_key, days_out + 7)
        pickup_esperado = max(0.5, (occ_esperada - exp_occ_7ago) * config.TOTAL_UNITS)
        if pickup_esperado > 0:
            ajuste_pickup = clamp(
                cfg["PICKUP_MIN"],
                1.0 + (pickup_real - pickup_esperado) / pickup_esperado * cfg["PICKUP_SENS"],
                cfg["PICKUP_MAX"],
            )

    # Event + vac + market
    event_info = get_event_factor(date_str, events)
    ajuste_evento = clamp(cfg["EVENTO_MIN"], event_info["factor"], cfg["EVENTO_MAX"])
    ajuste_vac = clamp(cfg["VAC_MIN"], get_vacaciones_factor(date_str), cfg["VAC_MAX"])
    ajuste_market = get_market_factor(date_str)

    demanda_total = demanda_base * ajuste_pace * ajuste_pickup * ajuste_evento * ajuste_vac * ajuste_market
    demanda_incremental = max(0, demanda_total - reservadas)
    demanda_incremental = min(demanda_incremental, disponibles)
    demanda_incremental = round(demanda_incremental, 1)

    return {
        "demanda": demanda_incremental,
        "demandaTotal": round(demanda_total, 1),
        "occEsperada": occ_esperada,
        "occActual": occ_actual,
        "paceRatioRaw": pace_ratio_raw,
        "pickupReal": pickup_real,
        "pickupEsperado": pickup_esperado,
        "desglose": {
            "base": round(demanda_base, 1),
            "pace": round(ajuste_pace, 3),
            "pickup": round(ajuste_pickup, 3),
            "evento": round(ajuste_evento, 3),
            "vac": round(ajuste_vac, 3),
            "market": round(ajuste_market, 3),
        },
        "eventInfo": event_info,
        "seasonCode": season_code,
        "daysOut": days_out,
    }


# ══════════════════════════════════════════
# MODULE 2: OPTIMIZE (Capa A base price + virtual availability)
# ══════════════════════════════════════════

def optimize(fecha, fc, otb):
    cfg_opt = config.V7["OPTIM"]
    date_str = fmt(fecha)
    seg = get_demand_segment(fecha)
    season_code = fc["seasonCode"]
    pricing = config.SEGMENT_BASE.get(seg)

    if not pricing:
        m = fecha.month if hasattr(fecha, 'month') else int(str(fecha)[5:7])
        pricing = config.SEGMENT_BASE.get(f"{m}-WD", {
            "code": config.SEASON_CODE.get(m, "M"),
            "base": 100, "suelo": 70, "techo": 200, "preciosPorDisp": None,
        })

    reservadas = otb.get(date_str, 0)
    disponibles_real = max(0, min(config.TOTAL_UNITS, config.TOTAL_UNITS - reservadas))
    disponibles = max(1, disponibles_real)

    # Price from Capa A by availability
    ppd = pricing.get("preciosPorDisp")
    if ppd and disponibles in ppd:
        p = ppd[disponibles]
        precio_base = p["precio"] if isinstance(p, dict) else p
    else:
        precio_base = pricing.get("base", 100)

    # Forecast: virtual availability (secondary signal)
    demanda_inc = fc["demanda"]
    disp_virtual = max(1, round(disponibles - demanda_inc))
    disp_virtual = min(disp_virtual, config.TOTAL_UNITS)

    if disp_virtual < disponibles and ppd and disp_virtual in ppd:
        p_fc = ppd[disp_virtual]
        precio_forecast = p_fc["precio"] if isinstance(p_fc, dict) else p_fc
        precio_base = round(
            precio_base * cfg_opt["PESO_REAL"] + precio_forecast * cfg_opt["PESO_FORECAST"]
        )

    # ── BOOST UA: extra push for scarcity in July/August ──
    boost_factor = 1.0
    if season_code == "UA" and disponibles_real <= 5:
        boost_factor = BOOST_UA.get(disponibles_real, 1.0)
        boosted = round(precio_base * boost_factor)
        if boosted > precio_base:
            precio_base = boosted

    # Unconstrained Demand Uplift
    unc_uplift = get_unconstrained_uplift(seg, disponibles_real)
    if unc_uplift > 1.0:
        precio_base = round(precio_base * unc_uplift)

    # Comp set adjustment (only brakes, never pushes — unchanged)
    ajuste_cs = _comp_set_adjustment(date_str, precio_base)
    precio_base = round(precio_base * ajuste_cs)

    return {
        "precioNeto": precio_base,
        "disponibles": disponibles_real,
        "disponiblesCalc": disponibles,
        "reservadas": reservadas,
        "dispVirtual": disp_virtual,
        "ajusteCompSet": ajuste_cs,
        "segment": seg,
        "uncUplift": unc_uplift,
        "boostUA": boost_factor,
    }


def _comp_set_adjustment(date_str, precio_neto):
    cfg_cs = config.V7["COMP_SET_ADJ"]
    month = int(date_str[5:7])
    comp_mediana = config.COMP_SET["ADR_PEER"].get(month, 0)
    if comp_mediana <= 0:
        return 1.0
    ratio = precio_neto / comp_mediana
    if ratio > cfg_cs["RATIO_ALTO"]:
        return cfg_cs["FACTOR_ALTO"]
    if ratio > cfg_cs["RATIO_MEDIO"]:
        return cfg_cs["FACTOR_MEDIO"]
    return 1.0


# ══════════════════════════════════════════
# MODULE 3: EXECUTE — Now with DIRECT MULTIPLIERS
# ══════════════════════════════════════════

def execute(fecha, precio_neto, fc, opt, otb, sold_prices, gaps, fill_curves, pace_data, pickup_data):
    """
    v7.3: Applies direct price multipliers (fOTB, fPickup, fPace)
    to the base price, like GAS v6.1.3 did, but with tighter clamps.
    """
    date_str = fmt(fecha)
    sc = fc["seasonCode"]
    days_out = fc["daysOut"]
    event_info = fc["eventInfo"]
    reservadas = otb.get(date_str, 0)
    disponibles_real = max(0, config.TOTAL_UNITS - reservadas)
    disponibles = max(1, disponibles_real)
    occ_now = reservadas / config.TOTAL_UNITS

    # ── 1. Floor & ceiling ──
    suelo = _get_suelo(sc, date_str)
    techo = _get_techo(sc, date_str)

    # ── 2. Event: raise floor and price ──
    if event_info.get("floorOverride") and event_info["floorOverride"] > suelo:
        suelo = event_info["floorOverride"]
    base_post_event = precio_neto
    if event_info["factor"] > 1.0:
        base_post_event = round(precio_neto * event_info["factor"])

    # ── 3. Apply Genius compensation ──
    base_pub = round(base_post_event * config.GENIUS_COMPENSATION)

    # ══════════════════════════════════════════
    # v7.3 CORE: DIRECT MULTIPLIERS ON PRICE
    # ══════════════════════════════════════════

    seg_fill = get_segment_key(fecha)
    occ_esperada = fc["occEsperada"]
    sens = SENS_BY_SEASON.get(sc, {"OTB": 0.35, "PICKUP": 0.25, "PACE": 0.30})

    # fOTB: current occupancy vs expected occupancy
    f_otb = 1 + (occ_now - occ_esperada) * sens["OTB"]
    # UA at >60 days: don't penalize below pace (2025 filled fast, unfair benchmark)
    if sc == "UA" and days_out > 60 and f_otb < 1.0:
        f_otb = 1.0
    f_otb = clamp(FACTOR_IND_MIN, f_otb, FACTOR_IND_MAX)

    # fPickup: recent booking velocity vs expected
    f_pickup = 1.0
    pickup_real = fc.get("pickupReal", 0)
    pickup_esperado = fc.get("pickupEsperado", 0)
    if pickup_esperado > 0 and pickup_real != 0:
        f_pickup = 1 + ((pickup_real - pickup_esperado) / pickup_esperado) * sens["PICKUP"]
        f_pickup = clamp(FACTOR_IND_MIN, f_pickup, FACTOR_IND_MAX)

    # fPace: year-over-year pace comparison
    f_pace = 1.0
    pace_ratio = fc.get("paceRatioRaw", 0)
    if pace_data and date_str in pace_data:
        otb_ly = pace_data[date_str]
        if otb_ly > 0.05:
            pace_ratio = occ_now / otb_ly
            f_pace = 1 + (pace_ratio - 1) * sens["PACE"]
            f_pace = clamp(FACTOR_IND_MIN, f_pace, FACTOR_IND_MAX)

    # Urgency: amplify signals closer to arrival
    urgency = 1.0
    for threshold in sorted(URGENCY_MULTIPLIERS.keys(), reverse=True):
        if days_out <= threshold:
            urgency = URGENCY_MULTIPLIERS[threshold]

    # Combine: fTotal = 1 + (product - 1) × urgency
    f_product = f_otb * f_pickup * f_pace
    f_adjusted = 1 + (f_product - 1) * urgency

    # Last-minute override can lower the floor
    lm = _get_last_minute(sc, days_out, disponibles)
    factor_total_min = FACTOR_TOTAL_MIN
    if lm:
        factor_total_min = lm["factorMin"]
        suelo_lm = max(35, round(suelo * lm["sueloPct"]))
        suelo = suelo_lm

    f_total = clamp(factor_total_min, f_adjusted, FACTOR_TOTAL_MAX)

    # Apply multiplier to price
    precio_bruto = round(base_pub * f_total)

    # ── 4. Price protection ──
    media_vendida = 0
    prot_level = 0
    precio_bruto_pre_prot = precio_bruto
    if sold_prices and date_str in sold_prices and sold_prices[date_str]:
        precios = sold_prices[date_str]
        media_vendida = sum(precios) / len(precios)
        if lm:
            prot_level = lm["priceProtection"]
        else:
            for threshold, level in sorted(config.PRICE_PROTECTION_BY_DAYS.items(), reverse=True):
                if days_out >= threshold:
                    prot_level = level
                    break
        if prot_level > 0:
            min_prot = round(media_vendida * prot_level)
            if precio_bruto < min_prot:
                precio_bruto = min_prot

    # ── 5. EBSA post-clamp: additional upside when pace is strong ──
    f_ebsa_raw = get_ebsa(days_out, occ_now, occ_esperada, sc)
    f_ebsa_applied = 1.0
    if f_ebsa_raw > 1.01:
        precio_ebsa = round(precio_bruto_pre_prot * f_ebsa_raw)
        if precio_ebsa > precio_bruto:
            precio_bruto = precio_ebsa
            f_ebsa_applied = f_ebsa_raw

    # ── 6. Clamp to floor/ceiling ──
    precio_pub = precio_bruto
    clamped_by = ""
    if precio_pub > techo:
        precio_pub = techo
        clamped_by = "TECHO"
    if precio_pub < suelo:
        precio_pub = suelo
        clamped_by = "SUELO"

    # ── 7. LOS dinámico ──
    los = get_min_stay_dinamico(fecha, occ_now, days_out, sc, occ_esperada, disponibles)
    min_stay = los["minStay"]
    los_premium = los["premium"]
    los_razon = los["razon"]
    los_reduccion = los["reduccion"]

    if event_info.get("minStay") and event_info["minStay"] > min_stay:
        min_stay = event_info["minStay"]

    # Gap overrides
    gap_info = gaps.get(date_str) if gaps else None
    gap_override = False
    gap_override_ground = False
    min_stay_ground = min_stay

    if gap_info and not event_info.get("minStay"):
        if gap_info.get("minStayGap") and gap_info["minStayGap"] < min_stay:
            min_stay = gap_info["minStayGap"]
            gap_override = True
        if gap_info.get("premiumGap") and gap_info["premiumGap"] > los_premium:
            los_premium = gap_info["premiumGap"]
        if gap_info.get("minStayGapGround"):
            min_stay_ground = gap_info["minStayGapGround"]
            gap_override_ground = True
            if gap_info.get("premiumGapGround") and gap_info["premiumGapGround"] > los_premium:
                los_premium = gap_info["premiumGapGround"]

    if los_reduccion > 0 or gap_override:
        precio_pub = round(precio_pub * los_premium)
        precio_pub = max(suelo, min(techo, precio_pub))

    # ── 8. Min booking revenue ──
    min_rev = config.MIN_BOOKING_REVENUE.get(sc, 415)
    min_rev_per_night = min_rev / min_stay if min_stay > 0 else min_rev
    min_rev_applied = False
    if precio_pub < min_rev_per_night:
        precio_pub = round(min_rev_per_night)
        min_rev_applied = True
    precio_pub = max(suelo, min(techo, precio_pub))

    return {
        "precioPublicado": precio_pub,
        "precioGenius": round(precio_pub * 0.85),
        "suelo": suelo, "techo": techo,
        "clampedBy": clamped_by,
        "minStay": min_stay,
        "minStayGround": min_stay_ground,
        "losRazon": los_razon, "losReduccion": los_reduccion, "losPremium": los_premium,
        "gapOverride": gap_override,
        "gapOverrideGround": gap_override_ground,
        "minRevApplied": min_rev_applied,
        "minRevPerNight": round(min_rev_per_night),
        "mediaVendida": round(media_vendida),
        "protLevel": prot_level,
        "lastMinuteLevel": lm["label"] if lm else None,
        "occNow": occ_now,
        "isWeekend": is_weekend(date_str),
        "eventName": event_info.get("name"),
        "eventFactor": event_info["factor"],
        # v7.3: actual multiplier values for transparency
        "fOTB": round(f_otb, 3),
        "fPickup": round(f_pickup, 3),
        "fPace": round(f_pace, 3),
        "fTotal": round(f_total, 3),
        "fEBSA": round(f_ebsa_applied, 3),
        "urgency": urgency,
        "basePub": base_pub,
    }


def _get_suelo(sc, date_str):
    month = int(date_str[5:7])
    suelo = config.MONTHLY_FLOOR.get(month, config.SEASONAL_FLOOR.get(sc, 50))
    if is_weekend(date_str):
        premium = config.WEEKEND_FLOOR_PREMIUM.get(sc, 1.0)
        suelo = round(suelo * premium)
    return suelo


def _get_techo(sc, date_str):
    month = int(date_str[5:7])
    if config.MONTHLY_CEILING.get(month):
        return config.MONTHLY_CEILING[month]
    seg = get_demand_segment(date_str)
    pricing = config.SEGMENT_BASE.get(seg, {})
    if pricing.get("techo"):
        return pricing["techo"]
    mult = config.CEILING_BY_SEASON.get(sc, 1.50)
    suelo = config.SEASONAL_FLOOR.get(sc, 100)
    return round(suelo * mult)


def _get_last_minute(sc, days_out, disponibles):
    lm = config.LAST_MINUTE_WINTER
    if not lm or not lm["enabled"]:
        return None
    if sc not in lm["seasons"]:
        return None
    if days_out <= lm["level2_days"] and disponibles >= lm["level2_min_units"]:
        return {
            "level": 2, "priceProtection": lm["level2_protection"],
            "factorMin": lm["level2_factor_min"], "sueloPct": lm["level2_suelo_pct"],
            "label": "LAST-MIN L2",
        }
    if days_out <= lm["max_days_out"] and disponibles >= lm["min_units_free"]:
        return {
            "level": 1, "priceProtection": lm["price_protection_override"],
            "factorMin": lm["factor_min_override"], "sueloPct": lm["suelo_override_pct"],
            "label": "LAST-MIN L1",
        }
    return None


# ══════════════════════════════════════════
# SMOOTHING
# ══════════════════════════════════════════

def smooth(results):
    max_var = config.V7["SUAVIZADO"]["MAX_VARIACION_DIARIA"]

    for i in range(1, len(results)):
        hoy = results[i]
        ayer = results[i - 1]
        if hoy["seasonCode"] != ayer["seasonCode"]:
            continue
        if hoy.get("eventName") or ayer.get("eventName"):
            continue
        ratio = hoy["precioFinal"] / ayer["precioFinal"] if ayer["precioFinal"] > 0 else 1
        if ratio > 1 + max_var:
            hoy["precioFinal"] = round(ayer["precioFinal"] * (1 + max_var))
            hoy["suavizado"] = "BAJADO"
        elif ratio < 1 - max_var:
            hoy["precioFinal"] = round(ayer["precioFinal"] * (1 - max_var))
            hoy["suavizado"] = "SUBIDO"
        hoy["precioFinal"] = max(hoy["suelo"], min(hoy["techo"], hoy["precioFinal"]))

    # Monotonicity: more booked → at least same price
    for i in range(1, len(results)):
        hoy = results[i]
        ayer = results[i - 1]
        if hoy["date"][:7] != ayer["date"][:7]:
            continue
        if hoy.get("eventName") or ayer.get("eventName"):
            continue
        if hoy["reservadas"] > ayer["reservadas"] and hoy["precioFinal"] < ayer["precioFinal"]:
            hoy["precioFinal"] = min(hoy["techo"], ayer["precioFinal"])
            if not hoy.get("suavizado"):
                hoy["suavizado"] = "MONO_UP"
        if hoy["reservadas"] < ayer["reservadas"] and hoy["precioFinal"] > ayer["precioFinal"]:
            hoy["precioFinal"] = max(hoy["suelo"], ayer["precioFinal"])
            if not hoy.get("suavizado"):
                hoy["suavizado"] = "MONO_DN"

    return results


# ══════════════════════════════════════════
# MAIN: calcular_precios_v7
# ══════════════════════════════════════════

def calcular_precios_v7(otb, events, otb_by_type=None):
    """
    Full v7.3 pricing pipeline.
    Now with direct price multipliers (conservative clamps).
    """
    log.info("  v7.3: Capa A + Direct Multipliers + Forecast + Smooth")

    hist = fetch_historical_bookings()
    fill_curves = build_fill_curves(hist)
    gaps = detect_gaps_dinamico(otb, otb_by_type)
    sold_prices = read_current_prices()
    pickup_data = calc_pickup(otb)
    pace_data = calc_pace(hist)

    today = date.today()
    results = []
    unc_count = 0
    market_adjusted = 0
    boost_count = 0
    multiplier_active = 0

    for di in range(config.PRICING_HORIZON):
        d = today + timedelta(days=di)
        date_str = fmt(d)

        # Step 1: Forecast (for virtual availability + raw signals)
        fc = forecast(d, fill_curves, pace_data, pickup_data, otb, events)

        # Step 2: Optimize (Capa A base price)
        opt = optimize(d, fc, otb)
        if opt.get("uncUplift", 1.0) > 1.0:
            unc_count += 1
        if opt.get("boostUA", 1.0) > 1.0:
            boost_count += 1

        # Step 3: Execute (direct multipliers + floor/ceiling)
        ej = execute(d, opt["precioNeto"], fc, opt, otb, sold_prices, gaps,
                     fill_curves, pace_data, pickup_data)

        mf = fc["desglose"].get("market", 1.0)
        if mf != 1.0:
            market_adjusted += 1

        # Track how many dates have active multipliers
        if abs(ej["fTotal"] - 1.0) > 0.02:
            multiplier_active += 1

        results.append({
            "date": date_str,
            "segment": opt["segment"],
            "seasonCode": fc["seasonCode"],
            "disponibles": opt["disponibles"],
            "reservadas": opt["reservadas"],
            "precioFinal": ej["precioPublicado"],
            "precioGenius": ej["precioGenius"],
            "suelo": ej["suelo"],
            "seasonalFloor": ej["suelo"],
            "techo": ej["techo"],
            "minStay": ej["minStay"],
            "minStayGround": ej.get("minStayGround", ej["minStay"]),
            "daysOut": di,
            "occNow": ej["occNow"],
            "isWeekend": ej["isWeekend"],
            "eventName": ej["eventName"],
            "eventFactor": ej["eventFactor"],
            "clampedBy": ej["clampedBy"],
            "gapOverride": ej["gapOverride"],
            "gapOverrideGround": ej.get("gapOverrideGround", False),
            "losRazon": ej["losRazon"] or "",
            "losReduccion": ej["losReduccion"] or 0,
            "losPremium": ej["losPremium"] or 1.0,
            "minRevPerNight": ej["minRevPerNight"],
            "minRevApplied": ej["minRevApplied"],
            "lastMinuteLevel": ej["lastMinuteLevel"],
            "mediaVendida": ej["mediaVendida"],
            "protLevel": ej["protLevel"],
            "precioNeto": opt["precioNeto"],
            "dispVirtual": opt["dispVirtual"],
            "ajusteCompSet": opt["ajusteCompSet"],
            "forecastDemanda": fc["demanda"],
            "expectedOcc": fc["occEsperada"],
            "suavizado": None,
            "base": opt["precioNeto"],
            "basePostEvent": round(opt["precioNeto"] * ej["eventFactor"]) if ej["eventFactor"] > 1 else opt["precioNeto"],
            # v7.3: REAL multiplier values (no longer hardcoded 1.0)
            "fOTB": ej["fOTB"],
            "fPickup": ej["fPickup"],
            "fPace": ej["fPace"],
            "fTotal": ej["fTotal"],
            "fEBSA": ej["fEBSA"],
            "urgency": ej["urgency"],
            "basePub": ej["basePub"],
            "paceRatio": fc.get("paceRatioRaw", 0),
            "marketFactor": mf,
            "vacFactor": fc["desglose"].get("vac", 1.0),
            "uncUplift": opt.get("uncUplift", 1.0),
            "boostUA": opt.get("boostUA", 1.0),
        })

    # Step 4: Smooth
    results = smooth(results)

    # Recalc genius after smoothing
    for r in results:
        r["precioGenius"] = round(r["precioFinal"] * 0.85)

    log.info(f"  ✅ v7.3: {len(results)} días calculados")
    log.info(f"  📊 Multiplicadores activos: {multiplier_active} fechas con fTotal ≠ 1.0")
    if unc_count > 0:
        log.info(f"  📈 Demanda no restringida: {unc_count} fechas con uplift")
    if boost_count > 0:
        log.info(f"  🔥 Boost UA: {boost_count} fechas con scarcity premium")
    if market_adjusted > 0:
        log.info(f"  🌍 Market factor: {market_adjusted} fechas ajustadas")

    vac_count = sum(1 for r in results if r.get("vacFactor", 1.0) > 1.0)
    if vac_count > 0:
        log.info(f"  🏫 Vacaciones escolares: {vac_count} fechas con boost")

    return results
