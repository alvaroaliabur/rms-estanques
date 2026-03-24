"""
Revenue Tracker + Feedback Mechanism
v7.1: Track revenue YTD vs LY + detect unconverted price increases

REVENUE TRACKER:
- Reads confirmed bookings from Beds24
- Calculates revenue by month (past + OTB future)
- Compares with last year
- Reports in daily email

FEEDBACK MECHANISM:
- Tracks prices set by the system
- If a date had a price increase (from Claude or unconstrained demand)
  and gets NO new bookings within 14 days, flags it for review
- System can auto-reduce price if no pickup detected
"""

import logging
from datetime import date, timedelta
from collections import defaultdict
from rms.otb import fetch_historical_bookings
from rms import config

log = logging.getLogger(__name__)

# In-memory price history (persists during Railway service lifetime)
_price_history = {}  # {date_str: [{timestamp, price, source}]}


# ══════════════════════════════════════════
# REVENUE TRACKER
# ══════════════════════════════════════════

def calcular_revenue_tracker():
    """
    Calculate revenue by month: past (cerrado) + future (OTB).
    Compare with last year.
    
    Returns: {
        month: {
            ty_revenue, ty_nights, ty_adr,
            ly_revenue, ly_nights, ly_adr,
            diff_pct, status
        }
    }
    """
    log.info("══ REVENUE TRACKER ══")
    
    today = date.today()
    current_year = today.year
    
    # Fetch bookings for current year and last year
    all_bookings = fetch_historical_bookings()
    
    # Separate by year
    ty_bookings = [b for b in all_bookings if b["ci"].year == current_year]
    ly_bookings = [b for b in all_bookings if b["ci"].year == current_year - 1]
    
    # Calculate revenue by month
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
        
        diff_pct = round((ty_rev - ly_rev) / ly_rev * 100) if ly_rev > 0 else 0
        
        # Status
        is_past = m < today.month or (m == today.month and today.day > 15)
        if is_past:
            status_type = "CERRADO"
        else:
            status_type = "OTB"
        
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
        if t:
            log.info(f"    {t['name']}: {t['ty_revenue']:,.0f}€ vs {t['ly_revenue']:,.0f}€ "
                     f"({t['diff_pct']:+d}%) — {t['status']}")
    
    return tracker


def _revenue_by_month(bookings):
    """Group booking revenue by arrival month."""
    by_month = defaultdict(lambda: {"revenue": 0, "nights": 0})
    
    for b in bookings:
        m = b["ci"].month
        by_month[m]["revenue"] += b["price"]
        by_month[m]["nights"] += b["nights"]
    
    return dict(by_month)


# ══════════════════════════════════════════
# FEEDBACK MECHANISM
# ══════════════════════════════════════════

def record_prices(results):
    """
    Record current prices for feedback tracking.
    Called after each pricing run.
    """
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
            "claudeAdjusted": r.get("precioFinal", 0) != r.get("precioNeto", 0),
        })


def check_feedback(results, otb):
    """
    Check for dates where we increased price but got no new bookings.
    
    Logic:
    - Look at dates 14-60 days out
    - Compare current price vs 14 days ago
    - If price went UP and availability didn't go DOWN (no new bookings),
      suggest a price reduction
    
    Returns list of feedback suggestions.
    """
    suggestions = []
    today = date.today()
    
    for r in results:
        d_str = r["date"]
        days_out = r.get("daysOut", 0)
        
        # Only check 14-60 days out
        if days_out < 14 or days_out > 60:
            continue
        
        history = _price_history.get(d_str, [])
        if len(history) < 14:  # Need at least 14 days of history
            continue
        
        # Compare current with 14 days ago
        current_price = r["precioFinal"]
        current_disp = r.get("disponibles", 9)
        
        old_entry = history[-14] if len(history) >= 14 else history[0]
        old_price = old_entry["price"]
        old_disp = old_entry["disponibles"]
        
        # Price went up but no new bookings (availability same or higher)
        if current_price > old_price * 1.05 and current_disp >= old_disp:
            price_increase_pct = round((current_price - old_price) / old_price * 100)
            
            suggestions.append({
                "date": d_str,
                "current_price": current_price,
                "old_price": old_price,
                "increase_pct": price_increase_pct,
                "disponibles": current_disp,
                "days_out": days_out,
                "suggestion": f"Bajada de {round(price_increase_pct * 0.5)}% recomendada",
            })
    
    if suggestions:
        log.info(f"  📉 Feedback: {len(suggestions)} fechas sin pickup tras subida de precio")
        for s in suggestions[:5]:
            log.info(f"    {s['date']}: {s['old_price']}€ → {s['current_price']}€ "
                     f"(+{s['increase_pct']}%), {s['disponibles']} libres, {s['days_out']}d vista")
    
    return suggestions
