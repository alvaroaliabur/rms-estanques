"""
Explicación — v7.7
Dashboard con métricas corregidas:
- ADR REAL CONFIRMADO: revenue_confirmado / noches_vendidas (no precio cotizado del RMS)
  Para meses futuros con pocas reservas muestra datos reales disponibles.
- REVPAR como columna en tabla mensual: revenue / (unidades × días mes)
- Canal "other" visible en canal mix: detecta OTAs no mapeadas
- Señales v7.5 mantenidas intactas
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


# ──────────────────────────────────────────
# BEAT-THE-BEST helper
# ──────────────────────────────────────────

def _btb_status(mes, rev_otb):
    """Returns BTB dict or None. Compares rev_otb vs target (best × 1.05)."""
    btb = getattr(config, 'BEAT_THE_BEST', {})
    if not btb.get("enabled"):
        return None

    best = btb.get("BEST_REVENUE_BY_MONTH", {}).get(mes, 0)
    best_year = btb.get("BEST_YEAR_BY_MONTH", {}).get(mes, "")
    uplift = btb.get("target_uplift", 1.05)
    target = round(best * uplift)

    if best <= 0 or rev_otb <= 0:
        return None

    pct = round((rev_otb - target) / target * 100)
    if pct >= 0:
        return {"emoji": "🏆", "color": "#27ae60", "label": f"+{pct}% vs target", "pct": pct,
                "target": target, "best": best, "best_year": best_year}
    elif pct >= -15:
        return {"emoji": "🎯", "color": "#f39c12", "label": f"{pct}% vs target", "pct": pct,
                "target": target, "best": best, "best_year": best_year}
    else:
        return {"emoji": "⚠️", "color": "#e74c3c", "label": f"{pct}% vs target", "pct": pct,
                "target": target, "best": best, "best_year": best_year}


def _build_vs_mejor_cell(ty_rev, best_rev, best_rev_now, diff_vs_now, diff_rev, diff_sign, rev_color, best_year, is_past):
    """
    Celda 'vs Mejor año' con dos niveles:
    - Principal: diff_vs_now = vs mismo momento del mejor año (comparativa justa)
    - Secundario: diff_rev = vs total final del mejor año (contexto)

    Para meses pasados (cerrados): solo el total final tiene sentido.
    Para meses futuros: el mismo momento es la métrica clave.
    """
    if best_rev == 0:
        return '<span style="color:#aaa;font-size:0.85em">—</span>'

    if is_past:
        # Mes cerrado: comparar total final vs total final
        sign = "+" if diff_rev >= 0 else ""
        return (
            f'<span style="color:{rev_color};font-weight:600">{sign}{diff_rev}%</span>'
            f'<span style="color:#aaa;font-size:0.78em"> vs {best_year}</span>'
        )

    # Mes futuro: mostrar "mismo momento" como dato principal
    if diff_vs_now is not None and best_rev_now > 0:
        now_sign = "+" if diff_vs_now >= 0 else ""
        now_color = "#27ae60" if diff_vs_now >= 5 else "#f39c12" if diff_vs_now >= -5 else "#e74c3c"
        # Dato secundario: vs total final (contexto del potencial máximo)
        final_sign = "+" if diff_rev >= 0 else ""
        return (
            f'<span style="color:{now_color};font-weight:700;font-size:1.05em">{now_sign}{diff_vs_now}%</span>'
            f'<span style="color:#aaa;font-size:0.75em"> vs {best_year} hoy</span><br>'
            f'<span style="color:#bbb;font-size:0.75em">{final_sign}{diff_rev}% vs total {best_year}</span>'
        )
    else:
        # Sin dato de mismo momento (año sin suficiente histórico)
        sign = "+" if diff_rev >= 0 else ""
        return (
            f'<span style="color:{rev_color};font-weight:600">{sign}{diff_rev}%</span>'
            f'<span style="color:#aaa;font-size:0.78em"> ({best_year} total)</span>'
        )


# ══════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════

def _build_dashboard(results):
    today = date.today()
    current_year = today.year

    ytd_rev = 0
    best_hist_ytd = 0

    meses = {}
    for r in results:
        m = int(r["date"][5:7])
        y = int(r["date"][:4])
        if y != current_year:
            continue
        if m not in meses:
            meses[m] = {
                "n": 0, "reservadas": 0,
                "suelos": 0, "techos": 0, "presion": 0,
                "early_bird": 0, "dynamic_floor": 0, "claude_ajustes": 0,
            }
        mm = meses[m]
        mm["n"] += 1
        mm["reservadas"] += r.get("reservadas", 0)
        if r.get("clampedBy") == "SUELO":
            mm["suelos"] += 1
        if r.get("clampedBy") == "TECHO":
            mm["techos"] += 1
        if r.get("presionTemporal"):
            mm["presion"] += 1
        if r.get("earlyBird"):
            mm["early_bird"] += 1
        if r.get("floorFactor", 1.0) < 1.0:
            mm["dynamic_floor"] += 1
        if r.get("claudeAjuste"):
            mm["claude_ajustes"] += 1

    rev_tracker = {}
    try:
        from rms.revenue import calcular_revenue_tracker
        rev_tracker = calcular_revenue_tracker()
    except Exception:
        pass

    for m in range(1, today.month + 1):
        rt = rev_tracker.get(m, {})
        ytd_rev += rt.get("ty_revenue", 0)
        best_hist_ytd += rt.get("best_revenue", 0)

    ytd_diff = round((ytd_rev - best_hist_ytd) / best_hist_ytd * 100) if best_hist_ytd > 0 else 0
    ytd_color = "#27ae60" if ytd_diff >= 0 else "#e74c3c"
    ytd_sign = "+" if ytd_diff >= 0 else ""

    ba = getattr(config, 'BOOKING_ANALYTICS', {})
    filas = ""
    alertas_acciones = []

    for m in sorted(meses.keys()):
        mm = meses[m]
        rt = rev_tracker.get(m, {})

        n_dias = mm["n"] or 1
        total_nights = config.TOTAL_UNITS * n_dias
        nights_otb = mm["reservadas"]
        occ_pct = round(nights_otb / total_nights * 100)

        # ── ADR REAL CONFIRMADO (v7.6) ──────────────────────────────────────
        # ty_adr viene del revenue tracker: revenue_confirmado / noches_vendidas
        # Es el ADR que los huéspedes han pagado realmente, no el precio cotizado.
        ty_adr_real = rt.get("ty_adr", 0)   # ADR real confirmado (€ Genius que paga el huésped)
        ty_nights_real = rt.get("ty_nights", 0)
        ty_rev = rt.get("ty_revenue", 0)

        # RevPAR real confirmado (v7.6)
        ty_revpar = rt.get("ty_revpar", 0)
        best_revpar = rt.get("best_revpar", 0)

        # Para meses con pocas reservas, indicar cuántas noches confirman el ADR
        adr_sample_note = ""
        if ty_nights_real > 0 and ty_nights_real < 10 and not (m < today.month):
            adr_sample_note = f'<span style="color:#aaa;font-size:0.75em"> ({ty_nights_real}n)</span>'

        best_rev = rt.get("best_revenue", 0)
        best_year = rt.get("best_year", "")
        best_adr = rt.get("best_adr", 0)
        diff_rev = round((ty_rev - best_rev) / best_rev * 100) if best_rev > 0 else 0
        diff_sign = "+" if diff_rev >= 0 else ""

        # v7.6: comparativa vs mismo momento del mejor año (diff_vs_now)
        best_rev_now = rt.get("best_rev_now", 0)
        _diff_vs_now_raw = rt.get("diff_vs_now", None)
        diff_vs_now = round(_diff_vs_now_raw) if _diff_vs_now_raw is not None else None

        rev_for_btb = ty_rev if ty_rev > 0 else 0
        btb = _btb_status(m, rev_for_btb)

        ba_m = ba.get(m, {})
        ref_adr = ba_m.get("ref_adr", 0)
        rank_nights = ba_m.get("rank_nights", 0)
        total_props = ba_m.get("total_props", 26)

        # ADR vs ref — usar ADR real confirmado para comparativa honesta
        adr_vs_ref = round(((ty_adr_real - ref_adr) / ref_adr * 100)) if ref_adr > 0 and ty_adr_real > 0 else None

        is_past = m < today.month
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

        # Color basado en diff_vs_now (mismo momento) si está disponible,
        # sino fallback a diff_rev (vs total final)
        _diff_for_color = diff_vs_now if diff_vs_now is not None else diff_rev
        if _diff_for_color >= 5:
            rev_color = "#27ae60"
        elif _diff_for_color >= -5:
            rev_color = "#f39c12"
        else:
            rev_color = "#e74c3c"

        if adr_vs_ref is not None:
            adr_ref_sign = "+" if adr_vs_ref >= 0 else ""
            adr_ref_color = "#27ae60" if adr_vs_ref >= 0 else "#e74c3c"
            adr_ref_html = f'<span style="color:{adr_ref_color};font-size:0.82em">({adr_ref_sign}{adr_vs_ref}% vs ref {ref_adr}€)</span>'
        else:
            adr_ref_html = '<span style="color:#aaa;font-size:0.82em">—</span>'

        if rank_nights > 0 and not is_past:
            rank_color = "#27ae60" if rank_nights <= 10 else "#e67e22" if rank_nights <= 18 else "#e74c3c"
            rank_html = f'<span style="color:{rank_color};font-size:0.85em">#{rank_nights}/{total_props}</span>'
        else:
            rank_html = ""

        if btb and not is_past:
            btb_html = f'<span style="color:{btb["color"]};font-size:0.82em;white-space:nowrap">{btb["emoji"]} {btb["label"]}<br><span style="color:#aaa;font-size:0.92em">target {btb["target"]:,}€</span></span>'
        elif not is_past:
            btb_html = '<span style="color:#aaa;font-size:0.82em">—</span>'
        else:
            btb_html = ""

        # ADR display: real confirmado
        if ty_adr_real > 0:
            adr_html = f'<strong>{ty_adr_real}€</strong>{adr_sample_note}<br>{adr_ref_html}'
        else:
            adr_html = f'<span style="color:#aaa">—</span><br>{adr_ref_html}'

        # RevPAR display (v7.6)
        if ty_revpar > 0:
            revpar_color = "#27ae60" if best_revpar == 0 or ty_revpar >= best_revpar else "#e74c3c"
            revpar_html = f'<span style="color:{revpar_color};font-weight:600">{ty_revpar}€</span>'
            if best_revpar > 0:
                revpar_html += f'<br><span style="color:#aaa;font-size:0.78em">best {best_revpar}€</span>'
        else:
            revpar_html = '<span style="color:#aaa">—</span>'

        # Señales v7.5 compactas
        signals = []
        if mm["early_bird"] > 0 and not is_past:
            signals.append(f'<span style="color:#e67e22;font-size:0.78em" title="Early bird activo">🐦{mm["early_bird"]}d</span>')
        if mm["dynamic_floor"] > 0 and not is_past:
            signals.append(f'<span style="color:#3498db;font-size:0.78em" title="Suelo dinámico">📉{mm["dynamic_floor"]}d</span>')
        if mm["presion"] > 0:
            signals.append(f'<span style="color:#e67e22;font-size:0.78em" title="Presión temporal">⏱{mm["presion"]}d</span>')
        if mm["claude_ajustes"] > 0:
            signals.append(f'<span style="color:#8e44ad;font-size:0.78em" title="Ajuste IA">🧠{mm["claude_ajustes"]}d</span>')
        signals_html = " ".join(signals)

        filas += f"""
        <tr onclick="filtrarMes({m})" style="cursor:pointer" class="fila-mes" data-mes="{m}">
            <td style="padding:10px 12px;font-weight:600;color:#1a1a2e">{MONTH_NAMES[m]}</td>
            <td style="padding:10px 12px;text-align:right">
                {'<span style="color:#aaa">—</span>' if ty_rev == 0 else f'<strong>{ty_rev:,}€</strong>'}
            </td>
            <td style="padding:10px 12px;text-align:center">
                {_build_vs_mejor_cell(ty_rev, best_rev, best_rev_now, diff_vs_now, diff_rev, diff_sign, rev_color, best_year, is_past)}
            </td>
            <td style="padding:10px 12px;text-align:center">
                {btb_html}
            </td>
            <td style="padding:10px 12px;text-align:center">
                {adr_html}
            </td>
            <td style="padding:10px 12px;text-align:center">
                {revpar_html}
            </td>
            <td style="padding:10px 12px;text-align:center">
                {rank_html}
            </td>
            <td style="padding:10px 12px;text-align:center;color:#666">
                {round(nights_otb / config.TOTAL_UNITS, 1) if not is_past else '—'}
            </td>
            <td style="padding:10px 12px;text-align:center">
                <span style="color:{llenado_color};font-weight:600">{llenado_icon} {llenado_txt}</span><br>
                {signals_html}
            </td>
        </tr>"""

        # Alertas: usar diff_vs_now (mismo momento) si está disponible, sino diff_rev
        _alert_diff = diff_vs_now if diff_vs_now is not None else diff_rev
        _alert_rev_ref = best_rev_now if best_rev_now > 0 else best_rev
        if not is_past and _alert_diff < -15 and _alert_rev_ref > 0:
            nights_gap = round((_alert_rev_ref - ty_rev) / (ty_adr_real if ty_adr_real > 0 else 200))
            if rank_nights > 15 and occ_pct < 60:
                accion = f"Bajar minStay a {max(3, config.DEFAULT_MIN_STAY.get('A', 5) - 2)}n para ganar volumen. Rank noches #{rank_nights} — precio OK, problema de volumen."
            elif occ_pct < 40:
                accion = f"Revisar suelo y minStay. Solo {occ_pct}% ocupado a {(date(current_year, m, 1) - today).days}d vista."
            else:
                accion = f"Monitorizar pickup. Necesitas ~{nights_gap} noches más para igualar {best_year}."
            alertas_acciones.append({
                "mes": MONTH_NAMES[m], "diff": diff_rev, "accion": accion,
                "nights_otb": nights_otb,
            })

    canal_html = _build_canal_html(rev_tracker, today)

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
        <table style="width:100%;border-collapse:collapse;font-size:0.88em">
            <thead>
                <tr style="background:#1a1a2e;color:white">
                    <th style="padding:10px 12px;text-align:left;font-weight:600">Mes</th>
                    <th style="padding:10px 12px;text-align:right;font-weight:600">Revenue OTB</th>
                    <th style="padding:10px 12px;text-align:center;font-weight:600" title="Revenue total final del mejor año histórico — no el mismo momento del año">vs Mejor año ⓘ</th>
                    <th style="padding:10px 12px;text-align:center;font-weight:600">🏆 Beat Target</th>
                    <th style="padding:10px 12px;text-align:center;font-weight:600">ADR real</th>
                    <th style="padding:10px 12px;text-align:center;font-weight:600">RevPAR</th>
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
    canales = {}
    total_rev = 0

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

    if not canales or total_rev == 0:
        return ""

    comisiones_pagadas = sum(c["rev"] - c["net_rev"] for c in canales.values())

    canal_items = []
    for canal, datos in sorted(canales.items(), key=lambda x: -x[1]["rev"]):
        pct = round(datos["rev"] / total_rev * 100)
        adr = round(datos["rev"] / datos["nights"]) if datos["nights"] > 0 else 0
        net_adr = round(datos["net_rev"] / datos["nights"]) if datos["nights"] > 0 else 0
        if canal == "direct":
            color = "#27ae60"
        elif canal == "booking":
            color = "#2980b9"
        else:
            color = "#8e44ad"  # airbnb
        canal_label = canal.title()
        canal_items.append(
            f'<span style="color:{color}"><strong>{canal_label}</strong> {pct}% '
            f'({datos["count"]}res, ADR {adr}€, neto <strong>{net_adr}€</strong>)</span>'
        )


    return f"""
    <div style="background:white;border-radius:10px;padding:14px 20px;margin-bottom:16px;
                box-shadow:0 2px 8px rgba(0,0,0,0.06);font-size:0.88em">
        <strong>Canal mix {today.year}:</strong>
        {' · '.join(canal_items)}
        <span style="color:#e74c3c"> — Comisiones pagadas: <strong>{comisiones_pagadas:,.0f}€</strong></span>
    </div>"""


# ══════════════════════════════════════════
# TABLA DE FECHAS
# ══════════════════════════════════════════

def _build_tabla_fechas(results, month_filter=None):
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
        gap = r.get("gapOverride", False)
        presion = r.get("presionTemporal", False)
        vac = r.get("vacFactor", 1.0)
        early_bird = r.get("earlyBird", False)
        floor_factor = r.get("floorFactor", 1.0)
        claude_ajuste = r.get("claudeAjuste", False)

        if disp == 0:
            disp_color = "#e74c3c"; disp_txt = "LLENO"
        elif disp <= 2:
            disp_color = "#e67e22"; disp_txt = str(disp)
        elif disp <= 4:
            disp_color = "#f39c12"; disp_txt = str(disp)
        else:
            disp_color = "#95a5a6"; disp_txt = str(disp)

        clamp_badge = ""
        if clamped == "SUELO":
            clamp_badge = '<span style="background:#3498db;color:white;padding:1px 6px;border-radius:3px;font-size:0.75em;margin-left:4px">SUELO</span>'
        elif clamped == "TECHO":
            clamp_badge = '<span style="background:#e74c3c;color:white;padding:1px 6px;border-radius:3px;font-size:0.75em;margin-left:4px">TECHO</span>'
        elif clamped == "PROT":
            clamp_badge = '<span style="background:#9b59b6;color:white;padding:1px 6px;border-radius:3px;font-size:0.75em;margin-left:4px">PROT</span>'

        if claude_ajuste:
            claude_orig = r.get("claudePrecioOriginal", 0)
            dir_arrow = "↑" if precio > claude_orig else "↓"
            clamp_badge += f'<span style="background:#8e44ad;color:white;padding:1px 6px;border-radius:3px;font-size:0.75em;margin-left:4px">🧠{dir_arrow}{claude_orig}→{precio}</span>'

        notas = []
        if event_name:
            notas.append(f"🎉 {event_name}")
        if vac > 1.0:
            notas.append(f"🏫 Vac+{round((vac-1)*100)}%")
        if early_bird:
            notas.append("🐦 EarlyBird")
        if floor_factor < 1.0:
            notas.append(f"📉 Suelo×{floor_factor:.0%}")
        if gap:
            notas.append("🔧 Gap")
        if presion:
            notas.append("⏱️ Presión")

        notas_txt = " · ".join(notas) if notas else ""
        bg = "#fafafa" if idx % 2 == 0 else "white"
        we_style = "font-weight:600;" if is_we else ""
        detalle = _build_detalle(r, dow_full)

        filas += f"""
        <tr style="background:{bg};cursor:pointer" onclick="toggleDetalle({idx})"
            class="fila-fecha" data-mes="{m}">
            <td style="padding:8px 10px;{we_style}color:#1a1a2e;white-space:nowrap">{d.day}{dow}</td>
            <td style="padding:8px 10px;text-align:center;color:{disp_color};font-weight:600">{disp_txt}</td>
            <td style="padding:8px 10px;text-align:right;font-weight:700;color:#1a1a2e">{precio}€{clamp_badge}</td>
            <td style="padding:8px 10px;text-align:right;color:#666">{genius}€</td>
            <td style="padding:8px 10px;text-align:center;color:#555">{min_stay}n</td>
            <td style="padding:8px 10px;color:#666;font-size:0.85em">{notas_txt}</td>
        </tr>
        <tr id="detalle-{idx}" style="display:none;background:#f0f4f8">
            <td colspan="6" style="padding:0">{detalle}</td>
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
    from rms.utils import parse_date

    d = parse_date(r["date"])

    precio_neto = r.get("precioNeto", 0)
    precio_final = r.get("precioFinal", 0)
    precio_genius = r.get("precioGenius", 0)
    suelo = r.get("suelo", 0)
    suelo_base = r.get("sueloBase", suelo)
    floor_factor = r.get("floorFactor", 1.0)
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
    early_bird = r.get("earlyBird", False)
    sc = r.get("seasonCode", "M")
    claude_ajuste = r.get("claudeAjuste", False)
    claude_motivo = r.get("claudeMotivo", "")
    claude_original = r.get("claudePrecioOriginal", 0)

    seg = r.get("segment", "")
    ppd = config.SEGMENT_BASE.get(seg, {}).get("preciosPorDisp", {})
    disp_lookup = max(1, config.TOTAL_UNITS - reservadas)
    capa_a = ppd.get(disp_lookup)
    if isinstance(capa_a, dict):
        capa_a = capa_a.get("precio", "?")

    pasos = []
    pasos.append(f"Capa A ({seg}, {disp_lookup} libre{'s' if disp_lookup != 1 else ''}): <strong>{capa_a}€</strong>")

    if early_bird:
        pasos.append(
            f"🐦 <strong>Early bird</strong>: {days_out}d vista, {round(occ_now*100)}% occ "
            f"→ descuento anticipado para capturar primera demanda (sep/oct)"
        )

    if presion:
        pasos.append(f"⏱️ <strong>Presión temporal</strong>: llenado retrasado vs curva → bajada proactiva")

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
        pasos.append(
            f"📈 <strong>Demanda no restringida</strong>: escasez histórica para esta combinación "
            f"(seg+disponibilidad) → ×{unc_uplift:.2f} (+{round((unc_uplift-1)*100)}%)"
        )

    genius_calculado = round(precio_neto * config.GENIUS_COMPENSATION)
    pasos.append(f"Neto {precio_neto}€ × {config.GENIUS_COMPENSATION} Genius = <strong>{genius_calculado}€</strong>")

    if floor_factor < 1.0:
        pasos.append(
            f"📉 <strong>Suelo dinámico</strong>: suelo base {suelo_base}€ × {floor_factor:.0%} "
            f"({days_out}d vista) = suelo efectivo <strong>{suelo}€</strong>"
        )

    if claude_ajuste:
        dir_txt = "subida" if precio_final > claude_original else "bajada"
        pasos.append(
            f"🧠 <strong>Ajuste IA</strong> ({dir_txt}): {claude_original}€ → {precio_final}€"
            + (f" — {claude_motivo}" if claude_motivo else "")
        )

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
        textos = {
            "BAJADO": "📉 Suavizado -12% vs ayer", "SUBIDO": "📈 Suavizado +12% vs ayer",
            "MONO_UP": "📈 Monotonía: precio igualado al alza", "MONO_DN": "📉 Monotonía: precio igualado a la baja",
        }
        guardarrail = textos.get(suavizado, suavizado)
    if last_minute:
        guardarrail += f' · ⏰ {last_minute}'

    if min_stay == min_stay_ground:
        minstay_txt = f"{min_stay} noches"
    else:
        minstay_txt = f"Upper: {min_stay}n · Ground: {min_stay_ground}n"
    if gap_override:
        minstay_txt += " <span style='color:#8e44ad'>(gap)</span>"
    if los_reduccion > 0:
        minstay_txt += f" <span style='color:#e67e22'>(reducido, premium ×{r.get('losPremium',1):.2f})</span>"

    pasos_html = "".join(
        f'<div style="padding:3px 0;border-bottom:1px solid #e8ecf0;font-size:0.87em">{p}</div>'
        for p in pasos
    )

    suelo_display = f"Suelo {suelo}€"
    if floor_factor < 1.0:
        suelo_display += f' <span style="color:#3498db;font-size:0.85em">(din. base {suelo_base}€)</span>'

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
            <div style="margin-top:4px;font-size:0.82em;color:#888">{suelo_display} · Techo {techo}€ · {days_out}d vista</div>
            <div style="margin-top:4px;font-size:0.82em;color:#888">{round(occ_now*100)}% ocupado · {round(occ_esperada*100)}% esperado</div>
        </div>
    </div>"""


# ══════════════════════════════════════════
# MAIN: generar_explicacion_html
# ══════════════════════════════════════════

def generar_explicacion_html(results, month_filter=None, date_filter=None):
    today = date.today()

    if date_filter:
        results_filtrados = [r for r in results if r["date"] == date_filter]
    elif month_filter:
        results_filtrados = results
    else:
        results_filtrados = results

    dashboard = _build_dashboard(results)
    mes_activo = month_filter or today.month

    nav_items = (
        '<a href="/explicacion" style="margin:0 4px;color:#1a1a2e;text-decoration:none;padding:4px 8px;border-radius:4px'
        + (';background:#1a1a2e;color:white' if not month_filter else '')
        + '">Todo</a>'
    )
    for m in range(1, 13):
        active_style = ";background:#1a1a2e;color:white" if month_filter == m else ""
        nav_items += (
            f'<a href="/explicacion?month={m}" style="margin:0 4px;color:#1a1a2e;'
            f'text-decoration:none;padding:4px 8px;border-radius:4px{active_style}">{MONTH_NAMES[m]}</a>'
        )

    tabla_fechas = _build_tabla_fechas(results, month_filter)

    leyenda = """
    <div style="background:white;border-radius:8px;padding:10px 16px;margin-bottom:12px;
                box-shadow:0 1px 4px rgba(0,0,0,0.05);font-size:0.82em;color:#555;line-height:1.6">
        <strong>Señales v7.6:</strong>
        ADR = revenue confirmado / noches vendidas ·
        RevPAR = revenue / (9 aptos × días mes) ·
        🐦 Early bird · 📉 Suelo dinámico · 📈 Demanda no restringida ·
        🧠 Ajuste IA · ⏱️ Presión temporal · 🏆 Beat-the-Best (+5% sobre mejor año)
    </div>"""

    n_visible = len([r for r in results if not month_filter or int(r['date'][5:7]) == month_filter])

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RMS Estanques v7.7</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif;
    background: #f0f2f5; color: #333; min-height: 100vh;
  }}
  .header {{
    background: #1a1a2e; color: white; padding: 16px 24px;
    display: flex; align-items: center; justify-content: space-between;
  }}
  .header h1 {{ font-size: 1.1em; font-weight: 700; letter-spacing: -0.02em; }}
  .header-links a {{ color: rgba(255,255,255,0.7); text-decoration: none; margin-left: 16px; font-size: 0.85em; }}
  .header-links a:hover {{ color: white; }}
  .nav {{
    background: white; padding: 10px 24px;
    border-bottom: 1px solid #e8ecf0;
    display: flex; align-items: center; flex-wrap: wrap; gap: 2px;
  }}
  .content {{ max-width: 1200px; margin: 0 auto; padding: 20px 16px; }}
  .section-title {{
    font-size: 0.78em; font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; color: #888; margin: 20px 0 10px 0;
  }}
  tbody tr.fila-fecha:hover td {{ background: #e8f4fd !important; }}
  tbody tr.fila-mes:hover td {{ background: #f0f7ff !important; }}
  .fila-fecha td, .fila-mes td {{ transition: background 0.1s; }}
</style>
</head>
<body>

<div class="header">
  <h1>RMS Estanques v7.7</h1>
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

  {leyenda}

  <div class="section-title">Dashboard</div>
  {dashboard}

  <div class="section-title">
    {'Todos los meses' if not month_filter else MONTH_NAMES_FULL.get(month_filter, '')} — {n_visible} días
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
