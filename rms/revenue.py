"""
Revenue Tracker + Feedback — v7.3

CHANGES from v7.1:
  - Compares vs BEST historical year per month (not just LY)
  - In 2027: compares vs max(2025, 2026). The bar always rises.
  - calcular_otb_futuro() added for pricing.py OTB Confirmado
  - Fetches bookings from 2025 onwards (configurable floor)
"""

import logging
from datetime import date, timedelta
from collections import defaultdict
from rms.beds24 import api_get_all
from rms import config

log = logging.getLogger(__name__)

_price_history = {}

# Earliest year to fetch for revenue comparison
REVENUE_HISTORY_START = 2025


# ══════════════════════════════════════════
# REVENUE TRACKER — vs BEST year
# ══════════════════════════════════════════

def _fetch_bookings_for_year(year):
    bookings = []
    try:
        data = api_get_all("bookings", {
            "arrivalFrom": f"{year}-01-01",
            "arrivalTo": f"{year}-12-31",
            "propertyId": config.PROPERTY_ID,
            "includeInvoiceItems": True,
        })

        if not data:
            return []

        for b in data:
            if not b.get("arrival") or not b.get("departure"):
                continue
            status = b.get("status", "")
            cancel_time = b.get("cancelTime", "")
            if str(status) in ("3", "4") or (cancel_time and cancel_time != "0000-00-00 00:00:00"):
                continue

            ci = date.fromisoformat(b["arrival"][:10])
            co = date.fromisoformat(b["departure"][:10])
            nights = (co - ci).days
            price = float(b.get("price", 0) or 0)

            if nights > 0 and price > 0:
                channel_raw = (b.get("apiSource") or "").strip().lower()
                if not channel_raw or channel_raw == "direct":
                    channel = "direct"
                elif "booking" in channel_raw:
                    channel = "booking"
                elif "airbnb" in channel_raw:
                    channel = "airbnb"
                else:
                    channel = channel_raw

                bookings.append({
                    "ci": ci,
                    "co": co,
                    "nights": nights,
                    "price": price,
                    "ppn": price / nights,
                    "year": year,
                    "month": ci.month,
                    "channel": channel,
                })
    except Exception as e:
        log.warning(f"  Error fetching {year} bookings: {e}")

    return bookings


def calcular_revenue_tracker():
    """
    v7.3: Revenue by month comparing vs BEST historical year.

    In 2026: compares vs 2025
    In 2027: compares vs max(2025, 2026) per month
    In 2028: compares vs max(2025, 2026, 2027) per month

    The bar always rises — always compare against your best.
    """
    log.info("══ REVENUE TRACKER v7.3 ══")

    today = date.today()
    current_year = today.year

    # Fetch bookings for current year + all historical years from 2025
    years_to_fetch = list(range(REVENUE_HISTORY_START, current_year + 1))
    bookings_by_year = {}

    for year in years_to_fetch:
        bks = _fetch_bookings_for_year(year)
        if bks:
            bookings_by_year[year] = bks
            log.info(f"  {year}: {len(bks)} reservas")

    if current_year not in bookings_by_year:
        log.warning("  No bookings found for current year")
        bookings_by_year[current_year] = []

    # Revenue by month for each year
    rev_by_year = {}
    for year, bks in bookings_by_year.items():
        rev_by_year[year] = _revenue_by_month(bks)

    # Channel breakdown for current year + LY
    channel_ty = _channel_breakdown(bookings_by_year.get(current_year, []))
    channel_ly = _channel_breakdown(bookings_by_year.get(current_year - 1, []))

    historical_years = [y for y in rev_by_year.keys() if y < current_year]

    tracker = {}
    month_names = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                   "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

    for m in range(1, 13):
        # Current year
        ty = rev_by_year.get(current_year, {}).get(m, {"revenue": 0, "nights": 0})
        ty_rev = ty["revenue"]
        ty_nights = ty["nights"]
        ty_adr = round(ty_rev / ty_nights) if ty_nights > 0 else 0

        # Find BEST historical year for this month
        best_rev = 0
        best_year = current_year - 1
        best_nights = 0
        best_adr = 0

        for hy in historical_years:
            hy_data = rev_by_year.get(hy, {}).get(m, {"revenue": 0, "nights": 0})
            if hy_data["revenue"] > best_rev:
                best_rev = hy_data["revenue"]
                best_year = hy
                best_nights = hy_data["nights"]
                best_adr = round(hy_data["revenue"] / hy_data["nights"]) if hy_data["nights"] > 0 else 0

        # Also get LY specifically
        ly = rev_by_year.get(current_year - 1, {}).get(m, {"revenue": 0, "nights": 0})
        ly_rev = ly["revenue"]
        ly_nights = ly["nights"]
        ly_adr = round(ly_rev / ly_nights) if ly_nights > 0 else 0

        # Compare vs BEST year
        compare_rev = best_rev
        diff_pct = round((ty_rev - compare_rev) / compare_rev * 100) if compare_rev > 0 else (100 if ty_rev > 0 else 0)
        diff_vs_ly = round((ty_rev - ly_rev) / ly_rev * 100) if ly_rev > 0 else 0

        # Status
        is_past = m < today.month or (m == today.month and today.day > 15)
        status_type = "CERRADO" if is_past else "OTB"

        if diff_pct >= 20:
            status = f"🟢 MUY BIEN ({status_type})"
        elif diff_pct >= 0:
            status = f"🟡 OK ({status_type})"
        elif diff_pct >= -15:
            status = f"🟠 VIGILAR ({status_type})"
        else:
            status = f"🔴 CRÍTICO ({status_type})"

        tracker[m] = {
            "name": month_names[m - 1],
            "ty_revenue": round(ty_rev),
            "ty_nights": ty_nights,
            "ty_adr": ty_adr,
            "ly_revenue": round(ly_rev),
            "ly_nights": ly_nights,
            "ly_adr": ly_adr,
            "best_revenue": round(best_rev),
            "best_year": best_year,
            "best_nights": best_nights,
            "best_adr": best_adr,
            "diff_pct": diff_pct,
            "diff_vs_ly": diff_vs_ly,
            "compare_year": best_year,
            "status": status,
            # Channel breakdown
            "channels_ty": channel_ty.get(m, {}),
            "channels_ly": channel_ly.get(m, {}),
        }

    # YTD totals
    ytd_ty = sum(tracker[m]["ty_revenue"] for m in range(1, today.month + 1))
    ytd_best = sum(tracker[m]["best_revenue"] for m in range(1, today.month + 1))
    ytd_diff = round((ytd_ty - ytd_best) / ytd_best * 100) if ytd_best > 0 else 0

    log.info(f"  YTD: {ytd_ty:,.0f}€ vs {ytd_best:,.0f}€ best ({ytd_diff:+d}%)")

    for m in range(max(1, today.month - 1), min(13, today.month + 4)):
        t = tracker.get(m)
        if t and (t["ty_revenue"] > 0 or t["best_revenue"] > 0):
            log.info(f"    {t['name']}: {t['ty_revenue']:,.0f}€ vs {t['best_revenue']:,.0f}€ "
                     f"best({t['best_year']}) ({t['diff_pct']:+d}%) — {t['status']}")

    return tracker


def _revenue_by_month(bookings):
    by_month = defaultdict(lambda: {"revenue": 0, "nights": 0})
    for b in bookings:
        m = b["month"] if "month" in b else b["ci"].month
        by_month[m]["revenue"] += b["price"]
        by_month[m]["nights"] += b["nights"]
    return dict(by_month)


def _channel_breakdown(bookings):
    """
    Channel breakdown by month.
    Returns: {month: {"direct": {revenue, nights, adr, pct_revenue, net_revenue},
                       "booking": {...}, ...}}

    COMMISSION RATES (approximate):
    - Booking.com: 17% commission → net = price * 0.83
    - Airbnb: 3% host fee → net = price * 0.97
    - Direct: 0% → net = price
    """
    COMMISSION = {
        "booking": 0.17,
        "airbnb": 0.03,
        "direct": 0.00,
    }

    by_month = defaultdict(lambda: defaultdict(lambda: {"revenue": 0, "nights": 0, "count": 0}))

    for b in bookings:
        m = b.get("month", b["ci"].month)
        ch = b.get("channel", "direct")
        by_month[m][ch]["revenue"] += b["price"]
        by_month[m][ch]["nights"] += b["nights"]
        by_month[m][ch]["count"] += 1

    result = {}
    for m, channels in by_month.items():
        total_rev = sum(ch["revenue"] for ch in channels.values())
        month_data = {}
        for ch_name, ch_data in channels.items():
            comm_rate = COMMISSION.get(ch_name, 0.15)  # default 15% for unknown OTAs
            net_rev = ch_data["revenue"] * (1 - comm_rate)
            adr = round(ch_data["revenue"] / ch_data["nights"]) if ch_data["nights"] > 0 else 0
            net_adr = round(net_rev / ch_data["nights"]) if ch_data["nights"] > 0 else 0
            pct = round(ch_data["revenue"] / total_rev * 100) if total_rev > 0 else 0

            month_data[ch_name] = {
                "revenue": round(ch_data["revenue"]),
                "net_revenue": round(net_rev),
                "nights": ch_data["nights"],
                "count": ch_data["count"],
                "adr": adr,
                "net_adr": net_adr,
                "pct_revenue": pct,
                "commission_rate": comm_rate,
            }
        result[m] = month_data

    return result


# ══════════════════════════════════════════
# OTB FUTURO — for pricing.py OTB Confirmado
# ══════════════════════════════════════════

def calcular_otb_futuro():
    """
    OTB future revenue by month — used by pricing OTB Confirmado.
    Compares confirmed future revenue vs same point last year.
    """
    today = date.today()
    current_year = today.year
    last_year = current_year - 1

    ty_bookings = _fetch_bookings_for_year(current_year)
    ly_bookings = _fetch_bookings_for_year(last_year)

    # Only future bookings for current year
    ty_future = [b for b in ty_bookings if b["ci"] > today]
    ty_by_month = _revenue_by_month(ty_future)
    ly_by_month = _revenue_by_month(ly_bookings)

    results = []
    for m in range(today.month, 13):
        ty = ty_by_month.get(m, {"revenue": 0, "nights": 0})
        ly = ly_by_month.get(m, {"revenue": 0, "nights": 0})
        results.append({
            "mes": m,
            "otbTY": ty["revenue"],
            "otbLY": ly["revenue"],
            "nochesTY": ty["nights"],
            "nochesLY": ly["nights"],
        })

    return results


# ══════════════════════════════════════════
# FEEDBACK MECHANISM
# ══════════════════════════════════════════

def record_prices(results):
    today = date.today().isoformat()
    for r in results:
        d = r["date"]
        if d not in _price_history:
            _price_history[d] = []
        _price_history[d].append({
            "timestamp": today,
            "price": r["precioFinal"],
            "disponibles": r.get("disponibles", 0),
            "uncUplift": r.get("uncUplift", 1.0),
        })


def check_feedback(results, otb):
    suggestions = []

    for r in results:
        d_str = r["date"]
        days_out = r.get("daysOut", 0)

        if days_out < 14 or days_out > 60:
            continue

        history = _price_history.get(d_str, [])
        if len(history) < 14:
            continue

        current_price = r["precioFinal"]
        current_disp = r.get("disponibles", 9)

        old_entry = history[-14]
        old_price = old_entry["price"]
        old_disp = old_entry["disponibles"]

        if current_price > old_price * 1.05 and current_disp >= old_disp:
            price_increase_pct = round((current_price - old_price) / old_price * 100)
            suggestions.append({
                "date": d_str,
                "current_price": current_price,
                "old_price": old_price,
                "increase_pct": price_increase_pct,
                "disponibles": current_disp,
                "days_out": days_out,
            })

    if suggestions:
        log.info(f"  📉 Feedback: {len(suggestions)} fechas sin pickup tras subida")

    return suggestions
