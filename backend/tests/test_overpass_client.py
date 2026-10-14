"""Tests for the shared Overpass API client (services/overpass_client.py)."""

import pytest
from unittest.mock import patch, MagicMock
import requests

from services.overpass_client import (
    overpass_query,
    OVERPASS_ENDPOINTS,
    REQUEST_TIMEOUT_S,
    MAX_RETRIES_PER_ENDPOINT,
    BACKOFF_BASE_S,
)
from services.water_exclusion import OVERPASS_API_URL


class TestOverpassClientEndpoints:
    """Verify the client has multiple endpoints configured."""

    def test_multiple_endpoints(self):
        assert len(OVERPASS_ENDPOINTS) >= 2, "Should have at least 2 endpoints"

    def test_primary_endpoint_is_overpass_api_de(self):
        assert OVERPASS_ENDPOINTS[0] == "https://overpass-api.de/api/interpreter"

    def test_alias_uses_primary(self):
        assert OVERPASS_API_URL == OVERPASS_ENDPOINTS[0]


class TestOverpassQuerySuccess:
    """Tests for successful Overpass API responses."""

    @patch("services.overpass_client.requests.post")
    def test_primary_endpoint_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"elements": []}
        mock_post.return_value = mock_resp

        data, error = overpass_query("[out:json];node(1,2,3,4);")

        assert error is None
        assert data == {"elements": []}
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "overpass-api.de" in call_url

    @patch("services.overpass_client.requests.post")
    def test_fallback_to_secondary_endpoint(self, mock_post):
        """Primary fails (429), secondary succeeds."""
        resp_primary = MagicMock()
        resp_primary.status_code = 429

        resp_secondary = MagicMock()
        resp_secondary.status_code = 200
        resp_secondary.json.return_value = {"elements": [{"type": "way", "id": 1}]}

        mock_post.side_effect = [resp_primary, resp_secondary]

        data, error = overpass_query("[out:json];node(1,2,3,4);")

        assert error is None
        assert data == {"elements": [{"type": "way", "id": 1}]}
        assert mock_post.call_count == 2


class TestOverpassQueryAllFail:
    """Tests for when all endpoints fail."""

    @patch("services.overpass_client.requests.post")
    def test_all_endpoints_fail_connection_error(self, mock_post):
        """All endpoints return connection errors."""
        mock_post.side_effect = requests.exceptions.ConnectionError("no network")

        data, error = overpass_query("[out:json];node(1,2,3,4);")

        assert data is None
        assert error is not None
        # Error should mention all endpoints that were tried.
        assert "overpass-api.de" in error
        assert "overpass.kumi.systems" in error
        assert "overpass.openstreetmap.fr" in error
        assert "connection error" in error.lower()

    @patch("services.overpass_client.requests.post")
    def test_all_endpoints_fail_http_500(self, mock_post):
        """All endpoints return 500 errors."""
        resp = MagicMock()
        resp.status_code = 500
        mock_post.return_value = resp

        data, error = overpass_query("[out:json];node(1,2,3,4);")

        assert data is None
        assert error is not None
        assert "500" in error

    @patch("services.overpass_client.requests.post")
    def test_all_endpoints_timeout(self, mock_post):
        """All endpoints time out."""
        mock_post.side_effect = requests.exceptions.Timeout("timeout")

        data, error = overpass_query("[out:json];node(1,2,3,4);")

        assert data is None
        assert error is not None
        assert "timed out" in error.lower()

    @patch("services.overpass_client.requests.post")
    def test_all_endpoints_http_429(self, mock_post):
        """All endpoints return 429 rate limit."""
        resp = MagicMock()
        resp.status_code = 429
        mock_post.return_value = resp

        data, error = overpass_query("[out:json];node(1,2,3,4);")

        assert data is None
        assert error is not None
        assert "429" in error
        assert "rate limit" in error.lower()

    @patch("services.overpass_client.requests.post")
    def test_http_504_retry_then_fallback(self, mock_post):
        """504 with retries, then fallback to next endpoint."""
        resp_504 = MagicMock()
        resp_504.status_code = 504

        resp_success = MagicMock()
        resp_success.status_code = 200
        resp_success.json.return_value = {"elements": []}

        mock_post.side_effect = [resp_504, resp_504, resp_504, resp_success]

        data, error = overpass_query("[out:json];node(1,2,3,4);")

        # First endpoint tried 3 times (0 retries + 2 retries), then second succeeded.
        assert error is None
        assert data == {"elements": []}
        assert mock_post.call_count == 4


class TestOverpassQueryEdgeCases:
    """Edge case tests."""

    @patch("services.overpass_client.requests.post")
    def test_http_404_does_not_retry(self, mock_post):
        """404 is not a retryable error; each endpoint is tried only once."""
        resp = MagicMock()
        resp.status_code = 404
        mock_post.return_value = resp

        data, error = overpass_query("[out:json];node(1,2,3,4);")

        assert data is None
        assert error is not None
        assert "404" in error
        # Each endpoint is tried exactly once (no retries for 404).
        # 3 endpoints in OVERPASS_ENDPOINTS = 3 total calls.
        assert mock_post.call_count == len(OVERPASS_ENDPOINTS)

    @patch("services.overpass_client.requests.post")
    def test_empty_query_returns_empty_elements(self, mock_post):
        """A valid response with empty elements is a valid result."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"elements": []}
        mock_post.return_value = resp

        data, error = overpass_query("[out:json];" )

        assert error is None
        assert data == {"elements": []}

    @patch("services.overpass_client.requests.post")
    def test_user_agent_includes_project_name(self, mock_post):
        """The User-Agent header identifies this project."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"elements": []}
        mock_post.return_value = resp

        overpass_query("[out:json];node(1,2,3,4);")

        headers = mock_post.call_args[1]["headers"]
        assert "VillagePondPlanning" in headers["User-Agent"]


class TestOverpassClientBackwardCompat:
    """Verify existing code that imports OVERPASS_API_URL still works."""

    def test_overpass_api_url_alias(self):
        from services.water_exclusion import OVERPASS_API_URL as water_url
        from services.land_cover import OVERPASS_API_URL as land_url
        assert water_url == OVERPASS_ENDPOINTS[0]
        assert land_url == OVERPASS_ENDPOINTS[0]
        assert water_url == land_url
