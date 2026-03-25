"""
Explicación — v7.4
Dashboard rediseñado:
- ADR propio vs ADR grupo referencia (Booking Analytics)
- Tabla de meses centrada, columnas claras
- Indicador de pace visual (velocidad de llenado)
- Alertas accionables con qué hacer exactamente
- Detalle por fecha: tabla compacta, expansión limpia
- Columnas centradas
"""

import logging
from datetime import date
from rms import config

log = logging.getLogger(__name__)

MONTH_NAMES = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic",
}
MONTH_NAMES_FULL = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}
DAY_NAMES = {
    0: "L", 1: "M", 2: "X", 3: "J", 4: "V", 5: "S", 6: "D",
}
DAY_NAMES_FULL = {
    0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves",
    4: "viernes", 5: "sábado", 6: "domingo",
}


# ══════════════════════════════════════════
# DASHBOARD — Vista superior (1 pantalla)
# ══════════════════════════════════════════

def _build_dashboard(results):
    today = date.today()
    current_year = today.year

    # YTD
    ytd_rev = 0
    ytd_genius = 0
    best_hist_ytd = 0

    # Agrupar por mes
    meses = {}
    for r in results:
        m = int(r["date"][5:7])
        y = int(r["date"][:4])
        if y != current_year:
            continue
        if m not in meses:
            meses[m] = {
                "n": 0, "reservadas": 0, "sum_precio": 0,
                "suelos": 0, "techos": 0, "presion": 0,
                "rev_otb": 0,
            }
        mm = meses[m]
        mm["n"] += 1
        mm["reservadas"] += r.get("reservadas", 0)
        mm["sum_precio"] += r.get("precioFinal", 0)
        if r.get("clampedBy") == "SUELO":
            mm["suelos"] += 1
        if r.get("clampedBy") == "TECHO":
            mm["techos"] += 1
        if r.get("presionTemporal"):
            mm["presion"] += 1

    # Revenue tracker (desde config si está disponible)
    rev_tracker = {}
    try:
        from rms.revenue import calcular_revenue_tracker
        rev_tracker = calcular_revenue_tracker()
    except Exception:
        pass

    # YTD
    for m in range(1, today.month + 1):
        rt = rev_tracker.get(m, {})
        ytd_rev += rt.get("ty_revenue", 0)
        best_hist_ytd += rt.get("best_revenue", 0)

    ytd_diff = round((ytd_rev - best_hist_ytd) / best_hist_ytd * 100) if best_hist_ytd > 0 else 0
    ytd_color = "#27ae60" if ytd_diff >= 0 else "#e74c3c"
    ytd_sign = "+" if ytd_diff >= 0 else ""

    # Booking Analytics para referencia
    ba = getattr(config, 'BOOKING_ANALYTICS', {})

    # Filas de la tabla de meses
    filas = ""
    alertas_acciones = []

    for m in sorted(meses.keys()):
        mm = meses[m]
        rt = rev_tracker.get(m, {})

        n_dias = mm["n"] or 1
        total_nights = config.TOTAL_UNITS * n_dias
        nights_otb = mm["reservadas"]
        occ_pct = round(nights_otb / total_nights * 100)
        adr_pub = round(mm["sum_precio"] / n_dias) if n_dias > 0 else 0
        adr_genius = round(adr_pub * 0.85)

        # Revenue
        rev_ty = rt.get("ty_revenue", 0)
        best_rev = rt.get("best_revenue", 0)
        best_year = rt.get("best_year", "")
        diff_rev = round((rev_ty - best_rev) / best_rev * 100) if best_rev > 0 else 0
        diff_sign = "+" if diff_rev >= 0 else ""

        # ADR referencia desde Booking Analytics
        ba_m = ba.get(m, {})
        ref_adr = ba_m.get("ref_adr", 0)
        rank_nights = ba_m.get("rank_nights", 0)
        total_props = ba_m.get("total_props", 26)
        adr_vs_ref = round(((adr_genius - ref_adr) / ref_adr * 100)) if ref_adr > 0 else None

        # Llenado
        is_past = m < today.month
        is_current = m == today.month
        if is_past:
            llenado_txt = "cerrado"
            llenado_color = "#95a5a6"
            llenado_icon = "●"
        else:
            if occ_pct >= 80:
                llenado_txt = f"{occ_pct}%"
                llenado_color = "#27ae60"
                llenado_icon = "🚀"
            elif occ_pct >= 55:
                llenado_txt = f"{occ_pct}%"
                llenado_color = "#f39c12"
                llenado_icon = "→"
            else:
                llenado_txt = f"{occ_pct}%"
                llenado_color = "#e74c3c"
                llenado_icon = "⚠"

        # Color revenue
        if diff_rev >= 5:
            rev_color = "#27ae60"
        elif diff_rev >= -5:
            rev_color = "#f39c12"
        else:
            rev_color = "#e74c3c"

        # ADR vs ref display
        if adr_vs_ref is not None:
            adr_ref_sign = "+" if adr_vs_ref >= 0 else ""
            adr_ref_color = "#27ae60" if adr_vs_ref >= 0 else "#e74c3c"
            adr_ref_html = f'<span style="color:{adr_ref_color};font-size:0.82em">({adr_ref_sign}{adr_vs_ref}% vs ref {ref_adr}€)</span>'
        else:
            adr_ref_html = '<span style="color:#aaa;font-size:0.82em">—</span>'

        # Rank noches
        if rank_nights > 0 and not is_past:
            rank_color = "#27ae60" if rank_nights <= 10 else "#e67e22" if rank_nights <= 18 else "#e74c3c"
            rank_html = f'<span style="color:{rank_color};font-size:0.85em">#{rank_nights}/{total_props}</span>'
        else:
            rank_html = ""

        # Presión temporal activa
        presion_html = f'<span style="color:#e67e22;font-size:0.8em">↓{mm["presion"]}d</span>' if mm["presion"] > 0 else ""

        filas += f"""
        <tr onclick="filtrarMes({m})" style="cursor:pointer" class="fila-mes" data-mes="{m}">
            <td style="padding:10px 12px;font-weight:600;color:#1a1a2e">{MONTH_NAMES[m]}</td>
            <td style="padding:10px 12px;text-align:right">
                {'<span style="color:#aaa">—</span>' if rev_ty == 0 else f'<strong>{rev_ty:,}€</strong>'}
            </td>
            <td style="padding:10px 12px;text-align:center">
                {'<span style="color:#aaa;font-size:0.85em">—</span>' if best_rev == 0 else f'<span style="color:{rev_color};font-weight:600">{diff_sign}{diff_rev}%</span><span style="color:#aaa;font-size:0.78em"> ({best_year})</span>'}
            </td>
            <td style="padding:10px 12px;text-align:center">
                <strong>{adr_genius}€</strong><br>{adr_ref_html}
            </td>
            <td style="padding:10px 12px;text-align:center">
                {rank_html}
            </td>
            <td style="padding:10px 12px;text-align:center;color:#666">
                {round(nights_otb / config.TOTAL_UNITS, 1) if not is_past else '—'}
            </td>
            <td style="padding:10px 12px;text-align:center">
                <span style="color:{llenado_color};font-weight:600">{llenado_icon} {llenado_txt}</span>
                {presion_html}
            </td>
        </tr>"""

        # Alertas accionables
        if not is_past and diff_rev < -15 and best_rev > 0:
            nights_gap = round((best_rev - rev_ty) / (adr_genius if adr_genius > 0 else 200))
            # Diagnóstico específico
            if rank_nights > 15 and occ_pct < 60:
                accion = f"Bajar minStay a {max(3, config.DEFAULT_MIN_STAY.get('A', 5) - 2)}n para ganar volumen. Tu rank de noches es #{rank_nights} — precio OK, el problema es volumen."
            elif occ_pct < 40:
                accion = f"Revisar suelo y minStay. Solo {occ_pct}% ocupado a {(date(current_year, m, 1) - today).days}d vista."
            else:
                accion = f"Monitorizar pickup. Necesitas ~{nights_gap} noches más para igualar {best_year}."
            alertas_acciones.append({
                "mes": MONTH_NAMES[m],
                "diff": diff_rev,
                "accion": accion,
                "nights_otb": nights_otb,
                "best_nights": round(best_rev / (adr_genius if adr_genius > 0 else 200)),
            })

    # Canal mix
    canal_html = _build_canal_html(rev_tracker, today)

    # Alertas
    alertas_html = ""
    for a in alertas_acciones:
        alertas_html += f"""
        <div style="background:#fff5f5;border-left:4px solid #e74c3c;padding:10px 16px;border-radius:4px;margin:6px 0;font-size:0.9em">
            <strong style="color:#e74c3c">🔴 {a['mes']}:</strong>
            {a['diff']}% vs mejor año. {a['nights_otb']}n vendidas.
            <span style="color:#555"> → {a['accion']}</span>
        </div>"""

    ytd_html = ""
    if ytd_rev > 0:
        ytd_html = f"""
        <div style="background:white;border-radius:10px;padding:14px 20px;margin-bottom:16px;
                    border-left:5px solid {ytd_color};box-shadow:0 2px 8px rgba(0,0,0,0.06)">
            <span style="font-size:1.1em">YTD: <strong>{ytd_rev:,}€</strong>
            vs {best_hist_ytd:,}€ mejor hist.
            <strong style="color:{ytd_color}">({ytd_sign}{ytd_diff}%)</strong></span>
        </div>"""

    tabla = f"""
    <div style="background:white;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);margin-bottom:16px">
        <table style="width:100%;border-collapse:collapse;font-size:0.9em">
            <thead>
                <tr style="background:#1a1a2e;color:white">
                    <th style="padding:10px 12px;text-align:left;font-weight:600">Mes</th>
                    <th style="padding:10px 12px;text-align:right;font-weight:600">Revenue OTB</th>
                    <th style="padding:10px 12px;text-align:center;font-weight:600">vs Mejor</th>
                    <th style="padding:10px 12px;text-align:center;font-weight:600">ADR (Genius / vs ref)</th>
                    <th style="padding:10px 12px;text-align:center;font-weight:600">Rank noches</th>
                    <th style="padding:10px 12px;text-align:center;font-weight:600">Disp media</th>
                    <th style="padding:10px 12px;text-align:center;font-weight:600">Llenado</th>
                </tr>
            </thead>
            <tbody id="tbody-meses">
                {filas}
            </tbody>
        </table>
    </div>"""

    return ytd_html + tabla + canal_html + alertas_html


def _build_canal_html(rev_tracker, today):
    """Canal mix del año actual."""
    canales = {}
    total_rev = 0
    total_res = 0

    for m, rt in rev_tracker.items():
        if m > today.month:
            continue
        for canal, datos in rt.get("channels_ty", {}).items():
            if canal not in canales:
                canales[canal] = {"rev": 0, "count": 0, "nights": 0, "net_rev": 0}
            canales[canal]["rev"] += datos.get("revenue", 0)
            canales[canal]["count"] += datos.get("count", 0)
            canales[canal]["nights"] += datos.get("nights", 0)
            canales[canal]["net_rev"] += datos.get("net_revenue", 0)
            total_rev += datos.get("revenue", 0)
            total_res += datos.get("count", 0)

    if not canales or total_rev == 0:
        return ""

    comisiones_pagadas = sum(
        c["rev"] - c["net_rev"] for c in canales.values()
    )

    canal_items = []
    for canal, datos in sorted(canales.items(), key=lambda x: -x[1]["rev"]):
        pct = round(datos["rev"] / total_rev * 100)
        adr = round(datos["rev"] / datos["nights"]) if datos["nights"] > 0 else 0
        net_adr = round(datos["net_rev"] / datos["nights"]) if datos["nights"] > 0 else 0
        color = "#27ae60" if canal == "direct" else "#2980b9" if canal == "booking" else "#8e44ad"
        canal_items.append(
            f'<span style="color:{color}"><strong>{canal.title()}</strong> {pct}% '
            f'({datos["count"]}res, ADR {adr}€, neto <strong>{net_adr}€</strong>)</span>'
        )

    # Directas este año vs LY
    direct_ty = canales.get("direct", {}).get("rev", 0)
    direct_pct_ty = round(direct_ty / total_rev * 100) if total_rev > 0 else 0

    return f"""
    <div style="background:white;border-radius:10px;padding:14px 20px;margin-bottom:16px;
                box-shadow:0 2px 8px rgba(0,0,0,0.06);font-size:0.88em">
        <strong>Canal mix {today.year}:</strong>
        {' · '.join(canal_items)}
        {'<span style="color:#27ae60"> — 📈 Directas ' + str(direct_pct_ty) + '%</span>' if direct_pct_ty > 0 else ''}
        <span style="color:#e74c3c"> — Comisiones pagadas: <strong>{comisiones_pagadas:,.0f}€</strong></span>
    </div>"""


# ══════════════════════════════════════════
# TABLA DE FECHAS — Compacta con expansión
# ══════════════════════════════════════════

def _build_tabla_fechas(results, month_filter=None):
    """Tabla compacta de fechas. Clic en fila = expandir detalle."""
    from rms.utils import parse_date

    filas = ""
    idx = 0

    for r in results:
        m = int(r["date"][5:7])
        if month_filter and m != month_filter:
            continue

        d = parse_date(r["date"])
        dow = DAY_NAMES.get(d.weekday(), "")
        dow_full = DAY_NAMES_FULL.get(d.weekday(), "")
        is_we = d.weekday() in (4, 5)

        disp = r.get("disponibles", 0)
        reservadas = r.get("reservadas", 0)
        precio = r.get("precioFinal", 0)
        genius = r.get("precioGenius", 0)
        min_stay = r.get("minStay", 3)
        clamped = r.get("clampedBy", "")
        event_name = r.get("eventName", "")
        days_out = r.get("daysOut", 0)
        suelo = r.get("suelo", 0)
        techo = r.get("techo", 0)
        gap = r.get("gapOverride", False)
        presion = r.get("presionTemporal", False)
        vac = r.get("vacFactor", 1.0)

        # Color de disponibilidad
        if disp == 0:
            disp_color = "#e74c3c"
            disp_txt = "LLENO"
        elif disp <= 2:
            disp_color = "#e67e22"
            disp_txt = str(disp)
        elif disp <= 4:
            disp_color = "#f39c12"
            disp_txt = str(disp)
        else:
            disp_color = "#95a5a6"
            disp_txt = str(disp)

        # Badge de clamp
        clamp_badge = ""
        if clamped == "SUELO":
            clamp_badge = '<span style="background:#3498db;color:white;padding:1px 6px;border-radius:3px;font-size:0.75em;margin-left:4px">SUELO</span>'
        elif clamped == "TECHO":
            clamp_badge = '<span style="background:#e74c3c;color:white;padding:1px 6px;border-radius:3px;font-size:0.75em;margin-left:4px">TECHO</span>'
        elif clamped == "PROT":
            clamp_badge = '<span style="background:#9b59b6;color:white;padding:1px 6px;border-radius:3px;font-size:0.75em;margin-left:4px">PROT</span>'

        # Notas compactas
        notas = []
        if event_name:
            notas.append(f"🎉 {event_name}")
        if vac > 1.0:
            notas.append(f"🏫 Vac+{round((vac-1)*100)}%")
        if gap:
            notas.append("🔧 Gap")
        if presion:
            notas.append("⏱️ Presión")

        notas_txt = " · ".join(notas) if notas else ""

        bg = "#fafafa" if idx % 2 == 0 else "white"
        we_style = "font-weight:600;" if is_we else ""

        # Detalle expandible
        detalle = _build_detalle(r, dow_full)

        filas += f"""
        <tr style="background:{bg};cursor:pointer" onclick="toggleDetalle({idx})"
            class="fila-fecha" data-mes="{m}">
            <td style="padding:8px 10px;{we_style}color:#1a1a2e;white-space:nowrap">
                {d.day}{dow}
            </td>
            <td style="padding:8px 10px;text-align:center;color:{disp_color};font-weight:600">
                {disp_txt}
            </td>
            <td style="padding:8px 10px;text-align:right;font-weight:700;color:#1a1a2e">
                {precio}€{clamp_badge}
            </td>
            <td style="padding:8px 10px;text-align:right;color:#666">
                {genius}€
            </td>
            <td style="padding:8px 10px;text-align:center;color:#555">
                {min_stay}n
            </td>
            <td style="padding:8px 10px;color:#666;font-size:0.85em">
                {notas_txt}
            </td>
        </tr>
        <tr id="detalle-{idx}" style="display:none;background:#f0f4f8">
            <td colspan="6" style="padding:0">
                {detalle}
            </td>
        </tr>"""
        idx += 1

    return f"""
    <div style="background:white;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06)">
        <table style="width:100%;border-collapse:collapse;font-size:0.88em">
            <thead>
                <tr style="background:#2c3e50;color:white">
                    <th style="padding:10px;text-align:left;font-weight:600">Día</th>
                    <th style="padding:10px;text-align:center;font-weight:600">Disp</th>
                    <th style="padding:10px;text-align:right;font-weight:600">Precio</th>
                    <th style="padding:10px;text-align:right;font-weight:600">Genius</th>
                    <th style="padding:10px;text-align:center;font-weight:600">Min</th>
                    <th style="padding:10px;text-align:left;font-weight:600">Notas</th>
                </tr>
            </thead>
            <tbody>{filas}</tbody>
        </table>
    </div>"""


def _build_detalle(r, dow_full):
    """Detalle expandido de una fecha — limpio y estructurado."""
    from rms.utils import parse_date

    d = parse_date(r["date"])
    month = d.month

    precio_neto = r.get("precioNeto", 0)
    precio_final = r.get("precioFinal", 0)
    precio_genius = r.get("precioGenius", 0)
    suelo = r.get("suelo", 0)
    techo = r.get("techo", 0)
    clamped = r.get("clampedBy", "")
    days_out = r.get("daysOut", 0)
    reservadas = r.get("reservadas", 0)
    occ_now = reservadas / config.TOTAL_UNITS
    occ_esperada = r.get("expectedOcc", 0)
    pace_ratio = r.get("paceRatio", 1.0)
    vac_factor = r.get("vacFactor", 1.0)
    market_factor = r.get("marketFactor", 1.0)
    unc_uplift = r.get("uncUplift", 1.0)
    event_name = r.get("eventName", "")
    event_factor = r.get("eventFactor", 1.0)
    min_stay = r.get("minStay", 3)
    min_stay_ground = r.get("minStayGround", min_stay)
    gap_override = r.get("gapOverride", False)
    los_razon = r.get("losRazon", "")
    los_reduccion = r.get("losReduccion", 0)
    media_vendida = r.get("mediaVendida", 0)
    prot_level = r.get("protLevel", 0)
    suavizado = r.get("suavizado", "")
    min_rev_applied = r.get("minRevApplied", False)
    min_rev_per_night = r.get("minRevPerNight", 0)
    last_minute = r.get("lastMinuteLevel", "")
    presion = r.get("presionTemporal", False)
    sc = r.get("seasonCode", "M")

    # Precio base Capa A
    seg = r.get("segment", "")
    ppd = config.SEGMENT_BASE.get(seg, {}).get("preciosPorDisp", {})
    disp_lookup = max(1, config.TOTAL_UNITS - reservadas)
    capa_a = ppd.get(disp_lookup)
    if isinstance(capa_a, dict):
        capa_a = capa_a.get("precio", "?")

    # Construir cadena de cálculo
    pasos = []
    pasos.append(f"Capa A ({seg}, {disp_lookup} libre{'s' if disp_lookup != 1 else ''}): <strong>{capa_a}€</strong>")

    if presion:
        pasos.append(f"⏱️ Presión temporal (retrasado vs curva): bajada proactiva")

    if pace_ratio != 1.0:
        direction = "adelantado" if pace_ratio > 1.0 else "retrasado"
        pct = abs(round((pace_ratio - 1.0) * 100))
        occ_pct = round(occ_now * 100)
        exp_pct = round(occ_esperada * 100)
        pasos.append(f"Pace: {occ_pct}% OTB vs {exp_pct}% esperado → {pct}% {direction} → ×{pace_ratio:.2f}")

    if vac_factor > 1.0:
        pasos.append(f"🏫 Vacaciones escolares DE/NL/UK: ×{vac_factor:.2f} (+{round((vac_factor-1)*100)}%)")

    if market_factor != 1.0:
        pasos.append(f"🌍 Mercado {'caliente' if market_factor > 1 else 'frío'}: ×{market_factor:.2f}")

    if event_name and event_factor > 1.0:
        pasos.append(f"🎉 {event_name}: ×{event_factor:.2f} (+{round((event_factor-1)*100)}%)")

    if unc_uplift > 1.0:
        pasos.append(f"📈 Demanda no restringida (escasez): ×{unc_uplift:.2f} (+{round((unc_uplift-1)*100)}%)")

    genius_calculado = round(precio_neto * config.GENIUS_COMPENSATION)
    pasos.append(f"Neto {precio_neto}€ × {config.GENIUS_COMPENSATION} Genius = <strong>{genius_calculado}€</strong>")

    # Guardarraíles
    guardarrail = ""
    if clamped == "SUELO":
        guardarrail = f'<span style="background:#3498db;color:white;padding:2px 8px;border-radius:3px">SUELO {suelo}€</span> (cálculo daba {genius_calculado}€)'
    elif clamped == "TECHO":
        guardarrail = f'<span style="background:#e74c3c;color:white;padding:2px 8px;border-radius:3px">TECHO {techo}€</span>'
    elif clamped == "PROT":
        min_prot = round(media_vendida * prot_level)
        guardarrail = f'🛡️ Protección: reservas existentes a {round(media_vendida)}€ → mínimo {min_prot}€'
    elif min_rev_applied:
        guardarrail = f'💰 Revenue mínimo: {min_rev_per_night}€/noche'
    elif suavizado:
        textos = {"BAJADO": "📉 Suavizado -12% vs ayer", "SUBIDO": "📈 Suavizado +12% vs ayer",
                  "MONO_UP": "📈 Monotonía: precio igualado al alza", "MONO_DN": "📉 Monotonía: precio igualado a la baja"}
        guardarrail = textos.get(suavizado, suavizado)
    if last_minute:
        guardarrail += f' · ⏰ {last_minute}'

    # MinStay
    if min_stay == min_stay_ground:
        minstay_txt = f"{min_stay} noches"
    else:
        minstay_txt = f"Upper: {min_stay}n · Ground: {min_stay_ground}n"
    if gap_override:
        minstay_txt += " <span style='color:#8e44ad'>(gap)</span>"
    if los_reduccion > 0:
        minstay_txt += f" <span style='color:#e67e22'>(reducido, premium ×{r.get('losPremium',1):.2f})</span>"

    pasos_html = "".join(f'<div style="padding:3px 0;border-bottom:1px solid #e8ecf0;font-size:0.87em">{p}</div>' for p in pasos)

    return f"""
    <div style="padding:14px 20px;display:grid;grid-template-columns:1fr 1fr;gap:16px">
        <div>
            <div style="font-size:0.78em;color:#888;font-weight:600;letter-spacing:0.05em;margin-bottom:6px">CÁLCULO</div>
            {pasos_html}
            {'<div style="margin-top:8px;font-size:0.87em">' + guardarrail + '</div>' if guardarrail else ''}
        </div>
        <div>
            <div style="font-size:0.78em;color:#888;font-weight:600;letter-spacing:0.05em;margin-bottom:6px">RESULTADO</div>
            <div style="font-size:1.6em;font-weight:800;color:#1a1a2e">{precio_final}€</div>
            <div style="color:#888;font-size:0.9em">Genius: {precio_genius}€</div>
            <div style="margin-top:8px;font-size:0.87em;color:#555">MinStay: {minstay_txt}</div>
            <div style="margin-top:4px;font-size:0.82em;color:#888">Suelo {suelo}€ · Techo {techo}€ · {days_out}d vista</div>
            <div style="margin-top:4px;font-size:0.82em;color:#888">{round(occ_now*100)}% ocupado · {round(occ_esperada*100)}% esperado</div>
        </div>
    </div>"""


# ══════════════════════════════════════════
# MAIN: generar_explicacion_html
# ══════════════════════════════════════════

def generar_explicacion_html(results, month_filter=None, date_filter=None):
    today = date.today()

    # Filtrar si hay date_filter
    if date_filter:
        results_filtrados = [r for r in results if r["date"] == date_filter]
    elif month_filter:
        results_filtrados = results  # Tabla muestra todos los meses, filtra con JS
    else:
        results_filtrados = results

    # Dashboard siempre con todos los meses
    dashboard = _build_dashboard(results)

    # Mes activo para la tabla
    mes_activo = month_filter or today.month

    # Navegación de meses
    nav_items = '<a href="/explicacion" style="margin:0 4px;color:#1a1a2e;text-decoration:none;padding:4px 8px;border-radius:4px' + (';background:#1a1a2e;color:white' if not month_filter else '') + '">Todo</a>'
    for m in range(1, 13):
        active_style = ";background:#1a1a2e;color:white" if month_filter == m else ""
        nav_items += f'<a href="/explicacion?month={m}" style="margin:0 4px;color:#1a1a2e;text-decoration:none;padding:4px 8px;border-radius:4px{active_style}">{MONTH_NAMES[m]}</a>'

    # Tabla de fechas del mes activo
    tabla_fechas = _build_tabla_fechas(results, month_filter)

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RMS Estanques v7.4</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif;
    background: #f0f2f5;
    color: #333;
    min-height: 100vh;
  }}
  .header {{
    background: #1a1a2e;
    color: white;
    padding: 16px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}
  .header h1 {{ font-size: 1.1em; font-weight: 700; letter-spacing: -0.02em; }}
  .header-links a {{ color: rgba(255,255,255,0.7); text-decoration: none; margin-left: 16px; font-size: 0.85em; }}
  .header-links a:hover {{ color: white; }}
  .nav {{
    background: white;
    padding: 10px 24px;
    border-bottom: 1px solid #e8ecf0;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 2px;
  }}
  .content {{ max-width: 1100px; margin: 0 auto; padding: 20px 16px; }}
  .section-title {{
    font-size: 0.78em;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #888;
    margin: 20px 0 10px 0;
  }}
  tbody tr.fila-fecha:hover td {{ background: #e8f4fd !important; }}
  tbody tr.fila-mes:hover td {{ background: #f0f7ff !important; }}
  .fila-fecha td, .fila-mes td {{ transition: background 0.1s; }}
</style>
</head>
<body>

<div class="header">
  <h1>RMS Estanques v7.4</h1>
  <div class="header-links">
    <a href="/run">↺ Recalcular</a>
    <a href="/prices/compare">Tabla</a>
    <a href="/revenue">Revenue</a>
    <a href="/health">Estado</a>
  </div>
</div>

<div class="nav">
  {nav_items}
</div>

<div class="content">

  <div class="section-title">Dashboard</div>
  {dashboard}

  <div class="section-title">
    {'Todos los meses' if not month_filter else MONTH_NAMES_FULL.get(month_filter, '')} — {len([r for r in results if not month_filter or int(r['date'][5:7]) == month_filter])} días
  </div>
  {tabla_fechas}

</div>

<script>
function toggleDetalle(idx) {{
  const el = document.getElementById('detalle-' + idx);
  if (el) el.style.display = el.style.display === 'none' ? 'table-row' : 'none';
}}

function filtrarMes(m) {{
  window.location.href = '/explicacion?month=' + m;
}}
</script>

</body>
</html>"""

    return html
