"""
Capa A — Demand curves.
Replaces: construirCapaA, cargarCapaA_, and related functions.
For now, loads pre-computed data from config SEGMENT_BASE.
Full rebuild from Beds24 historical data is done periodically.
"""

import logging
from rms import config

log = logging.getLogger(__name__)


def cargar_capa_a():
    """Load Capa A data into SEGMENT_BASE.
    
    In GAS this reads from the CapaA_Precios sheet.
    In Python, during the transition we use the SEGMENT_BASE
    already defined in config.py (which matches the GAS values).
    
    TODO: Build Capa A from Beds24 historical data directly.
    """
    # The SEGMENT_BASE in config.py already has the Capa A values
    # from the last calibration. For now, just verify they're there.
    seg_count = len(config.SEGMENT_BASE)
    if seg_count >= 20:
        log.info(f"  Capa A: {seg_count} segmentos cargados (from config)")
        return True
    else:
        log.warning(f"  Capa A: solo {seg_count} segmentos — datos incompletos")
        return False


def construir_capa_a():
    """Rebuild Capa A from Beds24 historical data.
    
    This is the full demand curve construction:
    1. Fetch all historical bookings
    2. Expand to night-level data
    3. Build demand curves per segment
    4. Extract optimal prices per availability level
    
    TODO: Implement full rebuild. For now, use pre-computed values.
    """
    log.info("══ CONSTRUIR CAPA A ══")
    log.warning("  Not yet implemented in Python — using pre-computed config values")
    return config.SEGMENT_BASE
