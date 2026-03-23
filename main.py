"""
RMS Estanques v7 — Main Entry Point
====================================
Railway runs this as a cron job at 5:00 UTC daily.

Pipeline:
  1. Connect to Beds24, read OTB
  2. Load Capa A (demand curves)
  3. Calculate prices (v7 engine)
  4. Audit results
  5. Apply prices to Beds24
  6. Run alerts
  7. Send daily email
"""

import sys
import logging
import traceback
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("RMS")


def run():
    """Full RMS execution — replaces paso1 + paso2 + paso3 from GAS."""
    start = datetime.now()
    log.info("══════════════════════════════════════════")
    log.info("  RMS ESTANQUES v7 — Python Edition")
    log.info(f"  {start.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("══════════════════════════════════════════")

    from rms import config

    # ── STEP 1: Verify connection ──
    log.info("\n── STEP 1: Conectar Beds24 ──")
    from rms.beds24 import api_get
    try:
        api_get("bookings", {"limit": 1})
        log.info("  ✅ Beds24 conectado")
    except Exception as e:
        log.error(f"  ❌ Beds24 no responde: {e}")
        _send_error_email(f"Beds24 no responde: {e}")
        return False

    # ── STEP 2: Load data ──
    log.info("\n── STEP 2: Cargar datos ──")
    from rms.otb import read_otb, save_otb_snapshot, calc_pickup, calc_pace, read_current_prices
    from rms.capa_a import cargar_capa_a
    from rms.events import build_events, get_vacaciones_factor

    otb = read_otb()
    save_otb_snapshot(otb)
    log.info(f"  ✅ OTB: {len(otb)} fechas")

    capa_a_ok = cargar_capa_a()
    if not capa_a_ok:
        log.warning("  ⚠️ Capa A no disponible — usando SEGMENT_BASE por defecto")

    events = build_events()
    log.info(f"  ✅ {len(events)} eventos cargados")

    # ── STEP 3: Calculate prices ──
    log.info("\n── STEP 3: Calcular precios v7 ──")
    from rms.pricing import calcular_precios_v7
    results = calcular_precios_v7(otb, events)
    log.info(f"  ✅ {len(results)} días calculados")

    # ── STEP 4: Audit ──
    log.info("\n── STEP 4: Auditar ──")
    audit = _audit(results)
    if not audit["ok"]:
        log.error(f"  ❌ Auditoría FALLIDA: {audit['alertas']}")
        _send_error_email(f"Auditoría FALLIDA:\n" + "\n".join(audit["alertas"]))
        return False
    log.info(f"  ✅ Auditoría OK")
    if audit["warnings"]:
        for w in audit["warnings"]:
            log.warning(f"  ⚠️ {w}")

    # ── STEP 5: Apply prices ──
    log.info("\n── STEP 5: Aplicar precios ──")
    if config.DRY_RUN:
        log.info("  🔒 DRY RUN — precios NO aplicados")
    else:
        from rms.apply import aplicar_precios
        aplicar_precios(results)
        log.info("  ✅ Precios aplicados en Beds24")

    # ── STEP 6: Alerts ──
    log.info("\n── STEP 6: Alertas ──")
    try:
        from rms.alerts import run_alerts
        run_alerts(otb)
    except Exception as e:
        log.warning(f"  ⚠️ Alertas: {e}")

    # ── STEP 7: Daily email ──
    log.info("\n── STEP 7: Email diario ──")
    try:
        from rms.email_report import send_daily_email
        send_daily_email(results)
    except Exception as e:
        log.warning(f"  ⚠️ Email diario: {e}")

    elapsed = (datetime.now() - start).total_seconds()
    log.info(f"\n✅ RMS completado en {elapsed:.1f}s")
    return True


def _audit(results):
    """Basic audit of pricing results."""
    alertas = []
    warnings = []

    if not results or len(results) < 30:
        alertas.append(f"Solo {len(results) if results else 0} días calculados (mínimo 30)")
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
    """Send error notification."""
    try:
        from rms.email_report import send_error_email
        send_error_email(msg)
    except Exception as e:
        log.error(f"  No se pudo enviar email de error: {e}")


if __name__ == "__main__":
    try:
        success = run()
        sys.exit(0 if success else 1)
    except Exception as e:
        log.error(f"❌ Error fatal: {e}")
        log.error(traceback.format_exc())
        _send_error_email(f"Error fatal: {e}\n\n{traceback.format_exc()}")
        sys.exit(1)
