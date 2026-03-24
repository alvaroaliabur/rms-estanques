"""
RMS Estanques v7 — Main Entry Point
====================================
Runs as a web server with:
  1. CRON: APScheduler runs full pricing daily at 05:00 UTC
  2. WEBHOOK: Beds24 sends POST on booking/cancellation → instant repricing
  3. /health endpoint for monitoring
  4. /run endpoint for manual trigger
  5. /prices endpoint to view calculated prices
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

# Store last results in memory for /prices endpoint
_last_results = None
_last_run_time = None


# ══════════════════════════════════════════
# FULL PRICING RUN (daily cron)
# ══════════════════════════════════════════

def run_full():
    global _last_results, _last_run_time
    start = datetime.now()
    log.info("══════════════════════════════════════════")
    log.info("  RMS ESTANQUES v7 — Full Pricing Run")
    log.info(f"  {start.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("══════════════════════════════════════════")

    from rms import config
    from rms.beds24 import api_get
    try:
        api_get("bookings", {"limit": 1})
        log.info("  ✅ Beds24 conectado")
    except Exception as e:
        log.error(f"  ❌ Beds24 no responde: {e}")
        return False

    from rms.otb import read_otb, save_otb_snapshot
    from rms.capa_a import cargar_capa_a
    from rms.events import build_events

    otb = read_otb()
    save_otb_snapshot(otb)
    cargar_capa_a()
    events = build_events()

    from rms.pricing import calcular_precios_v7
    results = calcular_precios_v7(otb, events)
    log.info(f"  ✅ {len(results)} días calculados")

    audit = _audit(results)
    if not audit["ok"]:
        log.error(f"  ❌ Auditoría FALLIDA: {audit['alertas']}")
        return False
    log.info("  ✅ Auditoría OK")
    for w in audit["warnings"]:
        log.warning(f"  ⚠️ {w}")

    # Step 4b: Claude optimization
    from rms.claude_api import optimize_with_claude
    results = optimize_with_claude(results, otb)  
    if config.DRY_RUN:
        log.info("  🔒 DRY RUN — precios NO aplicados")
    else:
        from rms.apply import aplicar_precios
        aplicar_precios(results)
        log.info("  ✅ Precios aplicados en Beds24")

    try:
        from rms.alerts import run_alerts
        run_alerts(otb)
    except Exception as e:
        log.warning(f"  ⚠️ Alertas: {e}")

    try:
        from rms.email_report import send_daily_email
        send_daily_email(results)
    except Exception as e:
        log.warning(f"  ⚠️ Email diario: {e}")

    _last_results = results
    _last_run_time = start

    elapsed = (datetime.now() - start).total_seconds()
    log.info(f"\n✅ RMS completado en {elapsed:.1f}s")
    return True


# ══════════════════════════════════════════
# WEBHOOK REPRICING
# ══════════════════════════════════════════

def run_repricing(webhook_data):
    global _last_results, _last_run_time
    start = datetime.now()
    from rms import config

    if config.DRY_RUN:
        log.info("  🔒 DRY RUN — webhook repricing skipped")
        return {"status": "dry_run"}

    log.info("── WEBHOOK REPRICING ──")
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
        return {"status": "audit_failed", "alertas": audit["alertas"]}

    aplicar_precios(results)
    _last_results = results
    _last_run_time = start

    elapsed = (datetime.now() - start).total_seconds()
    log.info(f"  ✅ Repricing: {len(results)} fechas en {elapsed:.1f}s")
    return {"status": "ok", "dates_updated": len(results), "elapsed_seconds": round(elapsed, 1)}


# ══════════════════════════════════════════
# WEB SERVER + SCHEDULER
# ══════════════════════════════════════════

def start_server():
    from flask import Flask, request, jsonify
    from apscheduler.schedulers.background import BackgroundScheduler

    app = Flask(__name__)

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
            "last_run": str(_last_run_time) if _last_run_time else "never",
        })

    @app.route("/webhook/booking", methods=["POST", "GET"])
    def webhook_booking():
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
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/run", methods=["POST", "GET"])
    def manual_run():
        try:
            success = run_full()
            return jsonify({"status": "ok" if success else "failed"}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/prices", methods=["GET"])
    def prices():
        """Show calculated prices. Use ?month=7 or ?month=8 to filter."""
        if not _last_results:
            return jsonify({"error": "No results yet. Hit /run first."}), 404

        month_filter = request.args.get("month", None)
        days_filter = request.args.get("days", None)

        filtered = _last_results
        if month_filter:
            m = int(month_filter)
            filtered = [r for r in filtered if int(r["date"][5:7]) == m]
        if days_filter:
            filtered = filtered[:int(days_filter)]

        output = []
        for r in filtered:
            output.append({
                "date": r["date"],
                "season": r["seasonCode"],
                "disp": r["disponibles"],
                "reserv": r["reservadas"],
                "precio": r["precioFinal"],
                "genius": r.get("precioGenius", round(r["precioFinal"] * 0.85)),
                "suelo": r["suelo"],
                "techo": r["techo"],
                "minStay": r["minStay"],
                "clamped": r.get("clampedBy", ""),
                "event": r.get("eventName", ""),
                "neto": r.get("precioNeto", ""),
                "dispVirtual": r.get("dispVirtual", ""),
                "forecast": r.get("forecastDemanda", ""),
            })

        return jsonify({
            "run_time": str(_last_run_time),
            "total": len(output),
            "prices": output,
        })

    @app.route("/prices/compare", methods=["GET"])
    def prices_compare():
        """Show prices formatted for easy comparison with GAS."""
        if not _last_results:
            return jsonify({"error": "No results yet. Hit /run first."}), 404

        lines = ["Fecha      | Disp | Precio PY | Genius | Suelo | Techo | Neto | DispV | Fcst | Clamp | MinSt"]
        lines.append("-" * 110)

        for r in _last_results:
            m = int(r["date"][5:7])
            if m not in (7, 8):
                continue
            if r["date"] > "2026-08-15":
                continue

            genius = r.get("precioGenius", round(r["precioFinal"] * 0.85))
            neto = r.get("precioNeto", "?")
            dv = r.get("dispVirtual", "?")
            fc = r.get("forecastDemanda", "?")
            clamp = r.get("clampedBy", "")

            lines.append(
                f"{r['date']} | {r['disponibles']:4d} | {r['precioFinal']:9d}€ | {genius:6d}€ | "
                f"{r['suelo']:5d} | {r['techo']:5d} | {neto:>4} | {dv:>5} | {fc:>4} | "
                f"{clamp:>5} | {r['minStay']:5d}"
            )

        return "<pre>" + "\n".join(lines) + "</pre>", 200, {"Content-Type": "text/html"}

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


if __name__ == "__main__":
    start_server()
