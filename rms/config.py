"""
RMS Estanques — Configuration
All pricing parameters, property details, and system settings.

UPDATED: v7.2.1 — 25 marzo 2026
- Techos calibrados con datos reales (max vendido 468€, no fantasía de 700€)
- Floors subidos para proteger últimas unidades en verano
- preciosPorDisp julio/agosto importados de GAS CAPA_A_OVERRIDE_UA (probados en producción)
- Comp set reducido a 6 peers reales (<1.5km)
- RECORDAR: precios en Beds24, Genius descuenta 15% al huésped
"""

import os
from datetime import datetime

# ══════════════════════════════════════════
# PROPERTY
# ══════════════════════════════════════════
PROPERTY_ID = 119628
ROOM_UPPER = 269521
ROOM_GROUND = 269520
TOTAL_UNITS = 9

BEDS24_API = "https://beds24.com/api/v2"
ALERT_EMAIL = "alvaro.estanques@gmail.com"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# ══════════════════════════════════════════
# CREDENTIALS (from environment variables)
# ══════════════════════════════════════════
BEDS24_REFRESH_TOKEN = os.getenv("BEDS24_REFRESH_TOKEN", "")
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
SMTP_USER = os.getenv("SMTP_USER", ALERT_EMAIL)
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SHEET_ID = os.getenv("SHEET_ID", "1aL5--wWdHiQV_G30YcbLKzt4stoPI_Ma24Me1QSTcEc")

# ══════════════════════════════════════════
# PRICING HORIZON
# ══════════════════════════════════════════
PRICING_HORIZON = 365
HISTORICAL_YEARS = [datetime.now().year - 1]
CURVE_WEIGHTS = {datetime.now().year - 1: 1.0}

# ══════════════════════════════════════════
# SEASONS
# ══════════════════════════════════════════
SEASON_CODE = {
    1: "B", 2: "B", 3: "MB", 4: "M", 5: "MA", 6: "A",
    7: "UA", 8: "UA", 9: "A", 10: "MA", 11: "B", 12: "MB",
}

# ══════════════════════════════════════════
# SEGMENT BASE — Real Capa A from production
# preciosPorDisp: {1: price_1_free, ..., 9: price_9_free}
#
# NOTA: Estos precios van a Beds24. El huésped Genius ve ~85% de esto.
# Ejemplo: disp=1 agosto WD = 420€ en Beds24 → Genius paga 357€
#
# v7.2.1: julio y agosto recalibrados con datos de GAS CAPA_A_OVERRIDE_UA
# que generaron el revenue real de 2025. Techos bajados a valores realistas.
# ══════════════════════════════════════════
SEGMENT_BASE = {
    "1-WD": {"code": "B",  "base": 40,  "suelo": 35,  "techo": 105,
             "preciosPorDisp": {1: 70, 2: 60, 3: 40, 4: 40, 5: 40, 6: 40, 7: 40, 8: 40, 9: 40}},
    "1-WE": {"code": "B",  "base": 40,  "suelo": 35,  "techo": 120,
             "preciosPorDisp": {1: 80, 2: 60, 3: 60, 4: 40, 5: 40, 6: 40, 7: 40, 8: 40, 9: 40}},
    "2-WD": {"code": "B",  "base": 60,  "suelo": 48,  "techo": 150,
             "preciosPorDisp": {1: 100, 2: 80, 3: 80, 4: 70, 5: 70, 6: 60, 7: 60, 8: 60, 9: 60}},
    "2-WE": {"code": "B",  "base": 60,  "suelo": 48,  "techo": 165,
             "preciosPorDisp": {1: 110, 2: 100, 3: 90, 4: 80, 5: 70, 6: 60, 7: 60, 8: 60, 9: 60}},
    "3-WD": {"code": "MB", "base": 70,  "suelo": 56,  "techo": 165,
             "preciosPorDisp": {1: 110, 2: 100, 3: 90, 4: 80, 5: 80, 6: 70, 7: 70, 8: 70, 9: 70}},
    "3-WE": {"code": "MB", "base": 70,  "suelo": 56,  "techo": 180,
             "preciosPorDisp": {1: 120, 2: 90, 3: 80, 4: 80, 5: 70, 6: 70, 7: 70, 8: 70, 9: 70}},
    "4-WD": {"code": "M",  "base": 100, "suelo": 80,  "techo": 195,
             "preciosPorDisp": {1: 130, 2: 120, 3: 120, 4: 110, 5: 110, 6: 110, 7: 100, 8: 100, 9: 100}},
    "4-WE": {"code": "M",  "base": 100, "suelo": 80,  "techo": 210,
             "preciosPorDisp": {1: 140, 2: 130, 3: 120, 4: 120, 5: 110, 6: 110, 7: 100, 8: 100, 9: 100}},
    "5-WD": {"code": "MA", "base": 110, "suelo": 88,  "techo": 240,
             "preciosPorDisp": {1: 160, 2: 140, 3: 130, 4: 130, 5: 120, 6: 110, 7: 110, 8: 110, 9: 110}},
    "5-WE": {"code": "MA", "base": 120, "suelo": 88,  "techo": 240,
             "preciosPorDisp": {1: 160, 2: 160, 3: 140, 4: 130, 5: 130, 6: 120, 7: 110, 8: 110, 9: 110}},
    "6-WD": {"code": "A",  "base": 170, "suelo": 112, "techo": 345,
             "preciosPorDisp": {1: 230, 2: 210, 3: 200, 4: 190, 5: 170, 6: 170, 7: 160, 8: 140, 9: 140}},
    "6-WE": {"code": "A",  "base": 170, "suelo": 128, "techo": 360,
             "preciosPorDisp": {1: 240, 2: 210, 3: 200, 4: 190, 5: 180, 6: 170, 7: 170, 8: 160, 9: 160}},
    # ── JULIO v7.2.1: importado de GAS CAPA_A_OVERRIDE_UA ──
    # disp=1 WD 400€ → Genius 340€ | disp=1 WE 420€ → Genius 357€
    "7-WD": {"code": "UA", "base": 260, "suelo": 168, "techo": 520,
             "preciosPorDisp": {1: 400, 2: 355, 3: 325, 4: 305, 5: 290, 6: 280, 7: 275, 8: 270, 9: 265}},
    "7-WE": {"code": "UA", "base": 260, "suelo": 168, "techo": 520,
             "preciosPorDisp": {1: 420, 2: 375, 3: 340, 4: 320, 5: 305, 6: 295, 7: 285, 8: 280, 9: 275}},
    # ── AGOSTO v7.2.1: importado de GAS CAPA_A_OVERRIDE_UA ──
    # disp=1 WD 440€ → Genius 374€ | disp=1 WE 460€ → Genius 391€
    # Max real vendido ago 2025 = 468€ (Genius 398€)
    "8-WD": {"code": "UA", "base": 300, "suelo": 208, "techo": 540,
             "preciosPorDisp": {1: 440, 2: 395, 3: 360, 4: 335, 5: 320, 6: 310, 7: 300, 8: 295, 9: 290}},
    "8-WE": {"code": "UA", "base": 300, "suelo": 208, "techo": 540,
             "preciosPorDisp": {1: 460, 2: 415, 3: 380, 4: 355, 5: 340, 6: 325, 7: 315, 8: 305, 9: 300}},
    "9-WD": {"code": "A",  "base": 180, "suelo": 136, "techo": 345,
             "preciosPorDisp": {1: 230, 2: 210, 3: 200, 4: 190, 5: 180, 6: 180, 7: 170, 8: 170, 9: 170}},
    "9-WE": {"code": "A",  "base": 180, "suelo": 136, "techo": 345,
             "preciosPorDisp": {1: 230, 2: 210, 3: 200, 4: 190, 5: 190, 6: 180, 7: 180, 8: 170, 9: 170}},
    "10-WD": {"code": "MA", "base": 120, "suelo": 96,  "techo": 255,
              "preciosPorDisp": {1: 170, 2: 160, 3: 140, 4: 140, 5: 140, 6: 130, 7: 120, 8: 120, 9: 120}},
    "10-WE": {"code": "MA", "base": 120, "suelo": 96,  "techo": 255,
              "preciosPorDisp": {1: 170, 2: 160, 3: 150, 4: 140, 5: 140, 6: 130, 7: 120, 8: 120, 9: 120}},
    "11-WD": {"code": "B",  "base": 70,  "suelo": 56,  "techo": 150,
              "preciosPorDisp": {1: 100, 2: 100, 3: 90, 4: 80, 5: 80, 6: 70, 7: 70, 8: 70, 9: 70}},
    "11-WE": {"code": "B",  "base": 70,  "suelo": 56,  "techo": 165,
              "preciosPorDisp": {1: 110, 2: 100, 3: 90, 4: 80, 5: 80, 6: 80, 7: 70, 8: 70, 9: 70}},
    "12-WD": {"code": "MB", "base": 120, "suelo": 96,  "techo": 225,
              "preciosPorDisp": {1: 150, 2: 120, 3: 120, 4: 120, 5: 120, 6: 120, 7: 120, 8: 120, 9: 120}},
    "12-WE": {"code": "MB", "base": 120, "suelo": 96,  "techo": 225,
              "preciosPorDisp": {1: 150, 2: 140, 3: 120, 4: 120, 5: 120, 6: 120, 7: 120, 8: 120, 9: 120}},
}

CHECKPOINTS = [120, 105, 90, 75, 60, 45, 30, 21, 14, 10, 7, 3, 0]

# ══════════════════════════════════════════
# PRICE SLOTS (Beds24 calendar fields)
# ══════════════════════════════════════════
PRICE_SLOTS = {
    "STANDARD": "price1",
    "6NOCHES": "price3",
    "5NOCHES": "price4",
    "4NOCHES": "price5",
    "SEMANAL":  "price10",
}

# ══════════════════════════════════════════
# DURATION DISCOUNTS
# ══════════════════════════════════════════
DURATION_DISCOUNTS_DYNAMIC = {
    "4NOCHES": {"base": 0.82, "min": 0.90},
    "5NOCHES": {"base": 0.75, "min": 0.85},
    "6NOCHES": {"base": 0.68, "min": 0.80},
    "SEMANAL":  {"base": 0.60, "min": 0.75},
}

DURATION_FLOOR_FACTOR = {
    "4NOCHES": 0.92,
    "5NOCHES": 0.85,
    "6NOCHES": 0.78,
    "SEMANAL":  0.70,
}

DURATION_DISCOUNT_OCC_LOW = 0.30
DURATION_DISCOUNT_OCC_HIGH = 0.75

DURATION_DISCOUNTS = {
    "4NOCHES": 0.87, "5NOCHES": 0.82, "6NOCHES": 0.77, "SEMANAL": 0.72,
}

# ══════════════════════════════════════════
# FLOORS & CEILINGS
# Todos los precios = lo que va a Beds24
# Genius = precio * 0.85 (lo que ve el huésped)
# ══════════════════════════════════════════
SEASONAL_FLOOR = {
    "B": 75, "MB": 90, "M": 140, "MA": 165, "A": 235, "UA": 395,
}

# v7.2.1: julio 320→390 (Genius 332€), agosto 367→440 (Genius 374€)
MONTHLY_FLOOR = {
    1: 60, 2: 65, 3: 95, 4: 130, 5: 170, 6: 260,
    7: 390, 8: 440, 9: 280, 10: 175, 11: 70, 12: 85,
}

# v7.2.1: julio 650→520 (Genius 442€), agosto 700→540 (Genius 459€)
# Max real vendido = 468€ en Beds24 (Genius 398€). Techo da ~15% margen.
MONTHLY_CEILING = {
    1: 180, 2: 180, 3: 200, 4: 310, 5: 360, 6: 500,
    7: 520, 8: 540, 9: 500, 10: 380, 11: 180, 12: 250,
}

CEILING_BY_SEASON = {
    "B": 2.00, "MB": 2.00, "M": 1.80, "MA": 1.80, "A": 1.80, "UA": 2.00,
}

WEEKEND_FLOOR_PREMIUM = {
    "UA": 1.10, "A": 1.10, "MA": 1.08, "M": 1.05, "MB": 1.00, "B": 1.00,
}

# ══════════════════════════════════════════
# PRICE PROTECTION
# ══════════════════════════════════════════
PRICE_PROTECTION_BY_DAYS = {60: 0.95, 30: 0.85, 14: 0.75, 7: 0.60, 0: 0.00}

MIN_BOOKING_REVENUE = {
    "B": 362, "MB": 362, "M": 550, "MA": 700, "A": 950, "UA": 2100,
}

# ══════════════════════════════════════════
# GENIUS COMPENSATION
# precio_publicado = precio_neto * 1.18
# Para que tras -15% Genius, revenue ≈ precio_neto
# ══════════════════════════════════════════
GENIUS_COMPENSATION = 1.18

# ══════════════════════════════════════════
# MIN STAY
# ══════════════════════════════════════════
DEFAULT_MIN_STAY = {"B": 3, "MB": 3, "M": 3, "MA": 4, "A": 5, "UA": 7}

MIN_STAY_REDUCTION = {
    "threshold_high": 0.70,
    "threshold_vhigh": 0.85,
    "absolute_min": 3,
    "absolute_min_winter": 3,
    "days_close": 21,
    "days_very_close": 7,
}

MIN_STAY_DYNAMIC = {
    "below_pace_threshold": -0.15,
    "below_pace_severe": -0.30,
    "above_pace_threshold": 0.10,
    "above_pace_strong": 0.25,
}

# ══════════════════════════════════════════
# LOS DINÁMICO
# ══════════════════════════════════════════
LOS_DINAMICO = {
    "enabled": True,
    "ABSOLUTE_MIN": {"UA": 3, "A": 3, "MA": 3, "M": 3, "MB": 3, "B": 3},
    "ESCALONES": [
        {"nombre": "HORIZONTE_LARGO", "dias_max": 999, "dias_min": 31,
         "reduccion": 0, "precio_premium": 1.00, "requiere_occ_baja": False},
        {"nombre": "MEDIO_PLAZO", "dias_max": 30, "dias_min": 15,
         "reduccion": 1, "precio_premium": 1.12, "requiere_occ_baja": True},
        {"nombre": "CORTO_PLAZO", "dias_max": 14, "dias_min": 8,
         "reduccion": 2, "precio_premium": 1.10, "requiere_occ_baja": True},
        {"nombre": "LAST_MINUTE", "dias_max": 7, "dias_min": 0,
         "reduccion": 3, "precio_premium": 1.06, "requiere_occ_baja": False},
    ],
    "OCC_NO_REDUCIR": {"UA": 0.70, "A": 0.75, "MA": 0.65, "M": 0.60, "MB": 0.55, "B": 0.50},
    "OCC_SUBIR_MINSTAY": {"UA": 0.85, "A": 0.80, "MA": 0.75, "M": 0.70, "MB": 0.65, "B": 0.60},
    "GAPS": {
        "horizonte_dias": 30,
        "occ_vecinos_alta": 0.78,
        "max_gap_noches": 4,
        "min_disponibles_gap": 1,
        "max_disponibles_gap": 4,
    },
}

# ══════════════════════════════════════════
# LAST MINUTE WINTER
# ══════════════════════════════════════════
LAST_MINUTE_WINTER = {
    "enabled": True,
    "seasons": ["B", "MB"],
    "max_days_out": 14,
    "min_units_free": 6,
    "price_protection_override": 0.40,
    "factor_min_override": 0.60,
    "suelo_override_pct": 0.70,
    "level2_days": 7,
    "level2_min_units": 7,
    "level2_protection": 0.00,
    "level2_factor_min": 0.50,
    "level2_suelo_pct": 0.60,
}

# ══════════════════════════════════════════
# COMP SET
# ══════════════════════════════════════════
COMP_SET = {
    "enabled": True,
    "ADR_PEER": {
        1: 70, 2: 97, 3: 103, 4: 121, 5: 131, 6: 165,
        7: 230, 8: 247, 9: 180, 10: 140, 11: 85, 12: 100,
    },
    "FLOOR_VS_PEER": 0.90,
    "CEILING_VS_PEER": 1.50,
    "APIFY_MAX_AGE_DAYS": 14,
}

# ══════════════════════════════════════════
# GROUND FLOOR
# ══════════════════════════════════════════
GROUND_FLOOR_LOS = {
    "enabled": True,
    "absolute_min": 2,
    "upper_occ_threshold": 0.75,
    "temporadas_protegidas": ["A", "UA"],
}

# ══════════════════════════════════════════
# EVENTS CONFIG
# ══════════════════════════════════════════
EVENTS_OVERLAP_RULE = "MAX"

# ══════════════════════════════════════════
# V7 ENGINE CONFIG
# ══════════════════════════════════════════
V7 = {
    # v7.2.1: julio 320→360, agosto 367→400 (coherente con MONTHLY_FLOOR)
    "MONTHLY_FLOOR_V7": {
        1: 78, 2: 89, 3: 94, 4: 134, 5: 154, 6: 218,
        7: 390, 8: 440, 9: 222, 10: 161, 11: 94, 12: 148,
    },

    "FORECAST": {
        "PACE_SENS": 0.30,
        "PACE_MIN": 0.80,
        "PACE_MAX": 1.20,
        "PICKUP_SENS": 0.20,
        "PICKUP_MIN": 0.85,
        "PICKUP_MAX": 1.15,
        "EVENTO_MIN": 0.90,
        "EVENTO_MAX": 1.30,
        "VAC_MIN": 0.95,
        "VAC_MAX": 1.15,
        "TRENDS_MIN": 0.95,
        "TRENDS_MAX": 1.10,
    },

    "OPTIM": {
        "PESO_REAL": 0.70,
        "PESO_FORECAST": 0.30,
    },

    "SUAVIZADO": {
        "MAX_VARIACION_DIARIA": 0.12,
    },

    "COMP_SET_ADJ": {
        "RATIO_ALTO": 1.40,
        "FACTOR_ALTO": 0.95,
        "RATIO_MEDIO": 1.25,
        "FACTOR_MEDIO": 0.98,
    },
}

# ══════════════════════════════════════════
# ALERTAS
# ══════════════════════════════════════════
ALERTAS_ANOMALIAS = {
    "enabled": True,
    "GAP_URGENTE": {
        "enabled": True,
        "horizonte_dias": 14,
        "min_disponibles": 5,
        "gap_critico_disponibles": 7,
        "gap_critico_dias": 7,
    },
    "PICKUP_MUERTO": {
        "enabled": True,
        "horizonte_semanas": 8,
        "min_dias_futuro": 7,
        "pickup_minimo": 1,
        "occ_threshold": 0.70,
    },
    "COMPSET_SALTO": {
        "enabled": True,
        "pct_cambio_alerta": 0.15,
        "pct_cambio_critico": 0.25,
        "meses_a_vigilar": [4, 5, 6, 7, 8, 9, 10],
    },
    "COOLDOWN_HORAS": 48,
}

# ══════════════════════════════════════════
# APIFY — v7.2.1: reducido a 6 peers reales
# ══════════════════════════════════════════
APIFY_CONFIG = {
    "ACTOR_ID": "voyager~booking-scraper",
    "COMP_SET_URLS": [
        "https://www.booking.com/hotel/es/apartamentos-piza.es.html",
        "https://www.booking.com/hotel/es/apartamentos-lemar-colonia-de-sant-jordi.es.html",
        "https://www.booking.com/hotel/es/aparthotelisladecabrera.es.html",
        "https://www.booking.com/hotel/es/blue-house-mallorca.es.html",
        "https://www.booking.com/hotel/es/apartamentos-ibiza-colonia-de-sant-jordi1.es.html",
        "https://www.booking.com/hotel/es/villa-piccola-by-cassai.es.html",
    ],
    "SCRAPE_ROTATION": {
        "enabled": True,
        "MESES_POR_DIA": {
            1: [1, 4],
            3: [2, 5],
            5: [3, 6],
        },
        "MAX_MESES_POR_EJECUCION": 2,
    },
    "SCRAPE_PROFILES": {
        "DEFAULT": {"nights": 3, "adults": 2},
        "SUMMER":  {"nights": 7, "adults": 4},
    },
    "SUMMER_MONTHS": [6, 7, 8, 9],
    "MAX_WAIT_SECONDS": 120,
    "POLL_INTERVAL_MS": 5000,
}

# ══════════════════════════════════════════
# VACACIONES ESCOLARES
# ══════════════════════════════════════════
CAPA_EVENTOS = {
    "enabled": True,
    "MERCADOS": [
        {"pais": "DE", "nombre": "Alemania", "peso": 1.0, "subdivisiones": True},
        {"pais": "NL", "nombre": "Holanda", "peso": 0.7, "subdivisiones": True},
        {"pais": "GB", "nombre": "Reino Unido", "peso": 0.5, "subdivisiones": True},
    ],
    "MAX_BOOST": 0.15,
    "MIN_PCT_PARA_BOOST": 0.10,
    "MESES_ACTIVOS": [3, 4, 5, 6, 7, 8, 9, 10],
    "API_BASE": "https://openholidaysapi.org",
    "HORIZONTE_MESES": 12,
}

# ══════════════════════════════════════════
# MONTHLY ALERTS
# ══════════════════════════════════════════
MONTHLY_ALERTS = {
    "enabled": True,
    "threshold_warning": -0.10,
    "threshold_critical": -0.20,
}

# ══════════════════════════════════════════
# DEMAND CURVE (Capa A)
# ══════════════════════════════════════════
DEMAND_CURVE = {
    "PRICE_STEP": 10,
    "MIN_OBS_PER_RANGE": 20,
    "CEILING_MULTIPLIER": 1.50,
}
