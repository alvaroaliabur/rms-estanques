"""
Claude API — v7.5
Optimización inteligente de pricing sobre el motor v7.5.

Novedades v7.5:
- Contexto Beat-the-Best: status actual vs target (+5% mejor año) por mes
- Señales early bird y suelo dinámico incluidas en el briefing
- El prompt distingue entre fechas con suelo dinámico activo (oportunidad) y fechas protegidas
"""

import os
import json
import logging
import requests
from datetime import date, timedelta
from rms import config
from rms.utils import fmt

log = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-5-20251001"


def optimize_with_claude(results, otb):
    """Let Claude review v7.5 pricing and suggest improvements."""
    if not ANTHROPIC_API_KEY:
        log.warning("  No ANTHROPIC_API_KEY — skipping Claude optimization")
        return results

    log.info("  🧠 Claude API: analizando pricing v7.5...")

    context = _build_context(results, otb)

    try:
        response = _call_claude(context)
        if not response:
            return results

        adjustments = _parse_adjustments(response)
        if adjustments:
            results = _apply_adjustments(results, adjustments)
            log.info(f"  🧠 Claude: {len(adjustments)} ajustes aplicados")
        else:
            log.info("  🧠 Claude: sin ajustes recomendados")

    except Exception as e:
        log.warning(f"  🧠 Claude error: {e}")

    return results


def _build_btb_summary(results):
    """Build Beat-the-Best status summary by month for the Claude prompt."""
    btb_cfg = getattr(config, 'BEAT_THE_BEST', {})
    if not btb_cfg.get("enabled"):
        return ""

    best_by_month = btb_cfg.get("BEST_REVENUE_BY_MONTH", {})
    best_year_by_month = btb_cfg.get("BEST_YEAR_BY_MONTH", {})
    uplift = btb_cfg.get("target_uplift", 1.05)

    # Calcular revenue OTB actual por mes desde results
    rev_otb = {}
    for r in results:
        m = int(r["date"][5:7])
        rev_otb[m] = rev_otb.get(m, 0) + r.get("reservadas", 0) * r.get("precioFinal", 0) * 0.85

    lines = []
    for m in sorted(best_by_month.keys()):
        best = best_by_month[m]
        best_year = best_year_by_month.get(m, "")
        target = round(best * uplift)
        actual = round(rev_otb.get(m, 0))
        if actual > 0:
            pct = round((actual - target) / target * 100)
            status = "🏆 ON TRACK" if pct >= 0 else ("🎯 CERCA" if pct >= -15 else "⚠️ REZAGADO")
            lines.append(
                f"  {_month_name(m)}: OTB={actual:,}€ vs target={target:,}€ ({'+' if pct >= 0 else ''}{pct}%) "
                f"[mejor={best:,}€ en {best_year}] {status}"
            )
        else:
            lines.append(
                f"  {_month_name(m)}: sin datos OTB — target={target:,}€ [mejor={best:,}€ en {best_year}]"
            )

    return "\n".join(lines)


def _month_name(m):
    names = {1:"Ene", 2:"Feb", 3:"Mar", 4:"Abr", 5:"May", 6:"Jun",
              7:"Jul", 8:"Ago", 9:"Sep", 10:"Oct", 11:"Nov", 12:"Dic"}
    return names.get(m, str(m))


def _build_context(results, otb):
    """Build concise pricing briefing for Claude, including v7.5 signals."""
    today = date.today()

    # Summary by month
    months = {}
    for r in results:
        m = r["date"][:7]
        if m not in months:
            months[m] = {
                "dias": 0, "sum_precio": 0, "sum_reserv": 0,
                "suelos": 0, "techos": 0, "min_disp": 9, "max_disp": 0,
                "early_bird": 0, "dynamic_floor": 0,
            }
        mm = months[m]
        mm["dias"] += 1
        mm["sum_precio"] += r["precioFinal"]
        mm["sum_reserv"] += r["reservadas"]
        if r.get("clampedBy") == "SUELO":
            mm["suelos"] += 1
        if r.get("clampedBy") == "TECHO":
            mm["techos"] += 1
        if r["disponibles"] < mm["min_disp"]:
            mm["min_disp"] = r["disponibles"]
        if r["disponibles"] > mm["max_disp"]:
            mm["max_disp"] = r["disponibles"]
        if r.get("earlyBird"):
            mm["early_bird"] += 1
        if r.get("floorFactor", 1.0) < 1.0:
            mm["dynamic_floor"] += 1

    month_summary = []
    for m in sorted(months.keys()):
        mm = months[m]
        adr = round(mm["sum_precio"] / mm["dias"])
        genius = round(adr * 0.85)
        occ = round(mm["sum_reserv"] / (mm["dias"] * config.TOTAL_UNITS) * 100)
        extras = []
        if mm["early_bird"] > 0:
            extras.append(f"EarlyBird={mm['early_bird']}d")
        if mm["dynamic_floor"] > 0:
            extras.append(f"SueloDin={mm['dynamic_floor']}d")
        extras_str = f" [{', '.join(extras)}]" if extras else ""
        month_summary.append(
            f"{m}: ADR_pub={adr}€ ADR_Genius={genius}€ Occ={occ}% "
            f"Disp={mm['min_disp']}-{mm['max_disp']} "
            f"Suelo={mm['suelos']}d Techo={mm['techos']}d{extras_str}"
        )

    # High-value months detail (jun-sep)
    detail_verano = []
    for r in results:
        m = int(r["date"][5:7])
        if m < 6 or m > 9:
            continue
        flags = []
        if r.get("earlyBird"):
            flags.append("EARLY_BIRD")
        if r.get("floorFactor", 1.0) < 1.0:
            flags.append(f"SUELO_DIN×{r['floorFactor']:.0%}")
        if r.get("uncUplift", 1.0) > 1.0:
            flags.append(f"UNC×{r['uncUplift']:.2f}")
        flags_str = f" [{','.join(flags)}]" if flags else ""
        detail_verano.append(
            f"{r['date']} disp={r['disponibles']} precio_pub={r['precioFinal']}€ "
            f"genius={round(r['precioFinal']*0.85)}€ "
            f"suelo={r['suelo']} suelo_base={r.get('sueloBase', r['suelo'])} "
            f"techo={r['techo']} clamp={r.get('clampedBy','')} "
            f"fcst={r.get('forecastDemanda','')}{flags_str}"
        )

    # Next 14 days detail
    detail_14d = []
    for r in results[:14]:
        detail_14d.append(
            f"{r['date']} disp={r['disponibles']} precio={r['precioFinal']}€ "
            f"suelo={r['suelo']} techo={r['techo']} clamp={r.get('clampedBy','')} "
            f"event={r.get('eventName','')}"
        )

    # Beat-the-Best status
    btb_summary = _build_btb_summary(results)

    context = f"""Eres el Director de Revenue Management de Apartamentos Estanques. v7.5

═══ POSICIONAMIENTO ═══
Propiedad PREMIUM de Colònia de Sant Jordi. 9 apartamentos vacacionales.
Mercados: Alemania (40%), Holanda, UK, España. Genius Partner en Booking.
ADR Genius real 2025: julio=272€, agosto=312€.
Revenue 2025: 321.861€ (+14% vs 2024).

═══ COMP SET ═══
Peers (Piza, Lemar, Ibiza, etc.) son propiedades MÁS BARATAS e INFERIORES.
Tu precio DEBE ser 20-40% por encima de ellos. NO recomiendes bajar para igualar al comp set.

═══ BEAT-THE-BEST STATUS (objetivo: +5% sobre mejor año) ═══
{btb_summary if btb_summary else "  Sin datos disponibles"}

═══ SEÑALES V7.5 ACTIVAS ═══
• SUELO DINÁMICO: A >90d vista, el suelo baja al 65% del nominal para capturar reservas anticipadas.
  A 60-89d: 75%. A 30-59d: 85%. A <30d: 100% (protección total).
  → Si una fecha tiene SUELO_DIN activo y poca disponibilidad, el precio puede subir más de lo que el suelo indica.
• EARLY BIRD: Sep/Oct a >60d con <15% occ → precio bajado para capturar primeras reservas.
  Una vez llega demanda, el motor sube el precio automáticamente.
• DEMANDA NO RESTRINGIDA (UNC): Escasez histórica detectada → uplift aplicado.

═══ DATOS OTB Y CONTEXTO ═══
Revenue YTD 2026: +14.8% vs 2025.
OTB futuro jul 2026: +43% vs mismo punto 2025 → DEMANDA MUY FUERTE.
OTB futuro ago 2026: +49% vs mismo punto 2025 → DEMANDA MUY FUERTE.
MONTHLY_FLOOR (publicado): jul=320€, ago=367€. Genius = publicado × 0.85.
Techo: jul=650€, ago=700€.
GENIUS_COMPENSATION=1.18 (neto × 1.18 = publicado).

═══ RESUMEN PRICING POR MES ═══
{chr(10).join(month_summary)}

═══ PRÓXIMOS 14 DÍAS ═══
{chr(10).join(detail_14d)}

═══ JUNIO-SEPTIEMBRE DETALLE ═══
{chr(10).join(detail_verano)}

═══ TU TAREA ═══
Busca oportunidades de SUBIR precios donde la demanda lo justifique.
Prioriza según el status Beat-the-Best: los meses REZAGADOS (⚠️) necesitan subidas.

REGLAS:
1. ESCASEZ julio-agosto: 1-2 aptos libres → ¿el precio refleja la escasez real?
   Con 1 libre en agosto (demanda +49%), ¿está al techo o hay margen?
2. SUELO DINÁMICO activo + poca disponibilidad: el motor fijó un suelo bajo para capturar demanda anticipada,
   pero si ya hay pocas plazas libres, el precio puede subir más. Identifica estas fechas.
3. DEMANDA NO RESTRINGIDA ya aplicada: revisa si el uplift fue suficiente.
4. FINES DE SEMANA: ¿premium adicional justificado en temporada alta?
5. TEMPORADA BAJA: solo recomendar bajadas si inventario en riesgo de quedar vacío.
   En julio-agosto NUNCA bajar, salvo 7+ aptos libres.

NUNCA recomiendes bajar precios cuando:
- Hay suelo dinámico activo (ya está por debajo del suelo nominal)
- El mes tiene status 🏆 ON TRACK en Beat-the-Best

Responde SOLO en JSON exacto:
{{
  "analisis": "2-3 frases sobre la situación general y oportunidades detectadas",
  "btb_comentario": "1 frase sobre el status Beat-the-Best y qué meses necesitan acción",
  "ajustes": [
    {{"fecha": "2026-07-01", "precio_actual": 320, "precio_recomendado": 340, "motivo": "..."}}
  ],
  "revenue_impact_estimado": "+X€ mensual"
}}

Si no hay ajustes necesarios, devuelve ajustes como array vacío.
Sé agresivo subiendo cuando quedan 1-2 libres en verano y la demanda es fuerte.
"""

    return context


def _call_claude(context):
    """Call Claude API and return the response text."""
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": MODEL,
        "max_tokens": 4096,
        "messages": [
            {"role": "user", "content": context}
        ],
    }

    response = requests.post(
        ANTHROPIC_API_URL,
        headers=headers,
        json=payload,
        timeout=60,
    )

    if response.status_code != 200:
        log.warning(f"  Claude API error: HTTP {response.status_code} — {response.text[:200]}")
        return None

    data = response.json()
    text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            text += block["text"]

    return text


def _parse_adjustments(response_text):
    """Parse Claude's JSON response into a list of adjustments."""
    try:
        text = response_text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        data = json.loads(text)

        analisis = data.get("analisis", "")
        if analisis:
            log.info(f"  🧠 Claude análisis: {analisis}")

        btb_comentario = data.get("btb_comentario", "")
        if btb_comentario:
            log.info(f"  🏆 BTB: {btb_comentario}")

        impact = data.get("revenue_impact_estimado", "")
        if impact:
            log.info(f"  🧠 Claude impacto estimado: {impact}")

        return data.get("ajustes", [])

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        log.warning(f"  Claude response parse error: {e}")
        log.warning(f"  Raw response: {response_text[:500]}")
        return []


def _apply_adjustments(results, adjustments):
    """Apply Claude's recommended price adjustments to results."""
    by_date = {r["date"]: r for r in results}

    applied = 0
    for adj in adjustments:
        fecha = adj.get("fecha", "")
        nuevo_precio = adj.get("precio_recomendado")
        motivo = adj.get("motivo", "")

        if not fecha or not nuevo_precio:
            continue

        r = by_date.get(fecha)
        if not r:
            continue

        nuevo_precio = int(nuevo_precio)

        # Safety: never go below floor or above ceiling
        if nuevo_precio < r["suelo"]:
            nuevo_precio = r["suelo"]
        if nuevo_precio > r["techo"]:
            nuevo_precio = r["techo"]

        # Safety: max 20% change from v7.5 calculation
        original = r["precioFinal"]
        max_up = round(original * 1.20)
        max_down = round(original * 0.80)
        nuevo_precio = max(max_down, min(max_up, nuevo_precio))

        if nuevo_precio != original:
            r["precioFinal"] = nuevo_precio
            r["precioGenius"] = round(nuevo_precio * 0.85)
            r["claudeAjuste"] = True
            r["claudeMotivo"] = motivo
            r["claudePrecioOriginal"] = original
            applied += 1
            log.info(f"    {fecha}: {original}€ → {nuevo_precio}€ ({motivo})")

    return results
