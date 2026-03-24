"""
Claude API — Intelligent pricing decisions.
Uses Claude to analyze OTB, pace, comp set, and recommend pricing adjustments.

This is NOT a replacement for the v7 engine. It's a layer ON TOP that:
1. Reviews the v7 output
2. Identifies opportunities the mechanical engine misses
3. Suggests adjustments that the engine then applies

Runs after calcular_precios_v7() and before aplicar_precios().
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
MODEL = "claude-sonnet-4-20250514"


def optimize_with_claude(results, otb):
    """Let Claude review v7 pricing and suggest improvements.
    
    Returns modified results with Claude's adjustments applied.
    """
    if not ANTHROPIC_API_KEY:
        log.warning("  No ANTHROPIC_API_KEY — skipping Claude optimization")
        return results

    log.info("  🧠 Claude API: analizando pricing...")

    # Build context for Claude
    context = _build_context(results, otb)

    # Ask Claude for pricing adjustments
    try:
        response = _call_claude(context)
        if not response:
            return results

        # Parse and apply adjustments
        adjustments = _parse_adjustments(response)
        if adjustments:
            results = _apply_adjustments(results, adjustments)
            log.info(f"  🧠 Claude: {len(adjustments)} ajustes aplicados")
        else:
            log.info("  🧠 Claude: sin ajustes recomendados")

    except Exception as e:
        log.warning(f"  🧠 Claude error: {e}")

    return results


def _build_context(results, otb):
    """Build a concise summary of the pricing situation for Claude."""
    today = date.today()
    
    # Summary by month
    months = {}
    for r in results:
        m = r["date"][:7]
        if m not in months:
            months[m] = {
                "dias": 0, "sum_precio": 0, "sum_reserv": 0,
                "suelos": 0, "techos": 0, "min_disp": 9, "max_disp": 0,
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

    month_summary = []
    for m in sorted(months.keys()):
        mm = months[m]
        adr = round(mm["sum_precio"] / mm["dias"])
        genius = round(adr * 0.85)
        occ = round(mm["sum_reserv"] / (mm["dias"] * config.TOTAL_UNITS) * 100)
        month_summary.append(
            f"{m}: ADR={adr}€ Genius={genius}€ Occ={occ}% "
            f"Disp={mm['min_disp']}-{mm['max_disp']} "
            f"Suelos={mm['suelos']}/{mm['dias']} Techos={mm['techos']}/{mm['dias']}"
        )

    # Next 30 days detail
    detail_30d = []
    for r in results[:30]:
        detail_30d.append(
            f"{r['date']} disp={r['disponibles']} precio={r['precioFinal']}€ "
            f"genius={round(r['precioFinal']*0.85)}€ suelo={r['suelo']} techo={r['techo']} "
            f"neto={r.get('precioNeto','')} clamp={r.get('clampedBy','')} "
            f"event={r.get('eventName','')}"
        )

    # High-value months detail (jun-sep)
    detail_verano = []
    for r in results:
        m = int(r["date"][5:7])
        if m < 6 or m > 9:
            continue
        detail_verano.append(
            f"{r['date']} disp={r['disponibles']} precio={r['precioFinal']}€ "
            f"neto={r.get('precioNeto','')} suelo={r['suelo']} "
            f"clamp={r.get('clampedBy','')} fcst={r.get('forecastDemanda','')}"
        )

    context = f"""Eres el Director de Revenue Management de Apartamentos Estanques, 9 apartamentos vacacionales en Colònia de Sant Jordi, Mallorca.

DATOS DE LA PROPIEDAD:
- 9 apartamentos (8 planta alta + 1 planta baja con premium)
- Mercados principales: Alemania, Holanda, UK, España
- ADR Genius 2025: julio 272€, agosto 312€
- Revenue YTD 2026: +14.8% vs 2025
- OTB futuro: julio +43%, agosto +49% vs mismo punto 2025

COMP SET ADR (€/noche por mes):
{json.dumps(config.COMP_SET["ADR_PEER"], indent=2)}

RESUMEN POR MES (precios calculados por el motor v7):
{chr(10).join(month_summary)}

PRÓXIMOS 30 DÍAS DETALLE:
{chr(10).join(detail_30d)}

JUNIO-SEPTIEMBRE DETALLE:
{chr(10).join(detail_verano)}

REGLAS DEL SISTEMA:
- MONTHLY_FLOOR julio=320€ agosto=367€ (precio publicado, no Genius)
- GENIUS_COMPENSATION=1.18 (precio neto × 1.18 = precio publicado)
- El motor v7 calcula precios mecánicamente: Capa A × forecast × Genius comp
- Muchos días tocan SUELO porque el precio neto × 1.18 no supera el floor

TU TAREA:
Analiza los precios y recomienda ajustes CONCRETOS para maximizar revenue.
Para cada ajuste, especifica: fecha, precio_actual, precio_recomendado, motivo.

Responde SOLO en JSON con este formato exacto:
{{
  "analisis": "Tu análisis en 2-3 frases",
  "ajustes": [
    {{"fecha": "2026-07-01", "precio_actual": 320, "precio_recomendado": 340, "motivo": "..."}},
  ],
  "revenue_impact_estimado": "+X€ mensual"
}}

Si no hay ajustes necesarios, devuelve ajustes como array vacío.
Sé agresivo en temporada alta cuando la demanda lo justifica.
Sé conservador en temporada baja — mejor vender barato que no vender.
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
        # Find JSON in the response
        text = response_text.strip()
        # Handle markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        data = json.loads(text)

        analisis = data.get("analisis", "")
        if analisis:
            log.info(f"  🧠 Claude análisis: {analisis}")

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
    # Index results by date for quick lookup
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

        # Safety: never go below floor or above ceiling
        nuevo_precio = int(nuevo_precio)
        if nuevo_precio < r["suelo"]:
            nuevo_precio = r["suelo"]
        if nuevo_precio > r["techo"]:
            nuevo_precio = r["techo"]

        # Safety: max 20% change from v7 calculation
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
