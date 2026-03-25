"""
Explicación — v7.3 Final
Compact dashboard (1 screen) + click-to-expand date details.

3 questions in 10 seconds:
  1. ¿Vamos ganando? Revenue vs best year
  2. ¿Se está llenando? Fill speed per month
  3. ¿Hay que hacer algo? Action alerts
"""

import logging
from datetime import date
from rms import config

log = logging.getLogger(__name__)

MONTH_NAMES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}

MONTH_SHORT = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic",
}


def _get_revenue_tracker():
    try:
        from rms.revenue import calcular_revenue_tracker
        return calcular_revenue_tracker()
    except Exception as e:
        log.warning(f"Revenue tracker unavailable: {e}")
        return {}


# ══════════════════════════════════════════
# COMPACT DASHBOARD
# ══════════════════════════════════════════

def _build_dashboard(tracker, results):
    today = date.today()
    if not tracker:
        return "<div class='dash warn'>Sin datos de revenue. Ejecuta <a href='/run'>/run</a>.</div>"

    html = "<div class='dash'>"

    # YTD headline
    ytd_ty = sum(tracker[m]["ty_revenue"] for m in range(1, today.month + 1) if m in tracker)
    ytd_best = sum(tracker[m].get("best_revenue", tracker[m].get("ly_revenue", 0))
                   for m in range(1, today.month + 1) if m in tracker)
    ytd_diff = round((ytd_ty - ytd_best) / ytd_best * 100) if ytd_best > 0 else 0

    if ytd_diff >= 5:
        yc = "#2d7a3a"
    elif ytd_diff >= 0:
        yc = "#8a6d00"
    else:
        yc = "#c0392b"

    html += (f"<div class='ytd' style='border-left:5px solid {yc}'>"
             f"YTD: <strong>{ytd_ty:,.0f}€</strong> vs {ytd_best:,.0f}€ mejor hist. "
             f"<strong style='color:{yc}'>({ytd_diff:+d}%)</strong></div>")

    # Month grid
    html += "<table class='grid'>"
    html += "<tr><th></th><th>Revenue</th><th>vs Mejor</th><th>ADR</th><th>Disp</th><th>Llenado</th><th></th></tr>"

    start_m = max(1, today.month - 1)
    end_m = min(12, today.month + 6)

    for m in range(start_m, end_m + 1):
        t = tracker.get(m)
        if not t:
            continue

        diff = t["diff_pct"]
        best_rev = t.get("best_revenue", t.get("ly_revenue", 0))
        best_year = t.get("best_year", today.year - 1)

        if diff >= 10:
            icon, bg = "🟢", "#eafaea"
        elif diff >= 0:
            icon, bg = "🟡", "#fefce8"
        elif diff >= -15:
            icon, bg = "🟠", "#fff3e0"
        else:
            icon, bg = "🔴", "#fde8e8"

        month_results = [r for r in results if int(r["date"][5:7]) == m]
        if month_results:
            avg_disp = sum(r.get("disponibles", 0) for r in month_results) / len(month_results)
            booked_pct = round((1 - avg_disp / 9) * 100)
        else:
            avg_disp = 9
            booked_pct = 0

        if m < today.month:
            speed = "cerrado"
            sc = "#999"
        elif booked_pct > 70:
            speed = f"🚀 {booked_pct}%"
            sc = "#2d7a3a"
        elif booked_pct > 40:
            speed = f"→ {booked_pct}%"
            sc = "#333"
        elif booked_pct > 15:
            speed = f"⚠ {booked_pct}%"
            sc = "#e67e22"
        else:
            speed = f"🐌 {booked_pct}%"
            sc = "#c0392b"

        marker = "◉" if m == today.month else ""

        # ADR comparison
        ty_adr = t.get("ty_adr", 0)
        best_adr = t.get("best_adr", t.get("ly_adr", 0))
        if ty_adr > 0 and best_adr > 0:
            adr_diff = round((ty_adr - best_adr) / best_adr * 100)
            adr_color = "#2d7a3a" if adr_diff >= 0 else "#c0392b"
            adr_cell = f"{ty_adr}€ <small style='color:{adr_color}'>({adr_diff:+d}%)</small>"
        elif ty_adr > 0:
            adr_cell = f"{ty_adr}€"
        else:
            adr_cell = "—"

        html += (f"<tr style='background:{bg}'>"
                 f"<td><strong>{MONTH_SHORT[m]}</strong> {marker}</td>"
                 f"<td class='r'>{t['ty_revenue']:,}€</td>"
                 f"<td class='r'><strong>{diff:+d}%</strong> <small>({best_year})</small></td>"
                 f"<td class='r'>{adr_cell}</td>"
                 f"<td class='r'>{avg_disp:.1f}</td>"
                 f"<td style='color:{sc}'>{speed}</td>"
                 f"<td>{icon}</td></tr>")

    html += "</table>"

    # Channel mix — direct vs OTAs
    html += _build_channel_html(tracker, today)

    # Actions
    actions = _generate_actions(tracker, results)
    if actions:
        html += "<div class='actions'>"
        for a in actions:
            html += f"<div class='act {a['level']}'>{a['icon']} <strong>{a['month']}:</strong> {a['text']}</div>"
        html += "</div>"

    html += "</div>"
    return html


def _build_channel_html(tracker, today):
    """Compact channel mix: direct vs booking vs others, with net revenue."""
    current_year = today.year

    # Aggregate channel data across all months this year
    total_by_channel = {}
    ly_direct_pct = 0
    ly_total_rev = 0

    for m in range(1, 13):
        t = tracker.get(m)
        if not t:
            continue

        for ch_name, ch_data in t.get("channels_ty", {}).items():
            if ch_name not in total_by_channel:
                total_by_channel[ch_name] = {"revenue": 0, "net_revenue": 0, "nights": 0, "count": 0}
            total_by_channel[ch_name]["revenue"] += ch_data.get("revenue", 0)
            total_by_channel[ch_name]["net_revenue"] += ch_data.get("net_revenue", 0)
            total_by_channel[ch_name]["nights"] += ch_data.get("nights", 0)
            total_by_channel[ch_name]["count"] += ch_data.get("count", 0)

        for ch_name, ch_data in t.get("channels_ly", {}).items():
            ly_total_rev += ch_data.get("revenue", 0)
            if ch_name == "direct":
                ly_direct_pct += ch_data.get("revenue", 0)

    if not total_by_channel:
        return ""

    grand_total = sum(c["revenue"] for c in total_by_channel.values())
    grand_net = sum(c["net_revenue"] for c in total_by_channel.values())
    if grand_total == 0:
        return ""

    # LY direct percentage
    ly_direct_pct_val = round(ly_direct_pct / ly_total_rev * 100) if ly_total_rev > 0 else 0

    # Current direct percentage
    direct_data = total_by_channel.get("direct", {"revenue": 0, "net_revenue": 0, "nights": 0, "count": 0})
    direct_pct = round(direct_data["revenue"] / grand_total * 100) if grand_total > 0 else 0
    direct_diff = direct_pct - ly_direct_pct_val

    # Color for direct trend
    if direct_diff > 3:
        dir_color = "#2d7a3a"
        dir_icon = "📈"
    elif direct_diff >= -3:
        dir_color = "#8a6d00"
        dir_icon = "→"
    else:
        dir_color = "#c0392b"
        dir_icon = "📉"

    commission_saved = grand_total - grand_net  # What we pay in commissions

    html = "<div style='margin-top:10px;padding:8px 12px;background:#f8f9fa;border-radius:6px;font-size:0.85em'>"
    html += f"<strong>Canal mix {current_year}:</strong> "

    # Show each channel inline
    sorted_channels = sorted(total_by_channel.items(), key=lambda x: x[1]["revenue"], reverse=True)
    parts = []
    for ch_name, ch_data in sorted_channels:
        pct = round(ch_data["revenue"] / grand_total * 100)
        adr = round(ch_data["revenue"] / ch_data["nights"]) if ch_data["nights"] > 0 else 0
        net_adr = round(ch_data["net_revenue"] / ch_data["nights"]) if ch_data["nights"] > 0 else 0
        label = ch_name.capitalize()
        if ch_name == "direct":
            parts.append(f"<strong style='color:#2d7a3a'>{label} {pct}%</strong> ({ch_data['count']}res, ADR {adr}€, neto {net_adr}€)")
        elif ch_name == "booking":
            parts.append(f"{label} {pct}% ({ch_data['count']}res, ADR {adr}€, <span style='color:#c0392b'>neto {net_adr}€</span>)")
        else:
            parts.append(f"{label} {pct}% ({ch_data['count']}res)")

    html += " · ".join(parts)

    # Direct trend vs LY
    html += f" — {dir_icon} Directas <span style='color:{dir_color}'>{direct_pct}% vs {ly_direct_pct_val}% LY ({direct_diff:+d}pp)</span>"

    # Commission cost
    if commission_saved > 0:
        html += f" — Comisiones pagadas: <span style='color:#c0392b'>{commission_saved:,.0f}€</span>"

    html += "</div>"
    return html


def _generate_actions(tracker, results):
    actions = []
    today = date.today()

    for m in range(today.month, min(today.month + 6, 13)):
        t = tracker.get(m)
        if not t:
            continue

        diff = t["diff_pct"]
        month_results = [r for r in results if int(r["date"][5:7]) == m]
        if not month_results:
            continue

        avg_disp = sum(r.get("disponibles", 0) for r in month_results) / len(month_results)
        suelo_days = sum(1 for r in month_results if r.get("clampedBy") == "SUELO")
        total_days = len(month_results)

        if diff < -20:
            actions.append({
                "month": MONTH_SHORT[m], "level": "crit", "icon": "🔴",
                "text": f"{diff:+d}% vs mejor año. {t['ty_nights']}n vendidas vs {t.get('best_nights',0)}n. "
                        f"Acción: bajar minStay o promoción.",
            })
        elif diff < -10 and avg_disp > 5:
            actions.append({
                "month": MONTH_SHORT[m], "level": "warn", "icon": "🟠",
                "text": f"{diff:+d}% con {avg_disp:.0f}/9 libres. Vigilar 2 semanas.",
            })
        elif diff > 20 and suelo_days > total_days * 0.3:
            actions.append({
                "month": MONTH_SHORT[m], "level": "opp", "icon": "💰",
                "text": f"+{diff}% (bien!), pero {suelo_days}/{total_days}d en suelo. Margen para subir.",
            })

    return actions


# ══════════════════════════════════════════
# DATE ROWS — compact + expandable
# ══════════════════════════════════════════

def _row_compact(r):
    disp = r.get("disponibles", 0)
    precio = r.get("precioFinal", 0)
    genius = r.get("precioGenius", 0)
    clamped = r.get("clampedBy", "")
    f_total = r.get("fTotal", 1.0)
    event = r.get("eventName", "")
    min_stay = r.get("minStay", 0)
    dow = date.fromisoformat(r["date"]).weekday()
    day_short = ["L", "M", "X", "J", "V", "S", "D"][dow]

    if disp == 0:
        bg = "#e8e8e8"
    elif clamped == "TECHO":
        bg = "#fce4ec"
    elif clamped == "SUELO":
        bg = "#fff8e1"
    elif f_total > 1.02:
        bg = "#e8f5e9"
    elif f_total < 0.98:
        bg = "#fbe9e7"
    else:
        bg = "#fff"

    notes = []
    if clamped:
        notes.append(clamped)
    if abs(f_total - 1.0) > 0.02:
        notes.append(f"×{f_total:.2f}")
    if event:
        notes.append(event[:18])
    if r.get("boostUA", 1.0) > 1.0:
        notes.append(f"boost+{round((r['boostUA']-1)*100)}%")
    if r.get("gapOverride"):
        notes.append("GAP")
    note_str = " · ".join(notes)

    return (f"<tr style='background:{bg}' class='clickrow'>"
            f"<td>{r['date'][8:]}{day_short}</td><td class='r'>{disp}</td>"
            f"<td class='r'><strong>{precio}€</strong></td><td class='r'>{genius}€</td>"
            f"<td class='r'>{min_stay}n</td>"
            f"<td class='note'>{note_str}</td></tr>")


def _row_detail(r):
    f_otb = r.get("fOTB", 1.0)
    f_pickup = r.get("fPickup", 1.0)
    f_pace = r.get("fPace", 1.0)
    f_total = r.get("fTotal", 1.0)
    f_ebsa = r.get("fEBSA", 1.0)
    urgency = r.get("urgency", 1.0)
    base_pub = r.get("basePub", 0)
    suelo = r.get("suelo", 0)
    techo = r.get("techo", 0)
    occ_now = r.get("occNow", 0)
    occ_exp = r.get("expectedOcc", 0)
    neto = r.get("precioNeto", 0)
    vac = r.get("vacFactor", 1.0)
    boost = r.get("boostUA", 1.0)
    clamped = r.get("clampedBy", "")
    suavizado = r.get("suavizado", "")

    parts = []
    parts.append(f"Neto {neto}€ → ×{config.GENIUS_COMPENSATION} = {base_pub}€")
    if boost > 1.0:
        parts.append(f"Boost +{round((boost-1)*100)}%")

    mp = []
    if abs(f_otb - 1.0) > 0.005:
        mp.append(f"OTB×{f_otb:.2f}({round(occ_now*100)}%vs{round(occ_exp*100)}%)")
    if abs(f_pickup - 1.0) > 0.005:
        mp.append(f"Pick×{f_pickup:.2f}")
    if abs(f_pace - 1.0) > 0.005:
        mp.append(f"Pace×{f_pace:.2f}")
    if urgency > 1.0:
        mp.append(f"Urg×{urgency:.1f}")
    if mp:
        parts.append(" ".join(mp) + f" → ×{f_total:.2f}")

    if f_ebsa > 1.01:
        parts.append(f"EBSA+{round((f_ebsa-1)*100)}%")
    if vac > 1.0:
        parts.append(f"Vac+{round((vac-1)*100)}%")
    if clamped:
        parts.append(f"{clamped}({suelo}–{techo}€)")
    if suavizado:
        parts.append(suavizado)

    detail = " | ".join(parts)
    return f"<tr class='detail'><td colspan='6'><small>{detail}</small></td></tr>"


# ══════════════════════════════════════════
# MAIN HTML
# ══════════════════════════════════════════

def generar_explicacion_html(results, month_filter=None, date_filter=None):
    tracker = _get_revenue_tracker()

    html = """<!DOCTYPE html>
<html lang="es"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RMS Estanques v7.3</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       max-width: 900px; margin: 0 auto; padding: 10px; background: #f5f5f5; color: #333; font-size: 14px; }
h1 { font-size: 1.2em; color: #1a1a2e; margin-bottom: 10px; }

.dash { background: white; border-radius: 10px; padding: 14px; margin-bottom: 14px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
.dash.warn { background: #fff3cd; padding: 20px; }
.ytd { padding: 8px 12px; border-radius: 6px; background: #f8f9fa; margin-bottom: 10px; font-size: 1em; }

.grid { width: 100%; border-collapse: collapse; font-size: 0.85em; }
.grid th { background: #1a1a2e; color: white; padding: 5px 6px; text-align: left; font-weight: 600; }
.grid td { padding: 4px 6px; border-bottom: 1px solid #e8e8e8; }
.grid .r { text-align: right; font-variant-numeric: tabular-nums; }
.grid small { color: #888; }

.actions { margin-top: 10px; }
.act { padding: 7px 10px; border-radius: 5px; margin: 5px 0; font-size: 0.88em; line-height: 1.4; }
.act.crit { background: #fde8e8; border-left: 3px solid #c0392b; }
.act.warn { background: #fff3e0; border-left: 3px solid #e67e22; }
.act.opp { background: #e8f5e9; border-left: 3px solid #2d7a3a; }

.nav { background: white; padding: 8px 12px; border-radius: 8px; margin-bottom: 10px;
       box-shadow: 0 1px 3px rgba(0,0,0,0.08); font-size: 0.85em; }
.nav a { margin: 0 5px; color: #0f3460; text-decoration: none; font-weight: 600; }
.nav a:hover { text-decoration: underline; }
.nav a.active { color: #e94560; }

.dates { background: white; border-radius: 8px; overflow: hidden;
         box-shadow: 0 1px 4px rgba(0,0,0,0.08); margin-top: 10px; }
.dates h2 { font-size: 0.95em; padding: 8px 12px; background: #1a1a2e; color: white; }
.dtable { width: 100%; border-collapse: collapse; font-size: 0.82em; }
.dtable th { background: #f0f4f8; padding: 4px 6px; text-align: left; font-weight: 600;
             position: sticky; top: 0; }
.dtable td { padding: 3px 6px; border-bottom: 1px solid #f0f0f0; }
.dtable .r { text-align: right; font-variant-numeric: tabular-nums; }
.dtable .note { color: #666; font-size: 0.88em; }
.clickrow { cursor: pointer; }
.clickrow:hover { background: #f0f8ff !important; }
.detail td { background: #f8f9fa; cursor: default; padding: 5px 10px; }
.detail small { color: #555; line-height: 1.5; }
</style>
<script>
document.addEventListener('click', function(e) {
    var row = e.target.closest('.clickrow');
    if (!row) return;
    var detail = row.nextElementSibling;
    if (detail && detail.classList.contains('detail')) {
        detail.style.display = detail.style.display === 'table-row' ? 'none' : 'table-row';
    }
});
</script>
</head><body>
<h1>RMS Estanques v7.3</h1>
"""

    # Nav
    html += "<div class='nav'>"
    html += "<a href='/explicacion'>Todo</a>"
    for m in range(1, 13):
        active = " class='active'" if month_filter == m else ""
        html += f" <a href='/explicacion?month={m}'{active}>{MONTH_SHORT[m]}</a>"
    html += "</div>"

    # Dashboard
    html += _build_dashboard(tracker, results)

    # Filter
    filtered = results
    if date_filter:
        filtered = [r for r in results if r["date"] == date_filter]
    elif month_filter:
        filtered = [r for r in results if int(r["date"][5:7]) == month_filter]

    # Date table
    if filtered:
        current_month = None
        for r in filtered:
            m = int(r["date"][5:7])
            if m != current_month:
                if current_month is not None:
                    html += "</table></div>"
                current_month = m
                html += f"<div class='dates'><h2>{MONTH_NAMES[m].capitalize()} {r['date'][:4]}</h2>"
                html += "<table class='dtable'>"
                html += "<tr><th>Día</th><th class='r'>Disp</th><th class='r'>Precio</th>"
                html += "<th class='r'>Genius</th><th class='r'>Min</th><th>Notas</th></tr>"

            html += _row_compact(r)
            html += _row_detail(r)

        html += "</table></div>"
    else:
        html += "<p style='padding:20px'>No hay datos. <a href='/run'>/run</a></p>"

    html += "</body></html>"
    return html
