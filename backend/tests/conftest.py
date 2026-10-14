"""Shared pytest configuration for the backend suite.

The service layer talks to third-party HTTP APIs:

* OpenStreetMap Overpass (water exclusion, land cover),
* Open-Meteo (historical rainfall, current weather, design rainfall),
* OpenTopography (DEM download for location mode).

Those APIs are external, rate-limited and frequently unreachable from CI or a
sandboxed machine. Because the production code degrades gracefully when a
provider fails, a *real* request that hangs on a dropped socket turns an
otherwise fast unit test into a multi-minute stall (or an outright hang when
the endpoint blackholes traffic instead of refusing it).

Every test that exercises provider *logic* monkeypatches the relevant
``requests`` call itself (see ``test_weather.py``, ``test_rainfall.py``,
``test_overpass_client.py`` ...). The autouse fixture below only guarantees
that no test ever opens a real socket to an external host: such a call fails
immediately with ``ConnectionError``, which is the same signal the production
code already handles via its "unavailable / fallback" paths. Requests to
localhost are still allowed so future local test servers keep working.

This keeps the suite deterministic and offline-friendly without changing any
production behaviour.
"""

from __future__ import annotations

import urllib.parse

import pytest
import requests

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0", "testserver"}


def _is_external(url: object) -> bool:
    """Return True if ``url`` points at a host that is not local."""
    try:
        host = urllib.parse.urlsplit(str(url)).hostname
    except Exception:
        return True
    return host not in _LOCAL_HOSTS


@pytest.fixture(autouse=True)
def _block_external_http(monkeypatch):
    """Fail fast on any real outbound request instead of hanging."""
    real_get = requests.get
    real_post = requests.post

    def guarded_get(url, *args, **kwargs):
        if _is_external(url):
            raise requests.exceptions.ConnectionError(
                f"external HTTP disabled during tests: {url}"
            )
        return real_get(url, *args, **kwargs)

    def guarded_post(url, *args, **kwargs):
        if _is_external(url):
            raise requests.exceptions.ConnectionError(
                f"external HTTP disabled during tests: {url}"
            )
        return real_post(url, *args, **kwargs)

    monkeypatch.setattr(requests, "get", guarded_get)
    monkeypatch.setattr(requests, "post", guarded_post)
    yield
