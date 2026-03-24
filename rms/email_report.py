"""
Email Report — Daily/weekly reports via Gmail API (OAuth2)
v7.1: Uses Gmail API via HTTP instead of SMTP (Railway blocks SMTP ports)

APPROACH:
Since Railway blocks SMTP (port 587), we use a different strategy:
1. PRIMARY: Send via Mailgun/SendGrid free tier (HTTP API, no SMTP needed)
2. FALLBACK: Log the email content and make it available via /email endpoint

For simplicity and zero external dependencies, we use Python's built-in
email capabilities with a free transactional email service.

SETUP (Mailgun free tier - 1000 emails/month):
1. Sign up at mailgun.com (free)
2. Add and verify your domain or use sandbox
3. Get API key
4. Add to Railway: MAILGUN_API_KEY, MAILGUN_DOMAIN

OR simply use the /email endpoint to view the last report in the browser.
"""

import os
import logging
import requests
from datetime import date
from rms import config

log = logging.getLogger(__name__)

# Mailgun config (free tier: 1000 emails/month)
MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN", "")
TO_EMAIL = config.ALERT_EMAIL

# Store last email for /email endpoint
_last_email = {"subject": "", "html": "", "sent": False}


def send_email(subject, html_body):
    """Send an HTML email. Try Mailgun first, fall back to logging."""
    global _last_email
    _last_email = {"subject": subject, "html": html_body, "sent": False}
    
    # Try Mailgun
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
                log.info(f"  ✅ Email enviado via Mailgun: {subject}")
                _last_email["sent"] = True
                return True
            else:
                log.warning(f"  Mailgun error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log.warning(f"  Mailgun error: {e}")
    
    # Fallback: just log and store for /email endpoint
    log.info(f"  📧 Email disponible en /email endpoint: {subject}")
    return False


def get_last_email():
    """Return the last email for the /email endpoint."""
    return _last_email


def enviar_email_diario(results, audit, alerts, claude_analysis=None):
    """Send daily pricing summary email."""
    today = date.today()
    
    # Calculate stats
    precios = [r["precioFinal"] for r in results if r.get("precioFinal")]
    avg_price = round(sum(precios) / len(precios)) if precios else 0
    min_price = min(precios) if precios else 0
    max_price = max(precios) if precios else 0
    
    dias_suelo = sum(1 for r in results if r.get("clampedBy") == "SUELO")
    dias_techo = sum(1 for r in results if r.get("clampedBy") == "TECHO")
    dias_unc = sum(1 for r in results if r.get("uncUplift", 1.0) > 1.0)
    
    # Status
    if not audit.get("ok"):
        status = "❌ Errores detectados"
        status_color = "#e74c3c"
    elif audit.get("warnings"):
        status = "⚠️ Con avisos"
        status_color = "#f39c12"
    else:
        status = "✅ Todo estable"
        status_color = "#27ae60"
    
    subject = f"📊 RMS v7.1 — {status}"
    
    # Build HTML
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 650px; margin: 0 auto;">
        <div style="background: {status_color}; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
            <h1 style="margin: 0; font-size: 20px;">{status}</h1>
            <p style="margin: 5px 0 0 0; opacity: 0.9;">{today.isoformat()} — RMS Estanques v7.1 Python/Railway</p>
        </div>
        
        <div style="background: #f8f9fa; padding: 20px;">
            <h2 style="margin: 0 0 15px 0; font-size: 16px; color: #333;">📈 Resumen de Precios ({len(results)} días)</h2>
            <table style="width: 100%; border-collapse: collapse;">
                <tr><td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Precio medio</strong></td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">{avg_price}€</td></tr>
                <tr><td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Rango</strong></td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">{min_price}€ — {max_price}€</td></tr>
                <tr><td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Días en suelo</strong></td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">{dias_suelo}</td></tr>
                <tr><td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Días en techo</strong></td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">{dias_techo}</td></tr>
                <tr><td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Uplift demanda no restringida</strong></td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">{dias_unc} fechas</td></tr>
            </table>
        </div>
    """
    
    # Key dates: next 14 days with low availability
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
            color = '#e74c3c' if r['disponibles'] <= 1 else '#f39c12'
            html += f"""
                <tr>
                    <td style="padding: 6px;">{r['date']}</td>
                    <td style="padding: 6px; text-align: center; color: {color};"><strong>{r['disponibles']}</strong></td>
                    <td style="padding: 6px; text-align: right;"><strong>{r['precioFinal']}€</strong></td>
                    <td style="padding: 6px; text-align: right;">{r['precioGenius']}€</td>
                </tr>
            """
        html += "</table></div>"
    
    # July-August snapshot
    jul_aug = [r for r in results if r["date"][:7] in (f"{today.year}-07", f"{today.year}-08") and r["date"] <= f"{today.year}-08-15"]
    if jul_aug:
        html += """
        <div style="background: #fff9e6; padding: 20px; border-top: 1px solid #eee;">
            <h2 style="margin: 0 0 15px 0; font-size: 16px; color: #333;">☀️ Julio-Agosto (hasta 15 ago)</h2>
            <table style="width: 100%; border-collapse: collapse; font-size: 12px;">
                <tr style="background: #f0f0f0;">
                    <th style="padding: 5px; text-align: left;">Fecha</th>
                    <th style="padding: 5px; text-align: center;">Disp</th>
                    <th style="padding: 5px; text-align: right;">Pub</th>
                    <th style="padding: 5px; text-align: right;">Genius</th>
                    <th style="padding: 5px; text-align: center;">MinSt</th>
                </tr>
        """
        for r in jul_aug:
            bg = "#ffeaea" if r["disponibles"] <= 1 else ("#fff3cd" if r["disponibles"] <= 3 else "")
            html += f"""
                <tr style="background: {bg};">
                    <td style="padding: 5px;">{r['date']}</td>
                    <td style="padding: 5px; text-align: center;">{r['disponibles']}</td>
                    <td style="padding: 5px; text-align: right;"><strong>{r['precioFinal']}€</strong></td>
                    <td style="padding: 5px; text-align: right;">{r['precioGenius']}€</td>
                    <td style="padding: 5px; text-align: center;">{r['minStay']}</td>
                </tr>
            """
        html += "</table></div>"
    
    # Claude analysis
    if claude_analysis and isinstance(claude_analysis, dict):
        analysis_text = claude_analysis.get('analysis', '')
        adj_count = claude_analysis.get('adjustments_count', 0)
        impact = claude_analysis.get('estimated_impact', 'N/A')
        if analysis_text:
            html += f"""
            <div style="background: #f0f4ff; padding: 20px; border-top: 1px solid #eee;">
                <h2 style="margin: 0 0 10px 0; font-size: 16px; color: #1a56db;">🧠 Análisis Claude</h2>
                <p style="font-size: 14px; color: #333; margin: 0;">{analysis_text}</p>
                <p style="font-size: 13px; color: #666; margin: 10px 0 0 0;">
                    Ajustes: {adj_count} | Impacto estimado: {impact}
                </p>
            </div>
            """
    
    # Warnings
    if audit.get("warnings"):
        html += '<div style="background: #fff8e1; padding: 20px; border-top: 1px solid #eee;">'
        html += '<h2 style="margin: 0 0 10px 0; font-size: 16px; color: #f57f17;">⚠️ Avisos</h2>'
        for w in audit["warnings"]:
            html += f'<p style="font-size: 14px; margin: 5px 0;">• {w}</p>'
        html += "</div>"
    
    # Footer
    html += """
        <div style="padding: 15px; text-align: center; color: #999; font-size: 12px; border-top: 1px solid #eee;">
            RMS Estanques v7.1 Python/Railway — <a href="https://rms-estanques-production.up.railway.app/email">Ver online</a>
        </div>
    </div>
    """
    
    return send_email(subject, html)
