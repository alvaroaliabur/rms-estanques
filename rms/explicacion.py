"""
Explicación Abuelita — v7.2.1
Clear narrative flow: each price explained step by step.

Flow for each date:
  1. Context (season, days out, availability)
  2. Starting price (Capa A)
  3. Adjustments UP or DOWN
  4. Genius compensation
  5. Guardrails (floor, ceiling, protection, min revenue, smoothing)
  6. Final price with reason
  7. MinStay
"""

import logging
from rms import config

log = logging.getLogger(__name__)

SEASON_NAMES = {
    "UA": "Ultra Alta (julio-agosto)",
    "A": "Alta (junio, septiembre)",
    "MA": "Media-Alta (mayo, octubre)",
    "M": "Media (abril)",
    "MB": "Media-Baja (marzo, diciembre)",
    "B": "Baja (enero, febrero, noviembre)",
}

MONTH_NAMES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}

DAY_NAMES = {
    0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves",
    4: "viernes", 5: "sábado", 6: "domingo",
}


def explicar_fecha(r):
    from rms.utils import parse_date

    d = parse_date(r["date"])
    month = d.month
    dow = d.weekday()
    day_name = DAY_NAMES.get(dow, "")
    month_name = MONTH_NAMES.get(month, "")
    sc = r.get("seasonCode", "M")
    season_name = SEASON_NAMES.get(sc, sc)
    is_we = r.get("isWeekend", False)
    tipo_dia = "fin de semana" if is_we else "entre semana"

    disp = r.get("disponibles", 0)
    reservadas = r.get("reservadas", 0)
    precio_final = r.get("precioFinal", 0)
    precio_genius = r.get("precioGenius", 0)
    precio_neto = r.get("precioNeto", 0)
    suelo = r.get("suelo", 0)
    techo = r.get("techo", 0)
    min_stay = r.get("minStay", 3)
    min_stay_ground = r.get("minStayGround", min_stay)
    clamped = r.get("clampedBy", "")
    event_name = r.get("eventName", "")
    event_factor = r.get("eventFactor", 1.0)
    disp_virtual = r.get("dispVirtual", disp)
    forecast_dem = r.get("forecastDemanda", 0)
    pace_ratio = r.get("paceRatio", 1.0)
    vac_factor = r.get("vacFactor", 1.0)
    market_factor = r.get("marketFactor", 1.0)
    unc_uplift = r.get("uncUplift", 1.0)
    ajuste_cs = r.get("ajusteCompSet", 1.0)
    gap_override = r.get("gapOverride", False)
    gap_override_ground = r.get("gapOverrideGround", False)
    los_razon = r.get("losRazon", "")
    los_reduccion = r.get("losReduccion", 0)
    los_premium = r.get("losPremium", 1.0)
    min_rev_applied = r.get("minRevApplied", False)
    min_rev_per_night = r.get("minRevPerNight", 0)
    media_vendida = r.get("mediaVendida", 0)
    prot_level = r.get("protLevel", 0)
    last_minute = r.get("lastMinuteLevel", "")
    suavizado = r.get("suavizado", "")
    days_out = r.get("daysOut", 0)

    lines = []

    # ── Header ──
    lines.append(f"<div class='fecha' id='{r['date']}'>")
    lines.append(f"<h3>{d.day} de {month_name} {d.year} ({day_name}, {tipo_dia})</h3>")
    lines.append(f"<div class='precio-final'>{precio_final}€ <span class='genius'>(Genius: {precio_genius}€)</span></div>")

    # ── 1. Context ──
    libres_txt = "libre" if disp == 1 else "libres"
    if disp == 0:
        lines.append(f"<p><strong>Temporada:</strong> {season_name}. "
                     f"Faltan <strong>{days_out} días</strong>. "
                     f"<strong>LLENO</strong> — los 9 apartamentos están reservados.</p>")
    else:
        lines.append(f"<p><strong>Temporada:</strong> {season_name}. "
                     f"Faltan <strong>{days_out} días</strong>. "
                     f"Hay <strong>{reservadas} de 9</strong> reservados, "
                     f"queda{'n' if disp != 1 else ''} <strong>{disp}</strong> {libres_txt}.</p>")

    # ── 2. Starting price (Capa A) ──
    seg = r.get("segment", "")
    seg_info = config.SEGMENT_BASE.get(seg, {})
    ppd = seg_info.get("preciosPorDisp", {})
    disp_for_lookup = max(1, disp)
    precio_capa_a = ppd.get(disp_for_lookup)
    if isinstance(precio_capa_a, dict):
        precio_capa_a = precio_capa_a.get("precio", "?")

    if disp == 0:
        lines.append(f"<p><strong>① Precio de partida:</strong> Lleno → se usa precio de máxima ocupación "
                     f"(1 libre): <strong>{precio_capa_a}€</strong> ({seg}).</p>")
    else:
        lines.append(f"<p><strong>① Precio de partida:</strong> Con {disp} {libres_txt} en {seg}, "
                     f"la curva histórica dice <strong>{precio_capa_a}€</strong>.</p>")

    # ── 3. Adjustments ──
    adj_lines = []

    if forecast_dem > 0 and disp > 0:
        adj_lines.append(f"Se esperan ~{forecast_dem:.0f} reservas más → disponibilidad efectiva baja a {disp_virtual}")

    if pace_ratio != 1.0:
        direction = "por encima" if pace_ratio > 1.0 else "por debajo"
        pct = abs(round((pace_ratio - 1.0) * 100))
        adj_lines.append(f"Pace vs año pasado: {pct}% {direction}")

    if vac_factor > 1.0:
        pct_vac = round((vac_factor - 1.0) * 100)
        adj_lines.append(f"Vacaciones escolares (DE/NL/UK): +{pct_vac}%")

    if market_factor != 1.0:
        if market_factor > 1.0:
            adj_lines.append(f"Mercado más caliente: +{round((market_factor-1)*100)}%")
        else:
            adj_lines.append(f"Mercado más frío: {round((market_factor-1)*100)}%")

    if event_name:
        pct_ev = round((event_factor - 1.0) * 100)
        adj_lines.append(f"Evento: {event_name} → +{pct_ev}%")

    # Unconstrained demand — ONLY when disp > 0 (real availability)
    if unc_uplift > 1.0 and disp > 0:
        pct_unc = round((unc_uplift - 1.0) * 100)
        from rms.pricing import SEGMENT_OCC_HIST
        occ_hist = SEGMENT_OCC_HIST.get(seg, 0)
        adj_lines.append(f"Demanda no restringida (occ hist {occ_hist}%, {disp} {libres_txt}): +{pct_unc}%")

    if adj_lines:
        lines.append("<p><strong>② Ajustes:</strong></p><ul>")
        for a in adj_lines:
            lines.append(f"<li>{a}</li>")
        lines.append("</ul>")
    else:
        lines.append("<p><strong>② Ajustes:</strong> Ninguno.</p>")

    # ── 4. Price buildup ──
    genius_price = round(precio_neto * config.GENIUS_COMPENSATION)
    lines.append(f"<p><strong>③ Precio calculado:</strong> "
                 f"Neto {precio_neto}€ × Genius {config.GENIUS_COMPENSATION} = <strong>{genius_price}€</strong></p>")

    # ── 5. Guardrails ──
    guardrail_lines = []

    if clamped == "SUELO":
        guardrail_lines.append(f"⬆️ Cálculo daba {genius_price}€ → <strong>suelo {suelo}€</strong> aplicado")
    elif clamped == "TECHO":
        guardrail_lines.append(f"⬇️ Cálculo daba {genius_price}€ → <strong>techo {techo}€</strong> aplicado")

    if media_vendida > 0 and prot_level > 0:
        min_prot = round(media_vendida * prot_level)
        guardrail_lines.append(f"🛡️ Protección: reservas existentes a {media_vendida}€ → no bajar de {min_prot}€")

    if min_rev_applied:
        min_rev = config.MIN_BOOKING_REVENUE.get(sc, 0)
        guardrail_lines.append(f"💰 Revenue mínimo: {min_rev}€ ÷ {min_stay}n = {min_rev_per_night}€/noche")

    if suavizado:
        smooth_txt = {
            "BAJADO": "📉 Suavizado: -12% máx vs ayer",
            "SUBIDO": "📈 Suavizado: +12% máx vs ayer",
            "MONO_UP": "📈 Más ocupado que ayer → precio igualado al alza",
            "MONO_DN": "📉 Menos ocupado que ayer → precio igualado a la baja",
        }
        guardrail_lines.append(smooth_txt.get(suavizado, suavizado))

    if last_minute:
        guardrail_lines.append(f"⏰ {last_minute}: temp baja + fecha cercana + alta disponibilidad")

    if guardrail_lines:
        lines.append("<p><strong>④ Guardarraíles:</strong></p><ul>")
        for g in guardrail_lines:
            lines.append(f"<li>{g}</li>")
        lines.append("</ul>")

    # ── 6. Final ──
    reason = ""
    if clamped == "SUELO":
        reason = f"limitado por suelo {suelo}€"
    elif clamped == "TECHO":
        reason = f"limitado por techo {techo}€"
    elif clamped == "PROT":
        reason = "protegido por reservas existentes"
    elif min_rev_applied:
        reason = "mínimo por revenue de reserva"
    elif suavizado:
        reason = "ajustado por suavizado"
    else:
        reason = "precio libre"

    lines.append(f"<p class='final-line'><strong>→ {precio_final}€</strong> ({reason}) | Genius: {precio_genius}€</p>")

    # ── 7. MinStay ──
    if min_stay == min_stay_ground:
        ms_txt = f"{min_stay} noches (ambas plantas)"
    else:
        ms_txt = f"Upper: {min_stay}n | Ground: {min_stay_ground}n"

    extra = ""
    if gap_override:
        extra += " — <span class='gap'>gap detectado</span>"
    if gap_override_ground:
        extra += " — <span class='gap'>gap planta baja</span>"

    lines.append(f"<p><strong>MinStay:</strong> {ms_txt}{extra}</p>")

    lines.append("</div>")
    return "\n".join(lines)


def generar_explicacion_html(results, month_filter=None, date_filter=None):
    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RMS Estanques v7.2 — Explicación de Precios</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #f5f5f5; color: #333; }
  h1 { color: #1a1a2e; border-bottom: 3px solid #16213e; padding-bottom: 10px; }
  h2 { color: #16213e; margin-top: 30px; }
  .fecha { background: white; border-radius: 8px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); border-left: 4px solid #0f3460; }
  .fecha h3 { margin: 0 0 5px 0; color: #0f3460; font-size: 1.1em; }
  .precio-final { font-size: 1.8em; font-weight: bold; color: #e94560; margin: 5px 0 15px 0; }
  .genius { font-size: 0.6em; color: #888; font-weight: normal; }
  .fecha p { margin: 8px 0; line-height: 1.5; font-size: 0.95em; }
  .fecha ul { margin: 5px 0; padding-left: 20px; }
  .fecha li { margin: 3px 0; font-size: 0.95em; }
  .warn { color: #e67e22; font-weight: bold; }
  .gap { color: #8e44ad; font-weight: bold; }
  .final-line { background: #f0f4f8; padding: 8px 12px; border-radius: 4px; font-size: 1.05em; }
  .nav { background: white; padding: 15px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
  .nav a { margin: 0 8px; color: #0f3460; text-decoration: none; font-weight: bold; }
  .nav a:hover { text-decoration: underline; }
  .nav a.active { color: #e94560; }
  .stats { background: #16213e; color: white; padding: 15px 20px; border-radius: 8px; margin-bottom: 20px; }
  .stats span { margin-right: 20px; }
</style>
</head>
<body>
<h1>RMS Estanques v7.2 — Explicación de Precios</h1>
"""

    html += "<div class='nav'>Mes: "
    html += "<a href='/explicacion'>Todos</a> "
    for m in range(1, 13):
        active = " class='active'" if month_filter == m else ""
        html += f"<a href='/explicacion?month={m}'{active}>{MONTH_NAMES[m][:3].capitalize()}</a> "
    html += "</div>"

    filtered = results
    if date_filter:
        filtered = [r for r in results if r["date"] == date_filter]
    elif month_filter:
        filtered = [r for r in results if int(r["date"][5:7]) == month_filter]

    if filtered:
        avg_price = round(sum(r["precioFinal"] for r in filtered) / len(filtered))
        min_price = min(r["precioFinal"] for r in filtered)
        max_price = max(r["precioFinal"] for r in filtered)
        avg_disp = round(sum(r["disponibles"] for r in filtered) / len(filtered), 1)
        suelo_count = sum(1 for r in filtered if r.get("clampedBy") == "SUELO")
        vac_count = sum(1 for r in filtered if r.get("vacFactor", 1.0) > 1.0)

        html += "<div class='stats'>"
        html += f"<span>{len(filtered)} días</span>"
        html += f"<span>Media: {avg_price}€</span>"
        html += f"<span>Rango: {min_price}–{max_price}€</span>"
        html += f"<span>Disp: {avg_disp}</span>"
        if suelo_count:
            html += f"<span>Suelo: {suelo_count}d</span>"
        if vac_count:
            html += f"<span>Vac: {vac_count}d</span>"
        html += "</div>"

    current_month = None
    for r in filtered:
        m = int(r["date"][5:7])
        if m != current_month:
            current_month = m
            html += f"<h2>{MONTH_NAMES[m].capitalize()} {r['date'][:4]}</h2>"
        html += explicar_fecha(r)

    if not filtered:
        html += "<p>No hay datos. <a href='/run'>Ejecutar /run</a> primero.</p>"

    html += "</body></html>"
    return html
