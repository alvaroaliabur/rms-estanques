"""
Capa A — Dynamic Demand Curves from Beds24 Historical Data
v7.5: DEMAND UNCONSTRAINING implementado.

El problema que resuelve:
  Usar precios de 2023 (180€/noche agosto) para construir curvas de demanda
  baja artificialmente los precios óptimos. 2025 vendió a 308€ — esa es
  la realidad del mercado actual.

La solución (RM avanzado — "Demand Uncensoring"):
  De 2023/2024 usamos el PATRÓN TEMPORAL (cuándo se reservó, a qué
  antelación, WD/WE) pero RECALIBRAMOS los precios al nivel actual:
    precio_recalibrado = precio_original × (ADR_2025 / ADR_año_original)

  Así tenemos 3x más observaciones para construir 48 segmentos
  sin que los precios bajos de 2023 contaminen la curva.

  Ejemplo: reserva agosto 2023 a 215€ → recalibrada a 215 × (308/215) = 308€
  La observación contribuye a la curva con el precio correcto de hoy.
"""

import logging
from datetime import date, timedelta
from collections import defaultdict
from rms import config
from rms.otb import fetch_historical_bookings

log = logging.getLogger(__name__)

PRICE_STEP = 10
MIN_OBS_PER_RANGE = 20
CEILING_MULTIPLIER = 1.50
UNCONSTRAINED_OCC_THRESHOLD = 0.85


def get_demand_segment_from_date(d):
    m = d.month
    dt = "WE" if d.weekday() in (4, 5) else "WD"
    return f"{m}-{dt}"


def expand_to_nights(bookings):
    """
    v7.5 DEMAND UNCONSTRAINING:
    Expand bookings to night-level data WITH price recalibration.

    For years != reference_year, recalibrate prices:
      ppn_recalibrado = ppn_original × (ADR_ref / ADR_año)

    This preserves the temporal PATTERN (when bookings came in, WD/WE,
    seasonality) while adjusting prices to current market level.

    Example: Aug 2023 booking at 215€ → 215 × (308/215) = 308€
    The observation contributes to demand curves at today's price.
    """
    nights_sold = []

    unc_cfg = config.DEMAND_UNCONSTRAINING if hasattr(config, 'DEMAND_UNCONSTRAINING') else {}
    unc_enabled = unc_cfg.get("enabled", False)
    adr_ref = unc_cfg.get("ADR_REFERENCE", {})
    adr_by_year = unc_cfg.get("ADR_BY_YEAR", {})
    ref_year = unc_cfg.get("reference_year", 2025)

    recalibrated_count = 0

    for b in bookings:
        ci = b["ci"]
        co = b["co"]
        ppn = b["ppn"]
        year = b["year"]
        if ppn <= 0:
            continue

        weight = config.CURVE_WEIGHTS.get(year, 0.33)

        # DEMAND UNCONSTRAINING: recalibrate price for non-reference years
        ppn_adjusted = ppn
        if unc_enabled and year != ref_year:
            month = ci.month
            adr_this_year = adr_by_year.get(year, {}).get(month, 0)
            adr_reference = adr_ref.get(month, 0)
            if adr_this_year > 0 and adr_reference > 0:
                factor = adr_reference / adr_this_year
                ppn_adjusted = ppn * factor
                recalibrated_count += 1

        price_range = round(ppn_adjusted / PRICE_STEP) * PRICE_STEP
        if price_range < PRICE_STEP:
            price_range = PRICE_STEP

        current = ci
        while current < co:
            seg = get_demand_segment_from_date(current)
            nights_sold.append({
                "segment": seg,
                "priceRange": price_range,
                "weight": weight,
                "units": b.get("roomQty", 1),
            })
            current += timedelta(days=1)

    if recalibrated_count > 0:
        log.info(f"  🔄 Demand Unconstraining: {recalibrated_count} reservas recalibradas al nivel {ref_year}")

    return nights_sold


def count_total_nights_by_segment():
    totals = defaultdict(float)
    for year in config.HISTORICAL_YEARS:
        w = config.CURVE_WEIGHTS.get(year, 0.33)
        d = date(year, 1, 1)
        end = date(year, 12, 31)
        while d <= end:
            seg = get_demand_segment_from_date(d)
            totals[seg] += config.TOTAL_UNITS * w
            d += timedelta(days=1)
    return dict(totals)


def build_demand_curves(nights_sold, total_nights_by_seg):
    sold_by_seg_range = defaultdict(lambda: defaultdict(float))
    for n in nights_sold:
        sold_by_seg_range[n["segment"]][n["priceRange"]] += n["weight"] * n["units"]

    result = {}
    for seg in sorted(sold_by_seg_range.keys()):
        total_avail = total_nights_by_seg.get(seg, 1)
        ranges = []
        for price in sorted(sold_by_seg_range[seg].keys()):
            sold = sold_by_seg_range[seg][price]
            ranges.append({
                "price": int(price),
                "offered": total_avail,
                "sold": sold,
                "pVenta": sold / total_avail if total_avail > 0 else 0,
                "ingEsp": price * (sold / total_avail) if total_avail > 0 else 0,
                "fiable": sold >= MIN_OBS_PER_RANGE,
            })
        result[seg] = {"ranges": ranges}
    return result


def extract_optimal_prices(curves, total_nights_by_seg):
    result = {}
    for seg in sorted(curves.keys()):
        ranges = curves[seg]["ranges"]
        month = int(seg.split("-")[0])
        code = config.SEASON_CODE.get(month, "M")

        total_nights = total_nights_by_seg.get(seg, 1)
        dias_en_segmento = max(1, total_nights / config.TOTAL_UNITS)

        demand_by_price = []
        for r in ranges:
            demand_by_price.append({
                "price": r["price"],
                "demandaDiaria": r["sold"] / dias_en_segmento,
                "fiable": r["fiable"],
            })
        demand_by_price.sort(key=lambda x: x["price"])

        total_sold = sum(r["sold"] for r in ranges)
        occ_hist = total_sold / total_nights if total_nights > 0 else 0

        if occ_hist > UNCONSTRAINED_OCC_THRESHOLD:
            p_turnaway = min((occ_hist - UNCONSTRAINED_OCC_THRESHOLD) / (1 - UNCONSTRAINED_OCC_THRESHOLD), 1.0)
            n_ranges = len(demand_by_price)
            top_half_start = n_ranges // 2
            for i in range(top_half_start, n_ranges):
                inflation = 1.0 + p_turnaway * 0.40
                demand_by_price[i]["demandaDiaria"] *= inflation

        demand_acum = []
        for i in range(len(demand_by_price)):
            acum = sum(d["demandaDiaria"] for d in demand_by_price[i:])
            demand_acum.append({
                "price": demand_by_price[i]["price"],
                "demandaDiaria": acum,
                "fiable": demand_by_price[i]["fiable"],
            })

        precios_por_disp = {}
        for disp in range(1, config.TOTAL_UNITS + 1):
            best_price = 0
            best_revenue = 0
            for dp in demand_acum:
                units_sold = min(dp["demandaDiaria"], disp)
                revenue = dp["price"] * units_sold
                if revenue > best_revenue:
                    best_revenue = revenue
                    best_price = dp["price"]
            precios_por_disp[disp] = {
                "precio": best_price,
                "revenue": round(best_revenue, 1),
            }

        suelo_m = precios_por_disp[config.TOTAL_UNITS]["precio"]
        suelo = max(35, round(suelo_m * 0.80))
        techo = round(precios_por_disp[1]["precio"] * CEILING_MULTIPLIER)
        if techo < precios_por_disp[1]["precio"]:
            techo = round(precios_por_disp[1]["precio"] * 1.20)

        disp_media = max(1, min(config.TOTAL_UNITS, round(config.TOTAL_UNITS * (1 - occ_hist))))
        base = precios_por_disp[disp_media]["precio"]

        result[seg] = {
            "code": code,
            "base": base,
            "suelo": suelo,
            "techo": techo,
            "preciosPorDisp": precios_por_disp,
            "dispMedia": disp_media,
            "occHistorica": round(occ_hist * 1000) / 10,
        }

    return result


def cargar_capa_a():
    seg_count = len(config.SEGMENT_BASE)
    if seg_count >= 20:
        log.info(f"  Capa A: {seg_count} segmentos cargados (from config)")
        return True
    else:
        log.warning(f"  Capa A: solo {seg_count} segmentos — datos incompletos")
        return False


def construir_capa_a(force=False):
    today = date.today()
    if not force:
        if today.day != 1 or today.month not in (1, 4, 7, 10):
            return None

    log.info("══ CONSTRUIR CAPA A v7.5 ══")
    log.info(f"  Años históricos: {config.HISTORICAL_YEARS}")
    log.info(f"  Pesos: {config.CURVE_WEIGHTS}")

    bookings = fetch_historical_bookings()
    if not bookings or len(bookings) < 50:
        log.warning(f"  Solo {len(bookings) if bookings else 0} reservas — insuficiente")
        return None

    # Log bookings per year
    by_year = defaultdict(int)
    for b in bookings:
        by_year[b["year"]] += 1
    for y in sorted(by_year):
        log.info(f"  {y}: {by_year[y]} reservas (peso={config.CURVE_WEIGHTS.get(y, 0)})")

    log.info(f"  {len(bookings)} reservas históricas totales")

    nights_sold = expand_to_nights(bookings)
    log.info(f"  {len(nights_sold)} noches expandidas")

    total_nights = count_total_nights_by_segment()
    curves = build_demand_curves(nights_sold, total_nights)
    log.info(f"  {len(curves)} segmentos con curvas de demanda")

    segment_pricing = extract_optimal_prices(curves, total_nights)

    for seg, pricing in segment_pricing.items():
        config.SEGMENT_BASE[seg] = pricing

    log.info(f"  ✅ Capa A recalibrada: {len(segment_pricing)} segmentos")

    for seg in ["7-WD", "7-WE", "8-WD", "8-WE", "9-WD", "9-WE"]:
        if seg in segment_pricing:
            p = segment_pricing[seg]
            ppd = p["preciosPorDisp"]
            log.info(f"    {seg}: Disp1={ppd[1]['precio']}€, Disp5={ppd[5]['precio']}€, "
                     f"occ={p['occHistorica']}%, suelo={p['suelo']}, techo={p['techo']}")

    return segment_pricing


def check_and_recalibrate():
    return construir_capa_a(force=False)
