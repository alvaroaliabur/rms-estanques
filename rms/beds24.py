"""
Beds24 API layer — token management, GET/POST with retries.
Replaces: getToken_, apiGet_, apiPost_ from GAS.
"""

import time
import logging
import requests
from rms import config

log = logging.getLogger(__name__)

# ══════════════════════════════════════════
# TOKEN MANAGEMENT
# ══════════════════════════════════════════

_token_cache = {"token": None, "expires": 0}


def get_token():
    """Get a valid Beds24 API token, refreshing if needed."""
    now = time.time()
    if _token_cache["token"] and _token_cache["expires"] > now:
        return _token_cache["token"]

    refresh_token = config.BEDS24_REFRESH_TOKEN
    if not refresh_token:
        raise RuntimeError("No BEDS24_REFRESH_TOKEN configured")

    log.info("Renovando token Beds24...")
    r = requests.get(
        f"{config.BEDS24_API}/authentication/token",
        headers={"refreshToken": refresh_token.strip()},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()

    _token_cache["token"] = data["token"]
    expires_in = data.get("expiresIn", 86400)
    _token_cache["expires"] = now + expires_in - 3600  # 1h margin

    # Auto-renew refresh token if Beds24 returns a new one
    if data.get("refreshToken"):
        config.BEDS24_REFRESH_TOKEN = data["refreshToken"]
        log.info("  Refresh token renovado automáticamente")

    return _token_cache["token"]


# ══════════════════════════════════════════
# API CALLS
# ══════════════════════════════════════════

def api_get(endpoint, params=None):
    """GET request to Beds24 API with auto-pagination awareness."""
    token = get_token()
    url = f"{config.BEDS24_API}/{endpoint}"
    r = requests.get(
        url,
        headers={"token": token},
        params=params,
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()

    # Beds24 wraps some responses in {"data": [...]}
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return data


def api_post(endpoint, payload, max_retries=3):
    """POST request to Beds24 API with retries."""
    token = get_token()
    last_error = None

    for attempt in range(max_retries):
        try:
            r = requests.post(
                f"{config.BEDS24_API}/{endpoint}",
                headers={"token": token, "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
            if r.status_code in (200, 201):
                return r.json()

            last_error = f"HTTP {r.status_code} — {r.text[:200]}"
            log.warning(f"  apiPost intento {attempt+1} fallido: {last_error}")

            if r.status_code in (401, 403):
                break  # Auth error, don't retry

            time.sleep(2 * (attempt + 1))

        except Exception as e:
            last_error = str(e)
            log.warning(f"  apiPost intento {attempt+1} excepción: {last_error}")
            time.sleep(2 * (attempt + 1))

    raise RuntimeError(f"API POST {endpoint} ({max_retries} intentos): {last_error}")


# ══════════════════════════════════════════
# PAGINATION HELPER
# ══════════════════════════════════════════

def api_get_all(endpoint, params=None, page_size=100):
    """GET all pages from a paginated Beds24 endpoint."""
    if params is None:
        params = {}
    params["limit"] = page_size

    all_data = []
    page = 1

    while True:
        params["page"] = page
        batch = api_get(endpoint, params)

        if not batch or not isinstance(batch, list) or len(batch) == 0:
            break

        all_data.extend(batch)

        if len(batch) < page_size:
            break

        page += 1
        time.sleep(0.4)

    return all_data
