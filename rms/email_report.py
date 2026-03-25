"""
Email Report — v7.4
CAMBIOS:
  - Email mensual día 1: solicita datos de Booking Analytics
  - Formato exacto de lo que copiar/pegar desde el portal BDC
  - Los datos se actualizan en config.BOOKING_ANALYTICS via /update endpoint
"""

import os
import logging
import requests
from datetime import date
from rms import config

log = logging.getLogger(__name__)

MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN", "")
TO_EMAIL = config.ALERT_EMAIL

_last_email = {"subject": "", "html": "", "sent": False}


def send_email(subject, html_body):
    global _last_email
    _last_email = {"subject": subject, "html": html_body, "sent": False}

    if MAILGUN_API_KEY and MAILGUN_DOMAIN:
        try:
            resp = requests.post(
                f"https://api.eu.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
                auth=("api", MAILGUN_API_KEY),
                data={
                    "from": f"RMS Estanques <rms@{MAILGUN_DOMAIN}>",
                    "to": [TO_EMAIL],
                    "subject": subject,
                    "html": html_body,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                log.info(f"  ✅ Email enviado: {subject}")
                _last_email["sent"] = True
                return True
            else:
                log.warning(f"  Mailgun error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log.warning(f"  Mailgun error: {e}")

    log.info(f"  📧 Email disponible en /email: {subject}")
    return False


def get_last_email():
    return _last_email


def es_primer_dia_del_mes():
    return date.today().day == 1


def enviar_email_booking_analytics():
    """
    Email mensual (día 1) pidiendo datos de Booking Analytics.
    Formato exacto para copiar/pegar desde el portal BDC.
    """
    today = date.today()
    mes_anterior = today.month - 1 if today.month > 1 else 12
    anyo = today.year if today.month > 1 else today.year - 1
    nombres_meses = {
        1:"Enero", 2:"Febrero", 3:"Marzo", 4:"Abril", 5:"Mayo", 6:"Junio",
        7:"Julio", 8:"Agosto", 9:"Septiembre", 10:"Octubre", 11:"Noviembre", 12:"Diciembre"
    }
    mes_nombre = nombres_meses[mes_anterior]

    # Datos actuales en config para mostrar referencia
    ba = config.BOOKING_ANALYTICS
    meses_verano = [6, 7, 8, 9]

    filas_actuales = ""
    for m in meses_verano:
        d = ba.get(m, {})
        filas_actuales += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #eee;"><strong>{nombres_meses[m]}</strong></td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center">{d.get('our_adr','—')}€</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center">{d.get('ref_adr','—')}€</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center">{d.get('rank_adr','—')}/{d.get('total_props','—')}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center">{d.get('rank_nights','—')}/{d.get('total_props','—')}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;color:#888;font-size:0.85em">{d.get('updated','—')}</td>
        </tr>"""

    railway_url = os.getenv("RAILWAY_PUBLIC_DOMAIN", "rms-estanques-production.up.railway.app")

    subject = f"📊 RMS — Datos Booking Analytics para actualizar ({mes_nombre} {anyo})"

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:650px;margin:0 auto;">

        <div style="background:#1a1a2e;color:white;padding:20px;border-radius:8px 8px 0 0;">
            <h1 style="margin:0;font-size:20px;">📊 Actualización mensual — Booking Analytics</h1>
            <p style="margin:5px 0 0 0;opacity:0.8">{today.strftime('%d %B %Y')} · RMS Estanques v7.4</p>
        </div>

        <div style="background:#f8f9fa;padding:20px;">

            <p style="color:#333">Hola Álvaro,</p>
            <p style="color:#333">Necesito que actualices los datos de Booking Analytics para calibrar correctamente los suelos y el comp set. Son 5 minutos.</p>

            <div style="background:#fff3cd;border-left:4px solid #ffc107;padding:12px 16px;border-radius:4px;margin:16px 0;">
                <strong>¿Por qué es importante?</strong><br>
                Los suelos de precio están calibrados con tu ADR real del mejor año histórico.
                Sin estos datos, el sistema usa valores desactualizados y puede dejar dinero encima de la mesa.
            </div>

            <h2 style="font-size:16px;color:#1a1a2e;margin-top:24px">Datos actuales en el sistema</h2>
            <table style="width:100%;border-collapse:collapse;font-size:14px;">
                <tr style="background:#e9ecef">
                    <th style="padding:8px;text-align:left">Mes</th>
                    <th style="padding:8px;text-align:center">Tu ADR</th>
                    <th style="padding:8px;text-align:center">Ref ADR</th>
                    <th style="padding:8px;text-align:center">Rank ADR</th>
                    <th style="padding:8px;text-align:center">Rank Noches</th>
                    <th style="padding:8px;text-align:center">Actualizado</th>
                </tr>
                {filas_actuales}
            </table>

            <h2 style="font-size:16px;color:#1a1a2e;margin-top:24px">📋 Pasos para actualizar</h2>

            <ol style="color:#333;line-height:1.8">
                <li>Entra en <strong>Booking.com Extranet → Analytics → Comparativa con grupo de referencia</strong></li>
                <li>Anota para <strong>cada mes (Jun, Jul, Ago, Sep)</strong>:
                    <ul>
                        <li>Tu ADR (precio medio de reserva, en €)</li>
                        <li>ADR del grupo de referencia</li>
                        <li>Tu ranking en ADR (ej: 7/26)</li>
                        <li>Tu ranking en noches vendidas (ej: 22/26)</li>
                    </ul>
                </li>
                <li>Responde a este email con los datos en este formato:</li>
            </ol>

            <div style="background:#2d2d2d;color:#f8f8f2;padding:16px;border-radius:6px;font-family:monospace;font-size:13px;margin:16px 0;">
                Jun: mi_adr=XXX ref_adr=XXX rank_adr=X/26 rank_noches=X/26<br>
                Jul: mi_adr=XXX ref_adr=XXX rank_adr=X/26 rank_noches=X/26<br>
                Ago: mi_adr=XXX ref_adr=XXX rank_adr=X/26 rank_noches=X/26<br>
                Sep: mi_adr=XXX ref_adr=XXX rank_adr=X/26 rank_noches=X/26
            </div>

            <p style="color:#666;font-size:0.9em">
                También puedes actualizar directamente en GitHub editando <code>rms/config.py</code> → sección <code>BOOKING_ANALYTICS</code>.
            </p>

            <div style="background:#d4edda;border-left:4px solid #28a745;padding:12px 16px;border-radius:4px;margin:16px 0;">
                <strong>¿Qué cambia cuando actualices?</strong><br>
                El siguiente /run recalibra automáticamente los suelos de precio para los meses de verano
                usando tu ADR real como base. Sin necesidad de tocar nada más.
            </div>

        </div>

        <div style="background:#e9ecef;padding:12px 20px;border-radius:0 0 8px 8px;font-size:0.85em;color:#666">
            RMS Estanques · Colònia de Sant Jordi · 
            <a href="https://{railway_url}/health" style="color:#0f3460">Estado del sistema</a> · 
            <a href="https://{railway_url}/explicacion" style="color:#0f3460">Ver precios</a>
        </div>

    </div>
    """

    return send_email(subject, html)


def enviar_email_diario(results, audit, alerts, claude_analysis=None):
    """Email diario con resumen de precios + alerta si es día 1 del mes."""
    today = date.today()

    # Día 1 del mes: también enviar email de Booking Analytics
    if es_primer_dia_del_mes():
        log.info("  📅 Día 1 del mes — enviando solicitud Booking Analytics")
        enviar_email_booking_analytics()

    # Stats generales
    precios = [r["precioFinal"] for r in results if r.get("precioFinal")]
    avg_price = round(sum(precios) / len(precios)) if precios else 0
    min_price = min(precios) if precios else 0
    max_price = max(precios) if precios else 0

    dias_suelo = sum(1 for r in results if r.get("clampedBy") == "SUELO")
    dias_techo = sum(1 for r in results if r.get("clampedBy") == "TECHO")
    dias_presion = sum(1 for r in results if r.get("presionTemporal"))
    dias_unc = sum(1 for r in results if r.get("uncUplift", 1.0) > 1.0)

    if not audit.get("ok"):
        status = "❌ Errores detectados"
        status_color = "#e74c3c"
    elif audit.get("warnings"):
        status = "⚠️ Con avisos"
        status_color = "#f39c12"
    else:
        status = "✅ Todo estable"
        status_color = "#27ae60"

    subject = f"📊 RMS v7.4 — {status} · {today.isoformat()}"

    # Resumen por mes (próximos 6)
    meses_resumen = {}
    for r in results:
        m = r["date"][:7]
        if m not in meses_resumen:
            meses_resumen[m] = {"n": 0, "rev_otb": 0, "reservadas": 0, "suelos": 0, "presion": 0}
        mm = meses_resumen[m]
        mm["n"] += 1
        mm["reservadas"] += r.get("reservadas", 0)
        mm["rev_otb"] += r.get("reservadas", 0) * r.get("precioFinal", 0) * 0.85  # genius
        if r.get("clampedBy") == "SUELO":
            mm["suelos"] += 1
        if r.get("presionTemporal"):
            mm["presion"] += 1

    filas_meses = ""
    for m in sorted(meses_resumen.keys())[:6]:
        mm = meses_resumen[m]
        occ_pct = round(mm["reservadas"] / (mm["n"] * config.TOTAL_UNITS) * 100)
        rev_k = round(mm["rev_otb"] / 1000, 1)
        suelo_pct = round(mm["suelos"] / mm["n"] * 100) if mm["n"] > 0 else 0
        color_occ = "#27ae60" if occ_pct >= 70 else "#e67e22" if occ_pct >= 40 else "#e74c3c"
        filas_meses += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #eee"><strong>{m}</strong></td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center">
                <span style="color:{color_occ};font-weight:bold">{occ_pct}%</span>
            </td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center">{rev_k}k€</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;color:#888">{suelo_pct}%</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;color:#e67e22">{mm['presion']}d</td>
        </tr>"""

    # Alertas
    alertas_html = ""
    if alerts:
        alertas_html = "<h2 style='font-size:15px;color:#e74c3c'>🚨 Alertas</h2><ul>"
        for a in (alerts or []):
            if isinstance(a, dict):
                alertas_html += f"<li><strong>{a.get('titulo','')}</strong>: {a.get('detalle','')}</li>"
        alertas_html += "</ul>"

    # Próximos 14 días críticos
    urgentes = [r for r in results if r.get("daysOut", 999) <= 14 and r.get("disponibles", 9) <= 3]
    urgentes_html = ""
    if urgentes:
        urgentes_html = """<h2 style='font-size:15px;color:#e67e22'>🔥 Próximos 14 días — baja disponibilidad</h2>
        <table style='width:100%;border-collapse:collapse;font-size:13px'>
        <tr style='background:#f8f9fa'>
            <th style='padding:6px;text-align:left'>Fecha</th>
            <th style='padding:6px;text-align:center'>Disp</th>
            <th style='padding:6px;text-align:center'>Precio</th>
            <th style='padding:6px;text-align:center'>Genius</th>
            <th style='padding:6px;text-align:center'>MinStay</th>
        </tr>"""
        for r in urgentes:
            urgentes_html += f"""
            <tr>
                <td style='padding:6px;border-bottom:1px solid #eee'>{r['date']}</td>
                <td style='padding:6px;border-bottom:1px solid #eee;text-align:center;color:#e74c3c'><strong>{r['disponibles']}</strong></td>
                <td style='padding:6px;border-bottom:1px solid #eee;text-align:center'>{r['precioFinal']}€</td>
                <td style='padding:6px;border-bottom:1px solid #eee;text-align:center'>{r['precioGenius']}€</td>
                <td style='padding:6px;border-bottom:1px solid #eee;text-align:center'>{r.get('minStay','')}n</td>
            </tr>"""
        urgentes_html += "</table>"

    railway_url = os.getenv("RAILWAY_PUBLIC_DOMAIN", "rms-estanques-production.up.railway.app")

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:650px;margin:0 auto;">

        <div style="background:{status_color};color:white;padding:20px;border-radius:8px 8px 0 0;">
            <h1 style="margin:0;font-size:20px;">{status}</h1>
            <p style="margin:5px 0 0 0;opacity:0.9">{today.isoformat()} · RMS Estanques v7.4</p>
        </div>

        <div style="background:#f8f9fa;padding:20px;">

            <h2 style="font-size:15px;color:#333;margin-top:0">📈 Resumen por mes (OTB)</h2>
            <table style="width:100%;border-collapse:collapse;font-size:14px">
                <tr style="background:#e9ecef">
                    <th style="padding:8px;text-align:left">Mes</th>
                    <th style="padding:8px;text-align:center">Occ%</th>
                    <th style="padding:8px;text-align:center">Rev OTB</th>
                    <th style="padding:8px;text-align:center">%Suelo</th>
                    <th style="padding:8px;text-align:center">Presión</th>
                </tr>
                {filas_meses}
            </table>

            <table style="width:100%;border-collapse:collapse;margin-top:16px">
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #ddd"><strong>Precio medio 365d</strong></td>
                    <td style="padding:8px;border-bottom:1px solid #ddd;text-align:right">{avg_price}€ ({round(avg_price*0.85)}€ Genius)</td>
                </tr>
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #ddd"><strong>Rango precios</strong></td>
                    <td style="padding:8px;border-bottom:1px solid #ddd;text-align:right">{min_price}€ — {max_price}€</td>
                </tr>
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #ddd"><strong>Días en suelo / techo</strong></td>
                    <td style="padding:8px;border-bottom:1px solid #ddd;text-align:right">{dias_suelo}d suelo · {dias_techo}d techo</td>
                </tr>
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #ddd"><strong>Presión temporal activa</strong></td>
                    <td style="padding:8px;border-bottom:1px solid #ddd;text-align:right">{dias_presion} fechas bajadas proactivamente</td>
                </tr>
                <tr>
                    <td style="padding:8px"><strong>Uplift demanda no restringida</strong></td>
                    <td style="padding:8px;text-align:right">{dias_unc} fechas</td>
                </tr>
            </table>

            {alertas_html}
            {urgentes_html}

            {'<div style="background:#fff3cd;border-left:4px solid #ffc107;padding:12px 16px;border-radius:4px;margin-top:16px"><strong>⚠️ Auditoría:</strong> ' + ' | '.join(audit.get('alertas', [])) + '</div>' if not audit.get('ok') else ''}

        </div>

        <div style="background:#e9ecef;padding:12px 20px;border-radius:0 0 8px 8px;font-size:0.85em;color:#666">
            RMS Estanques v7.4 · 
            <a href="https://{railway_url}/explicacion" style="color:#0f3460">Ver precios</a> · 
            <a href="https://{railway_url}/prices/compare" style="color:#0f3460">Comparativa</a> · 
            <a href="https://{railway_url}/revenue" style="color:#0f3460">Revenue</a>
        </div>

    </div>
    """

    return send_email(subject, html)
