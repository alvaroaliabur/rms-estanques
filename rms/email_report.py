"""
Email reports — Daily and error emails via SMTP.
Replaces: enviarEmailDiario_ from GAS.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date
from rms import config
from rms.utils import fmt

log = logging.getLogger(__name__)

ADR_2025 = {1: 66, 2: 76, 3: 80, 4: 114, 5: 131, 6: 185, 7: 272, 8: 312, 9: 189, 10: 137, 11: 80, 12: 126}
MONTH_NAMES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def send_daily_email(results):
    """Send daily pricing summary email."""
    if not config.ALERT_EMAIL or not results:
        return

    today = date.today()
    today_str = fmt(today)

    # OTB by month
    otb_por_mes = {}
    alertas_fechas = []

    for i, r in enumerate(results):
        mes_key = r["date"][:7]
        month = int(r["date"][5:7])
        if mes_key not in otb_por_mes:
            otb_por_mes[mes_key] = {"reservadas": 0, "dias": 0, "sumPrecio": 0, "mes": month, "suelos": 0}
        om = otb_por_mes[mes_key]
        om["reservadas"] += r.get("reservadas", 0)
        om["dias"] += 1
        om["sumPrecio"] += r.get("precioFinal", 0)
        if r.get("clampedBy") == "SUELO":
            om["suelos"] += 1

        # Alert: near dates with low occupancy
        disp = r.get("disponibles", 0)
        if disp >= 6 and i <= 14:
            alertas_fechas.append({"fecha": r["date"], "disp": disp, "daysOut": i, "precio": r["precioFinal"]})

    # Build HTML
    html = f'<div style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto">'
    html += f'<h1 style="color:#1a1a2e;border-bottom:3px solid #333;padding-bottom:8px">📊 Informe Diario RMS v7</h1>'
    html += f'<p style="color:#888;font-size:13px">{today_str} · Python Edition</p>'

    # OTB table
    html += '<h2 style="font-size:15px">🏨 Ocupación y pricing por mes</h2>'
    html += '<table style="border-collapse:collapse;width:100%;font-size:12px">'
    html += '<tr style="background:#2c3e50;color:#fff"><th style="padding:6px">Mes</th><th style="padding:6px;text-align:right">Occ%</th><th style="padding:6px;text-align:right">ADR pub.</th><th style="padding:6px;text-align:right">Genius</th><th style="padding:6px;text-align:right">vs 2025</th></tr>'

    for m_key in sorted(otb_por_mes.keys()):
        om = otb_por_mes[m_key]
        occ = round(om["reservadas"] / (om["dias"] * config.TOTAL_UNITS) * 100) if om["dias"] > 0 else 0
        adr = round(om["sumPrecio"] / om["dias"]) if om["dias"] > 0 else 0
        genius = round(adr * 0.85)
        adr25 = ADR_2025.get(om["mes"], 0)
        vs25 = round((genius - adr25) / adr25 * 100) if adr25 > 0 else 0

        bg = "#d4edda" if occ >= 70 else "#fff3cd" if occ >= 20 else "#fff"
        html += f'<tr style="background:{bg}"><td style="padding:5px 6px;font-weight:bold">{MONTH_NAMES[om["mes"]-1]}</td>'
        html += f'<td style="padding:5px 6px;text-align:right">{occ}%</td>'
        html += f'<td style="padding:5px 6px;text-align:right">{adr}€</td>'
        html += f'<td style="padding:5px 6px;text-align:right">{genius}€</td>'
        color = "#28a745" if vs25 >= 0 else "#dc3545"
        html += f'<td style="padding:5px 6px;text-align:right;color:{color}">{"+" if vs25>=0 else ""}{vs25}%</td></tr>'

    html += '</table>'

    # Alerts
    if alertas_fechas:
        html += '<h2 style="color:#dc3545;font-size:15px;margin-top:20px">🚨 Fechas próximas con baja ocupación</h2>'
        html += '<div style="background:#fff3cd;padding:12px;border-radius:8px;font-size:13px">'
        for af in alertas_fechas:
            html += f'<p style="margin:3px 0">📅 <strong>{af["fecha"]}</strong> — {af["disp"]}/9 libres, {af["daysOut"]}d vista, {af["precio"]}€</p>'
        html += '</div>'

    # Next 14 days
    html += '<h2 style="font-size:15px;margin-top:20px">📅 Próximos 14 días</h2>'
    html += '<table style="border-collapse:collapse;width:100%;font-size:11px">'
    html += '<tr style="background:#2c3e50;color:#fff"><th style="padding:5px">Fecha</th><th style="padding:5px">Temp</th><th style="padding:5px;text-align:right">Disp</th><th style="padding:5px;text-align:right">Precio</th><th style="padding:5px;text-align:right">Genius</th><th style="padding:5px">Notas</th></tr>'

    for r in results[:14]:
        precio = r["precioFinal"]
        genius = round(precio * 0.85)
        disp = r.get("disponibles", 0)
        notas = []
        if r.get("eventName"):
            notas.append(f"🎯{str(r['eventName'])[:15]}")
        if r.get("clampedBy") == "SUELO":
            notas.append("SUELO")
        if r.get("isWeekend"):
            notas.append("WE")

        bg = "#fff3cd" if disp >= 7 else "#d4edda" if disp <= 2 else "#fff"
        html += f'<tr style="background:{bg}"><td style="padding:4px 5px">{r["date"]}</td>'
        html += f'<td style="padding:4px 5px">{r["seasonCode"]}</td>'
        html += f'<td style="padding:4px 5px;text-align:right">{disp}</td>'
        html += f'<td style="padding:4px 5px;text-align:right;font-weight:bold">{precio}€</td>'
        html += f'<td style="padding:4px 5px;text-align:right;color:#888">{genius}€</td>'
        html += f'<td style="padding:4px 5px;font-size:10px">{" ".join(notas)}</td></tr>'

    html += '</table>'
    html += f'<div style="margin-top:20px;padding-top:12px;border-top:1px solid #ddd;color:#999;font-size:11px">'
    html += f'RMS Estanques v7 Python · {today_str}</div></div>'

    # Subject
    subject = f"📊 RMS v7 — "
    if alertas_fechas:
        subject += f"⚠️ {len(alertas_fechas)} fechas baja occ"
    else:
        subject += "✅ Todo estable"

    _send_html_email(subject, html)


def send_error_email(msg):
    """Send error notification."""
    _send_html_email(
        f"❌ RMS Estanques — Error",
        f'<div style="font-family:Arial;max-width:600px"><h2 style="color:#dc3545">❌ Error RMS</h2><pre>{msg}</pre></div>',
    )


def _send_html_email(subject, html_body):
    """Send HTML email via SMTP."""
    if not config.SMTP_PASSWORD:
        log.warning("  No SMTP_PASSWORD configured — email not sent")
        log.info(f"  Subject would be: {subject}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.SMTP_USER
    msg["To"] = config.ALERT_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)
        log.info(f"  📧 Email enviado: {subject}")
    except Exception as e:
        log.error(f"  ⚠️ Error email: {e}")
