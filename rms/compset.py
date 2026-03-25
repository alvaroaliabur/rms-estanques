# ============================================================
# COMP SET — RMS Estanques v7.2.2
# ============================================================
#
# DOS NIVELES DE COMP SET:
#
# TIER 1 — PRICING PEERS (ajustan precio dinámico)
#   Apartamentos similares en Colònia de Sant Jordi (<2km).
#   Sus precios se usan para moderar los tuyos si te alejas mucho.
#
# TIER 2 — MARKET REFERENCE (solo monitoring)
#   Los 25 de BDC: agroturismos, aparthoteles lejanos, etc.
#   Se scrapean para ver tendencias de mercado pero NO ajustan precio.
#   Nota: muchos tienen piscina y Estanques no. Producto diferente.
#
# Fuente: BDC "Alojamientos comparables" actualizado 10-mar-2026.
# Basado en clics, vistas y reservas reales de viajeros.
#
# v7.2.2: Añadido check_and_update_comp_set() requerido por main.py
# ============================================================

import logging
import os
import time
import requests
from datetime import datetime, timedelta

logger = logging.getLogger("rms.compset")

# ════════════════════════════════════════════════════════════
# TIER 1 — PRICING PEERS (ajustan precio)
# Apartamentos comparables <2km en Colònia de Sant Jordi
# ════════════════════════════════════════════════════════════

PRICING_PEERS = [
    {
        "name": "Apartamentos Piza",
        "url": "https://www.booking.com/hotel/es/apartamentos-piza.es.html",
        "distance_km": 0.35,
        "type": "apartamentos",
    },
    {
        "name": "Apartamentos Lemar",
        "url": "https://www.booking.com/hotel/es/apartamentos-lemar-colonia-de-sant-jordi.es.html",
        "distance_km": 0.20,
        "type": "apartamentos",
    },
    {
        "name": "Aparthotel Isla de Cabrera",
        "url": "https://www.booking.com/hotel/es/aparthotelisladecabrera.es.html",
        "distance_km": 0.43,
        "type": "aparthotel",
    },
    {
        "name": "Blue House Mallorca",
        "url": "https://www.booking.com/hotel/es/blue-house-mallorca.es.html",
        "distance_km": 0.91,
        "type": "apartamentos",
    },
    {
        "name": "Apartamentos Ibiza",
        "url": "https://www.booking.com/hotel/es/apartamentos-ibiza-colonia-de-sant-jordi1.es.html",
        "distance_km": 0.99,
        "type": "apartamentos",
    },
    {
        "name": "Villa Piccola by Cassai",
        "url": "https://www.booking.com/hotel/es/villa-piccola-by-cassai.es.html",
        "distance_km": 1.06,
        "type": "apartamentos",
    },
]

# ════════════════════════════════════════════════════════════
# TIER 2 — MARKET REFERENCE (solo monitoring, NO ajustan precio)
# BDC "Alojamientos comparables" — 19 props adicionales
# Basado en clics + reservas reales de viajeros.
# Actualizado: 10-mar-2026
# ════════════════════════════════════════════════════════════

MARKET_REFERENCE = [
    {
        "name": "Agroturismo Son Marge",
        "url": "https://www.booking.com/hotel/es/agroturismo-son-marge.es.html",
        "distance_km": 7.51,
        "type": "agroturismo",
    },
    {
        "name": "Agroturismo Son Barceló Mas",
        "url": "https://www.booking.com/hotel/es/son-barcelo-mas.es.html",
        "distance_km": 11.93,
        "type": "agroturismo",
    },
    {
        "name": "Finca Agroturismo Sa Cova den Borino",
        "url": "https://www.booking.com/hotel/es/finca-sa-cova-den-borino.es.html",
        "distance_km": 11.83,
        "type": "agroturismo",
    },
    {
        "name": "Finca Sa Canova Agroturismo",
        "url": "https://www.booking.com/hotel/es/finca-sa-canova-agroturismo-campos.es.html",
        "distance_km": 13.34,
        "type": "agroturismo",
    },
    {
        "name": "Apartamentos Cala Figuera",
        "url": "https://www.booking.com/hotel/es/apartamentos-cala-figuera-cala-figuera.es.html",
        "distance_km": 15.37,
        "type": "apartamentos",
    },
    {
        "name": "Apartamentos Villa Sirena",
        "url": "https://www.booking.com/hotel/es/carrer-de-l-esglesia-1.es.html",
        "distance_km": 15.42,
        "type": "apartamentos",
    },
    {
        "name": "Aparthotel Niu d'Aus",
        "url": "https://www.booking.com/hotel/es/aparthotel-niu-d-aus.es.html",
        "distance_km": 19.70,
        "type": "aparthotel",
    },
    {
        "name": "Agroturismo son Sampoli by MHR",
        "url": "https://www.booking.com/hotel/es/agroturismo-pol.es.html",
        "distance_km": 21.68,
        "type": "agroturismo",
    },
    {
        "name": "Apartamentos Sol Romántica by DOT Suites",
        "url": "https://www.booking.com/hotel/es/maritim-club-romantica.es.html",
        "distance_km": 34.55,
        "type": "apartamentos",
    },
    {
        "name": "S'Hort Can Capità",
        "url": "https://www.booking.com/hotel/es/s-hort-can-capita.es.html",
        "distance_km": 39.91,
        "type": "agroturismo",
    },
    {
        "name": "Sa Casa Rotja",
        "url": "https://www.booking.com/hotel/es/sa-casa-rotja.es.html",
        "distance_km": 39.65,
        "type": "agroturismo",
    },
    {
        "name": "Agroturisme Es Racó De Maria",
        "url": "https://www.booking.com/hotel/es/es-reco-de-maria.es.html",
        "distance_km": 40.77,
        "type": "agroturismo",
    },
    {
        "name": "Apartamentos Playa Moreia",
        "url": "https://www.booking.com/hotel/es/playa-moreia.es.html",
        "distance_km": 42.69,
        "type": "apartamentos",
    },
    {
        "name": "Apartamentos Xaloc HRC",
        "url": "https://www.booking.com/hotel/es/apartamentos-xaloc-cala-millor.es.html",
        "distance_km": 46.34,
        "type": "apartamentos",
    },
    {
        "name": "Apartaments Sa Torre by SUREDA MAS",
        "url": "https://www.booking.com/hotel/es/apartamentos-sa-torre.es.html",
        "distance_km": 53.78,
        "type": "apartamentos",
    },
    {
        "name": "Club del Sol Aparthotel",
        "url": "https://www.booking.com/hotel/es/club-del-sol-aparthotel.es.html",
        "distance_km": 63.02,
        "type": "aparthotel",
    },
    {
        "name": "Hotel Eu Bahia Pollença",
        "url": "https://www.booking.com/hotel/es/aparthotel-bahia-pollensa.es.html",
        "distance_km": 64.54,
        "type": "hotel",
    },
    {
        "name": "Apartamentos Bellamar",
        "url": "https://www.booking.com/hotel/es/apartamentos-bellamar.es.html",
        "distance_km": 64.99,
        "type": "apartamentos",
    },
    {
        "name": "Aparthotel Duva & Spa",
        "url": "https://www.booking.com/hotel/es/aparthotel-duva-spa.es.html",
        "distance_km": 65.55,
        "type": "aparthotel",
    },
]

# Nombres a EXCLUIR del scraping (nosotros mismos)
SELF_NAMES = [
    "estanques", "apartamentos estanques",
]

# ════════════════════════════════════════════════════════════
# CONFIGURACIÓN APIFY
# ════════════════════════════════════════════════════════════

APIFY_CONFIG = {
    "actor_id": "voyager~booking-scraper",
    "max_wait_seconds": 300,  # 5 min — startUrls tarda ~3min en Apify
    "poll_interval_seconds": 5,
    "scrape_windows_days": [14, 30, 60],  # 3 ventanas: suficiente para comp set
    "profiles": {
        "default": {"nights": 3, "adults": 2},
        "summer":  {"nights": 7, "adults": 4},
    },
    "summer_months": [6, 7, 8, 9],
}


def get_all_peer_urls():
    """URLs de PRICING PEERS para scraping con ajuste de precio."""
    return [p["url"] for p in PRICING_PEERS]


def get_all_market_urls():
    """URLs de MARKET REFERENCE para monitoring (sin ajuste de precio)."""
    return [m["url"] for m in MARKET_REFERENCE]


def get_all_urls():
    """Todas las URLs únicas (peers + market ref)."""
    urls = get_all_peer_urls() + get_all_market_urls()
    return list(dict.fromkeys(urls))  # deduplicate preserving order


def get_peer_names():
    """Nombres de pricing peers (para filtrado de resultados)."""
    return [p["name"] for p in PRICING_PEERS]


def is_self(name):
    """¿Es nuestra propia propiedad?"""
    if not name:
        return False
    name_lower = name.lower().strip()
    for s in SELF_NAMES:
        if s in name_lower:
            return True
    return False


def is_pricing_peer(name):
    """¿Es un pricing peer (tier 1)?"""
    if not name:
        return False
    name_lower = name.lower().strip()
    for p in PRICING_PEERS:
        if p["name"].lower() in name_lower or name_lower in p["name"].lower():
            return True
    return False


# ════════════════════════════════════════════════════════════
# SCRAPING — APIFY
# ════════════════════════════════════════════════════════════

def run_apify_scrape(apify_token, check_in, check_out, adults=2, urls=None):
    """
    Ejecuta scrape en Apify usando startUrls (URLs directas de hotel).
    NO usa 'search' — eso devuelve búsqueda genérica de la zona.
    Por defecto scrapea SOLO pricing peers.
    Para market reference, pasar urls=get_all_urls().
    """
    if not apify_token:
        logger.warning("No Apify token")
        return []

    if urls is None:
        urls = get_all_peer_urls()

    cfg = APIFY_CONFIG

    # Construir startUrls: cada URL de hotel como objeto {url: "..."}
    start_urls = [{"url": u} for u in urls]

    input_data = {
        "startUrls": start_urls,
        "checkIn": check_in,
        "checkOut": check_out,
        "adults": adults,
        "rooms": 1,
        "currency": "EUR",
        "language": "es",
        "maxItems": len(urls),
    }

    try:
        # Start run
        run_url = f"https://api.apify.com/v2/acts/{cfg['actor_id']}/runs?token={apify_token}"
        resp = requests.post(run_url, json=input_data, timeout=30)
        if resp.status_code != 201:
            logger.warning(f"Apify start failed: HTTP {resp.status_code}")
            return []

        run_data = resp.json()
        run_id = run_data["data"]["id"]
        dataset_id = run_data["data"]["defaultDatasetId"]

        # Poll for completion
        status_url = f"https://api.apify.com/v2/actor-runs/{run_id}?token={apify_token}"
        elapsed = 0
        status = "RUNNING"
        while status in ("RUNNING", "READY"):
            time.sleep(cfg["poll_interval_seconds"])
            elapsed += cfg["poll_interval_seconds"]
            if elapsed > cfg["max_wait_seconds"]:
                logger.warning(f"Apify timeout after {cfg['max_wait_seconds']}s")
                return []
            try:
                sr = requests.get(status_url, timeout=15)
                if sr.status_code == 200:
                    status = sr.json()["data"]["status"]
            except:
                pass

        if status != "SUCCEEDED":
            logger.warning(f"Apify run status: {status}")
            return []

        # Fetch results
        data_url = f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={apify_token}&format=json"
        dr = requests.get(data_url, timeout=30)
        if dr.status_code != 200:
            return []

        raw_results = dr.json()
        if not isinstance(raw_results, list):
            return []

        # Parse and filter
        nights = (datetime.strptime(check_out, "%Y-%m-%d") - datetime.strptime(check_in, "%Y-%m-%d")).days
        if nights < 1:
            nights = 1

        parsed = []
        for r in raw_results:
            name = r.get("name") or r.get("hotel_name") or "Desconocido"
            price = r.get("price") or r.get("room_price") or r.get("min_price") or 0

            # Filtrar: excluir nosotros mismos
            if is_self(name):
                logger.info(f"    Filtrado (self): {name}")
                continue

            ppn = round(price / nights) if price > 0 and nights > 0 else 0

            parsed.append({
                "name": name,
                "price_per_night": ppn,
                "price_total": price,
                "rating": r.get("rating") or 0,
                "review_count": r.get("reviewCount") or 0,
                "is_pricing_peer": is_pricing_peer(name),
                "check_in": check_in,
                "check_out": check_out,
            })

        return parsed

    except Exception as e:
        logger.error(f"Apify error: {e}")
        return []


def calculate_comp_set_adr(results, peers_only=True):
    """
    Calcula ADR del comp set.
    peers_only=True: solo PRICING PEERS (para ajuste de precio)
    peers_only=False: todos los resultados (para market reference)
    """
    if peers_only:
        prices = [r["price_per_night"] for r in results if r["price_per_night"] > 0 and r["is_pricing_peer"]]
    else:
        prices = [r["price_per_night"] for r in results if r["price_per_night"] > 0]

    if not prices:
        return 0

    prices.sort()

    # Trimmed mean: quitar extremos si hay suficientes datos
    if len(prices) >= 4:
        prices = prices[1:-1]

    return round(sum(prices) / len(prices))


def scrape_comp_set(apify_token, windows_config=None):
    """
    Ejecuta scraping completo del comp set.
    Retorna dict con ADR por ventana para PRICING PEERS
    y datos de MARKET REFERENCE por separado.
    """
    cfg = APIFY_CONFIG
    today = datetime.now()

    if windows_config is None:
        windows_config = cfg["scrape_windows_days"]

    results_by_window = {}
    market_results = []

    for days_out in windows_config:
        ci = today + timedelta(days=days_out)
        ci_month = ci.month
        is_summer = ci_month in cfg["summer_months"]
        profile = cfg["profiles"]["summer" if is_summer else "default"]

        co = ci + timedelta(days=profile["nights"])
        ci_str = ci.strftime("%Y-%m-%d")
        co_str = co.strftime("%Y-%m-%d")

        logger.info(f"  Scraping +{days_out}d ({ci_str}, {profile['nights']}n, {profile['adults']}a)...")

        # Scrape con TODAS las URLs (peers + market ref)
        results = run_apify_scrape(apify_token, ci_str, co_str, profile["adults"], get_all_urls())

        if results:
            # ADR de pricing peers (para ajuste de precio)
            adr_peers = calculate_comp_set_adr(results, peers_only=True)
            # ADR de todo el market (para referencia)
            adr_market = calculate_comp_set_adr(results, peers_only=False)

            n_peers = len([r for r in results if r["is_pricing_peer"] and r["price_per_night"] > 0])
            n_total = len([r for r in results if r["price_per_night"] > 0])

            logger.info(f"    +{days_out}d: ADR peers = {adr_peers}€ ({n_peers} peers) | ADR market = {adr_market}€ ({n_total} props)")

            # Log detalle
            for r in sorted(results, key=lambda x: -x["price_per_night"]):
                tag = "⭐" if r["is_pricing_peer"] else "  "
                logger.info(f"      {tag} {r['name']}: {r['price_per_night']}€/noche")

            results_by_window[days_out] = {
                "adr_peers": adr_peers,
                "adr_market": adr_market,
                "n_peers": n_peers,
                "n_total": n_total,
                "check_in": ci_str,
                "results": results,
            }

            market_results.extend(results)
        else:
            logger.warning(f"    +{days_out}d: Sin resultados")

        # Pausa entre scrapes
        time.sleep(3)

    return {
        "by_window": results_by_window,
        "market_results": market_results,
        "timestamp": datetime.now().isoformat(),
    }


# ════════════════════════════════════════════════════════════
# ORQUESTADOR — check_and_update_comp_set
# Llamado por main.py Step 3. Decide si toca scrapear.
# ════════════════════════════════════════════════════════════

# Estado interno: timestamp del último scrape exitoso
_last_scrape_ts = None


def check_and_update_comp_set():
    """
    Comprueba si el comp set necesita actualizarse (scrape periódico).
    - Si el último scrape fue hace < APIFY_MAX_AGE_DAYS → None (sin cambios)
    - Si toca → ejecuta scrape_comp_set() y actualiza config.COMP_SET["ADR_PEER"]
    - Retorna dict con resultados por ventana si se actualizó, None si no.
    """
    global _last_scrape_ts

    from rms import config

    apify_token = os.getenv("APIFY_TOKEN", "")
    if not apify_token:
        logger.warning("  No Apify token — saltando comp set update")
        return None

    max_age_days = config.COMP_SET.get("APIFY_MAX_AGE_DAYS", 14)

    # Check if we need to scrape
    if _last_scrape_ts:
        age = (datetime.now() - _last_scrape_ts).total_seconds() / 86400
        if age < max_age_days:
            logger.info(f"  Comp set fresh ({age:.1f}d < {max_age_days}d) — skip")
            return None

    logger.info("  Ejecutando scrape de comp set...")

    try:
        data = scrape_comp_set(apify_token)
    except Exception as e:
        logger.error(f"  Scrape error: {e}")
        return None

    if not data or not data.get("by_window"):
        logger.warning("  Scrape sin resultados")
        return None

    # Actualizar ADR_PEER en config con datos frescos de pricing peers
    updated_months = {}
    for days_out, window in data["by_window"].items():
        if window.get("adr_peers") and window["adr_peers"] > 0:
            ci = datetime.strptime(window["check_in"], "%Y-%m-%d")
            month = ci.month
            old_adr = config.COMP_SET["ADR_PEER"].get(month, 0)
            new_adr = window["adr_peers"]

            # Solo actualizar si hay cambio significativo (>5€)
            if abs(new_adr - old_adr) > 5:
                config.COMP_SET["ADR_PEER"][month] = new_adr
                updated_months[month] = {"old": old_adr, "new": new_adr, "days_out": days_out}
                logger.info(f"    ADR_PEER mes {month}: {old_adr}€ → {new_adr}€ (ventana +{days_out}d)")

    _last_scrape_ts = datetime.now()

    if updated_months:
        logger.info(f"  ✅ ADR_PEER actualizado: {len(updated_months)} meses")
    else:
        logger.info("  ADR_PEER sin cambios significativos")

    return data["by_window"]
