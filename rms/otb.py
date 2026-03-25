"""
OTB module — v7.3
CHANGES from v7.2:
  - calc_pace() now uses MULTI-YEAR weighted average (3 years)
  - read_otb_by_type(): Returns OTB split by room type (upper vs ground)
  - Snapshots in /data/ (Railway persistent volume) with /tmp fallback
"""

import logging
import json
import os
from datetime import date, timedelta
from rms import config
from rms.beds24 import api_get, api_get_all
from rms.utils import fmt, parse_date, days_until

log = logging.getLogger(__name__)


# ══════════════════════════════════════════
# BOOKING PARSING
# ══════════════════════════════════════════

def es_cancelada(b):
    s = b.get("status")
    if s in (0, "0"):
        return True
    if isinstance(s, str) and s.lower() in ("cancelled", "canceled"):
        return True
    sub = b.get("subStatus")
    if sub in (3, "3", 4, "4"):
        return True
    if isinstance(sub, str) and "cancel" in sub.lower():
        return True
    ct = b.get("cancelTime", "")
    if ct and str(ct).strip() not in ("", "0000-00-00 00:00:00", "0000-00-00"):
        return True
    return False


def es_activa(b):
    if es_cancelada(b):
        return False
    s = b.get("status")
    if s in (1, "1", 2, "2"):
        return True
    if isinstance(s, str) and s.lower() in ("confirmed", "new"):
        return True
    if s not in (3, "3", 4, "4", 5, "5"):
        return True
    return False


def precio_alojamiento(b):
    return float(b.get("price", 0) or 0)


def parsear_reserva(b):
    ci = parse_date(b["arrival"])
    co = parse_date(b["departure"])
    nights = (co - ci).days
    cancelada = es_cancelada(b)
    price = 0 if cancelada else precio_alojamiento(b)
    bd = parse_date(b.get("bookingTime", b["arrival"]))
    return {
        "id": b.get("id"),
        "ci": ci, "co": co, "bd": bd,
        "nights": nights,
        "price": price,
        "ppn": price / nights if nights > 0 and price > 0 else 0,
        "year": ci.year,
        "month": ci.month,
        "channel": b.get("apiSource", "direct"),
        "roomId": b.get("roomId"),
        "roomQty": b.get("roomQty", 1) or 1,
        "status": b.get("status"),
        "cancelada": cancelada,
        "activa": not cancelada and nights > 0 and price > 0,
    }


# ══════════════════════════════════════════
# READ OTB
# ══════════════════════════════════════════

def read_otb():
    today = date.today()
    end = today + timedelta(days=config.PRICING_HORIZON)

    all_bks = api_get_all("bookings", {
        "arrivalFrom": fmt(today),
        "departureTo": fmt(end),
        "propertyId": config.PROPERTY_ID,
    })

    active_bks = api_get("bookings", {
        "departureFrom": fmt(today),
        "arrivalTo": fmt(today),
        "propertyId": config.PROPERTY_ID,
        "limit": 100,
    })
    if active_bks:
        all_bks.extend(active_bks)

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

        ci = parse_date(b["arrival"])
        co = parse_date(b["departure"])
        units = b.get("roomQty", 1) or 1

        d = max(ci, today)
        while d < co:
            if d > end:
                break
            k = fmt(d)
            otb[k] = otb.get(k, 0) + units
            d += timedelta(days=1)

    log.info(f"  OTB: {len(otb)} fechas")

    try:
        save_otb_snapshot(otb)
    except Exception as e:
        log.warning(f"  Snapshot save error: {e}")

    return otb


def read_otb_by_type():
    today = date.today()
    end = today + timedelta(days=config.PRICING_HORIZON)

    all_bks = api_get_all("bookings", {
        "arrivalFrom": fmt(today),
        "departureTo": fmt(end),
        "propertyId": config.PROPERTY_ID,
    })

    active_bks = api_get("bookings", {
        "departureFrom": fmt(today),
        "arrivalTo": fmt(today),
        "propertyId": config.PROPERTY_ID,
        "limit": 100,
    })
    if active_bks:
        all_bks.extend(active_bks)

    otb_total = {}
    otb_upper = {}
    otb_ground = {}
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

        ci = parse_date(b["arrival"])
        co = parse_date(b["departure"])
        units = b.get("roomQty", 1) or 1
        room_id = b.get("roomId")

        if room_id == config.ROOM_GROUND:
            target = otb_ground
        else:
            target = otb_upper

        d = max(ci, today)
        while d < co:
            if d > end:
                break
            k = fmt(d)
            otb_total[k] = otb_total.get(k, 0) + units
            target[k] = target.get(k, 0) + units
            d += timedelta(days=1)

    log.info(f"  OTB by type: {len(otb_total)} fechas (upper: {sum(otb_upper.values())}, ground: {sum(otb_ground.values())} room-nights)")

    try:
        save_otb_snapshot(otb_total)
    except Exception as e:
        log.warning(f"  Snapshot save error: {e}")

    return otb_total, {"upper": otb_upper, "ground": otb_ground}


# ══════════════════════════════════════════
# OTB SNAPSHOT — Persistent storage
# ══════════════════════════════════════════

SNAPSHOT_DIR = "/data" if os.path.isdir("/data") else "/tmp"
SNAPSHOT_FILE = os.path.join(SNAPSHOT_DIR, "otb_snapshots.json")


def save_otb_snapshot(otb):
    today_str = fmt(date.today())
    snapshots = _load_snapshots()
    snapshots[today_str] = otb

    cutoff = fmt(date.today() - timedelta(days=14))
    snapshots = {k: v for k, v in snapshots.items() if k >= cutoff}

    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(snapshots, f)


def _load_snapshots():
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


# ══════════════════════════════════════════
# PICKUP
# ══════════════════════════════════════════

def calc_pickup(otb_actual):
    pickup = {}
    snapshots = _load_snapshots()
    today = date.today()

    otb_7ago = None
    for offset in (7, 6, 8):
        key = fmt(today - timedelta(days=offset))
        if key in snapshots:
            otb_7ago = snapshots[key]
            break

    if not otb_7ago:
        return pickup

    for d in otb_actual:
        if d in otb_7ago:
            pickup[d] = otb_actual.get(d, 0) - otb_7ago.get(d, 0)

    return pickup


# ══════════════════════════════════════════
# HISTORICAL BOOKINGS
# ══════════════════════════════════════════

def fetch_historical_bookings(years=None):
    if years is None:
        years = config.HISTORICAL_YEARS

    all_bookings = []
    for year in years:
        bks = api_get_all("bookings", {
            "arrivalFrom": f"{year}-01-01",
            "arrivalTo": f"{year}-12-31",
            "propertyId": config.PROPERTY_ID,
            "includeInvoiceItems": True,
        })

        year_count = 0
        for b in bks:
            if not b.get("arrival") or not b.get("departure"):
                continue
            if es_cancelada(b):
                continue
            price = precio_alojamiento(b)
            ci = parse_date(b["arrival"])
            co = parse_date(b["departure"])
            bd = parse_date(b.get("bookingTime", b["arrival"]))
            nights = (co - ci).days
            if nights > 0 and price > 0:
                all_bookings.append({
                    "id": b.get("id"),
                    "ci": ci, "co": co, "bd": bd,
                    "nights": nights,
                    "price": price,
                    "ppn": price / nights,
                    "year": year,
                    "channel": b.get("apiSource", "direct"),
                })
                year_count += 1

        log.info(f"  {year}: {year_count} reservas activas")

    log.info(f"  Total histórico: {len(all_bookings)}")
    return all_bookings


# ══════════════════════════════════════════
# FILL CURVES
# ══════════════════════════════════════════

def get_segment_key(d):
    if isinstance(d, str):
        d = parse_date(d)
    m = d.month
    half = "1H" if d.day <= 15 else "2H"
    dt = "WE" if d.weekday() in (4, 5) else "WD"
    return f"{m}-{half}-{dt}"


def build_fill_curves(bookings):
    stays_by_seg = {}
    for b in bookings:
        ci = b["ci"]
        co = b["co"]
        bd = b["bd"]
        w = config.CURVE_WEIGHTS.get(b["year"], 0.33)

        d = ci
        while d < co:
            seg_key = get_segment_key(d)
            ant = (d - bd).days
            if ant < 0:
                ant = 0
            if seg_key not in stays_by_seg:
                stays_by_seg[seg_key] = []
            stays_by_seg[seg_key].append({"ant": ant, "weight": w})
            d += timedelta(days=1)

    curves = {}
    for seg, stays in stays_by_seg.items():
        curves[seg] = {}
        for cp in config.CHECKPOINTS:
            wb = sum(s["weight"] for s in stays if s["ant"] >= cp)
            tw = sum(s["weight"] for s in stays)
            curves[seg][cp] = wb / tw if tw > 0 else 0

    return curves


def get_expected_occ(fill_curves, seg_key, days_out):
    curve = fill_curves.get(seg_key)
    if not curve:
        return 0.5

    cps = config.CHECKPOINTS
    for i in range(len(cps) - 1):
        cp_h = cps[i]
        cp_l = cps[i + 1]
        if cp_l <= days_out <= cp_h:
            occ_h = curve.get(cp_h, 0)
            occ_l = curve.get(cp_l, 0)
            if cp_h == cp_l:
                return occ_h
            return occ_l + (occ_h - occ_l) * ((days_out - cp_l) / (cp_h - cp_l))

    if days_out >= cps[0]:
        return curve.get(cps[0], 0)
    return curve.get(cps[-1], 0)


# ══════════════════════════════════════════
# PACE — v7.3: MULTI-YEAR WEIGHTED AVERAGE
# ══════════════════════════════════════════

def calc_pace(hist):
    """
    v7.3: Pace uses WEIGHTED AVERAGE of all historical years.
    Instead of only comparing vs LY (which might be anomalous),
    we compare vs the weighted mean of 2023/2024/2025.
    This gives a stable benchmark for booking velocity.

    Returns: {date_str: weighted_avg_occ_at_this_lead_time}
    """
    pace = {}
    today = date.today()

    # Group historical bookings by year
    hist_by_year = {}
    for b in hist:
        y = b["year"]
        if y not in hist_by_year:
            hist_by_year[y] = []
        hist_by_year[y].append(b)

    if not hist_by_year:
        return pace

    for di in range(config.PRICING_HORIZON):
        d = today + timedelta(days=di)
        date_str = fmt(d)

        weighted_occ_sum = 0.0
        weight_sum = 0.0

        for year, year_bks in hist_by_year.items():
            w = config.CURVE_WEIGHTS.get(year, 0.33)

            # Find equivalent date in historical year
            try:
                d_hist = d.replace(year=year)
            except ValueError:
                # Feb 29 edge case
                d_hist = d.replace(year=year, month=2, day=28)

            # Deadline: how many bookings existed at the same lead time?
            deadline = d_hist - timedelta(days=di)

            # Count reservations for that date booked by the deadline
            res = sum(
                1 for b in year_bks
                if b["ci"] <= d_hist < b["co"] and b["bd"] <= deadline
            )

            if res > 0:
                occ = res / config.TOTAL_UNITS
                weighted_occ_sum += occ * w
                weight_sum += w

        if weight_sum > 0:
            pace[date_str] = weighted_occ_sum / weight_sum

    years_used = sorted(hist_by_year.keys())
    log.info(f"  Pace v7.3: {len(pace)} fechas (media ponderada de {len(years_used)} años: {years_used})")
    return pace


# ══════════════════════════════════════════
# CURRENT PRICES (sold prices for protection)
# ══════════════════════════════════════════

def read_current_prices():
    today = date.today()
    end = today + timedelta(days=config.PRICING_HORIZON)

    all_bks = api_get_all("bookings", {
        "arrivalFrom": fmt(today),
        "departureTo": fmt(end),
        "propertyId": config.PROPERTY_ID,
        "includeInvoiceItems": True,
    })

    prices = {}
    seen = set()

    for b in all_bks:
        if es_cancelada(b):
            continue
        bid = b.get("id")
        if bid in seen:
            continue
        seen.add(bid)

        price = precio_alojamiento(b)
        ci = parse_date(b["arrival"])
        co = parse_date(b["departure"])
        nights = (co - ci).days
        if nights <= 0 or price <= 0:
            continue
        ppn = price / nights

        d = ci
        while d < co:
            if d < today or d > end:
                d += timedelta(days=1)
                continue
            k = fmt(d)
            if k not in prices:
                prices[k] = []
            prices[k].append(ppn)
            d += timedelta(days=1)

    return prices
