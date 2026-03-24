"""
RMS Estanques v7.1 — Python/Railway Edition
Main entry point — Flask server + APScheduler + webhook handler

DAILY RUN (05:00 UTC / 07:00 Spain):
1. Connect Beds24
2. Check & rebuild Capa A (quarterly)
3. Check & update Comp Set (weekly, Wednesdays)
4. Check & update Vacaciones (monthly)
5. Load OTB + events
6. Calculate prices v7 (forecast → optimize → execute → smooth)
7. Claude API optimization
8. Audit
9. Apply prices to Beds24 (unless DRY_RUN)
10. Revenue tracker
11. Feedback check
12. Email daily report

WEBHOOK (on booking/cancellation):
- Recalculate prices for affected dates
- Apply immediately
"""

import os
import sys
import logging
from datetime import datetime, date
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("RMS")

# ══════════════════════════════════════════
# FLASK APP
# ══════════════════════════════════════════

app = Flask(__name__)

# Store last run results for /prices/compare endpoint
_last_results = []
_last_audit = {}
_last_claude = {}


def run_full():
    """Full daily pricing pipeline."""
    global _last_results, _last_audit, _last_claude
    
    from rms import config
    from rms.beds24 import get_token
    from rms.otb import read_otb
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
    log.info("  RMS ESTANQUES v7.1 — Full Pricing Run")
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
        
        # Step 2: Capa A check (quarterly rebuild)
        log.info("\n── STEP 2: Capa A ──")
        recalibrated = check_and_recalibrate()
        if recalibrated:
            log.info("  ✅ Capa A recalibrada")
        else:
            cargar_capa_a()
        
        # Step 3: Comp Set check (weekly)
        log.info("\n── STEP 3: Comp Set ──")
        comp_updated = check_and_update_comp_set()
        if comp_updated:
            log.info(f"  ✅ Comp Set actualizado ({len(comp_updated)} ventanas)")
        else:
            log.info("  Usando ADR_PEER existente")
        
        # Step 4: Vacaciones check (monthly)
        log.info("\n── STEP 4: Vacaciones escolares ──")
        vac_updated = check_and_update_vacaciones()
        if vac_updated:
            log.info(f"  ✅ Vacaciones actualizadas ({len(vac_updated)} días con boost)")
        else:
            log.info("  Cache de vacaciones vigente")
        
        # Step 5: Load data
        log.info("\n── STEP 5: Cargar datos ──")
        otb = read_otb()
        log.info(f"  ✅ OTB: {len(otb)} fechas")
        events = build_events()
        log.info(f"  ✅ {len(events)} eventos cargados")
        
        # Step 6: Calculate prices v7
        log.info("\n── STEP 6: Calcular precios v7 ──")
        results = calcular_precios_v7(otb, events)
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
        
        # Store for API endpoints
        _last_results = results
        _last_audit = audit
        _last_claude = claude_result
        
        elapsed = (datetime.now() - start).total_seconds()
        log.info(f"\n✅ RMS completado en {elapsed:.1f}s")
        
    except Exception as e:
        log.error(f"❌ Error fatal: {e}", exc_info=True)


def audit_results(results):
    """Audit pricing results for sanity."""
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
    
    return {"ok": ok, "alertas": alertas, "warnings": warnings}


# ══════════════════════════════════════════
# WEBHOOK HANDLER
# ══════════════════════════════════════════

@app.route("/webhook/booking", methods=["POST"])
def webhook_booking():
    """Handle Beds24 booking webhook — trigger repricing."""
    log.info("📨 Webhook recibido: booking event")
    
    try:
        # Parse webhook data (Beds24 Auto Action format)
        data = request.get_json(silent=True) or {}
        booking_id = data.get("bookingId") or data.get("id") or "unknown"
        log.info(f"  Booking ID: {booking_id}")
        
        # Run full pricing (in production, could be partial for affected dates)
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
        "service": "RMS Estanques v7.1",
        "next_run": next_run,
    })


@app.route("/run")
def trigger_run():
    """Manual trigger for full pricing run."""
    run_full()
    return jsonify({
        "status": "ok",
        "results": len(_last_results),
        "audit": _last_audit,
    })


@app.route("/prices/compare")
def prices_compare():
    """Show July-August prices for comparison."""
    if not _last_results:
        return "No results yet. Hit /run first.", 404
    
    lines = []
    header = f"{'Fecha':<11}| {'Disp':>4} | {'Precio PY':>10} | {'Genius':>7} | {'Suelo':>5} | {'Techo':>5} | {'Neto':>5} | {'DispV':>5} | {'Fcst':>4} | {'Clamp':>5} | {'MinSt':>5}"
    lines.append(header)
    lines.append("-" * len(header))
    
    for r in _last_results:
        month = int(r["date"][5:7])
        if month < 7 or month > 8:
            continue
        if r["date"] > "2026-08-15":
            continue
        
        lines.append(
            f"{r['date']:<11}| {r['disponibles']:>4} | {r['precioFinal']:>7}€ | {r['precioGenius']:>5}€ | {r.get('suelo',''):>5} | {r.get('techo',''):>5} | "
            f"{r.get('precioNeto',''):>5} | {r.get('dispVirtual',''):>5} | {r.get('forecastDemanda',''):>4} | {r.get('clampedBy',''):>5} | {r.get('minStay',''):>5}"
        )
    
    return "<pre>" + "\n".join(lines) + "</pre>"


@app.route("/revenue")
def revenue_endpoint():
    """Show revenue tracker."""
    try:
        from rms.revenue import calcular_revenue_tracker
        tracker = calcular_revenue_tracker()
        return jsonify(tracker)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════
# SCHEDULER
# ══════════════════════════════════════════

scheduler = BackgroundScheduler()
scheduler.add_job(run_full, "cron", hour=5, minute=0, id="daily_full")
scheduler.start()
log.info("⏰ Scheduler: daily full run at 05:00 UTC")


# ══════════════════════════════════════════
# START
# ══════════════════════════════════════════

port = int(os.getenv("PORT", 8080))
log.info(f"🌐 Servidor arrancado en puerto {port}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port)
