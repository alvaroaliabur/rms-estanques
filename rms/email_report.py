"""
Email Report — SMTP email sending for daily/weekly reports
v7.1: Full implementation with Gmail SMTP

SETUP:
1. Go to Google Account → Security → 2-Step Verification (enable it)
2. Go to Google Account → Security → App passwords
3. Generate a new app password for "Mail" / "Other (RMS)"
4. Copy the 16-character password
5. In Railway Variables, add:
   SMTP_USER=alvaro.estanques@gmail.com
   SMTP_PASSWORD=xxxx xxxx xxxx xxxx  (the app password)

The module sends:
- Daily summary: prices applied, anomalies, warnings
- Weekly summary: revenue tracker, comp set update, Capa A status
"""

import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date
from rms import config

log = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.getenv("SMTP_USER", config.ALERT_EMAIL)
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
TO_EMAIL = config.ALERT_EMAIL


def send_email(subject, html_body):
    """Send an HTML email via Gmail SMTP."""
    if not SMTP_PASSWORD:
        log.warning(f"  No SMTP_PASSWORD configured — email not sent")
        log.info(f"  Subject would be: {subject}")
        return False
    
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = TO_EMAIL
        msg.attach(MIMEText(html_body, "html"))
        
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        
        log.info(f"  ✅ Email enviado: {subject}")
        return True
    except Exception as e:
        log.warning(f"  ❌ Email error: {e}")
        return False


def enviar_email_diario(results, audit, alerts, claude_analysis=None):
    """
    Send daily pricing summary email.
    
    Includes:
    - Pricing stats (avg, min, max, days at floor/ceiling)
    - Top changes vs yesterday
    - Anomalies and warnings  
    - Claude analysis summary (if available)
    - Revenue tracker snapshot
    """
    today = date.today()
    
    # Calculate stats
    precios = [r["precioFinal"] for r in results if r.get("precioFinal")]
    avg_price = round(sum(precios) / len(precios)) if precios else 0
    min_price = min(precios) if precios else 0
    max_price = max(precios) if precios else 0
    
    dias_suelo = sum(1 for r in results if r.get("clampedBy") == "SUELO")
    dias_techo = sum(1 for r in results if r.get("clampedBy") == "TECHO")
    dias_unc = sum(1 for r in results if r.get("uncUplift", 1.0) > 1.0)
    
    # Status emoji
    if not audit.get("ok"):
        status = "❌ Errores detectados"
        status_color = "#e74c3c"
    elif audit.get("warnings"):
        status = "⚠️ Con avisos"
        status_color = "#f39c12"
    else:
        status = "✅ Todo estable"
        status_color = "#27ae60"
    
    subject = f"📊 RMS v7 — {status}"
    
    # Build HTML
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: {status_color}; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
            <h1 style="margin: 0; font-size: 20px;">{status}</h1>
            <p style="margin: 5px 0 0 0; opacity: 0.9;">{today.isoformat()} — RMS Estanques v7 Python</p>
        </div>
        
        <div style="background: #f8f9fa; padding: 20px;">
            <h2 style="margin: 0 0 15px 0; font-size: 16px; color: #333;">📈 Resumen de Precios</h2>
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Precio medio</strong></td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">{avg_price}€</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Rango</strong></td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">{min_price}€ — {max_price}€</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Días en suelo</strong></td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">{dias_suelo}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Días en techo</strong></td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">{dias_techo}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Demanda no restringida</strong></td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">{dias_unc} fechas con uplift</td>
                </tr>
            </table>
        </div>
    """
    
    # Key dates (next 14 days with low availability)
    urgent = [r for r in results if r.get("daysOut", 999) <= 14 and r.get("disponibles", 9) <= 3]
    if urgent:
        html += """
        <div style="background: white; padding: 20px; border-top: 1px solid #eee;">
            <h2 style="margin: 0 0 15px 0; font-size: 16px; color: #333;">🔥 Próximos 14 días — Baja disponibilidad</h2>
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <tr style="background: #f0f0f0;">
                    <th style="padding: 6px; text-align: left;">Fecha</th>
                    <th style="padding: 6px; text-align: center;">Disp</th>
                    <th style="padding: 6px; text-align: right;">Precio</th>
                    <th style="padding: 6px; text-align: right;">Genius</th>
                </tr>
        """
        for r in urgent[:10]:
            html += f"""
                <tr>
                    <td style="padding: 6px;">{r['date']}</td>
                    <td style="padding: 6px; text-align: center; color: {'#e74c3c' if r['disponibles'] <= 1 else '#f39c12'};">{r['disponibles']}</td>
                    <td style="padding: 6px; text-align: right;"><strong>{r['precioFinal']}€</strong></td>
                    <td style="padding: 6px; text-align: right;">{r['precioGenius']}€</td>
                </tr>
            """
        html += "</table></div>"
    
    # Claude analysis
    if claude_analysis:
        html += f"""
        <div style="background: #f0f4ff; padding: 20px; border-top: 1px solid #eee;">
            <h2 style="margin: 0 0 10px 0; font-size: 16px; color: #1a56db;">🧠 Análisis Claude</h2>
            <p style="font-size: 14px; color: #333; margin: 0;">{claude_analysis.get('analysis', 'Sin análisis')}</p>
            <p style="font-size: 13px; color: #666; margin: 10px 0 0 0;">
                Ajustes: {claude_analysis.get('adjustments_count', 0)} | 
                Impacto estimado: {claude_analysis.get('estimated_impact', 'N/A')}
            </p>
        </div>
        """
    
    # Warnings
    if audit.get("warnings"):
        html += """
        <div style="background: #fff8e1; padding: 20px; border-top: 1px solid #eee;">
            <h2 style="margin: 0 0 10px 0; font-size: 16px; color: #f57f17;">⚠️ Avisos</h2>
        """
        for w in audit["warnings"]:
            html += f'<p style="font-size: 14px; margin: 5px 0;">• {w}</p>'
        html += "</div>"
    
    # Alerts (errors)
    if audit.get("alertas"):
        html += """
        <div style="background: #fce4ec; padding: 20px; border-top: 1px solid #eee;">
            <h2 style="margin: 0 0 10px 0; font-size: 16px; color: #c62828;">❌ Alertas</h2>
        """
        for a in audit["alertas"]:
            html += f'<p style="font-size: 14px; margin: 5px 0;">• {a}</p>'
        html += "</div>"
    
    html += """
        <div style="padding: 15px; text-align: center; color: #999; font-size: 12px;">
            RMS Estanques v7 Python — Railway
        </div>
    </div>
    """
    
    return send_email(subject, html)
