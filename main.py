"""
RMS Estanques v7.3 — Python/Railway Edition
Main entry point — Flask server + APScheduler + webhook handler

v7.3 CHANGES:
  - Direct price multipliers (fOTB, fPickup, fPace, fTotal)
  - Multi-year historical data (3 years for fill curves)
  - Revenue audit: compares vs BEST historical year
  - /prices/compare shows multiplier columns
  - /explicacion shows revenue audit dashboard
"""

import os
import sys
import logging
from datetime import datetime, date
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("RMS")

app = Flask(__name__)

_last_results = []
_last_audit = {}
_last_claude = {}
_run_in_progress = False


def run_full():
    """Full daily pricing pipeline."""
    global _last_results, _last_audit, _last_claude, _run_in_progress

    if _run_in_progress:
        log.warning("Run already in progress, skipping")
        return

    _run_in_progress = True

    from rms import config
    from rms.beds24 import get_token
    from rms.otb import read_otb_by_type
    from rms.capa_a import cargar_capa_a, check_and_recalibrate
    from rms.compset import check_and_update_comp_set
    from rms.vacaciones import check_and_update_vacaciones
    from rms.events import build_events
    from rms.pricing import calcular_precios_v7
    from rms.alerts import run_alerts
    from rms.apply import aplicar_precios
    from rms.email_report import enviar_email_diario
    from rms.revenue import calcular_revenue_tracker, record_prices, check_feedback

    start = datetime.now()
    log.info("══════════════════════════════════════════")
    log.info("  RMS ESTANQUES v7.4 — Full Pricing Run")
    log.info(f"  {start.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("══════════════════════════════════════════")

    try:
        # Step 1: Connect Beds24
        log.info("\n── STEP 1: Conectar Beds24 ──")
        token = get_token()
        if not token:
            log.error("  ❌ No se pudo conectar a Beds24")
            return
        log.info("  ✅ Beds24 conectado")

        # Step 2: Capa A check
        log.info("\n── STEP 2: Capa A ──")
        recalibrated = check_and_recalibrate()
        if recalibrated:
            log.info("  ✅ Capa A recalibrada")
        else:
            cargar_capa_a()

        # Step 3: Comp Set check
        log.info("\n── STEP 3: Comp Set ──")
        comp_updated = check_and_update_comp_set()
        if comp_updated:
            log.info(f"  ✅ Comp Set actualizado ({len(comp_updated)} ventanas)")
        else:
            log.info("  Usando ADR_PEER existente")

        # Step 4: Vacaciones check
        log.info("\n── STEP 4: Vacaciones escolares ──")
        vac_updated = check_and_update_vacaciones()
        if vac_updated:
            log.info(f"  ✅ Vacaciones actualizadas ({len(vac_updated)} días con boost)")
        else:
            log.info("  Cache de vacaciones vigente")

        # Step 4b: Market Intelligence
        log.info("\n── STEP 4b: Market Intelligence ──")
        try:
            from rms.market_intelligence import check_and_update_market
            market = check_and_update_market()
            if market:
                log.info(f"  ✅ Market intelligence: {len(market)} datasets")
            else:
                log.info("  Usando datos de mercado existentes")
        except Exception as e:
            log.warning(f"  Market intelligence error: {e}")

        # Step 5: Load data
        log.info("\n── STEP 5: Cargar datos ──")
        otb, otb_by_type = read_otb_by_type()
        log.info(f"  ✅ OTB: {len(otb)} fechas (per-type loaded)")
        events = build_events()
        log.info(f"  ✅ {len(events)} eventos cargados")

        # Step 6: Calculate prices v7.3
        log.info("\n── STEP 6: Calcular precios v7.3 ──")
        results = calcular_precios_v7(otb, events, otb_by_type=otb_by_type)
        log.info(f"  ✅ {len(results)} días calculados")

        # Step 7: Audit
        log.info("\n── STEP 7: Auditar ──")
        audit = audit_results(results)
        if audit["ok"]:
            log.info("  ✅ Auditoría OK")
        else:
            log.warning(f"  ❌ Auditoría FALLIDA: {audit['alertas']}")
        for w in audit.get("warnings", []):
            log.warning(f"  ⚠️ {w}")

        # Step 8: Claude API optimization
        log.info("\n── STEP 8: Claude API ──")
        claude_result = {}
        try:
            from rms.claude_api import optimize_with_claude
            results = optimize_with_claude(results, otb)
        except Exception as e:
            log.warning(f"  Claude API error: {e}")

        # Step 9: Apply prices
        log.info("\n── STEP 9: Aplicar precios ──")
        apply_result = aplicar_precios(results)

        # Step 10: Revenue tracker
        log.info("\n── STEP 10: Revenue Tracker ──")
        try:
            tracker = calcular_revenue_tracker()
        except Exception as e:
            log.warning(f"  Revenue tracker error: {e}")
            tracker = {}

        # Step 11: Feedback check
        log.info("\n── STEP 11: Feedback ──")
        try:
            record_prices(results)
            feedback = check_feedback(results, otb)
        except Exception as e:
            log.warning(f"  Feedback error: {e}")
            feedback = []

        # Step 12: Alerts
        log.info("\n── STEP 12: Alertas ──")
        alerts = run_alerts(otb)

        # Step 13: Email
        log.info("\n── STEP 13: Email diario ──")
        try:
            enviar_email_diario(results, audit, alerts, claude_result)
        except Exception as e:
            log.warning(f"  Email error: {e}")

        _last_results = results
        _last_audit = audit
        _last_claude = claude_result

        elapsed = (datetime.now() - start).total_seconds()
        log.info(f"\n✅ RMS v7.3 completado en {elapsed:.1f}s")

    except Exception as e:
        log.error(f"❌ Error fatal: {e}", exc_info=True)
    finally:
        _run_in_progress = False


def audit_results(results):
    alertas = []
    warnings = []
    ok = True
    dias_suelo = 0
    dias_techo = 0

    if not results or len(results) < 30:
        alertas.append(f"Solo {len(results) if results else 0} días calculados")
        ok = False

    if results:
        for r in results:
            pf = r.get("precioFinal", 0)
            if not pf or pf < 35:
                alertas.append(f"Precio muy bajo: {r['date']} → {pf}€")
                ok = False
            elif pf > 2000:
                alertas.append(f"Precio muy alto: {r['date']} → {pf}€")
                ok = False

            ms = r.get("minStay", 0)
            if ms < 1 or ms > 14:
                alertas.append(f"MinStay inválido: {r['date']} → {ms}")
                ok = False

            month = int(r["date"][5:7])
            if month == 7 and pf < 200:
                alertas.append(f"Julio muy bajo: {r['date']} → {pf}€")
                ok = False
            if month == 8 and pf < 220:
                alertas.append(f"Agosto muy bajo: {r['date']} → {pf}€")
                ok = False

            if r.get("clampedBy") == "SUELO":
                dias_suelo += 1
            if r.get("clampedBy") == "TECHO":
                dias_techo += 1

        if dias_suelo > 60:
            warnings.append(f"{dias_suelo} días limitados por SUELO")
        if dias_techo > 20:
            warnings.append(f"{dias_techo} días limitados por TECHO")

        # v7.3: warn if multipliers aren't working
        mult_active = sum(1 for r in results if abs(r.get("fTotal", 1.0) - 1.0) > 0.02)
        if mult_active < 10:
            warnings.append(f"Solo {mult_active} días con multiplicadores activos — revisar señales")

    return {"ok": ok, "alertas": alertas, "warnings": warnings}


# ══════════════════════════════════════════
# WEBHOOK HANDLER
# ══════════════════════════════════════════

@app.route("/webhook/booking", methods=["POST"])
def webhook_booking():
    log.info("📨 Webhook recibido: booking event")
    try:
        data = request.get_json(silent=True) or {}
        booking_id = data.get("bookingId") or data.get("id") or "unknown"
        log.info(f"  Booking ID: {booking_id}")
        run_full()
        return jsonify({"status": "ok", "action": "repricing_triggered"})
    except Exception as e:
        log.error(f"  Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ══════════════════════════════════════════
# API ENDPOINTS
# ══════════════════════════════════════════

@app.route("/health")
def health():
    scheduler_job = scheduler.get_job("daily_full")
    next_run = str(scheduler_job.next_run_time) if scheduler_job else "not scheduled"
    return jsonify({
        "status": "ok",
        "service": "RMS Estanques v7.4",
        "next_run": next_run,
        "run_in_progress": _run_in_progress,
    })


@app.route("/run")
def trigger_run():
    run_full()
    return jsonify({
        "status": "ok",
        "results": len(_last_results),
        "audit": _last_audit,
    })


@app.route("/prices/compare")
def prices_compare():
    """v7.3: Shows multiplier columns for full transparency."""
    if not _last_results:
        return "No results yet. Hit /run first.", 404

    lines = []
    header = (f"{'Fecha':<11}| {'Disp':>4} | {'Precio':>6} | {'Genius':>6} | "
              f"{'Suelo':>5} | {'Techo':>5} | {'Neto':>5} | "
              f"{'fOTB':>5} | {'fPick':>5} | {'fPace':>5} | {'fTot':>5} | "
              f"{'Urg':>4} | {'EBSA':>5} | {'Boost':>5} | "
              f"{'Clamp':>5} | {'MinSt':>5} | {'Vac':>4}")
    lines.append(header)
    lines.append("-" * len(header))

    for r in _last_results:
        month = int(r["date"][5:7])
        if month < 4 or month > 10:
            continue

        lines.append(
            f"{r['date']:<11}| {r['disponibles']:>4} | {r['precioFinal']:>4}€ | {r['precioGenius']:>4}€ | "
            f"{r.get('suelo',''):>5} | {r.get('techo',''):>5} | {r.get('precioNeto',''):>5} | "
            f"{r.get('fOTB',1.0):>5.2f} | {r.get('fPickup',1.0):>5.2f} | {r.get('fPace',1.0):>5.2f} | {r.get('fTotal',1.0):>5.2f} | "
            f"{r.get('urgency',1.0):>4.1f} | {r.get('fEBSA',1.0):>5.2f} | {r.get('boostUA',1.0):>5.2f} | "
            f"{r.get('clampedBy',''):>5} | {r.get('minStay',''):>5} | {r.get('vacFactor',1.0):>4.2f}"
        )

    return "<pre>" + "\n".join(lines) + "</pre>"


@app.route("/revenue")
def revenue_endpoint():
    try:
        from rms.revenue import calcular_revenue_tracker
        tracker = calcular_revenue_tracker()
        return jsonify(tracker)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/email")
def email_view():
    from rms.email_report import get_last_email
    email = get_last_email()
    if not email or not email.get("html"):
        return "<h1>No email generated yet. Hit /run first.</h1>", 404
    return email["html"]


@app.route("/explicacion")
def explicacion():
    """Human-readable explanation of all prices + revenue audit."""
    if not _last_results:
        return "<h1>No hay datos. Ejecuta <a href='/run'>/run</a> primero.</h1>", 404
    from rms.explicacion import generar_explicacion_html
    month = request.args.get("month", type=int)
    date_filter = request.args.get("date", type=str)
    return generar_explicacion_html(_last_results, month_filter=month, date_filter=date_filter)


@app.route("/market/test")
def market_test():
    import requests as req
    key = os.getenv("AIRROI_API_KEY", "")
    headers = {"X-API-KEY": key, "Content-Type": "application/json"}
    results = {}
    r1 = req.post("https://api.airroi.com/markets/metrics/occupancy", headers=headers, json={"market": {"country": "Spain", "region": "Balearic Islands", "locality": "ses Salines"}, "num_months": 6}, timeout=15)
    results["occ_locality"] = r1.json() if r1.status_code == 200 else {"status": r1.status_code, "text": r1.text[:300]}
    r2 = req.post("https://api.airroi.com/markets/metrics/occupancy", headers=headers, json={"market": {"country": "Spain", "region": "Balearic Islands", "locality": "ses Salines", "district": "Colònia de Sant Jordi"}, "num_months": 6}, timeout=15)
    results["occ_district"] = r2.json() if r2.status_code == 200 else {"status": r2.status_code, "text": r2.text[:300]}
    r3 = req.post("https://api.airroi.com/listings/search/radius", headers=headers, json={"latitude": 39.3167, "longitude": 2.9889, "radius_miles": 2, "pagination": {"page_size": 5, "offset": 0}, "currency": "native"}, timeout=15)
    results["compset"] = r3.json() if r3.status_code == 200 else {"status": r3.status_code, "text": r3.text[:300]}
    r4 = req.get("https://api.airroi.com/markets/lookup?lat=39.3167&lng=2.9889", headers=headers, timeout=15)
    results["coords"] = r4.json() if r4.status_code == 200 else {"status": r4.status_code, "text": r4.text[:300]}
    return jsonify(results)


# ══════════════════════════════════════════
# SCHEDULER
# ══════════════════════════════════════════

scheduler = BackgroundScheduler()
scheduler.add_job(run_full, "cron", hour=5, minute=0, id="daily_full")
scheduler.start()
log.info("⏰ Scheduler: daily full run at 05:00 UTC")

port = int(os.getenv("PORT", 8080))
log.info(f"🌐 Servidor arrancado en puerto {port}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port)
