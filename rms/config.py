"""
RMS Estanques — Configuration
v7.5 — 26 marzo 2026

CAMBIOS v7.5:
- BEAT_THE_BEST: auditoría continua vs mejor año histórico por fecha
  El RMS siempre intenta batir occ+ADR del mejor año para cada día/mes
  La comparación es relativa a days_out: a 200d de agosto es normal tener 2/9
- DEMAND_UNCONSTRAINING: recalibrar precios de años antiguos al nivel actual
  De 2023/2024 usamos el patrón temporal pero recalibramos precios
  precio_2023 × (ADR_2025 / ADR_2023) → la curva no baja precios
- GOOGLE_CREDENTIALS_JSON para pickup persistente en Sheets
- SOURCE_TOKEN para endpoint /source
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
# CREDENTIALS
# ══════════════════════════════════════════
BEDS24_REFRESH_TOKEN = os.getenv("BEDS24_REFRESH_TOKEN", "")
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
SMTP_USER = os.getenv("SMTP_USER", ALERT_EMAIL)
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SHEET_ID = os.getenv("SHEET_ID", "1aL5--wWdHiQV_G30YcbLKzt4stoPI_Ma24Me1QSTcEc")

# v7.5: Google Sheets para persistencia OTB snapshots + price history
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
# Token para proteger /source endpoint (opcional)
SOURCE_TOKEN = os.getenv("SOURCE_TOKEN", "")

# ══════════════════════════════════════════
# PRICING HORIZON
# ══════════════════════════════════════════
PRICING_HORIZON = 365

# v7.4: 3 años para fill curves y pace
HISTORICAL_YEARS = [2023, 2024, 2025]
CURVE_WEIGHTS = {2023: 0.20, 2024: 0.35, 2025: 0.45}

# ══════════════════════════════════════════
# DEMAND UNCONSTRAINING — v7.5
#
# Problema: usar precios de 2023 (180€/noche en agosto) para construir
# la curva de demanda baja artificialmente los precios óptimos.
# 2025 vendió agosto a 308€ Genius — esa es la realidad del mercado.
#
# Solución (RM avanzado — "Demand Uncensoring"):
# De años anteriores usamos el PATRÓN temporal (cuándo se reservó,
# a qué antelación, WD/WE) pero recalibramos los precios:
#   precio_recalibrado = precio_original × (ADR_referencia / ADR_año)
#
# Así 3 años de datos contribuyen volumen de observaciones
# sin contaminar la curva de precios a la baja.
#
# ADR_REFERENCE: el nivel de precios "actual" (mejor año = 2025)
# ADR_BY_YEAR: ADR medio por mes y año (de Beds24 real)
# ══════════════════════════════════════════
DEMAND_UNCONSTRAINING = {
    "enabled": True,
    # Año de referencia para el nivel de precios
    "reference_year": 2025,
    # ADR Genius real por mes del año de referencia (2025)
    # Fuente: /revenue endpoint + Booking Analytics
    "ADR_REFERENCE": {
        1: 68, 2: 79, 3: 85, 4: 115, 5: 139, 6: 201,
        7: 282, 8: 308, 9: 184, 10: 140, 11: 70, 12: 85,
    },
    # ADR Genius real por mes de años históricos
    # Se usa para calcular el factor de recalibración
    "ADR_BY_YEAR": {
        2023: {
            1: 45, 2: 55, 3: 60, 4: 80, 5: 95, 6: 145,
            7: 195, 8: 215, 9: 130, 10: 100, 11: 50, 12: 60,
        },
        2024: {
            1: 55, 2: 65, 3: 72, 4: 98, 5: 118, 6: 172,
            7: 245, 8: 270, 9: 158, 10: 120, 11: 60, 12: 72,
        },
        2025: {
            1: 68, 2: 79, 3: 85, 4: 115, 5: 139, 6: 201,
            7: 282, 8: 308, 9: 184, 10: 140, 11: 70, 12: 85,
        },
    },
}

# ══════════════════════════════════════════
# BEAT THE BEST YEAR — v7.5
#
# Filosofía: el RMS siempre intenta batir ocupación Y precio
# del mejor año histórico para cada fecha.
#
# Pero la comparación es RELATIVA A DAYS_OUT:
# - A 200 días de agosto es normal tener 2/9 ocupados
# - La pregunta no es "¿tengo menos que agosto 2025?"
# - Sino "¿a estas mismas alturas, tenía más o menos?"
# - Eso ya lo hace el pace ponderado de otb.py
#
# Lo que añadimos es:
# 1. Target de revenue por mes = best year revenue × 1.05 (batir +5%)
# 2. Auditoría en cada run: ¿voy ganando o perdiendo vs target?
# 3. Si voy perdiendo en revenue → señal para pricing
# 4. En email diario: semáforo por mes vs target
# ══════════════════════════════════════════
BEAT_THE_BEST = {
    "enabled": True,
    "target_uplift": 1.00,  # Objetivo: SUPERAR el mejor año (sin colchón artificial)
    # Revenue del mejor año por mes (se actualiza desde /revenue)
    # Estos son valores semilla — el sistema los actualiza automáticamente
    "BEST_REVENUE_BY_MONTH": {
        1: 4200, 2: 5800, 3: 8500, 4: 14200, 5: 18500, 6: 28000,
        7: 42000, 8: 46000, 9: 25000, 10: 16000, 11: 5500, 12: 8000,
    },
    "BEST_YEAR_BY_MONTH": {
        1: 2025, 2: 2025, 3: 2025, 4: 2025, 5: 2025, 6: 2025,
        7: 2025, 8: 2025, 9: 2025, 10: 2025, 11: 2025, 12: 2025,
    },
}

# ══════════════════════════════════════════
# SEASONS
# ══════════════════════════════════════════
SEASON_CODE = {
    1: "B", 2: "B", 3: "MB", 4: "M", 5: "MA", 6: "A",
    7: "UA", 8: "UA", 9: "A", 10: "MA", 11: "B", 12: "MB",
}

# ══════════════════════════════════════════
# BOOKING ANALYTICS
# ══════════════════════════════════════════
BOOKING_ANALYTICS = {
    6: {"our_adr": 196, "ref_adr": 170, "rank_adr": 8,  "rank_nights": 14, "total_props": 26, "updated": "2026-03"},
    7: {"our_adr": 283, "ref_adr": 238, "rank_adr": 7,  "rank_nights": 11, "total_props": 26, "updated": "2026-03"},
    8: {"our_adr": 298, "ref_adr": 252, "rank_adr": 7,  "rank_nights": 22, "total_props": 26, "updated": "2026-03"},
    9: {"our_adr": 204, "ref_adr": 177, "rank_adr": 7,  "rank_nights": 10, "total_props": 26, "updated": "2026-03"},
}

# ══════════════════════════════════════════
# SEGMENT BASE — Capa A (sin cambios vs v7.4)
# Los precios de referencia son de 2025 (mejor año).
# La Capa A recalibra trimestralmente con Demand Unconstraining.
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
    "7-WD": {"code": "UA", "base": 260, "suelo": 168, "techo": 520,
             "preciosPorDisp": {1: 400, 2: 355, 3: 325, 4: 305, 5: 290, 6: 280, 7: 275, 8: 270, 9: 265}},
    "7-WE": {"code": "UA", "base": 260, "suelo": 168, "techo": 520,
             "preciosPorDisp": {1: 420, 2: 375, 3: 340, 4: 320, 5: 305, 6: 295, 7: 285, 8: 280, 9: 275}},
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
# PRICE SLOTS
# ══════════════════════════════════════════
PRICE_SLOTS = {
    "STANDARD": "price1", "6NOCHES": "price3",
    "5NOCHES": "price4", "4NOCHES": "price5", "SEMANAL": "price10",
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
    "4NOCHES": 0.92, "5NOCHES": 0.85, "6NOCHES": 0.78, "SEMANAL": 0.70,
}
DURATION_DISCOUNT_OCC_LOW = 0.30
DURATION_DISCOUNT_OCC_HIGH = 0.75
DURATION_DISCOUNTS = {
    "4NOCHES": 0.87, "5NOCHES": 0.82, "6NOCHES": 0.77, "SEMANAL": 0.72,
}

# ══════════════════════════════════════════
# FLOORS & CEILINGS (v7.4 — calibrados desde ADR real)
# ══════════════════════════════════════════
SEASONAL_FLOOR = {
    "B": 75, "MB": 90, "M": 140, "MA": 165, "A": 235, "UA": 395,
}
MONTHLY_FLOOR = {
    1:  60, 2:  65, 3:  95, 4: 115, 5: 139, 6: 237,
    7: 332, 8: 362, 9: 216, 10: 165, 11: 70, 12: 85,
}
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
GENIUS_COMPENSATION = 1.18

# ══════════════════════════════════════════
# MIN STAY
# ══════════════════════════════════════════
DEFAULT_MIN_STAY = {"B": 3, "MB": 3, "M": 3, "MA": 4, "A": 5, "UA": 7}
MIN_STAY_REDUCTION = {
    "threshold_high": 0.70, "threshold_vhigh": 0.85,
    "absolute_min": 3, "absolute_min_winter": 3,
    "days_close": 21, "days_very_close": 7,
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
        "horizonte_dias": 30, "occ_vecinos_alta": 0.78,
        "max_gap_noches": 4, "min_disponibles_gap": 1, "max_disponibles_gap": 4,
    },
}

# ══════════════════════════════════════════
# LAST MINUTE WINTER
# ══════════════════════════════════════════
LAST_MINUTE_WINTER = {
    "enabled": True, "seasons": ["B", "MB"],
    "max_days_out": 14, "min_units_free": 6,
    "price_protection_override": 0.40, "factor_min_override": 0.60, "suelo_override_pct": 0.70,
    "level2_days": 7, "level2_min_units": 7,
    "level2_protection": 0.00, "level2_factor_min": 0.50, "level2_suelo_pct": 0.60,
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
    "FLOOR_VS_PEER": 0.90, "CEILING_VS_PEER": 1.50, "APIFY_MAX_AGE_DAYS": 14,
}

# ══════════════════════════════════════════
# GROUND FLOOR
# ══════════════════════════════════════════
GROUND_FLOOR_LOS = {
    "enabled": True, "absolute_min": 2,
    "upper_occ_threshold": 0.75, "temporadas_protegidas": ["A", "UA"],
}
EVENTS_OVERLAP_RULE = "MAX"

# ══════════════════════════════════════════
# V7 ENGINE CONFIG
# ══════════════════════════════════════════
V7 = {
    "MONTHLY_FLOOR_V7": {
        1: 78, 2: 89, 3: 94, 4: 134, 5: 154, 6: 218,
        7: 390, 8: 440, 9: 222, 10: 161, 11: 94, 12: 148,
    },
    "FORECAST": {
        "PACE_SENS": 0.30, "PACE_MIN": 0.80, "PACE_MAX": 1.20,
        "PICKUP_SENS": 0.20, "PICKUP_MIN": 0.85, "PICKUP_MAX": 1.15,
        "EVENTO_MIN": 0.90, "EVENTO_MAX": 1.30,
        "VAC_MIN": 0.95, "VAC_MAX": 1.15,
        "TRENDS_MIN": 0.95, "TRENDS_MAX": 1.10,
    },
    "OPTIM": {"PESO_REAL": 0.70, "PESO_FORECAST": 0.30},
    "SUAVIZADO": {"MAX_VARIACION_DIARIA": 0.12},
    "COMP_SET_ADJ": {
        "RATIO_ALTO": 1.60, "FACTOR_ALTO": 0.97,
        "RATIO_MEDIO": 1.45, "FACTOR_MEDIO": 0.99,
    },
}

# ══════════════════════════════════════════
# ALERTAS
# ══════════════════════════════════════════
ALERTAS_ANOMALIAS = {
    "enabled": True,
    "GAP_URGENTE": {
        "enabled": True, "horizonte_dias": 14, "min_disponibles": 5,
        "gap_critico_disponibles": 7, "gap_critico_dias": 7,
    },
    "PICKUP_MUERTO": {
        "enabled": True, "horizonte_semanas": 8, "min_dias_futuro": 7,
        "pickup_minimo": 1, "occ_threshold": 0.70,
    },
    "COMPSET_SALTO": {
        "enabled": True, "pct_cambio_alerta": 0.15,
        "pct_cambio_critico": 0.25, "meses_a_vigilar": [4, 5, 6, 7, 8, 9, 10],
    },
    "COOLDOWN_HORAS": 48,
}

# ══════════════════════════════════════════
# APIFY
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
    "SCRAPE_ROTATION": {"enabled": True, "MESES_POR_DIA": {1: [1, 4], 3: [2, 5], 5: [3, 6]}, "MAX_MESES_POR_EJECUCION": 2},
    "SCRAPE_PROFILES": {"DEFAULT": {"nights": 3, "adults": 2}, "SUMMER": {"nights": 7, "adults": 4}},
    "SUMMER_MONTHS": [6, 7, 8, 9],
    "MAX_WAIT_SECONDS": 180, "POLL_INTERVAL_MS": 5000,
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
    "MAX_BOOST": 0.15, "MIN_PCT_PARA_BOOST": 0.10,
    "MESES_ACTIVOS": [3, 4, 5, 6, 7, 8, 9, 10],
    "API_BASE": "https://openholidaysapi.org", "HORIZONTE_MESES": 12,
}

MONTHLY_ALERTS = {"enabled": True, "threshold_warning": -0.10, "threshold_critical": -0.20}
DEMAND_CURVE = {"PRICE_STEP": 10, "MIN_OBS_PER_RANGE": 20, "CEILING_MULTIPLIER": 1.50}
