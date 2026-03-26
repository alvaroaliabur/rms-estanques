"""
RMS v7.5 Pricing Engine — Forecast → Optimize → Execute → Smooth

CAMBIOS v7.5 vs v7.4:
  - P3: Suelos dinámicos por days_out
    Un suelo de 362€ tiene sentido a 14d, no a 150d.
    Escalonado: 100% a <30d, 85% a 30-60d, 75% a 60-90d, 65% a >90d
    Permite capturar early bookers a precio atractivo en temporadas lejanas.
  - P6: Early bird para sep-oct abandonados
    Cuando days_out > 60 y occ < 0.15 y temporada MA/A:
    bajar precio base un escalón para capturar primeras reservas.
    Una vez entran las primeras, el motor sube naturalmente.
  - fOTB/fPick/fPace ahora se propagan correctamente al output
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
# UNCONSTRAINED DEMAND ESTIMATION
# ══════════════════════════════════════════

UNCONSTRAINED_DEMAND = {
    "enabled": True,
    "occ_threshold": 0.85,
    "max_uplift": 1.25,
    "max_disp_affected": 3,
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


def get_unconstrained_uplift(segment, disponibles_real):
    cfg = UNCONSTRAINED_DEMAND
    if not cfg["enabled"]:
        return 1.0
    if disponibles_real > cfg["max_disp_affected"]:
        return 1.0

    occ_hist = SEGMENT_OCC_HIST.get(segment, 0) / 100.0
    if occ_hist < cfg["occ_threshold"]:
        return 1.0

    p_turnaway = (occ_hist - cfg["occ_threshold"]) / (1 - cfg["occ_threshold"])
    p_turnaway = min(p_turnaway, 1.0)

    scarcity = {1: 1.0, 2: 0.60, 3: 0.30}
    scarcity_factor = scarcity.get(disponibles_real, 0.0)

    uplift = 1.0 + p_turnaway * scarcity_factor * (cfg["max_uplift"] - 1.0)
    return round(min(uplift, cfg["max_uplift"]), 3)


# ══════════════════════════════════════════
# MARKET FACTOR — AirROI
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
# P3: DYNAMIC FLOOR BY DAYS_OUT
#
# Un suelo de 362€ es correcto a 14 días vista.
# A 150 días, con 8 disp, bloquea early bookers.
# Escalonado:
#   <30 días:  100% del suelo (protección máxima)
#   30-60 días: 85% (ligera flexibilidad)
#   60-90 días: 75% (capturar demanda temprana)
#   >90 días:  65% (early bird agresivo)
#
# Solo aplica a meses de alta/ultra alta temporada.
# En baja temporada los suelos ya son bajos — no tocar.
# ══════════════════════════════════════════

FLOOR_DISCOUNT_BY_DAYS_OUT = {
    # (min_days, max_days): factor
    (0, 29): 1.00,    # Protección total
    (30, 59): 0.85,   # Ligera flexibilidad
    (60, 89): 0.75,   # Capturar demanda temprana
    (90, 999): 0.65,  # Early bird
}

# Temporadas donde aplicar suelo dinámico (las que tienen suelos altos)
FLOOR_DYNAMIC_SEASONS = ("UA", "A", "MA")


def get_dynamic_floor_factor(days_out, season_code):
    """
    Returns factor to apply to the monthly floor based on how far out the date is.
    Only for high-season months where floors are meaningful.
    """
    if season_code not in FLOOR_DYNAMIC_SEASONS:
        return 1.0  # Low season: don't touch floors

    for (lo, hi), factor in FLOOR_DISCOUNT_BY_DAYS_OUT.items():
        if lo <= days_out <= hi:
            return factor

    return 1.0


# ══════════════════════════════════════════
# P6: EARLY BIRD — Sep/Oct strategy
#
# Problem: Sep 15-30 and all of Oct show 8 disp, all SUELO, pace 1.0
# at 5-6 months out. The motor has no strategy for far-out empty periods.
#
# Solution: When a date is far out (>60d), nearly empty (<15% occ),
# and in a shoulder season (MA, A), lower the starting price by one
# availability step to make it more attractive for first movers.
# Once bookings come in, the motor naturally raises prices.
# ══════════════════════════════════════════

EARLY_BIRD = {
    "enabled": True,
    "min_days_out": 60,         # Only for dates > 60 days away
    "max_occ_threshold": 0.15,  # Only when < 15% occupied
    "seasons": ("A", "MA"),     # Sep=A, Oct=MA
    "escalones_bajar": 2,       # Use price for 2 more units available
    "factor_directo": 0.90,     # Fallback: 10% discount if no ppd table
}


def _apply_early_bird(precio_base, days_out, season_code, reservadas, ppd):
    """Apply early bird discount for far-out empty shoulder season dates."""
    cfg = EARLY_BIRD
    if not cfg["enabled"]:
        return precio_base

    if days_out < cfg["min_days_out"]:
        return precio_base

    if season_code not in cfg["seasons"]:
        return precio_base

    occ = reservadas / config.TOTAL_UNITS
    if occ >= cfg["max_occ_threshold"]:
        return precio_base  # Already has bookings, no early bird needed

    # Lower price using ppd table
    disponibles = config.TOTAL_UNITS - reservadas
    disp_early = min(config.TOTAL_UNITS, disponibles + cfg["escalones_bajar"])

    if ppd and disp_early in ppd:
        p = ppd[disp_early]
        precio_early = p["precio"] if isinstance(p, dict) else p
        # Blend: 50% early bird price, 50% base
        return round(precio_base * 0.50 + precio_early * 0.50)

    # Fallback: direct factor
    return round(precio_base * cfg["factor_directo"])


# ══════════════════════════════════════════
# MODULE 1: FORECAST
# ══════════════════════════════════════════

def forecast(fecha, fill_curves, pace_data, pickup_data, otb, events):
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

    # Pace — v7.4: referencia multi-año ponderada
    ajuste_pace = 1.0
    if pace_data and date_str in pace_data:
        otb_ref = pace_data[date_str]
        if otb_ref > 0.05:
            ratio = occ_actual / otb_ref
            ajuste_pace = clamp(
                cfg["PACE_MIN"],
                1.0 + (ratio - 1.0) * cfg["PACE_SENS"],
                cfg["PACE_MAX"]
            )
            if days_out > 90:
                ajuste_pace = 1.0 + (ajuste_pace - 1.0) * 0.5

    # Pickup — v7.5: now actually works with persistent snapshots
    ajuste_pickup = 1.0
    if pickup_data and date_str in pickup_data:
        pickup = pickup_data[date_str]
        exp_occ_7ago = get_expected_occ(fill_curves, seg_key, days_out + 7)
        pickup_esperado = max(0.5, (occ_esperada - exp_occ_7ago) * config.TOTAL_UNITS)
        if pickup_esperado > 0:
            ajuste_pickup = clamp(
                cfg["PICKUP_MIN"],
                1.0 + (pickup - pickup_esperado) / pickup_esperado * cfg["PICKUP_SENS"],
                cfg["PICKUP_MAX"],
            )

    # Eventos
    event_info = get_event_factor(date_str, events)
    ajuste_evento = clamp(cfg["EVENTO_MIN"], event_info["factor"], cfg["EVENTO_MAX"])

    # Vacaciones escolares
    ajuste_vac = clamp(cfg["VAC_MIN"], get_vacaciones_factor(date_str), cfg["VAC_MAX"])

    # Market (AirROI)
    ajuste_market = get_market_factor(date_str)

    demanda_total = demanda_base * ajuste_pace * ajuste_pickup * ajuste_evento * ajuste_vac * ajuste_market
    demanda_incremental = max(0, min(demanda_total - reservadas, disponibles))
    demanda_incremental = round(demanda_incremental, 1)

    return {
        "demanda": demanda_incremental,
        "demandaTotal": round(demanda_total, 1),
        "occEsperada": occ_esperada,
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
# MODULE 2: OPTIMIZE
# ══════════════════════════════════════════

def optimize(fecha, fc, otb):
    cfg_opt = config.V7["OPTIM"]
    date_str = fmt(fecha)
    seg = get_demand_segment(fecha)
    season_code = fc["seasonCode"]
    days_out = fc["daysOut"]
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

    ppd = pricing.get("preciosPorDisp")
    if ppd and disponibles in ppd:
        p = ppd[disponibles]
        precio_base = p["precio"] if isinstance(p, dict) else p
    else:
        precio_base = pricing.get("base", 100)

    # Forecast: disponibilidad virtual
    demanda_inc = fc["demanda"]
    disp_virtual = max(1, round(disponibles - demanda_inc))
    disp_virtual = min(disp_virtual, config.TOTAL_UNITS)

    if disp_virtual < disponibles and ppd and disp_virtual in ppd:
        p_fc = ppd[disp_virtual]
        precio_forecast = p_fc["precio"] if isinstance(p_fc, dict) else p_fc
        precio_base = round(
            precio_base * cfg_opt["PESO_REAL"] + precio_forecast * cfg_opt["PESO_FORECAST"]
        )

    # Unconstrained demand uplift
    unc_uplift = get_unconstrained_uplift(seg, disponibles_real)
    if unc_uplift > 1.0:
        precio_base = round(precio_base * unc_uplift)

    # Comp set adj desactivado en UA/A
    ajuste_cs = 1.0
    if season_code not in ("UA", "A"):
        ajuste_cs = _comp_set_adjustment(date_str, precio_base)
        if ajuste_cs < 1.0:
            precio_base = round(precio_base * ajuste_cs)

    # Presión temporal (v7.4)
    precio_base = _aplicar_presion_temporal(
        precio_base, days_out, season_code,
        reservadas, fc["occEsperada"], ppd
    )

    # P6: Early bird para fechas lejanas vacías en shoulder season
    precio_base = _apply_early_bird(
        precio_base, days_out, season_code, reservadas, ppd
    )

    return {
        "precioNeto": precio_base,
        "disponibles": disponibles_real,
        "disponiblesCalc": disponibles,
        "reservadas": reservadas,
        "dispVirtual": disp_virtual,
        "ajusteCompSet": ajuste_cs,
        "segment": seg,
        "uncUplift": unc_uplift,
    }


def _aplicar_presion_temporal(precio_base, days_out, season_code, reservadas, occ_esperada, ppd):
    """v7.4: Presión de ventas integrada — reemplaza urgency."""
    if days_out > 60:
        return precio_base

    occ_actual = reservadas / config.TOTAL_UNITS
    deficit = occ_esperada - occ_actual

    if deficit <= 0.05:
        return precio_base

    if days_out <= 14:
        escalones_bajar = 2
        factor_presion = min(0.92, 1.0 - deficit * 0.8)
    elif days_out <= 30:
        escalones_bajar = 1
        factor_presion = min(0.95, 1.0 - deficit * 0.5)
    else:
        escalones_bajar = 0
        factor_presion = min(0.97, 1.0 - deficit * 0.2)

    if season_code == "UA":
        if occ_actual >= 0.44:
            return precio_base
        factor_presion = max(factor_presion, 0.95)

    if ppd and escalones_bajar > 0:
        disponibles_actual = config.TOTAL_UNITS - reservadas
        disp_presion = min(config.TOTAL_UNITS, disponibles_actual + escalones_bajar)
        if disp_presion in ppd:
            p = ppd[disp_presion]
            precio_presion = p["precio"] if isinstance(p, dict) else p
            precio_base = round(precio_base * 0.40 + precio_presion * 0.60)
            return precio_base

    return round(precio_base * factor_presion)


def _comp_set_adjustment(date_str, precio_neto):
    """v7.4: Umbrales corregidos. Desactivado en UA/A."""
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
# MODULE 3: EXECUTE
# ══════════════════════════════════════════

def execute(fecha, precio_neto, fc, otb, sold_prices, gaps):
    date_str = fmt(fecha)
    sc = fc["seasonCode"]
    days_out = fc["daysOut"]
    event_info = fc["eventInfo"]
    reservadas = otb.get(date_str, 0)
    disponibles_real = max(0, config.TOTAL_UNITS - reservadas)
    disponibles = max(1, disponibles_real)
    occ_now = reservadas / config.TOTAL_UNITS

    # P3: Suelo dinámico por days_out
    suelo_base = _get_suelo(sc, date_str)
    floor_factor = get_dynamic_floor_factor(days_out, sc)
    suelo = max(35, round(suelo_base * floor_factor))

    techo = _get_techo(sc, date_str)

    if event_info.get("floorOverride") and event_info["floorOverride"] > suelo:
        suelo = event_info["floorOverride"]
    if event_info["factor"] > 1.0:
        precio_neto = round(precio_neto * event_info["factor"])

    lm = _get_last_minute(sc, days_out, disponibles)
    if lm:
        suelo_lm = max(35, round(suelo * lm["sueloPct"]))
        suelo = suelo_lm

    precio_pub = round(precio_neto * config.GENIUS_COMPENSATION)

    clamped_by = ""
    if precio_pub > techo:
        precio_pub = techo
        clamped_by = "TECHO"
    if precio_pub < suelo:
        precio_pub = suelo
        clamped_by = "SUELO"

    # Price protection
    media_vendida = 0
    prot_level = 0
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
            if precio_pub < min_prot:
                precio_pub = min_prot
                if not clamped_by:
                    clamped_by = "PROT"

    # LOS dinámico
    los = get_min_stay_dinamico(fecha, occ_now, days_out, sc, fc["occEsperada"], disponibles)
    min_stay = los["minStay"]
    los_premium = los["premium"]
    los_razon = los["razon"]
    los_reduccion = los["reduccion"]

    if event_info.get("minStay") and event_info["minStay"] > min_stay:
        min_stay = event_info["minStay"]

    # Gap detection
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

    # Min booking revenue
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
        "suelo": suelo, "sueloBase": suelo_base, "floorFactor": floor_factor,
        "techo": techo,
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
    log.info("  v7.5: Forecast → Optimización → Ejecución → Suavizado")

    hist = fetch_historical_bookings()
    fill_curves = build_fill_curves(hist)
    gaps = detect_gaps_dinamico(otb, otb_by_type)
    sold_prices = read_current_prices()
    pickup_data = calc_pickup(otb)
    pace_data = calc_pace(hist)

    # Log pickup health
    if pickup_data:
        log.info(f"  ✅ Pickup activo: {len(pickup_data)} fechas con datos")
    else:
        log.warning(f"  ⚠️ Pickup inactivo — sin snapshots históricos")

    today = date.today()
    results = []
    unc_count = 0
    presion_count = 0
    early_bird_count = 0
    dynamic_floor_count = 0
    market_adjusted = 0
    pickup_active_count = 0

    for di in range(config.PRICING_HORIZON):
        d = today + timedelta(days=di)
        date_str = fmt(d)

        fc = forecast(d, fill_curves, pace_data, pickup_data, otb, events)
        opt = optimize(d, fc, otb)

        if opt.get("uncUplift", 1.0) > 1.0:
            unc_count += 1

        ej = execute(d, opt["precioNeto"], fc, otb, sold_prices, gaps)

        mf = fc["desglose"].get("market", 1.0)
        if mf != 1.0:
            market_adjusted += 1

        # Track pickup activity
        if fc["desglose"]["pickup"] != 1.0:
            pickup_active_count += 1

        # Track dynamic floor
        if ej.get("floorFactor", 1.0) < 1.0:
            dynamic_floor_count += 1

        # Detect presión temporal
        ppd = config.SEGMENT_BASE.get(opt["segment"], {}).get("preciosPorDisp", {})
        disp = max(1, config.TOTAL_UNITS - otb.get(date_str, 0))
        base_capa_a = ppd.get(disp, {})
        base_capa_a = base_capa_a.get("precio", base_capa_a) if isinstance(base_capa_a, dict) else base_capa_a
        presion_aplicada = isinstance(base_capa_a, (int, float)) and opt["precioNeto"] < base_capa_a * 0.98
        if presion_aplicada:
            presion_count += 1

        # Detect early bird
        early_bird_aplicado = (
            di > 60 and
            fc["seasonCode"] in EARLY_BIRD["seasons"] and
            (otb.get(date_str, 0) / config.TOTAL_UNITS) < EARLY_BIRD["max_occ_threshold"]
        )
        if early_bird_aplicado:
            early_bird_count += 1

        results.append({
            "date": date_str,
            "segment": opt["segment"],
            "seasonCode": fc["seasonCode"],
            "disponibles": opt["disponibles"],
            "reservadas": opt["reservadas"],
            "precioFinal": ej["precioPublicado"],
            "precioGenius": ej["precioGenius"],
            "suelo": ej["suelo"],
            "sueloBase": ej.get("sueloBase", ej["suelo"]),
            "floorFactor": ej.get("floorFactor", 1.0),
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
            "fOTB": round(fc["desglose"]["pace"], 3),
            "fPickup": round(fc["desglose"]["pickup"], 3),
            "fPace": round(fc["desglose"]["pace"], 3),
            "fTotal": round(fc["desglose"]["pace"] * fc["desglose"]["pickup"], 3),
            "paceRatio": fc["desglose"]["pace"],
            "marketFactor": mf,
            "vacFactor": fc["desglose"].get("vac", 1.0),
            "uncUplift": opt.get("uncUplift", 1.0),
            "presionTemporal": presion_aplicada,
            "earlyBird": early_bird_aplicado,
        })

    results = smooth(results)

    for r in results:
        r["precioGenius"] = round(r["precioFinal"] * 0.85)

    log.info(f"  ✅ v7.5: {len(results)} días calculados")
    if pickup_active_count > 0:
        log.info(f"  📈 Pickup activo en {pickup_active_count} fechas")
    if unc_count > 0:
        log.info(f"  📈 Demanda no restringida: {unc_count} fechas")
    if presion_count > 0:
        log.info(f"  ⏱️ Presión temporal: {presion_count} fechas")
    if early_bird_count > 0:
        log.info(f"  🐦 Early bird: {early_bird_count} fechas con descuento anticipado")
    if dynamic_floor_count > 0:
        log.info(f"  📉 Suelo dinámico: {dynamic_floor_count} fechas con floor reducido")
    if market_adjusted > 0:
        log.info(f"  🌍 Market factor: {market_adjusted} fechas")

    vac_count = sum(1 for r in results if r.get("vacFactor", 1.0) > 1.0)
    if vac_count > 0:
        log.info(f"  🏫 Vacaciones escolares: {vac_count} fechas")

    return results
