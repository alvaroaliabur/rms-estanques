"""
RMS Estanques v7 — Main Entry Point
====================================
Two modes:
  1. CRON: Railway runs this daily at 05:00 UTC → full pricing run
  2. WEBHOOK: Beds24 sends POST on booking/cancellation → instant repricing

If PORT env var is set, runs as a web server (webhook mode).
If not, runs the cron job and exits.
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
# FULL PRICING RUN (cron job)
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
    """Quick repricing triggered by Beds24 webhook.
    Only recalculates affected dates, not all 365."""
    start = datetime.now()
    from rms import config

    if config.DRY_RUN:
        log.info("  🔒 DRY RUN — webhook repricing skipped")
        return {"status": "dry_run"}

    log.info("── WEBHOOK REPRICING ──")

    # Extract affected dates from webhook
    arrival = webhook_data.get("arrival", "")
    departure = webhook_data.get("departure", "")
    booking_id = webhook_data.get("id", "unknown")
    status = webhook_data.get("status", "")

    if not arrival or not departure:
        log.warning(f"  Webhook sin fechas: booking {booking_id}")
        return {"status": "no_dates"}

    log.info(f"  Booking {booking_id}: {arrival} → {departure} (status: {status})")

    # Calculate date range to reprice (affected dates + 3 days buffer)
    from rms.utils import parse_date, fmt, add_days
    ci = parse_date(arrival)
    co = parse_date(departure)
    range_start = add_days(ci, -3)  # 3 days before check-in
    range_end = add_days(co, 3)     # 3 days after check-out
    today = date.today()
    if range_start < today:
        range_start = today

    # Full data load (quick — takes ~2 seconds)
    from rms.otb import read_otb
    from rms.capa_a import cargar_capa_a
    from rms.events import build_events
    from rms.pricing import calcular_precios_v7

    otb = read_otb()
    cargar_capa_a()
    events = build_events()

    # Calculate all prices (the engine is fast, 365 days in <1s)
    results = calcular_precios_v7(otb, events)

    # Filter to only affected dates
    affected = [r for r in results
                if range_start <= parse_date(r["date"]) <= range_end]

    if not affected:
        log.info("  No hay fechas afectadas en el horizonte")
        return {"status": "no_affected_dates"}

    # Apply only affected dates
    from rms.apply import aplicar_precios
    aplicar_precios(affected)

    elapsed = (datetime.now() - start).total_seconds()
    log.info(f"  ✅ Repricing: {len(affected)} fechas actualizadas en {elapsed:.1f}s")

    return {
        "status": "ok",
        "booking_id": booking_id,
        "dates_updated": len(affected),
        "range": f"{fmt(range_start)} → {fmt(range_end)}",
        "elapsed_seconds": round(elapsed, 1),
    }


# ══════════════════════════════════════════
# WEB SERVER (for webhook reception)
# ══════════════════════════════════════════

def start_server():
    """Start Flask web server to receive Beds24 webhooks."""
    from flask import Flask, request, jsonify

    app = Flask(__name__)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "service": "RMS Estanques v7"})

    @app.route("/webhook/booking", methods=["POST"])
    def webhook_booking():
        """Receive Beds24 booking webhook and trigger repricing."""
        try:
            data = request.get_json(force=True, silent=True)
            if not data:
                data = {}

            # Beds24 can send an array or a single object
            if isinstance(data, list):
                data = data[0] if data else {}

            log.info(f"📨 Webhook recibido: booking {data.get('id', '?')}")

            result = run_repricing(data)
            return jsonify(result), 200

        except Exception as e:
            log.error(f"❌ Webhook error: {e}")
            log.error(traceback.format_exc())
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/run", methods=["POST"])
    def manual_run():
        """Manual trigger for full pricing run (for testing)."""
        try:
            success = run_full()
            return jsonify({"status": "ok" if success else "failed"}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    port = int(os.getenv("PORT", 8080))
    log.info(f"🌐 Servidor webhook arrancado en puerto {port}")
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
    # If PORT is set, run as web server (webhook mode)
    # If not, run cron job and exit
    if os.getenv("PORT"):
        start_server()
    else:
        try:
            success = run_full()
            sys.exit(0 if success else 1)
        except Exception as e:
            log.error(f"❌ Error fatal: {e}")
            log.error(traceback.format_exc())
            _send_error_email(f"Error fatal: {e}\n\n{traceback.format_exc()}")
            sys.exit(1)
