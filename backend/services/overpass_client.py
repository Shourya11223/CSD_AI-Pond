"""
Shared Overpass API client with endpoint fallback and retry support.

Public Overpass API endpoints
-----------------------------
The Overpass API is a read-only mirror of OpenStreetMap data. Several
publicly-accessible servers are available:

1. https://overpass-api.de/api/interpreter
   Primary server hosted by OpenStreetMap Germany. Well-maintained but
   heavily used. Rate limits apply.

2. https://overpass.kumi.systems/api/interpreter
   Public mirror maintained by Kumi Systems. Good uptime and less crowded
   than the primary.

3. https://overpass.openstreetmap.fr/api/interpreter
   Public mirror hosted by OpenStreetMap France. Good alternative when
   primary is rate-limited.

All servers use the same API endpoint format and return identical data.

Rate limiting / etiquette
-------------------------
- The Overpass API is a free volunteer-run service.
- Each endpoint enforces per-IP rate limits (typically 2 requests/second).
- Use a bounded timeout and finite retries to avoid hammering the servers.
- The existing graceful fallback behaviour is preserved: if all endpoints
  fail, the services return the same "unavailable" result type.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Ordered list of public Overpass API endpoints (tried in order with fallback).
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

# Per-request READ timeout in seconds (conservative to avoid long hangs on a
# server that accepted the connection but is slow to answer).
REQUEST_TIMEOUT_S = 20.0

# Connection-phase timeout in seconds, deliberately short and separate from the
# read timeout. A public endpoint that silently drops packets fails over
# quickly instead of multiplying the timeout by (resolved addresses x retries).
# Hostnames here can resolve to several IPv4/IPv6 addresses, and urllib3 tries
# each one in turn, so a single "20 s connect timeout" can cost minutes on a
# blackholed host. A reachable endpoint still gets the full REQUEST_TIMEOUT_S to
# respond, so this does not disable any provider.
CONNECT_TIMEOUT_S = 5.0

# Maximum retries per endpoint on retryable HTTP responses (504 / 5xx).
# Timeouts and connection failures are NOT retried on the same endpoint; the
# client fails over to the next endpoint instead — see ``overpass_query``.
MAX_RETRIES_PER_ENDPOINT = 2

# Base delay for exponential backoff (seconds).
BACKOFF_BASE_S = 2.0


def _build_error_summary(errors: List[Tuple[str, str]]) -> str:
    """Summarise the errors from all failed endpoints for a useful error message."""
    lines = []
    for endpoint, reason in errors:
        reason_short = (reason or "unknown error")[:80]
        lines.append(f"{endpoint}: {reason_short}")
    return " | ".join(lines)


def overpass_query(query: str, timeout_s: float = REQUEST_TIMEOUT_S) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Execute an Overpass QL query against the configured endpoints.

    Tries each endpoint in order with bounded retries and exponential backoff.
    On any successful response (HTTP 200) the parsed JSON is returned.
    On final failure returns ``(None, error_message)`` with enough detail to
    understand which endpoint(s) failed and why.

    Parameters
    ----------
    query : str
        Overpass QL query string.
    timeout_s : float, optional
        Per-request timeout in seconds. Defaults to ``REQUEST_TIMEOUT_S``.

    Returns
    -------
    Tuple[Optional[dict], Optional[str]]
        - On success: ``(response_json, None)``
        - On all-endpoints-failed: ``(None, "endpoint1: reason | endpoint2: reason")``
    """
    errors: List[Tuple[str, str]] = []

    for endpoint in OVERPASS_ENDPOINTS:
        headers = {
            "User-Agent": "VillagePondPlanning/1.0 (educational project; "
                          "contact via GitHub if rate-limited)",
            "Accept": "application/json",
        }

        for attempt in range(MAX_RETRIES_PER_ENDPOINT + 1):
            try:
                response = requests.post(
                    endpoint,
                    data={"data": query},
                    # (connect, read): bound the connection phase tightly so a
                    # dead endpoint fails over fast, while a reachable endpoint
                    # keeps the full read budget.
                    timeout=(CONNECT_TIMEOUT_S, timeout_s),
                    headers=headers,
                )

                if response.status_code == 429:
                    # Rate limited - try next endpoint immediately.
                    errors.append((endpoint, "HTTP 429 rate limit"))
                    break

                if response.status_code == 504:
                    # Gateway timeout - treat as retryable.
                    if attempt < MAX_RETRIES_PER_ENDPOINT:
                        delay = BACKOFF_BASE_S * (2 ** attempt)
                        logger.debug(
                            "Endpoint %s returned 504; retrying in %.1fs (attempt %d)",
                            endpoint, delay, attempt + 1,
                        )
                        time.sleep(delay)
                        continue
                    errors.append((endpoint, "HTTP 504 gateway timeout"))
                    break

                if 500 <= response.status_code < 600:
                    # Server-side error - retryable.
                    if attempt < MAX_RETRIES_PER_ENDPOINT:
                        delay = BACKOFF_BASE_S * (2 ** attempt)
                        logger.debug(
                            "Endpoint %s returned HTTP %d; retrying in %.1fs "
                            "(attempt %d)", endpoint, response.status_code,
                            delay, attempt + 1,
                        )
                        time.sleep(delay)
                        continue
                    errors.append(
                        (endpoint, f"HTTP {response.status_code} server error")
                    )
                    break

                if response.status_code != 200:
                    errors.append((endpoint, f"HTTP {response.status_code}"))
                    break

                # Success
                return response.json(), None

            except requests.exceptions.Timeout as exc:
                # Timed out (either opening the connection, or waiting for the
                # response). Retrying the SAME endpoint only repeats the wait,
                # and a hostname can resolve to several unreachable addresses,
                # so fail over to the next endpoint immediately. The overall
                # query still tries every endpoint, so resilience across
                # providers is preserved; retries remain for the retryable
                # HTTP responses (504 / 5xx) handled above.
                is_connect = isinstance(exc, requests.exceptions.ConnectTimeout)
                errors.append(
                    (endpoint, "connection timed out" if is_connect
                     else "request timed out")
                )
                break

            except requests.exceptions.ConnectionError as exc:
                # Network-level failure - try next endpoint immediately.
                errors.append((endpoint, f"connection error: {exc}"))
                break

            except requests.exceptions.RequestException as exc:
                # Unexpected error - record and try next endpoint.
                errors.append((endpoint, f"request error: {exc}"))
                break

    summary = _build_error_summary(errors)
    logger.warning("All Overpass endpoints failed: %s", summary)
    return None, summary
