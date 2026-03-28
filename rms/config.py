"""
RMS Estanques — Configuration
v7.6 — 28 marzo 2026

CAMBIOS v7.6 vs v7.5:
- LAST_MINUTE_WINTER extendido a M y MA (abril, mayo, octubre):
  con 3+ unidades libres a <10 días activa modo urgencia.
  Level 2: 5+ libres a <5 días → suelo al 55%, sin protección de precio.
- MIN_BOOKING_REVENUE bajado en temporadas bajas/medias para poder
  vender la última unidad. Verano (A, UA) mantiene mínimos altos.
- PRICE_PROTECTION_BY_DAYS más agresiva a corto plazo (7d: 0.50, 14d: 0.70).
- ADR_HISTORICAL_MIN: floor absoluto Genius — el sistema nunca vende
  por debajo del ADR real de 2025 en verano (protege precio medio).
  En invierno/media temporada sí permite bajar para vender volumen.

FILOSOFÍA:
  B/MB/M/MA a <10 días: VENDER > precio. Unidad vacía = 0€.
  A/UA: nunca por debajo del ADR histórico. El verano no se malvende.
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
# ══════════════════════════════════════════
DEMAND_UNCONSTRAINING = {
    "enabled": True,
    "reference_year": 2025,
    "ADR_REFERENCE": {
        1: 68, 2: 79, 3: 85, 4: 115, 5: 139, 6: 201,
        7: 282, 8: 308, 9: 184, 10: 140, 11: 70, 12: 85,
    },
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
# ══════════════════════════════════════════
BEAT_THE_BEST = {
    "enabled": True,
    "target_uplift": 1.00,
    "BEST_REVENUE_BY_MONTH": {
        1: 3041, 2: 16800, 3: 21427, 4: 27089, 5: 33432, 6: 53156,
        7: 66895, 8: 82290, 9: 49559, 10: 31078, 11: 18285, 12: 18618,
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
# SEGMENT BASE — Capa A (sin cambios vs v7.5)
# ══════════════════════════════════════════
SEGMENT_BASE = {
    "1-WD": {"code": "B",  "base": 40,  "suelo": 35,  "techo": 105,
             "preciosPorDisp": {1: 150, 2: 130, 3: 120, 4: 115, 5: 105, 6: 100, 7: 95, 8: 90, 9: 90}},
    "1-WE": {"code": "B",  "base": 40,  "suelo": 35,  "techo": 120,
             "preciosPorDisp": {1: 150, 2: 130, 3: 120, 4: 115, 5: 110, 6: 105, 7: 100, 8: 95, 9: 90}},
    "2-WD": {"code": "B",  "base": 60,  "suelo": 48,  "techo": 150,
             "preciosPorDisp": {1: 150, 2: 130, 3: 125, 4: 120, 5: 115, 6: 110, 7: 105, 8: 100, 9: 100}},
    "2-WE": {"code": "B",  "base": 60,  "suelo": 48,  "techo": 165,
             "preciosPorDisp": {1: 150, 2: 135, 3: 125, 4: 120, 5: 115, 6: 115, 7: 110, 8: 105, 9: 100}},
    "3-WD": {"code": "MB", "base": 70,  "suelo": 56,  "techo": 165,
             "preciosPorDisp": {1: 160, 2: 145, 3: 135, 4: 130, 5: 125, 6: 120, 7: 115, 8: 110, 9: 110}},
    "3-WE": {"code": "MB", "base": 70,  "suelo": 56,  "techo": 180,
             "preciosPorDisp": {1: 160, 2: 145, 3: 140, 4: 135, 5: 130, 6: 125, 7: 120, 8: 115, 9: 110}},
    "4-WD": {"code": "M",  "base": 100, "suelo": 80,  "techo": 195,
             "preciosPorDisp": {1: 250, 2: 215, 3: 200, 4: 190, 5: 175, 6: 170, 7: 160, 8: 150, 9: 140}},
    "4-WE": {"code": "M",  "base": 100, "suelo": 80,  "techo": 210,
             "preciosPorDisp": {1: 250, 2: 220, 3: 205, 4: 195, 5: 185, 6: 175, 7: 165, 8: 160, 9: 150}},
    "5-WD": {"code": "MA", "base": 110, "suelo": 88,  "techo": 240,
             "preciosPorDisp": {1: 290, 2: 255, 3: 235, 4: 220, 5: 205, 6: 195, 7: 185, 8: 175, 9: 170}},
    "5-WE": {"code": "MA", "base": 120, "suelo": 88,  "techo": 240,
             "preciosPorDisp": {1: 290, 2: 255, 3: 240, 4: 225, 5: 215, 6: 205, 7: 195, 8: 185, 9: 180}},
    "6-WD": {"code": "A",  "base": 170, "suelo": 112, "techo": 345,
             "preciosPorDisp": {1: 400, 2: 350, 3: 330, 4: 310, 5: 295, 6: 280, 7: 265, 8: 255, 9: 240}},
    "6-WE": {"code": "A",  "base": 170, "suelo": 128, "techo": 360,
             "preciosPorDisp": {1: 400, 2: 360, 3: 335, 4: 320, 5: 305, 6: 295, 7: 285, 8: 270, 9: 260}},
    "7-WD": {"code": "UA", "base": 260, "suelo": 168, "techo": 520,
             "preciosPorDisp": {1: 420, 2: 395, 3: 385, 4: 375, 5: 365, 6: 355, 7: 350, 8: 345, 9: 340}},
    "7-WE": {"code": "UA", "base": 260, "suelo": 168, "techo": 520,
             "preciosPorDisp": {1: 420, 2: 405, 3: 395, 4: 390, 5: 385, 6: 380, 7: 375, 8: 370, 9: 370}},
    "8-WD": {"code": "UA", "base": 300, "suelo": 208, "techo": 540,
             "preciosPorDisp": {1: 440, 2: 415, 3: 405, 4: 395, 5: 390, 6: 385, 7: 380, 8: 370, 9: 370}},
    "8-WE": {"code": "UA", "base": 300, "suelo": 208, "techo": 540,
             "preciosPorDisp": {1: 440, 2: 425, 3: 420, 4: 415, 5: 410, 6: 405, 7: 405, 8: 400, 9: 400}},
    "9-WD": {"code": "A",  "base": 180, "suelo": 136, "techo": 345,
             "preciosPorDisp": {1: 400, 2: 345, 3: 320, 4: 300, 5: 280, 6: 265, 7: 250, 8: 235, 9: 220}},
    "9-WE": {"code": "A",  "base": 180, "suelo": 136, "techo": 345,
             "preciosPorDisp": {1: 400, 2: 350, 3: 330, 4: 310, 5: 295, 6: 280, 7: 265, 8: 255, 9: 240}},
    "10-WD": {"code": "MA", "base": 120, "suelo": 96,  "techo": 255,
              "preciosPorDisp": {1: 310, 2: 265, 3: 245, 4: 230, 5: 215, 6: 205, 7: 190, 8: 180, 9: 170}},
    "10-WE": {"code": "MA", "base": 120, "suelo": 96,  "techo": 255,
              "preciosPorDisp": {1: 310, 2: 270, 3: 250, 4: 235, 5: 220, 6: 210, 7: 200, 8: 190, 9: 180}},
    "11-WD": {"code": "B",  "base": 70,  "suelo": 56,  "techo": 150,
              "preciosPorDisp": {1: 150, 2: 135, 3: 125, 4: 120, 5: 115, 6: 115, 7: 110, 8: 105, 9: 100}},
    "11-WE": {"code": "B",  "base": 70,  "suelo": 56,  "techo": 165,
              "preciosPorDisp": {1: 150, 2: 135, 3: 125, 4: 120, 5: 115, 6: 115, 7: 110, 8: 105, 9: 100}},
    "12-WD": {"code": "MB", "base": 120, "suelo": 96,  "techo": 225,
              "preciosPorDisp": {1: 200, 2: 175, 3: 165, 4: 155, 5: 150, 6: 140, 7: 135, 8: 130, 9: 120}},
    "12-WE": {"code": "MB", "base": 120, "suelo": 96,  "techo": 225,
              "preciosPorDisp": {1: 200, 2: 175, 3: 165, 4: 155, 5: 150, 6: 140, 7: 135, 8: 130, 9: 120}},
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
# FLOORS & CEILINGS
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
# v7.6: más agresiva a corto plazo para facilitar venta de últimas unidades
# A <7 días: puede bajar hasta el 50% del precio medio vendido
# A <14 días: puede bajar hasta el 70%
# ══════════════════════════════════════════
PRICE_PROTECTION_BY_DAYS = {60: 0.95, 30: 0.85, 14: 0.70, 7: 0.50, 0: 0.00}

# ══════════════════════════════════════════
# MIN BOOKING REVENUE — v7.6
#
# FILOSOFÍA POR TEMPORADA:
#   B/MB/M/MA: unidad vacía = 0€. Preferimos vender a precio bajo.
#              El mínimo es lo que tiene sentido operativamente.
#   A (jun/sep): nunca por debajo del ADR histórico Genius × minStay.
#                Jun/sep: ~200€ Genius/noche × 5n = 1000€ min por reserva.
#   UA (jul/ago): el verano no se malvende. Mínimo protege ADR medio.
#                 282€ Genius/noche × 5n = 1410€. Usamos 1500€ con margen.
#
# Fórmula de comprobación: MIN_BOOKING_REVENUE / minStay = min €/noche publicado
#   B:  320/3 = 107€/noche pub → Genius 91€  ✓ razonable invierno
#   MB: 330/3 = 110€/noche pub → Genius 93€  ✓
#   M:  390/3 = 130€/noche pub → Genius 110€ ✓ abril last-minute
#   MA: 480/3 = 160€/noche pub → Genius 136€ ✓ mayo/oct last-minute
#   A:  900/5 = 180€/noche pub → Genius 153€ ✓ jun/sep no se regala
#   UA: 1500/5= 300€/noche pub → Genius 255€ ✓ jul/ago protegido
# ══════════════════════════════════════════
MIN_NET_PER_BOOKING = 300
BOOKING_COMMISSION = 0.15
MIN_BOOKING_REVENUE = {
    "B":  320,   # 107€/noche pub | Genius 91€  — invierno, vender volumen
    "MB": 330,   # 110€/noche pub | Genius 93€  — mar/dic, idem
    "M":  390,   # 130€/noche pub | Genius 110€ — abril, last-minute activo
    "MA": 480,   # 160€/noche pub | Genius 136€ — may/oct, last-minute activo
    "A":  900,   # 180€/noche pub | Genius 153€ — jun/sep, proteger ADR
    "UA": 1500,  # 300€/noche pub | Genius 255€ — jul/ago, no malvender
}

GENIUS_COMPENSATION = 1.18

# Floor absoluto Genius por mes — el sistema nunca vende más barato
# que el ADR real de 2025 en temporada alta.
# En invierno/media temporada NO aplica (queremos vender volumen).
ADR_HISTORICAL_MIN = {
    1: 68, 2: 79, 3: 85, 4: 115, 5: 139, 6: 201,
    7: 282, 8: 308, 9: 184, 10: 140, 11: 82, 12: 101,
}

# ══════════════════════════════════════════
# MIN STAY
# ══════════════════════════════════════════
DEFAULT_MIN_STAY = {"B": 3, "MB": 3, "M": 3, "MA": 3, "A": 5, "UA": 5}
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
    "ABSOLUTE_MIN": {"UA": 5, "A": 5, "MA": 3, "M": 3, "MB": 3, "B": 3},
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
# LAST MINUTE — v7.6
#
# CAMBIO PRINCIPAL: extendido a M (abril) y MA (mayo, octubre).
# Antes solo aplicaba a invierno (B, MB).
#
# TRIGGER:
#   Level 1: temporada M/MA/B/MB + <10 días + 3+ unidades libres
#            → suelo al 65%, protección de precio al 35%
#            → permite bajar hasta ~65% del floor para vender
#   Level 2: <5 días + 5+ unidades libres (emergencia real)
#            → suelo al 55%, sin protección de precio
#            → cualquier precio por encima del suelo mínimo vale
#
# IMPORTANTE: A/UA (jun-sep) NO tienen last-minute aquí.
# En verano el motor normal ya gestiona urgencia vía PRICE_PROTECTION
# y los mínimos de MIN_BOOKING_REVENUE protegen el ADR.
#
# EJEMPLO PRÁCTICO:
#   Abril, 1 apto libre, 6 días: floor 115€ × 0.65 = 75€ pub → Genius 64€
#   Abril, 4 aptos libres, 3 días: floor 115€ × 0.55 = 63€ pub → Genius 54€
#   Mayo, 1 apto libre, 8 días: floor 139€ × 0.65 = 90€ pub → Genius 77€
# ══════════════════════════════════════════
LAST_MINUTE_WINTER = {
    "enabled": True,
    # v7.6: añadidos M (abril) y MA (mayo, octubre)
    "seasons": ["B", "MB", "M", "MA"],
    # Activar cuando quedan <10 días y hay 3+ unidades libres
    "max_days_out": 10,
    "min_units_free": 3,
    # Level 1: suelo al 65%, protección al 35% del precio medio vendido
    "price_protection_override": 0.35,
    "factor_min_override": 0.55,
    "suelo_override_pct": 0.65,
    # Level 2: emergencia — <5 días + 5+ libres → sin protección, suelo al 55%
    "level2_days": 5,
    "level2_min_units": 5,
    "level2_protection": 0.00,
    "level2_factor_min": 0.45,
    "level2_suelo_pct": 0.55,
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
        1: 85, 2: 95, 3: 105, 4: 140, 5: 165, 6: 240,
        7: 335, 8: 365, 9: 220, 10: 170, 11: 100, 12: 120,
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
    "enabled": False,
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

AIRroi_ENABLED = False

MONTHLY_ALERTS = {"enabled": True, "threshold_warning": -0.10, "threshold_critical": -0.20}
DEMAND_CURVE = {"PRICE_STEP": 10, "MIN_OBS_PER_RANGE": 20, "CEILING_MULTIPLIER": 1.50}
