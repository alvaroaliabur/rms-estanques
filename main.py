""" 
RMS Estanques v7.5 — Python/Railway Edition
Main entry point — Flask server + APScheduler + webhook handler

v7.5 CHANGES:
  - P1: Pickup persistente via Google Sheets (sobrevive redeploys)
  - P3: Suelos dinámicos por days_out (65-100% según distancia)
  - P4: Feedback persistente via Sheets
  - P6: Early bird para sep-oct abandonados
  - Endpoint /source/<filename> para acceso al código en producción
  - Version bump a v7.5
"""

import os
import sys
import logging
import inspect
from datetime import datetime, date
from flask import Flask, request, jsonify, Response
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
    from rms.vacaciones import check_and_update_vacaciones
    from rms.events import build_events
    from rms.pricing import calcular_precios_v7
    from rms.alerts import run_alerts
    from rms.apply import aplicar_precios
    from rms.email_report import enviar_email_diario
    from rms.revenue import calcular_revenue_tracker, record_prices, check_feedback

    start = datetime.now()
    log.info("══════════════════════════════════════════")
    log.info("  RMS ESTANQUES v7.5 — Full Pricing Run")
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

        # Step 3: Comp Set — DESACTIVADO v7.4+
        log.info("\n── STEP 3: Comp Set ──")
        log.info("  Apify desactivado — referencia: Booking Analytics (config.py)")

        # Step 4: Vacaciones check
        log.info("\n── STEP 4: Vacaciones escolares ──")
        vac_updated = check_and_update_vacaciones()
        if vac_updated:
            log.info(f"  ✅ Vacaciones actualizadas ({len(vac_updated)} días con boost)")
        else:
            log.info("  Cache de vacaciones vigente")

        # Step 4b: Market Intelligence (AirROI)
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
        log.info(f"  ✅ OTB: {len(otb)} fechas")
        events = build_events()
        log.info(f"  ✅ {len(events)} eventos cargados")

        # Step 6: Calculate prices v7.5
        log.info("\n── STEP 6: Calcular precios v7.5 ──")
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
        log.info(f"\n✅ RMS v7.5 completado en {elapsed:.1f}s")

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

        mult_active = sum(1 for r in results if abs(r.get("fTotal", 1.0) - 1.0) > 0.02)
        if mult_active < 10:
            warnings.append(f"Solo {mult_active} días con multiplicadores activos")

        # v7.5: warn if pickup is dead
        pickup_active = sum(1 for r in results if r.get("fPickup", 1.0) != 1.0)
        if pickup_active == 0:
            warnings.append("⚠️ fPickup=1.0 en TODOS los días — snapshots perdidos?")

    return {"ok": ok, "alertas": alertas, "warnings": warnings}


# ══════════════════════════════════════════
# WEBHOOK
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
# ENDPOINTS
# ══════════════════════════════════════════

@app.route("/health")
def health():
    scheduler_job = scheduler.get_job("daily_full")
    next_run = str(scheduler_job.next_run_time) if scheduler_job else "not scheduled"
    return jsonify({
        "status": "ok",
        "service": "RMS Estanques v7.5",
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
    if not _last_results:
        return "No results yet. Hit /run first.", 404

    lines = []
    header = (f"{'Fecha':<11}| {'Disp':>4} | {'Precio':>6} | {'Genius':>6} | "
              f"{'Suelo':>5} | {'Techo':>5} | {'Neto':>5} | "
              f"{'fOTB':>5} | {'fPick':>5} | {'fPace':>5} | {'fTot':>5} | "
              f"{'FlrF':>4} | {'Clamp':>5} | {'MinSt':>5} | {'Vac':>4} | {'EB':>2}")
    lines.append(header)
    lines.append("-" * len(header))

    for r in _last_results:
        month = int(r["date"][5:7])
        if month < 4 or month > 10:
            continue

        eb = "Y" if r.get("earlyBird") else ""
        lines.append(
            f"{r['date']:<11}| {r['disponibles']:>4} | {r['precioFinal']:>4}€ | {r['precioGenius']:>4}€ | "
            f"{r.get('suelo',''):>5} | {r.get('techo',''):>5} | {r.get('precioNeto',''):>5} | "
            f"{r.get('fOTB',1.0):>5.2f} | {r.get('fPickup',1.0):>5.2f} | {r.get('fPace',1.0):>5.2f} | {r.get('fTotal',1.0):>5.2f} | "
            f"{r.get('floorFactor',1.0):>4.2f} | "
            f"{r.get('clampedBy',''):>5} | {r.get('minStay',''):>5} | {r.get('vacFactor',1.0):>4.2f} | {eb:>2}"
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
    r1 = req.post("https://api.airroi.com/markets/metrics/occupancy", headers=headers,
                  json={"market": {"country": "Spain", "region": "Balearic Islands",
                        "locality": "ses Salines"}, "num_months": 6}, timeout=15)
    results["occ_locality"] = r1.json() if r1.status_code == 200 else {"status": r1.status_code}
    r2 = req.post("https://api.airroi.com/markets/metrics/occupancy", headers=headers,
                  json={"market": {"country": "Spain", "region": "Balearic Islands",
                        "locality": "ses Salines", "district": "Colònia de Sant Jordi"},
                        "num_months": 6}, timeout=15)
    results["occ_district"] = r2.json() if r2.status_code == 200 else {"status": r2.status_code}
    return jsonify(results)


# ══════════════════════════════════════════
# /source/<filename> — Acceso al código fuente en producción
# Resuelve el problema del CDN de GitHub cacheando versiones viejas.
# Protegido con token opcional (SOURCE_TOKEN env var).
# ══════════════════════════════════════════

SOURCE_TOKEN = os.getenv("SOURCE_TOKEN", "")

# Map of allowed filenames to module references
_SOURCE_MAP = {
    "main": None,  # Special: read this file directly
    "config": "rms.config",
    "pricing": "rms.pricing",
    "otb": "rms.otb",
    "compset": "rms.compset",
    "capa_a": "rms.capa_a",
    "revenue": "rms.revenue",
    "apply": "rms.apply",
    "alerts": "rms.alerts",
    "beds24": "rms.beds24",
    "events": "rms.events",
    "vacaciones": "rms.vacaciones",
    "los": "rms.los",
    "explicacion": "rms.explicacion",
    "email_report": "rms.email_report",
    "market_intelligence": "rms.market_intelligence",
    "claude_api": "rms.claude_api",
    "utils": "rms.utils",
}


@app.route("/source")
def source_index():
    """List available source files."""
    if SOURCE_TOKEN and request.args.get("token") != SOURCE_TOKEN:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"files": sorted(_SOURCE_MAP.keys())})


@app.route("/source/<filename>")
def source_file(filename):
    """Return source code of a module. No CDN cache issues."""
    if SOURCE_TOKEN and request.args.get("token") != SOURCE_TOKEN:
        return jsonify({"error": "unauthorized"}), 401

    if filename not in _SOURCE_MAP:
        return jsonify({"error": f"Unknown file: {filename}", "available": sorted(_SOURCE_MAP.keys())}), 404

    try:
        if filename == "main":
            # Read this file
            with open(__file__, "r") as f:
                source = f.read()
        else:
            module_name = _SOURCE_MAP[filename]
            import importlib
            mod = importlib.import_module(module_name)
            source = inspect.getsource(mod)

        return Response(source, mimetype="text/plain")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════
# TEST: Price field mapping
# ══════════════════════════════════════════

@app.route("/test-mapping")
def test_mapping():
    """
    Escribe precios únicos (111-999) en price1-price9 para 2027-01-15
    en Upper Floor. Después mira el calendar de Beds24 en esa fecha
    para ver qué fila muestra cada número.
    """
    from rms.beds24 import get_token, api_post
    from rms import config

    TEST_DATE = "2027-01-15"
    ROOM_ID = config.ROOM_UPPER

    get_token()

    entry = {
        "from": TEST_DATE, "to": TEST_DATE, "minStay": 2,
        "price1": 111, "price2": 222, "price3": 333,
        "price4": 444, "price5": 555, "price6": 666,
        "price7": 777, "price8": 888, "price9": 999,
    }

    payload = [{"roomId": ROOM_ID, "calendar": [entry]}]
    result = api_post("inventory/rooms/calendar", payload)

    return (
        "<h2>✅ Test escrito en 2027-01-15 (Upper Floor)</h2>"
        "<p>Ve al calendar de Beds24 → enero 2027 → día 15</p>"
        "<p>Anota qué fila muestra cada número:</p>"
        "<pre>"
        "111 → price1 = ¿?\n"
        "222 → price2 = ¿?\n"
        "333 → price3 = ¿?\n"
        "444 → price4 = ¿?\n"
        "555 → price5 = ¿?\n"
        "666 → price6 = ¿?\n"
        "777 → price7 = ¿?\n"
        "888 → price8 = ¿?\n"
        "999 → price9 = ¿?\n"
        "</pre>"
        "<p>Mándame un pantallazo y corrijo el mapping.</p>"
        "<p><a href='/test-mapping-rollback'>Limpiar después</a></p>"
    )


@app.route("/test-mapping-rollback")
def test_mapping_rollback():
    from rms.beds24 import get_token, api_post
    from rms import config

    get_token()
    entry = {"from": "2027-01-15", "to": "2027-01-15", "minStay": 3}
    for i in range(1, 10):
        entry[f"price{i}"] = 9999
    payload = [{"roomId": config.ROOM_UPPER, "calendar": [entry]}]
    api_post("inventory/rooms/calendar", payload)
    return "<h2>✅ Rollback completado — 2027-01-15 limpio</h2>"


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
