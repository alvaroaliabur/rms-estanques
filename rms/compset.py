"""
CompSet — Apify scraping + MarketRef.
TODO: Full implementation. For now, uses ADR_PEER from config.
"""

import logging
from rms import config

log = logging.getLogger(__name__)


def actualizar_compset():
    """Run Apify comp set scrape. TODO: Implement."""
    log.info("  CompSet scrape: not yet implemented in Python")
    pass


def get_market_adr(month):
    """Get market ADR for a month. Uses ADR_PEER fallback."""
    adr = config.COMP_SET["ADR_PEER"].get(month, 0)
    if adr > 0:
        return {"adr": adr, "source": "fallback"}
    return None
