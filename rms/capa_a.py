"""
Capa A — Dynamic Demand Curves from Beds24 Historical Data
v7.1: Full rebuild with unconstrained demand estimation

Replaces: construirCapaA, cargarCapaA_, extraerPreciosOptimos_, etc.

PROCESS:
1. Fetch all historical bookings from Beds24 (already done in otb.py)
2. Expand each booking to night-level data with price ranges
3. Group by demand segment (month × WD/WE)
4. Build demand curve per segment: at each price point, how many units sold?
5. Extract optimal price per availability level (revenue-maximizing)
6. Apply unconstrained demand correction for high-occupancy segments
7. Store in config.SEGMENT_BASE for use by pricing engine

CALIBRATION SCHEDULE:
- Full rebuild: quarterly (Jan 1, Apr 1, Jul 1, Oct 1) or on demand
- The daily pricing run uses the stored SEGMENT_BASE values
- Between calibrations, unconstrained demand uplift in pricing.py
  provides a real-time correction
"""

import logging
from datetime import date, timedelta
from collections import defaultdict
from rms import config
from rms.otb import fetch_historical_bookings

log = logging.getLogger(__name__)

# ══════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════

PRICE_STEP = 10          # Group prices into €10 ranges
MIN_OBS_PER_RANGE = 20   # Minimum observations for a price range to be "reliable"
CEILING_MULTIPLIER = 1.50 # Ceiling = top price × 1.5
UNCONSTRAINED_OCC_THRESHOLD = 0.85  # Inflate demand above this occupancy


# ══════════════════════════════════════════
# SEGMENT HELPERS  
# ══════════════════════════════════════════

def get_demand_segment_from_date(d):
    """Month × WD/WE segment key."""
    m = d.month
    dt = "WE" if d.weekday() in (4, 5) else "WD"
    return f"{m}-{dt}"


# ══════════════════════════════════════════
# STEP 1: Expand bookings to night-level data
# ══════════════════════════════════════════

def expand_to_nights(bookings):
    """
    Convert each booking to individual night records.
    Each night gets: segment, price_range, weight (for multi-year weighting).
    
    Returns list of dicts: {segment, priceRange, weight, units}
    """
    nights_sold = []
    
    for b in bookings:
        ci = b["ci"]
        co = b["co"]
        ppn = b["ppn"]
        year = b["year"]
        
        if ppn <= 0:
            continue
            
        # Weight by year (recent years count more)
        weight = config.CURVE_WEIGHTS.get(year, 0.33)
        
        # Round price to nearest PRICE_STEP
        price_range = round(ppn / PRICE_STEP) * PRICE_STEP
        if price_range < PRICE_STEP:
            price_range = PRICE_STEP
        
        # Expand to individual nights
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
    
    return nights_sold


# ══════════════════════════════════════════
# STEP 2: Count total available nights by segment
# ══════════════════════════════════════════

def count_total_nights_by_segment():
    """
    For each segment, count total unit-nights available across all historical years.
    Weighted by CURVE_WEIGHTS.
    """
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


# ══════════════════════════════════════════
# STEP 3: Build demand curves
# ══════════════════════════════════════════

def build_demand_curves(nights_sold, total_nights_by_seg):
    """
    For each segment, build a demand curve:
    - Group sold nights by price range
    - Calculate probability of sale at each price
    - Calculate expected revenue at each price
    
    Returns: {segment: {ranges: [{price, offered, sold, pVenta, ingEsp, fiable}]}}
    """
    # Aggregate sold units by segment × price range
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


# ══════════════════════════════════════════
# STEP 4: Extract optimal prices per availability
# ══════════════════════════════════════════

def extract_optimal_prices(curves, total_nights_by_seg):
    """
    For each segment and each availability level (1-9 units free),
    find the price that maximizes expected revenue.
    
    This is the core of the Capa A: 
    revenue(price, disp) = price × min(demand_at_price, disp)
    
    We pick the price that maximizes this for each disp level.
    
    ★ NEW: Unconstrained demand correction ★
    For segments with high historical occupancy, we inflate the
    demand at high price ranges before computing optimal prices.
    This makes the system more aggressive in high-demand periods.
    """
    result = {}
    
    for seg in sorted(curves.keys()):
        ranges = curves[seg]["ranges"]
        month = int(seg.split("-")[0])
        code = config.SEASON_CODE.get(month, "M")
        
        total_nights = total_nights_by_seg.get(seg, 1)
        dias_en_segmento = total_nights / config.TOTAL_UNITS
        
        if dias_en_segmento < 1:
            dias_en_segmento = 1
        
        # Build demand-by-price array
        demand_by_price = []
        for r in ranges:
            demand_by_price.append({
                "price": r["price"],
                "demandaDiaria": r["sold"] / dias_en_segmento,
                "fiable": r["fiable"],
            })
        demand_by_price.sort(key=lambda x: x["price"])
        
        # ★ UNCONSTRAINED DEMAND CORRECTION ★
        # Calculate historical occupancy for this segment
        total_sold = sum(r["sold"] for r in ranges)
        occ_hist = total_sold / total_nights if total_nights > 0 else 0
        
        if occ_hist > UNCONSTRAINED_OCC_THRESHOLD:
            # Estimate turnaway probability
            p_turnaway = (occ_hist - UNCONSTRAINED_OCC_THRESHOLD) / (1 - UNCONSTRAINED_OCC_THRESHOLD)
            p_turnaway = min(p_turnaway, 1.0)
            
            # Inflate demand at TOP HALF of price ranges
            # (the invisible demand was willing to pay HIGH prices)
            n_ranges = len(demand_by_price)
            top_half_start = n_ranges // 2
            
            for i in range(top_half_start, n_ranges):
                inflation = 1.0 + p_turnaway * 0.40  # Up to 40% more demand at high prices
                demand_by_price[i]["demandaDiaria"] *= inflation
            
            log.debug(f"  {seg}: occ={occ_hist:.1%}, P(turnaway)={p_turnaway:.2f}, "
                      f"inflating top {n_ranges - top_half_start} price ranges")
        
        # Build cumulative demand curve (higher price = less demand)
        demand_acum = []
        for i in range(len(demand_by_price)):
            acum = sum(d["demandaDiaria"] for d in demand_by_price[i:])
            demand_acum.append({
                "price": demand_by_price[i]["price"],
                "demandaDiaria": acum,
                "fiable": demand_by_price[i]["fiable"],
            })
        
        # For each availability level, find revenue-maximizing price
        precios_por_disp = {}
        for disp in range(1, config.TOTAL_UNITS + 1):
            best_price = 0
            best_revenue = 0
            best_demand = 0
            
            for dp in demand_acum:
                units_sold = min(dp["demandaDiaria"], disp)
                revenue = dp["price"] * units_sold
                if revenue > best_revenue:
                    best_revenue = revenue
                    best_price = dp["price"]
                    best_demand = units_sold
            
            precios_por_disp[disp] = {
                "precio": best_price,
                "revenue": round(best_revenue, 1),
                "demanda": round(best_demand, 2),
            }
        
        # Calculate floor and ceiling
        suelo_m = precios_por_disp[config.TOTAL_UNITS]["precio"]
        suelo = max(35, round(suelo_m * 0.80))
        
        techo = round(precios_por_disp[1]["precio"] * CEILING_MULTIPLIER)
        if techo < precios_por_disp[1]["precio"]:
            techo = round(precios_por_disp[1]["precio"] * 1.20)
        
        # Occupancy and average availability
        disp_media = round(config.TOTAL_UNITS * (1 - occ_hist))
        disp_media = max(1, min(config.TOTAL_UNITS, disp_media))
        
        base = precios_por_disp[disp_media]["precio"]
        
        result[seg] = {
            "code": code,
            "base": base,
            "suelo": suelo,
            "techo": techo,
            "preciosPorDisp": precios_por_disp,
            "dispMedia": disp_media,
            "occHistorica": round(occ_hist * 1000) / 10,  # As percentage with 1 decimal
        }
    
    return result


# ══════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════

def cargar_capa_a():
    """Load Capa A data into SEGMENT_BASE.
    
    Uses pre-computed values from config.py (from last GAS calibration).
    These get overwritten when construir_capa_a() runs.
    """
    seg_count = len(config.SEGMENT_BASE)
    if seg_count >= 20:
        log.info(f"  Capa A: {seg_count} segmentos cargados (from config)")
        return True
    else:
        log.warning(f"  Capa A: solo {seg_count} segmentos — datos incompletos")
        return False


def construir_capa_a(force=False):
    """
    Full Capa A rebuild from Beds24 historical data.
    
    Should run:
    - Quarterly (Jan 1, Apr 1, Jul 1, Oct 1)
    - On demand (force=True)
    
    Updates config.SEGMENT_BASE in-place so the next pricing run
    uses the new values.
    """
    today = date.today()
    
    # Check if it's calibration day (1st of quarter) unless forced
    if not force:
        if today.day != 1 or today.month not in (1, 4, 7, 10):
            return None
    
    log.info("══ CONSTRUIR CAPA A ══")
    
    # Step 1: Fetch historical bookings
    bookings = fetch_historical_bookings()
    if not bookings or len(bookings) < 50:
        log.warning(f"  Solo {len(bookings) if bookings else 0} reservas — insuficiente para recalibrar")
        return None
    
    log.info(f"  {len(bookings)} reservas históricas")
    
    # Step 2: Expand to night-level data
    nights_sold = expand_to_nights(bookings)
    log.info(f"  {len(nights_sold)} noches expandidas")
    
    # Step 3: Count total available nights
    total_nights = count_total_nights_by_segment()
    
    # Step 4: Build demand curves
    curves = build_demand_curves(nights_sold, total_nights)
    log.info(f"  {len(curves)} segmentos con curvas de demanda")
    
    # Step 5: Extract optimal prices (with unconstrained demand)
    segment_pricing = extract_optimal_prices(curves, total_nights)
    
    # Step 6: Update SEGMENT_BASE in-place
    for seg, pricing in segment_pricing.items():
        config.SEGMENT_BASE[seg] = pricing
    
    log.info(f"  ✅ Capa A recalibrada: {len(segment_pricing)} segmentos")
    
    # Log key segments for verification
    for seg in ["7-WD", "7-WE", "8-WD", "8-WE"]:
        if seg in segment_pricing:
            p = segment_pricing[seg]
            ppd = p["preciosPorDisp"]
            log.info(f"    {seg}: Disp1={ppd[1]['precio']}€, Disp5={ppd[5]['precio']}€, "
                     f"occ={p['occHistorica']}%, suelo={p['suelo']}, techo={p['techo']}")
    
    return segment_pricing


def check_and_recalibrate():
    """Called daily — only recalibrates on quarterly dates."""
    return construir_capa_a(force=False)
