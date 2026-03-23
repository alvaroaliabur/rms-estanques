"""
Alerts — Gap urgente, pickup muerto.
Replaces: alertasAnomalias_, detectarGapsUrgentes_, detectarPickupMuerto_
"""

import logging
from datetime import date, timedelta
from rms import config
from rms.utils import fmt
from rms.otb import calc_pickup

log = logging.getLogger(__name__)


def run_alerts(otb):
    """Run all anomaly alerts."""
    cfg = config.ALERTAS_ANOMALIAS
    if not cfg or not cfg["enabled"]:
        return

    log.info("  Checking anomalies...")
    alertas = []

    if cfg["GAP_URGENTE"]["enabled"]:
        alertas.extend(_detect_gaps_urgentes(otb, cfg["GAP_URGENTE"]))

    if cfg["PICKUP_MUERTO"]["enabled"]:
        pickup = calc_pickup(otb)
        alertas.extend(_detect_pickup_muerto(otb, pickup, cfg["PICKUP_MUERTO"]))

    if not alertas:
        log.info("  ✅ Sin anomalías")
        return

    log.info(f"  🚨 {len(alertas)} alertas detectadas")
    # TODO: Send alert email
    for a in alertas:
        log.warning(f"  {a['emoji']} {a['titulo']}: {a['detalle']}")


def _detect_gaps_urgentes(otb, cfg):
    alertas = []
    today = date.today()
    bloque = None

    for di in range(cfg["horizonte_dias"] + 1):
        d = today + timedelta(days=di)
        ds = fmt(d)
        reservadas = otb.get(ds, 0)
        disponibles = config.TOTAL_UNITS - reservadas

        es_gap = disponibles >= cfg["min_disponibles"]
        es_critico = disponibles >= cfg["gap_critico_disponibles"] and di <= cfg["gap_critico_dias"]
        if es_critico:
            es_gap = True

        if es_gap:
            if not bloque:
                bloque = {"desde": ds, "hasta": ds, "diasOut": di, "fechas": [ds],
                          "maxDisp": disponibles, "critico": es_critico}
            else:
                bloque["hasta"] = ds
                bloque["fechas"].append(ds)
                bloque["maxDisp"] = max(bloque["maxDisp"], disponibles)
                if es_critico:
                    bloque["critico"] = True
        else:
            if bloque:
                alertas.append(_format_gap(bloque))
                bloque = None

    if bloque:
        alertas.append(_format_gap(bloque))

    return alertas


def _format_gap(bloque):
    noches = len(bloque["fechas"])
    nivel = "CRITICO" if bloque["critico"] else "WARNING"
    return {
        "tipo": "GAP_URGENTE",
        "nivel": nivel,
        "emoji": "🔴" if nivel == "CRITICO" else "⚠️",
        "titulo": f"{'🔴 GAP CRÍTICO' if nivel == 'CRITICO' else '⚠️ Gap urgente'} — {bloque['desde']}",
        "detalle": f"{bloque['desde']} → {bloque['hasta']} ({noches}n) — {bloque['maxDisp']}/{config.TOTAL_UNITS} libres, {bloque['diasOut']}d vista",
    }


def _detect_pickup_muerto(otb, pickup_data, cfg):
    alertas = []
    today = date.today()

    for semana in range(cfg["horizonte_semanas"]):
        inicio = cfg["min_dias_futuro"] + semana * 7
        pickup_total = 0
        occ_semana = 0
        dias_datos = 0
        fecha_inicio = None

        for di in range(inicio, inicio + 7):
            d = today + timedelta(days=di)
            ds = fmt(d)
            if not fecha_inicio:
                fecha_inicio = ds

            otb_hoy = otb.get(ds, 0)
            if ds in pickup_data:
                pickup_total += pickup_data[ds]
                dias_datos += 1
            occ_semana += otb_hoy / config.TOTAL_UNITS

        if dias_datos < 4:
            continue

        occ_media = occ_semana / 7
        if pickup_total < cfg["pickup_minimo"] and occ_media < cfg["occ_threshold"]:
            nivel = "CRITICO" if occ_media < 0.40 else "WARNING"
            alertas.append({
                "tipo": "PICKUP_MUERTO",
                "nivel": nivel,
                "emoji": "🔴" if nivel == "CRITICO" else "🟡",
                "titulo": f"Pickup muerto — Semana {fecha_inicio}",
                "detalle": f"Pickup 7d: {pickup_total} reservas · Occ media: {round(occ_media*100)}% · {inicio}d vista",
            })

    return alertas
