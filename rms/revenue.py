"""
Revenue Tracker + Feedback Mechanism
v7.1.1: Fixed to fetch current year bookings (not just historical)

REVENUE TRACKER:
- Reads confirmed bookings from Beds24 for BOTH years
- Calculates revenue by month (past + OTB future)
- Compares with last year
"""

import logging
from datetime import date, timedelta
from collections import defaultdict
from rms.beds24 import api_get_all
from rms import config

log = logging.getLogger(__name__)

# In-memory price history for feedback
_price_history = {}


# ══════════════════════════════════════════
# REVENUE TRACKER
# ══════════════════════════════════════════

def _fetch_bookings_for_year(year):
    """Fetch all confirmed bookings for a specific year."""
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
            # Skip cancelled
            status = b.get("status", "")
            cancel_time = b.get("cancelTime", "")
            if str(status) in ("3", "4") or (cancel_time and cancel_time != "0000-00-00 00:00:00"):
                continue
            
            ci = date.fromisoformat(b["arrival"][:10])
            co = date.fromisoformat(b["departure"][:10])
            nights = (co - ci).days
            price = float(b.get("price", 0) or 0)
            
            if nights > 0 and price > 0:
                bookings.append({
                    "ci": ci,
                    "co": co,
                    "nights": nights,
                    "price": price,
                    "ppn": price / nights,
                    "year": year,
                    "month": ci.month,
                })
    except Exception as e:
        log.warning(f"  Error fetching {year} bookings: {e}")
    
    return bookings


def calcular_revenue_tracker():
    """
    Calculate revenue by month for current year vs last year.
    Fetches bookings directly from Beds24 for both years.
    """
    log.info("══ REVENUE TRACKER ══")
    
    today = date.today()
    current_year = today.year
    last_year = current_year - 1
    
    # Fetch bookings for BOTH years
    ty_bookings = _fetch_bookings_for_year(current_year)
    ly_bookings = _fetch_bookings_for_year(last_year)
    
    log.info(f"  {current_year}: {len(ty_bookings)} reservas, {last_year}: {len(ly_bookings)} reservas")
    
    # Group by month
    ty_by_month = _revenue_by_month(ty_bookings)
    ly_by_month = _revenue_by_month(ly_bookings)
    
    tracker = {}
    month_names = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                   "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    
    for m in range(1, 13):
        ty = ty_by_month.get(m, {"revenue": 0, "nights": 0})
        ly = ly_by_month.get(m, {"revenue": 0, "nights": 0})
        
        ty_rev = ty["revenue"]
        ly_rev = ly["revenue"]
        ty_nights = ty["nights"]
        ly_nights = ly["nights"]
        
        ty_adr = round(ty_rev / ty_nights) if ty_nights > 0 else 0
        ly_adr = round(ly_rev / ly_nights) if ly_nights > 0 else 0
        
        diff_pct = round((ty_rev - ly_rev) / ly_rev * 100) if ly_rev > 0 else (100 if ty_rev > 0 else 0)
        
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
            "diff_pct": diff_pct,
            "status": status,
        }
    
    # YTD totals
    ytd_ty = sum(tracker[m]["ty_revenue"] for m in range(1, today.month + 1))
    ytd_ly = sum(tracker[m]["ly_revenue"] for m in range(1, today.month + 1))
    ytd_diff = round((ytd_ty - ytd_ly) / ytd_ly * 100) if ytd_ly > 0 else 0
    
    log.info(f"  YTD: {ytd_ty:,.0f}€ vs {ytd_ly:,.0f}€ LY ({ytd_diff:+d}%)")
    
    # Log key months
    for m in range(max(1, today.month - 1), min(13, today.month + 4)):
        t = tracker.get(m)
        if t and (t["ty_revenue"] > 0 or t["ly_revenue"] > 0):
            log.info(f"    {t['name']}: {t['ty_revenue']:,.0f}€ vs {t['ly_revenue']:,.0f}€ "
                     f"({t['diff_pct']:+d}%) — {t['status']}")
    
    return tracker


def _revenue_by_month(bookings):
    """Group booking revenue by arrival month."""
    by_month = defaultdict(lambda: {"revenue": 0, "nights": 0})
    for b in bookings:
        m = b["month"] if "month" in b else b["ci"].month
        by_month[m]["revenue"] += b["price"]
        by_month[m]["nights"] += b["nights"]
    return dict(by_month)


# ══════════════════════════════════════════
# FEEDBACK MECHANISM
# ══════════════════════════════════════════

def record_prices(results):
    """Record current prices for feedback tracking."""
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
    """Check for dates where price increased but no new bookings came."""
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
