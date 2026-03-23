"""
RMS Estanques v7 — Main Entry Point
====================================
Runs as a web server with:
  1. CRON: APScheduler runs full pricing daily at 05:00 UTC
  2. WEBHOOK: Beds24 sends POST on booking/cancellation → instant repricing
  3. /health endpoint for monitoring
  4. /run endpoint for manual trigger
"""

import sys
import os
import logging
import traceback
import json
from datetime import datetime, date, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("RMS")


# ══════════════════════════════════════════
# FULL PRICING RUN (daily cron)
# ══════════════════════════════════════════

def run_full():
    """Full RMS execution — replaces paso1 + paso2 + paso3 from GAS."""
    start = datetime.now()
    log.info("══════════════════════════════════════════")
    log.info("  RMS ESTANQUES v7 — Full Pricing Run")
    log.info(f"  {start.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("══════════════════════════════════════════")

    from rms import config

    # Step 1: Verify connection
    log.info("\n── STEP 1: Conectar Beds24 ──")
    from rms.beds24 import api_get
    try:
        api_get("bookings", {"limit": 1})
        log.info("  ✅ Beds24 conectado")
    except Exception as e:
        log.error(f"  ❌ Beds24 no responde: {e}")
        _send_error_email(f"Beds24 no responde: {e}")
        return False

    # Step 2: Load data
    log.info("\n── STEP 2: Cargar datos ──")
    from rms.otb import read_otb, save_otb_snapshot
    from rms.capa_a import cargar_capa_a
    from rms.events import build_events

    otb = read_otb()
    save_otb_snapshot(otb)
    log.info(f"  ✅ OTB: {len(otb)} fechas")

    cargar_capa_a()
    events = build_events()
    log.info(f"  ✅ {len(events)} eventos cargados")

    # Step 3: Calculate prices
    log.info("\n── STEP 3: Calcular precios v7 ──")
    from rms.pricing import calcular_precios_v7
    results = calcular_precios_v7(otb, events)
    log.info(f"  ✅ {len(results)} días calculados")

    # Step 4: Audit
    log.info("\n── STEP 4: Auditar ──")
    audit = _audit(results)
    if not audit["ok"]:
        log.error(f"  ❌ Auditoría FALLIDA: {audit['alertas']}")
        _send_error_email(f"Auditoría FALLIDA:\n" + "\n".join(audit["alertas"]))
        return False
    log.info("  ✅ Auditoría OK")
    for w in audit["warnings"]:
        log.warning(f"  ⚠️ {w}")

    # Step 5: Apply prices
    log.info("\n── STEP 5: Aplicar precios ──")
    if config.DRY_RUN:
        log.info("  🔒 DRY RUN — precios NO aplicados")
    else:
        from rms.apply import aplicar_precios
        aplicar_precios(results)
        log.info("  ✅ Precios aplicados en Beds24")

    # Step 6: Alerts
    log.info("\n── STEP 6: Alertas ──")
    try:
        from rms.alerts import run_alerts
        run_alerts(otb)
    except Exception as e:
        log.warning(f"  ⚠️ Alertas: {e}")

    # Step 7: Daily email
    log.info("\n── STEP 7: Email diario ──")
    try:
        from rms.email_report import send_daily_email
        send_daily_email(results)
    except Exception as e:
        log.warning(f"  ⚠️ Email diario: {e}")

    elapsed = (datetime.now() - start).total_seconds()
    log.info(f"\n✅ RMS completado en {elapsed:.1f}s")
    return True


# ══════════════════════════════════════════
# WEBHOOK REPRICING (instant, on booking change)
# ══════════════════════════════════════════

def run_repricing(webhook_data):
    """Quick repricing triggered by Beds24 webhook."""
    start = datetime.now()
    from rms import config

    if config.DRY_RUN:
        log.info("  🔒 DRY RUN — webhook repricing skipped")
        return {"status": "dry_run"}

    log.info("── WEBHOOK REPRICING ──")

    # V1 webhooks don't include booking data in body
    # We just recalculate everything — it's fast (12 seconds)
    booking_id = webhook_data.get("id", "unknown") if webhook_data else "unknown"
    log.info(f"  Trigger: booking {booking_id}")

    from rms.otb import read_otb
    from rms.capa_a import cargar_capa_a
    from rms.events import build_events
    from rms.pricing import calcular_precios_v7
    from rms.apply import aplicar_precios

    otb = read_otb()
    cargar_capa_a()
    events = build_events()
    results = calcular_precios_v7(otb, events)

    audit = _audit(results)
    if not audit["ok"]:
        log.error(f"  ❌ Repricing audit failed: {audit['alertas']}")
        return {"status": "audit_failed", "alertas": audit["alertas"]}

    aplicar_precios(results)

    elapsed = (datetime.now() - start).total_seconds()
    log.info(f"  ✅ Repricing: {len(results)} fechas en {elapsed:.1f}s")

    return {
        "status": "ok",
        "dates_updated": len(results),
        "elapsed_seconds": round(elapsed, 1),
    }


# ══════════════════════════════════════════
# WEB SERVER + SCHEDULER
# ══════════════════════════════════════════

def start_server():
    """Start Flask web server with APScheduler for daily cron."""
    from flask import Flask, request, jsonify
    from apscheduler.schedulers.background import BackgroundScheduler

    app = Flask(__name__)

    # ── Scheduler: daily full run at 05:00 UTC ──
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_full, "cron", hour=5, minute=0, id="daily_pricing")
    scheduler.start()
    log.info("⏰ Scheduler: daily full run at 05:00 UTC")

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "status": "ok",
            "service": "RMS Estanques v7",
            "next_run": str(scheduler.get_job("daily_pricing").next_run_time),
        })

    @app.route("/webhook/booking", methods=["POST", "GET"])
    def webhook_booking():
        """Receive Beds24 booking webhook and trigger repricing."""
        try:
            data = {}
            if request.method == "POST":
                data = request.get_json(force=True, silent=True) or {}
                if isinstance(data, list):
                    data = data[0] if data else {}

            log.info(f"📨 Webhook recibido: booking {data.get('id', '?')}")
            result = run_repricing(data)
            return jsonify(result), 200

        except Exception as e:
            log.error(f"❌ Webhook error: {e}")
            log.error(traceback.format_exc())
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/run", methods=["POST", "GET"])
    def manual_run():
        """Manual trigger for full pricing run."""
        try:
            success = run_full()
            return jsonify({"status": "ok" if success else "failed"}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    port = int(os.getenv("PORT", 8080))
    log.info(f"🌐 Servidor arrancado en puerto {port}")
    app.run(host="0.0.0.0", port=port)


# ══════════════════════════════════════════
# AUDIT
# ══════════════════════════════════════════

def _audit(results):
    alertas = []
    warnings = []

    if not results or len(results) < 30:
        alertas.append(f"Solo {len(results) if results else 0} días calculados")
        return {"ok": False, "alertas": alertas, "warnings": warnings}

    dias_suelo = 0
    dias_techo = 0
    for r in results:
        pf = r.get("precioFinal", 0)
        if not pf or pf < 35:
            alertas.append(f"Precio muy bajo: {r['date']} → {pf}€")
        elif pf > 2000:
            alertas.append(f"Precio muy alto: {r['date']} → {pf}€")

        ms = r.get("minStay", 0)
        if not ms or ms < 1 or ms > 14:
            alertas.append(f"MinStay inválido: {r['date']} → {ms}")

        month = int(r["date"][5:7])
        if month == 7 and pf < 200:
            alertas.append(f"Julio precio muy bajo: {r['date']} → {pf}€")
        if month == 8 and pf < 220:
            alertas.append(f"Agosto precio muy bajo: {r['date']} → {pf}€")

        if r.get("clampedBy") == "SUELO":
            dias_suelo += 1
        if r.get("clampedBy") == "TECHO":
            dias_techo += 1

    if dias_suelo > 60:
        warnings.append(f"{dias_suelo} días limitados por SUELO")
    if dias_techo > 20:
        warnings.append(f"{dias_techo} días limitados por TECHO")

    return {"ok": len(alertas) == 0, "alertas": alertas, "warnings": warnings}


def _send_error_email(msg):
    try:
        from rms.email_report import send_error_email
        send_error_email(msg)
    except Exception as e:
        log.error(f"  No se pudo enviar email de error: {e}")


# ══════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════

if __name__ == "__main__":
    start_server()
