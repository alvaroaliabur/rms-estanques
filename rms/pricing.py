"""
RMS v7 Pricing Engine — Forecast → Optimize → Execute → Smooth
v7.1: + Unconstrained Demand Estimation in optimize()

Replaces: calcularPrecios_v7, forecast_v7_, optimizar_v7_, ejecutar_v7_, suavizarPrecios_v7_
"""

import logging
from datetime import date, timedelta
from rms import config
from rms.utils import fmt, clamp, is_weekend, get_month, days_until, add_days
from rms.otb import (
    fetch_historical_bookings, build_fill_curves, calc_pickup, calc_pace,
    read_current_prices, get_expected_occ, get_segment_key,
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
# 
# Problem: When August historically had 94% occupancy, the Capa A
# recorded "sold 9 at 350€" as max demand. But real demand was
# higher — people wanted to book but no inventory was available.
# The demand curve is truncated at capacity (9 units).
#
# Solution: For segments with high historical occupancy (>85%),
# we estimate how much demand was invisible using the
# Weatherford & Bodily method (industry standard):
#
#   unconstrained_demand = observed_demand / (1 - P(turnaway))
#
# Where P(turnaway) is estimated from historical occupancy.
# This translates to a price uplift for low-availability dates.
#
# Implementation: We apply the uplift at optimize() time, 
# BEFORE floors/ceilings, so it compounds with event factors
# and other adjustments. Only affects dates with 1-3 units free.
#
# The uplift is conservative: max +25% for segments at 95% occ.
# This is LESS than what a full unconstrained demand rebuild would
# give, but it's safe to apply immediately without recalibrating
# the entire Capa A.

# Config for unconstrained demand — can be moved to config.py later
UNCONSTRAINED_DEMAND = {
    "enabled": True,
    "occ_threshold": 0.85,     # Only inflate segments above this
    "max_uplift": 1.25,        # Maximum price multiplier
    "max_disp_affected": 3,    # Only affect dates with 1-3 units free
    "method": "proportional",  # proportional to (occ - threshold)
}

# Pre-computed historical occupancy by segment (from CapaA_Precios)
# These come from the GAS Capa A calibration. Format: segment -> occ%
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
    """
    Calculate price uplift factor for unconstrained demand.
    
    Returns a multiplier >= 1.0.
    Only applies when:
    - Segment had high historical occupancy (demand was truncated)
    - Current availability is low (1-3 units)
    
    The logic: if 8-WD had 94.2% occ, roughly 6% of demand was
    turned away. With only 1 unit left, the marginal guest is 
    willing to pay MORE than the historical price suggests,
    because the Capa A underestimates demand at that price point.
    
    Uplift formula (Weatherford simplified):
      P(turnaway) = max(0, (occ_hist - threshold) / (1 - threshold))
      uplift = 1 + P(turnaway) * scarcity_factor
    
    Where scarcity_factor increases as availability decreases:
      1 unit free -> full uplift
      2 units free -> 60% of uplift  
      3 units free -> 30% of uplift
    """
    cfg = UNCONSTRAINED_DEMAND
    if not cfg["enabled"]:
        return 1.0
    
    if disponibles > cfg["max_disp_affected"]:
        return 1.0
    
    occ_hist = SEGMENT_OCC_HIST.get(segment, 0) / 100.0  # Convert from % to ratio
    
    if occ_hist < cfg["occ_threshold"]:
        return 1.0
    
    # Probability of turnaway — how much demand was invisible
    p_turnaway = (occ_hist - cfg["occ_threshold"]) / (1 - cfg["occ_threshold"])
    p_turnaway = min(p_turnaway, 1.0)
    
    # Scarcity factor — more uplift when fewer units available
    scarcity = {1: 1.0, 2: 0.60, 3: 0.30}
    scarcity_factor = scarcity.get(disponibles, 0.0)
    
    # Final uplift
    uplift = 1.0 + p_turnaway * scarcity_factor * (cfg["max_uplift"] - 1.0)
    
    return round(min(uplift, cfg["max_uplift"]), 3)


# ══════════════════════════════════════════
# MODULE 1: FORECAST
# ══════════════════════════════════════════

def forecast(fecha, fill_curves, pace_data, pickup_data, otb, events):
    cfg = config.V7["FORECAST"]
    date_str = fmt(fecha)
    seg_key = get_segment_key(fecha)
    days_out = days_until(fecha)
    season_code = get_season_code(fecha)

    # 1. Base: historical expected occupancy
    occ_esperada = get_expected_occ(fill_curves, seg_key, days_out)
    demanda_base = occ_esperada * config.TOTAL_UNITS

    # 2. Current bookings
    reservadas = otb.get(date_str, 0)
    disponibles = config.TOTAL_UNITS - reservadas
    occ_actual = reservadas / config.TOTAL_UNITS

    # 3. Pace adjustment
    ajuste_pace = 1.0
    if pace_data and date_str in pace_data:
        otb_ly = pace_data[date_str]
        if otb_ly > 0.05:
            ratio = occ_actual / otb_ly
            ajuste_pace = clamp(cfg["PACE_MIN"], 1.0 + (ratio - 1.0) * cfg["PACE_SENS"], cfg["PACE_MAX"])
    if days_out > 90:
        ajuste_pace = 1.0 + (ajuste_pace - 1.0) * 0.5

    # 4. Pickup adjustment
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

    # 5. Event adjustment
    event_info = get_event_factor(date_str, events)
    ajuste_evento = clamp(cfg["EVENTO_MIN"], event_info["factor"], cfg["EVENTO_MAX"])

    # 6. School holidays
    ajuste_vac = clamp(cfg["VAC_MIN"], get_vacaciones_factor(date_str), cfg["VAC_MAX"])

    # 7. Forecast final
    demanda_total = demanda_base * ajuste_pace * ajuste_pickup * ajuste_evento * ajuste_vac
    demanda_incremental = max(0, demanda_total - reservadas)
    demanda_incremental = min(demanda_incremental, disponibles)
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
        },
        "eventInfo": event_info,
        "seasonCode": season_code,
        "daysOut": days_out,
    }


# ══════════════════════════════════════════
# MODULE 2: OPTIMIZE (with Unconstrained Demand)
# ══════════════════════════════════════════

def optimize(fecha, fc, otb):
    cfg_opt = config.V7["OPTIM"]
    date_str = fmt(fecha)
    seg = get_demand_segment(fecha)
    pricing = config.SEGMENT_BASE.get(seg)

    if not pricing:
        m = fecha.month if hasattr(fecha, 'month') else int(str(fecha)[5:7])
        pricing = config.SEGMENT_BASE.get(f"{m}-WD", {
            "code": config.SEASON_CODE.get(m, "M"),
            "base": 100, "suelo": 70, "techo": 200, "preciosPorDisp": None,
        })

    reservadas = otb.get(date_str, 0)
    disponibles = max(1, min(config.TOTAL_UNITS, config.TOTAL_UNITS - reservadas))

    # Price from Capa A by availability
    ppd = pricing.get("preciosPorDisp")
    if ppd and disponibles in ppd:
        p = ppd[disponibles]
        precio_base = p["precio"] if isinstance(p, dict) else p
    else:
        precio_base = pricing.get("base", 100)

    # Forecast adjustment: virtual availability
    demanda_inc = fc["demanda"]
    disp_virtual = max(1, round(disponibles - demanda_inc))
    disp_virtual = min(disp_virtual, config.TOTAL_UNITS)

    if disp_virtual < disponibles and ppd and disp_virtual in ppd:
        p_fc = ppd[disp_virtual]
        precio_forecast = p_fc["precio"] if isinstance(p_fc, dict) else p_fc
        precio_base = round(
            precio_base * cfg_opt["PESO_REAL"] + precio_forecast * cfg_opt["PESO_FORECAST"]
        )

    # ★ NEW: Unconstrained Demand Uplift ★
    # If this segment historically had high occupancy, the Capa A
    # underestimates demand at high prices. We correct by inflating
    # the price for low-availability dates.
    unc_uplift = get_unconstrained_uplift(seg, disponibles)
    if unc_uplift > 1.0:
        precio_base = round(precio_base * unc_uplift)

    # Comp set adjustment
    ajuste_cs = _comp_set_adjustment(date_str, precio_base)
    precio_base = round(precio_base * ajuste_cs)

    return {
        "precioNeto": precio_base,
        "disponibles": disponibles,
        "reservadas": reservadas,
        "dispVirtual": disp_virtual,
        "ajusteCompSet": ajuste_cs,
        "segment": seg,
        "uncUplift": unc_uplift,  # Track for logging/debugging
    }


def _comp_set_adjustment(date_str, precio_neto):
    """Single moderate comp set adjustment."""
    cfg_cs = config.V7["COMP_SET_ADJ"]
    month = int(date_str[5:7])

    # Try MarketRef / ADR_PEER
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
    disponibles = max(1, config.TOTAL_UNITS - reservadas)
    occ_now = reservadas / config.TOTAL_UNITS

    # 1. Floor & ceiling
    suelo = _get_suelo(sc, date_str)
    techo = _get_techo(sc, date_str)

    # 2. Event: raise floor and price
    if event_info.get("floorOverride") and event_info["floorOverride"] > suelo:
        suelo = event_info["floorOverride"]
    if event_info["factor"] > 1.0:
        precio_neto = round(precio_neto * event_info["factor"])

    # 3. Last-minute winter
    lm = _get_last_minute(sc, days_out, disponibles)
    if lm:
        suelo_lm = max(35, round(suelo * lm["sueloPct"]))
        suelo = suelo_lm

    # 4. Genius compensation
    precio_pub = round(precio_neto * config.GENIUS_COMPENSATION)

    # 5. Clamp
    clamped_by = ""
    if precio_pub > techo:
        precio_pub = techo
        clamped_by = "TECHO"
    if precio_pub < suelo:
        precio_pub = suelo
        clamped_by = "SUELO"

    # 6. Price protection
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

    # 7. LOS dinámico
    los = get_min_stay_dinamico(fecha, occ_now, days_out, sc, fc["occEsperada"], disponibles)
    min_stay = los["minStay"]
    los_premium = los["premium"]
    los_razon = los["razon"]
    los_reduccion = los["reduccion"]

    if event_info.get("minStay") and event_info["minStay"] > min_stay:
        min_stay = event_info["minStay"]

    gap_info = gaps.get(date_str) if gaps else None
    gap_override = False
    if gap_info and not event_info.get("minStay"):
        if gap_info["minStayGap"] < min_stay:
            min_stay = gap_info["minStayGap"]
            gap_override = True
        if gap_info["premiumGap"] > los_premium:
            los_premium = gap_info["premiumGap"]

    if los_reduccion > 0 or gap_override:
        precio_pub = round(precio_pub * los_premium)
        precio_pub = max(suelo, min(techo, precio_pub))

    # 8. Min booking revenue
    min_rev = config.MIN_BOOKING_REVENUE.get(sc, 415)
    min_rev_per_night = min_rev / min_stay
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
        "losRazon": los_razon, "losReduccion": los_reduccion, "losPremium": los_premium,
        "gapOverride": gap_override,
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

    # Pass 1: limit daily variation
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

    # Pass 2: monotonicity — more occupancy = higher price
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

def calcular_precios_v7(otb, events):
    """Full v7 pricing pipeline."""
    log.info("  Forecast → Optimización → Ejecución → Suavizado")

    hist = fetch_historical_bookings()
    fill_curves = build_fill_curves(hist)
    gaps = detect_gaps_dinamico(otb)
    sold_prices = read_current_prices()
    pickup_data = calc_pickup(otb)
    pace_data = calc_pace(hist)

    today = date.today()
    results = []
    unc_count = 0  # Track how many dates got unconstrained uplift

    for di in range(config.PRICING_HORIZON):
        d = today + timedelta(days=di)
        date_str = fmt(d)

        # Step 1: Forecast
        fc = forecast(d, fill_curves, pace_data, pickup_data, otb, events)

        # Step 2: Optimize (now includes unconstrained demand)
        opt = optimize(d, fc, otb)
        
        if opt.get("uncUplift", 1.0) > 1.0:
            unc_count += 1

        # Step 3: Execute
        ej = execute(d, opt["precioNeto"], fc, otb, sold_prices, gaps)

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
            "daysOut": di,
            "occNow": ej["occNow"],
            "isWeekend": ej["isWeekend"],
            "eventName": ej["eventName"],
            "eventFactor": ej["eventFactor"],
            "clampedBy": ej["clampedBy"],
            "gapOverride": ej["gapOverride"],
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
            "fOTB": 1.0, "fPickup": 1.0, "fPace": 1.0, "fTotal": 1.0,
            "paceRatio": fc["desglose"]["pace"],
            "marketFactor": 1.0,
            "uncUplift": opt.get("uncUplift", 1.0),
        })

    # Step 4: Smooth
    results = smooth(results)

    # Recalc genius after smoothing
    for r in results:
        r["precioGenius"] = round(r["precioFinal"] * 0.85)

    log.info(f"  ✅ v7: {len(results)} días calculados")
    if unc_count > 0:
        log.info(f"  📈 Demanda no restringida: {unc_count} fechas con uplift aplicado")
    return results
