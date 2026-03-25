"""
Explicación Abuelita — v7.2
Generates human-readable explanation of how each price is formed.

Endpoint: GET /explicacion
  - Returns HTML page with all 365 days explained
  - Optional ?month=7 to filter by month
  - Optional ?date=2026-07-15 for a single date

Each date gets a paragraph explaining:
  1. Season and base context
  2. Availability and Capa A price
  3. Forecast adjustments (pace, pickup, events, vacaciones, market)
  4. Unconstrained demand uplift
  5. Comp set adjustment
  6. Genius compensation
  7. Floor/ceiling/clamp
  8. LOS and gaps
  9. Final price
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
    """Generate human-readable explanation for a single date result."""
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
    lines.append(f"<p><strong>Temporada:</strong> {season_name}. "
                 f"Faltan <strong>{days_out} días</strong>. "
                 f"Hay <strong>{reservadas} de 9</strong> apartamentos reservados, "
                 f"queda{'n' if disp != 1 else ''} <strong>{disp}</strong> {libres_txt}.</p>")

    # ── 2. Capa A base price ──
    seg = r.get("segment", "")
    seg_info = config.SEGMENT_BASE.get(seg, {})
    ppd = seg_info.get("preciosPorDisp", {})
    precio_capa_a = ppd.get(disp, {})
    if isinstance(precio_capa_a, dict):
        precio_capa_a = precio_capa_a.get("precio", "?")

    lines.append(f"<p><strong>Precio base (Capa A):</strong> Con {disp} libres en segmento {seg}, "
                 f"la curva de demanda histórica dice <strong>{precio_capa_a}€/noche</strong>.</p>")

    # ── 3. Forecast adjustments ──
    adjustments = []
    if forecast_dem > 0:
        adjustments.append(f"Se esperan <strong>{forecast_dem}</strong> reservas más → "
                          f"disponibilidad virtual baja a <strong>{disp_virtual}</strong>")

    if pace_ratio != 1.0:
        direction = "por encima" if pace_ratio > 1.0 else "por debajo"
        pct = abs(round((pace_ratio - 1.0) * 100))
        adjustments.append(f"Pace vs año pasado: <strong>{pct}% {direction}</strong> → "
                          f"factor {pace_ratio:.2f}")

    if vac_factor > 1.0:
        pct_vac = round((vac_factor - 1.0) * 100)
        adjustments.append(f"Vacaciones escolares (DE/NL/UK): <strong>+{pct_vac}%</strong> demanda")

    if market_factor != 1.0:
        if market_factor > 1.0:
            adjustments.append(f"Mercado más caliente que nosotros: <strong>+{round((market_factor-1)*100)}%</strong>")
        else:
            adjustments.append(f"Mercado más frío que nosotros: <strong>{round((market_factor-1)*100)}%</strong>")

    if event_name:
        pct_ev = round((event_factor - 1.0) * 100)
        adjustments.append(f"Evento: <strong>{event_name}</strong> → +{pct_ev}%")

    if adjustments:
        lines.append("<p><strong>Ajustes de demanda:</strong></p><ul>")
        for a in adjustments:
            lines.append(f"<li>{a}</li>")
        lines.append("</ul>")
    else:
        lines.append("<p><strong>Ajustes de demanda:</strong> Ninguno significativo.</p>")

    # ── 4. Unconstrained demand ──
    if unc_uplift > 1.0:
        pct_unc = round((unc_uplift - 1.0) * 100)
        occ_hist = None
        from rms.pricing import SEGMENT_OCC_HIST
        occ_hist = SEGMENT_OCC_HIST.get(seg, 0)
        lines.append(f"<p><strong>Demanda no restringida:</strong> Este segmento tuvo "
                     f"<strong>{occ_hist}%</strong> de ocupación histórica. Con solo {disp} libres, "
                     f"hay demanda invisible → precio sube <strong>+{pct_unc}%</strong>.</p>")

    # ── 5. Comp set ──
    if ajuste_cs != 1.0:
        comp_adr = config.COMP_SET["ADR_PEER"].get(month, 0)
        lines.append(f"<p><strong>Comp set:</strong> La competencia cobra ~{comp_adr}€ de media en {month_name}. "
                     f"Nuestro precio estaba por encima → ajuste <strong>{ajuste_cs:.2f}</strong>.</p>")

    # ── 6. Genius + floor/ceiling ──
    lines.append(f"<p><strong>Precio neto:</strong> {precio_neto}€. "
                 f"Con compensación Genius (×{config.GENIUS_COMPENSATION}): "
                 f"<strong>{round(precio_neto * config.GENIUS_COMPENSATION)}€</strong>.</p>")

    lines.append(f"<p><strong>Suelo:</strong> {suelo}€ | <strong>Techo:</strong> {techo}€")
    if clamped == "SUELO":
        lines.append(f" → <span class='warn'>Precio limitado por SUELO (el cálculo daba menos de {suelo}€)</span>")
    elif clamped == "TECHO":
        lines.append(f" → <span class='warn'>Precio limitado por TECHO (el cálculo daba más de {techo}€)</span>")
    elif clamped == "PROT":
        lines.append(f" → <span class='warn'>Protección de precio: ya se vendieron noches a {media_vendida}€ de media</span>")
    lines.append("</p>")

    # ── 7. Price protection ──
    if media_vendida > 0:
        lines.append(f"<p><strong>Protección:</strong> Ya hay reservas a {media_vendida}€/noche de media. "
                     f"Nivel de protección: {round(prot_level*100)}% (no bajar de {round(media_vendida * prot_level)}€).</p>")

    # ── 8. Last minute ──
    if last_minute:
        lines.append(f"<p><strong>Last minute:</strong> Modo <strong>{last_minute}</strong> activo "
                     f"(temporada baja, cerca de la fecha, mucha disponibilidad).</p>")

    # ── 9. Min booking revenue ──
    if min_rev_applied:
        min_rev = config.MIN_BOOKING_REVENUE.get(sc, 0)
        lines.append(f"<p><strong>Revenue mínimo por reserva:</strong> En temporada {sc}, una reserva debe generar "
                     f"al menos {min_rev}€. Con minStay {min_stay}, eso son {min_rev_per_night}€/noche mínimo.</p>")

    # ── 10. LOS / MinStay ──
    lines.append(f"<p><strong>Estancia mínima:</strong>")
    if min_stay == min_stay_ground:
        lines.append(f" <strong>{min_stay} noches</strong> (ambas plantas).")
    else:
        lines.append(f" Upper: <strong>{min_stay} noches</strong> | Ground: <strong>{min_stay_ground} noches</strong>.")

    if los_reduccion > 0:
        lines.append(f" Reducida {los_reduccion} noches ({los_razon})")
        if los_premium > 1.0:
            lines.append(f" con premium de +{round((los_premium-1)*100)}% por estancia más corta.")

    if gap_override:
        lines.append(f" <span class='gap'>Gap detectado: minStay ajustada para llenar hueco.</span>")
    if gap_override_ground:
        lines.append(f" <span class='gap'>Gap en planta baja: minStay ground ajustada independientemente.</span>")

    lines.append("</p>")

    # ── 11. Smoothing ──
    if suavizado:
        if suavizado == "BAJADO":
            lines.append(f"<p><strong>Suavizado:</strong> Precio reducido para no subir >12% respecto al día anterior.</p>")
        elif suavizado == "SUBIDO":
            lines.append(f"<p><strong>Suavizado:</strong> Precio subido para no bajar >12% respecto al día anterior.</p>")
        elif suavizado == "MONO_UP":
            lines.append(f"<p><strong>Monotonía:</strong> Más ocupación que ayer → precio igualado al alza.</p>")
        elif suavizado == "MONO_DN":
            lines.append(f"<p><strong>Monotonía:</strong> Menos ocupación que ayer → precio igualado a la baja.</p>")

    lines.append("</div>")
    return "\n".join(lines)


def generar_explicacion_html(results, month_filter=None, date_filter=None):
    """Generate full HTML page with explanations."""
    
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
  .nav { background: white; padding: 15px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
  .nav a { margin: 0 8px; color: #0f3460; text-decoration: none; font-weight: bold; }
  .nav a:hover { text-decoration: underline; }
  .nav a.active { color: #e94560; }
  .stats { background: #16213e; color: white; padding: 15px 20px; border-radius: 8px; margin-bottom: 20px; }
  .stats span { margin-right: 20px; }
</style>
</head>
<body>
<h1>🏨 RMS Estanques v7.2 — Explicación de Precios</h1>
"""

    # Navigation
    html += "<div class='nav'>Filtrar por mes: "
    html += "<a href='/explicacion'>Todos</a> "
    for m in range(1, 13):
        active = " class='active'" if month_filter == m else ""
        html += f"<a href='/explicacion?month={m}'{active}>{MONTH_NAMES[m][:3].capitalize()}</a> "
    html += "</div>"

    # Filter results
    filtered = results
    if date_filter:
        filtered = [r for r in results if r["date"] == date_filter]
    elif month_filter:
        filtered = [r for r in results if int(r["date"][5:7]) == month_filter]

    # Stats
    if filtered:
        avg_price = round(sum(r["precioFinal"] for r in filtered) / len(filtered))
        min_price = min(r["precioFinal"] for r in filtered)
        max_price = max(r["precioFinal"] for r in filtered)
        avg_disp = round(sum(r["disponibles"] for r in filtered) / len(filtered), 1)
        suelo_count = sum(1 for r in filtered if r.get("clampedBy") == "SUELO")
        techo_count = sum(1 for r in filtered if r.get("clampedBy") == "TECHO")
        vac_count = sum(1 for r in filtered if r.get("vacFactor", 1.0) > 1.0)

        html += "<div class='stats'>"
        html += f"<span>📊 {len(filtered)} días</span>"
        html += f"<span>💰 Media: {avg_price}€</span>"
        html += f"<span>⬇️ Mín: {min_price}€</span>"
        html += f"<span>⬆️ Máx: {max_price}€</span>"
        html += f"<span>🏠 Disp media: {avg_disp}</span>"
        if suelo_count:
            html += f"<span>🔻 Suelo: {suelo_count}d</span>"
        if techo_count:
            html += f"<span>🔺 Techo: {techo_count}d</span>"
        if vac_count:
            html += f"<span>🏫 Vac: {vac_count}d</span>"
        html += "</div>"

    # Generate explanations
    current_month = None
    for r in filtered:
        m = int(r["date"][5:7])
        if m != current_month:
            current_month = m
            html += f"<h2>{MONTH_NAMES[m].capitalize()} {r['date'][:4]}</h2>"
        html += explicar_fecha(r)

    if not filtered:
        html += "<p>No hay datos. Ejecuta <a href='/run'>/run</a> primero.</p>"

    html += "</body></html>"
    return html
