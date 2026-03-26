"""
OTB module — v7.5
CHANGES vs v7.4:
  - P1: Pickup persistente via Google Sheets — sobrevive redeploys de Railway
    El problema: /data/ y /tmp/ se borran en cada deploy (128+ deploys).
    Los snapshots OTB se perdían → fPick = 1.00 SIEMPRE.
    Solución: guardar snapshots en una hoja de Google Sheets (ya tenemos SHEET_ID).
    Fallback a /data/ si Sheets no disponible.
  - calc_pace(): media ponderada 3 años (sin cambios vs v7.4)
  - fetch_historical_bookings(): usa HISTORICAL_YEARS=[2023,2024,2025]
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
    """Read current OTB — units booked per date."""
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
    """Read OTB split by room type (upper/ground)."""
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

        target = otb_ground if room_id == config.ROOM_GROUND else otb_upper

        d = max(ci, today)
        while d < co:
            if d > end:
                break
            k = fmt(d)
            otb_total[k] = otb_total.get(k, 0) + units
            target[k] = target.get(k, 0) + units
            d += timedelta(days=1)

    log.info(f"  OTB by type: {len(otb_total)} fechas")

    try:
        save_otb_snapshot(otb_total)
    except Exception as e:
        log.warning(f"  Snapshot save error: {e}")

    return otb_total, {"upper": otb_upper, "ground": otb_ground}


# ══════════════════════════════════════════
# OTB SNAPSHOT — PERSISTENT STORAGE
#
# v7.5: Triple-layer persistence:
#   1. Google Sheets (survives redeploys, shared across instances)
#   2. /data/ volume (Railway persistent if mounted)
#   3. /tmp/ (last resort, lost on redeploy)
#
# The key insight: Railway redeploys kill /tmp/ AND /data/ unless
# you've explicitly mounted a volume. With 128+ deploys, snapshots
# were ALWAYS lost. Google Sheets is the reliable store.
# ══════════════════════════════════════════

SNAPSHOT_DIR = "/data" if os.path.isdir("/data") else "/tmp"
SNAPSHOT_FILE = os.path.join(SNAPSHOT_DIR, "otb_snapshots.json")

# Google Sheets snapshot storage
_SHEETS_SNAPSHOT_TAB = "otb_snapshots"
_sheets_available = None  # Lazy check


def _check_sheets_available():
    """Check if we can use Google Sheets for persistence."""
    global _sheets_available
    if _sheets_available is not None:
        return _sheets_available
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
        if not creds_json:
            _sheets_available = False
            return False
        _sheets_available = True
        return True
    except ImportError:
        _sheets_available = False
        return False


def _get_sheets_client():
    """Get authenticated gspread client."""
    import gspread
    from google.oauth2.service_account import Credentials
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    if not creds_json:
        return None
    import json as _json
    creds_dict = _json.loads(creds_json)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)


def _save_snapshot_sheets(otb):
    """Save OTB snapshot to Google Sheets."""
    try:
        client = _get_sheets_client()
        if not client:
            return False
        sheet = client.open_by_key(config.SHEET_ID)

        # Get or create the snapshots tab
        try:
            tab = sheet.worksheet(_SHEETS_SNAPSHOT_TAB)
        except Exception:
            tab = sheet.add_worksheet(title=_SHEETS_SNAPSHOT_TAB, rows=20, cols=2)
            tab.update_cell(1, 1, "snapshot_date")
            tab.update_cell(1, 2, "otb_json")

        today_str = fmt(date.today())

        # Find existing row for today or append
        all_rows = tab.get_all_values()
        row_idx = None
        for i, row in enumerate(all_rows):
            if i == 0:
                continue  # header
            if len(row) >= 1 and row[0] == today_str:
                row_idx = i + 1  # 1-indexed
                break

        otb_json = json.dumps(otb)
        if row_idx:
            tab.update_cell(row_idx, 2, otb_json)
        else:
            tab.append_row([today_str, otb_json])

        # Clean old snapshots (keep last 14 days)
        cutoff = fmt(date.today() - timedelta(days=14))
        rows_to_delete = []
        for i, row in enumerate(all_rows):
            if i == 0:
                continue
            if len(row) >= 1 and row[0] < cutoff:
                rows_to_delete.append(i + 1)
        # Delete from bottom up to preserve indices
        for row_idx in reversed(rows_to_delete):
            try:
                tab.delete_rows(row_idx)
            except Exception:
                pass

        log.info(f"  📊 Snapshot guardado en Google Sheets ({today_str})")
        return True
    except Exception as e:
        log.warning(f"  Sheets snapshot save error: {e}")
        return False


def _load_snapshots_sheets():
    """Load all OTB snapshots from Google Sheets."""
    try:
        client = _get_sheets_client()
        if not client:
            return {}
        sheet = client.open_by_key(config.SHEET_ID)
        try:
            tab = sheet.worksheet(_SHEETS_SNAPSHOT_TAB)
        except Exception:
            return {}

        all_rows = tab.get_all_values()
        snapshots = {}
        for i, row in enumerate(all_rows):
            if i == 0:
                continue  # header
            if len(row) >= 2 and row[0] and row[1]:
                try:
                    snapshots[row[0]] = json.loads(row[1])
                except (json.JSONDecodeError, ValueError):
                    pass

        if snapshots:
            log.info(f"  📊 Snapshots cargados de Sheets: {len(snapshots)} días")
        return snapshots
    except Exception as e:
        log.debug(f"  Sheets snapshot load error: {e}")
        return {}


def save_otb_snapshot(otb):
    """Save today's OTB snapshot. Tries Sheets first, then local file."""
    today_str = fmt(date.today())

    # 1. Try Google Sheets (persistent across redeploys)
    sheets_ok = False
    if _check_sheets_available():
        sheets_ok = _save_snapshot_sheets(otb)

    # 2. Always save locally too (faster reads during same run)
    snapshots = _load_snapshots_local()
    snapshots[today_str] = otb
    cutoff = fmt(date.today() - timedelta(days=14))
    snapshots = {k: v for k, v in snapshots.items() if k >= cutoff}
    try:
        with open(SNAPSHOT_FILE, "w") as f:
            json.dump(snapshots, f)
    except Exception as e:
        log.warning(f"  Local snapshot save error: {e}")

    if not sheets_ok:
        log.info(f"  💾 Snapshot guardado localmente ({today_str})")


def _load_snapshots_local():
    """Load snapshots from local file."""
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _load_snapshots():
    """Load snapshots from best available source.
    Priority: local (fast) → Sheets (persistent).
    """
    # 1. Try local first (faster, works during same run)
    local = _load_snapshots_local()
    if local and len(local) >= 2:
        return local

    # 2. If local is empty/insufficient, try Sheets
    if _check_sheets_available():
        sheets = _load_snapshots_sheets()
        if sheets:
            # Also cache locally for rest of this run
            try:
                with open(SNAPSHOT_FILE, "w") as f:
                    json.dump(sheets, f)
            except Exception:
                pass
            return sheets

    return local


# ══════════════════════════════════════════
# PICKUP
# ══════════════════════════════════════════

def calc_pickup(otb_actual):
    """Pickup = OTB hoy - OTB hace 7 días.
    v7.5: Now reads from persistent Sheets storage → fPick ALIVE.
    """
    pickup = {}
    snapshots = _load_snapshots()
    today = date.today()

    if not snapshots:
        log.warning("  ⚠️ No OTB snapshots found — pickup disabled (fPick=1.0)")
        return pickup

    # Find snapshot closest to 7 days ago
    otb_7ago = None
    best_offset = None
    for offset in (7, 6, 8, 5, 9, 10):
        key = fmt(today - timedelta(days=offset))
        if key in snapshots:
            otb_7ago = snapshots[key]
            best_offset = offset
            break

    if not otb_7ago:
        available = sorted(snapshots.keys())
        log.warning(f"  ⚠️ No snapshot ~7 days ago. Available: {available}")
        return pickup

    log.info(f"  ✅ Pickup calculado con snapshot de hace {best_offset} días")

    for d in otb_actual:
        if d in otb_7ago:
            pickup[d] = otb_actual.get(d, 0) - otb_7ago.get(d, 0)

    # Log pickup summary
    total_pickup = sum(pickup.values())
    dates_with_pickup = sum(1 for v in pickup.values() if v > 0)
    if total_pickup > 0:
        log.info(f"  📈 Pickup total: +{total_pickup} room-nights en {dates_with_pickup} fechas")

    return pickup


# ══════════════════════════════════════════
# HISTORICAL BOOKINGS
# ══════════════════════════════════════════

def fetch_historical_bookings(years=None):
    """Fetch reservas históricas. Usa HISTORICAL_YEARS=[2023,2024,2025] por defecto."""
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
    """Fill curves ponderadas por año (CURVE_WEIGHTS)."""
    stays_by_seg = {}
    for b in bookings:
        ci = b["ci"]
        co = b["co"]
        bd = b["bd"]
        w = config.CURVE_WEIGHTS.get(b["year"], 0.33)

        d = ci
        while d < co:
            seg_key = get_segment_key(d)
            ant = max(0, (d - bd).days)
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
# PACE — v7.4: media ponderada 3 años
# ══════════════════════════════════════════

def calc_pace(hist):
    """Pace ponderado multi-año."""
    pace = {}
    today = date.today()
    weights = config.CURVE_WEIGHTS

    hist_by_year = {}
    for b in hist:
        y = b["year"]
        if y not in hist_by_year:
            hist_by_year[y] = []
        hist_by_year[y].append(b)

    if not hist_by_year:
        return pace

    total_weight = sum(weights.get(y, 0) for y in hist_by_year)
    if total_weight <= 0:
        return pace

    for di in range(config.PRICING_HORIZON):
        d = today + timedelta(days=di)
        date_str = fmt(d)

        pace_ponderado = 0.0
        peso_total = 0.0

        for year, bks in hist_by_year.items():
            w = weights.get(year, 0)
            if w <= 0:
                continue

            try:
                d_hist = d.replace(year=year)
            except ValueError:
                d_hist = d.replace(year=year, day=28)

            deadline_hist = d_hist - timedelta(days=di)

            reservas_hist = sum(
                1 for b in bks
                if b["ci"] <= d_hist < b["co"] and b["bd"] <= deadline_hist
            )
            occ_hist = reservas_hist / config.TOTAL_UNITS

            pace_ponderado += occ_hist * w
            peso_total += w

        if peso_total > 0:
            pace_ref = pace_ponderado / peso_total
            if pace_ref > 0.02:
                pace[date_str] = pace_ref

    paces_con_datos = len(pace)
    if paces_con_datos > 0:
        log.info(f"  Pace multi-año: {paces_con_datos} fechas "
                 f"(años: {sorted(hist_by_year.keys())}, pesos: {weights})")

    return pace


# ══════════════════════════════════════════
# CURRENT PRICES (price protection)
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
