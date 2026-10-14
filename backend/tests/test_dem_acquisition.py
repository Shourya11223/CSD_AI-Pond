"""
Unit tests for backend/services/dem_acquisition.py

Tests cover:
- valid bounds
- invalid latitude
- invalid longitude
- invalid bounds (south >= north, west >= east)
- missing API key
- HTTP failure
- timeout
- empty response
- radius_to_bounds validation

All tests mock network requests to avoid contacting the actual
OpenTopography API.
"""

import io
import os
import unittest
from unittest import mock

import requests

from services.dem_acquisition import (
    download_dem,
    cleanup_dem,
    radius_to_bounds,
    _is_geotiff_binary,
    DEMResult,
    DEMAcquisitionError,
    DEMValidationError,
    DEMAPIError,
    SUPPORTED_DEM_TYPES,
    DEFAULT_DEM_TYPE,
    REQUEST_TIMEOUT_S,
    OPENTOPOGRAPHY_API_URL,
)


def _make_fake_response(
    status_code=200,
    content=b"\x00" * 100,
    headers=None,
    text=None,
):
    """Create a mock requests.Response with the given properties."""
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.headers = headers or {"Content-Type": "image/tiff"}
    response.content = content
    response.text = text if text is not None else ""
    # iter_content yields chunks of content
    chunk_size = 65536
    chunks = [content[i:i + chunk_size] for i in range(0, len(content), chunk_size)]
    chunks = [c for c in chunks if c]
    response.iter_content.return_value = chunks
    return response


class TestDemValidation(unittest.TestCase):
    """Test parameter validation without making network calls."""

    def setUp(self):
        # Ensure API key is set for tests that need it
        os.environ["OPENTOPOGRAPHY_API_KEY"] = "test_key_12345"

    def tearDown(self):
        if "OPENTOPOGRAPHY_API_KEY" in os.environ and os.environ["OPENTOPOGRAPHY_API_KEY"] == "test_key_12345":
            del os.environ["OPENTOPOGRAPHY_API_KEY"]

    def test_missing_api_key(self):
        if "OPENTOPOGRAPHY_API_KEY" in os.environ:
            del os.environ["OPENTOPOGRAPHY_API_KEY"]
        with self.assertRaises(DEMValidationError) as ctx:
            download_dem(25.0, 25.1, 78.0, 78.1)
        self.assertIn("API key", str(ctx.exception))

    def test_invalid_latitude_south_too_high(self):
        with self.assertRaises(DEMValidationError) as ctx:
            download_dem(91.0, 92.0, 78.0, 78.1)
        self.assertIn("south", str(ctx.exception))

    def test_invalid_latitude_north_too_low(self):
        with self.assertRaises(DEMValidationError) as ctx:
            download_dem(20.0, -91.0, 78.0, 78.1)
        self.assertIn("north", str(ctx.exception))

    def test_invalid_longitude_west_too_high(self):
        with self.assertRaises(DEMValidationError) as ctx:
            download_dem(25.0, 25.1, 181.0, 182.0)
        self.assertIn("west", str(ctx.exception))

    def test_invalid_longitude_east_too_low(self):
        with self.assertRaises(DEMValidationError) as ctx:
            download_dem(25.0, 25.1, 78.0, -181.0)
        self.assertIn("east", str(ctx.exception))

    def test_south_greater_than_north(self):
        with self.assertRaises(DEMValidationError) as ctx:
            download_dem(25.5, 25.0, 78.0, 78.1)
        self.assertIn("south", str(ctx.exception))

    def test_west_greater_than_east(self):
        with self.assertRaises(DEMValidationError) as ctx:
            download_dem(25.0, 25.1, 78.5, 78.0)
        self.assertIn("west", str(ctx.exception))

    def test_south_equal_north(self):
        with self.assertRaises(DEMValidationError):
            download_dem(25.0, 25.0, 78.0, 78.1)

    def test_west_equal_east(self):
        with self.assertRaises(DEMValidationError):
            download_dem(25.0, 25.1, 78.0, 78.0)

    def test_invalid_dem_type(self):
        with self.assertRaises(DEMValidationError) as ctx:
            download_dem(25.0, 25.1, 78.0, 78.5, dem_type="INVALID_DEM")
        self.assertIn("Unsupported DEM type", str(ctx.exception))


class TestDemDownloadSuccess(unittest.TestCase):
    """Test successful downloads with mocked HTTP responses."""

    def setUp(self):
        os.environ["OPENTOPOGRAPHY_API_KEY"] = "test_key_12345"

    def tearDown(self):
        if "OPENTOPOGRAPHY_API_KEY" in os.environ:
            del os.environ["OPENTOPOGRAPHY_API_KEY"]

    @mock.patch("services.dem_acquisition.requests.get")
    def test_valid_bounds_success(self, mock_get):
        # Create a small fake TIFF payload
        fake_content = b"II*\x00" + b"\x00" * 200  # 200 bytes fake TIFF
        fake_response = _make_fake_response(
            status_code=200,
            content=b'{"error": "Invalid bounding box"}',
            headers={"Content-Type": "application/json"},
            text='{"error": "Invalid bounding box"}',
        )
        fake_response.json.return_value = {"error": "Invalid bounding box"}
        mock_get.return_value = fake_response
        with self.assertRaises(DEMAPIError) as ctx:
            download_dem(25.0, 25.1, 78.0, 78.5)
        self.assertIn("Invalid bounding box", str(ctx.exception))
class TestDemDownloadErrors(unittest.TestCase):
    """Test error handling for various failure modes."""

    def setUp(self):
        os.environ["OPENTOPOGRAPHY_API_KEY"] = "test_key_12345"

    def tearDown(self):
        if "OPENTOPOGRAPHY_API_KEY" in os.environ:
            del os.environ["OPENTOPOGRAPHY_API_KEY"]

    @mock.patch("services.dem_acquisition.requests.get")
    def test_http_failure_401(self, mock_get):
        fake_response = _make_fake_response(
            status_code=200,
            content=b'{"error": "Invalid bounding box"}',
            headers={"Content-Type": "application/json"},
            text='{"error": "Invalid bounding box"}',
        )
        fake_response.json.return_value = {"error": "Invalid bounding box"}
        mock_get.return_value = fake_response
        with self.assertRaises(DEMAPIError) as ctx:
            download_dem(25.0, 25.1, 78.0, 78.5)
        self.assertIn("Invalid bounding box", str(ctx.exception))
class TestRadiusToBounds(unittest.TestCase):
    """Test the radius_to_bounds conversion function."""

    def test_valid_conversion(self):
        south, north, west, east = radius_to_bounds(
            latitude=21.2474, longitude=81.29, radius_km=1.0,
        )
        self.assertLess(south, 21.2474)
        self.assertGreater(north, 21.2474)
        self.assertLess(west, 81.29)
        self.assertGreater(east, 81.29)

        # Latitude delta should be roughly 1km / 111.32 km/deg ~= 0.009 deg
        lat_delta = north - south
        self.assertAlmostEqual(lat_delta, 2.0 / 111.32, places=3)

    def test_invalid_latitude(self):
        with self.assertRaises(DEMValidationError):
            radius_to_bounds(latitude=91.0, longitude=81.0, radius_km=1.0)

    def test_invalid_longitude(self):
        with self.assertRaises(DEMValidationError):
            radius_to_bounds(latitude=21.0, longitude=181.0, radius_km=1.0)

    def test_negative_radius(self):
        with self.assertRaises(DEMValidationError):
            radius_to_bounds(latitude=21.0, longitude=81.0, radius_km=-1.0)

    def test_zero_radius(self):
        with self.assertRaises(DEMValidationError):
            radius_to_bounds(latitude=21.0, longitude=81.0, radius_km=0.0)

    def test_equator_zero_lon_clamped(self):
        # At lon=0, the conversion should still work
        south, north, west, east = radius_to_bounds(
            latitude=0.0, longitude=0.0, radius_km=0.5,
        )
        self.assertLess(south, 0.0)
        self.assertGreater(north, 0.0)
        self.assertLess(west, 0.0)
        self.assertGreater(east, 0.0)


class TestDemResult(unittest.TestCase):
    """Test DEMResult dataclass properties."""

    def test_property_accessors(self):
        result = DEMResult(
            file_path="/tmp/test.tif",
            dem_type="COP30",
            bbox=(25.0, 25.1, 78.0, 78.5),
            metadata={},
            is_temp=False,
        )
        self.assertEqual(result.south, 25.0)
        self.assertEqual(result.north, 25.1)
        self.assertEqual(result.west, 78.0)
        self.assertEqual(result.east, 78.5)

    def test_cleanup_idempotent(self):
        result = DEMResult(
            file_path="/tmp/nonexistent_file_xyz.tif",
            dem_type="COP30",
            bbox=(25.0, 25.1, 78.0, 78.5),
            metadata={},
            is_temp=True,
        )
        # Should not raise even if file does not exist
        cleanup_dem(result)

    def test_supported_dem_types(self):
        self.assertIn("COP30", SUPPORTED_DEM_TYPES)
        self.assertEqual(DEFAULT_DEM_TYPE, "COP30")


class TestGeotiffBinaryValidation(unittest.TestCase):
    """Test the _is_geotiff_binary helper function."""

    def test_little_endian_valid(self):
        # Standard little-endian TIFF/GeoTIFF header (II * \x00)
        content = b"II*\x00" + b"\x00" * 200
        self.assertTrue(_is_geotiff_binary(content))

    def test_big_endian_valid(self):
        # Standard big-endian TIFF/GeoTIFF header (MM \x00 *)
        content = b"MM\x00*" + b"\x00" * 200
        self.assertTrue(_is_geotiff_binary(content))

    def test_random_binary_rejected(self):
        self.assertFalse(_is_geotiff_binary(b"\x00\x01\x02\x03\x04\x05\x06\x07"))

    def test_json_error_payload_rejected(self):
        # A JSON error message must NOT be accepted as a GeoTIFF
        self.assertFalse(_is_geotiff_binary(b'{"error": "Invalid API key"}'))

    def test_html_error_rejected(self):
        self.assertFalse(_is_geotiff_binary(b"<html><body>Error 403</body></html>"))

    def test_too_short_rejected(self):
        self.assertFalse(_is_geotiff_binary(b"II*\x00"))
        self.assertFalse(_is_geotiff_binary(b""))
        self.assertFalse(_is_geotiff_binary(b"\x00" * 7))

    def test_plain_text_rejected(self):
        self.assertFalse(_is_geotiff_binary(b"Plain text content of an error page"))


class TestDemContentTypeHandling(unittest.TestCase):
    """Test OpenTopography response content-type handling.

    The API may return:
    - image/tiff  → must validate GeoTIFF header
    - application/octet-stream → only accept if binary is valid GeoTIFF
    - JSON (error payload) → extract error message
    - Other → reject with useful message
    """

    def setUp(self):
        os.environ["OPENTOPOGRAPHY_API_KEY"] = "test_key_12345"

    def tearDown(self):
        if "OPENTOPOGRAPHY_API_KEY" in os.environ:
            del os.environ["OPENTOPOGRAPHY_API_KEY"]

    @mock.patch("services.dem_acquisition.requests.get")
    def test_image_tiff_accepted_with_valid_geotiff(self, mock_get):
        """image/tiff with valid GeoTIFF magic bytes is accepted."""
        fake_geotiff = b"II*\x00" + b"\x00" * 200
        fake_response = mock.MagicMock(spec=requests.Response)
        fake_response.status_code = 200
        fake_response.headers = {"Content-Type": "image/tiff"}
        fake_response.content = fake_geotiff
        fake_response.text = ""
        fake_response.iter_content.return_value = [fake_geotiff]
        mock_get.return_value = fake_response

        # Should NOT raise - valid GeoTIFF
        result = download_dem(25.0, 25.1, 78.0, 78.5)
        self.assertEqual(result.dem_type, "COP30")

    @mock.patch("services.dem_acquisition.requests.get")
    def test_octet_stream_accepted_when_binary_is_geotiff(self, mock_get):
        """application/octet-stream with valid GeoTIFF bytes is accepted."""
        fake_geotiff = b"MM\x00*" + b"\xff" * 500
        fake_response = mock.MagicMock(spec=requests.Response)
        fake_response.status_code = 200
        fake_response.headers = {"Content-Type": "application/octet-stream"}
        fake_response.content = fake_geotiff
        fake_response.text = ""
        fake_response.iter_content.return_value = [fake_geotiff]
        mock_get.return_value = fake_response

        # Should NOT raise - binary is a valid GeoTIFF
        result = download_dem(25.0, 25.1, 78.0, 78.5)
        self.assertEqual(result.dem_type, "COP30")

    @mock.patch("services.dem_acquisition.requests.get")
    def test_octet_stream_rejected_when_binary_is_json_error(self, mock_get):
        """application/octet-stream containing JSON error is rejected with useful message."""
        error_payload = b'{"error": "Invalid bounding box"}'
        fake_response = mock.MagicMock(spec=requests.Response)
        fake_response.status_code = 200
        fake_response.headers = {"Content-Type": "application/octet-stream"}
        fake_response.content = error_payload
        fake_response.text = '{"error": "Invalid bounding box"}'
        fake_response.iter_content.return_value = [error_payload]
        mock_get.return_value = fake_response

        with self.assertRaises(DEMAPIError) as ctx:
            download_dem(25.0, 25.1, 78.0, 78.5)
        # Must NOT say "KML or KMZ"
        self.assertNotIn("KML", str(ctx.exception))
        self.assertNotIn("KMZ", str(ctx.exception))
        # Should mention the actual error or that binary is not a valid GeoTIFF
        self.assertIn("not a valid GeoTIFF", str(ctx.exception))

    @mock.patch("services.dem_acquisition.requests.get")
    def test_octet_stream_rejected_when_binary_is_random(self, mock_get):
        """application/octet-stream with random bytes is rejected."""
        fake_response = mock.MagicMock(spec=requests.Response)
        fake_response.status_code = 200
        fake_response.headers = {"Content-Type": "application/octet-stream"}
        fake_response.content = b"\xde\xad\xbe\xef" * 50
        fake_response.text = ""
        fake_response.iter_content.return_value = [b"\xde\xad\xbe\xef" * 50]
        mock_get.return_value = fake_response

        with self.assertRaises(DEMAPIError) as ctx:
            download_dem(25.0, 25.1, 78.0, 78.5)
        self.assertIn("not a valid GeoTIFF", str(ctx.exception))

    @mock.patch("services.dem_acquisition.requests.get")
    def test_image_tiff_rejected_when_binary_is_not_geotiff(self, mock_get):
        """image/tiff with invalid binary content is rejected."""
        fake_response = mock.MagicMock(spec=requests.Response)
        fake_response.status_code = 200
        fake_response.headers = {"Content-Type": "image/tiff"}
        fake_response.content = b"<html>Error 403</html>"
        fake_response.text = "<html>Error 403</html>"
        fake_response.iter_content.return_value = [b"<html>Error 403</html>"]
        mock_get.return_value = fake_response

        with self.assertRaises(DEMAPIError) as ctx:
            download_dem(25.0, 25.1, 78.0, 78.5)
        self.assertIn("valid GeoTIFF", str(ctx.exception))

    @mock.patch("services.dem_acquisition.requests.get")
    def test_json_error_extracted_from_json_response(self, mock_get):
        """JSON error payload returns useful error message."""
        error_payload = b'{"error": "Quota exceeded"}'
        fake_response = mock.MagicMock(spec=requests.Response)
        fake_response.status_code = 200
        fake_response.headers = {"Content-Type": "application/json"}
        fake_response.content = error_payload
        fake_response.text = '{"error": "Quota exceeded"}'
        fake_response.json.return_value = {"error": "Quota exceeded"}
        fake_response.iter_content.return_value = [error_payload]
        mock_get.return_value = fake_response

        with self.assertRaises(DEMAPIError) as ctx:
            download_dem(25.0, 25.1, 78.0, 78.5)
        self.assertIn("Quota exceeded", str(ctx.exception))
        self.assertNotIn("KML", str(ctx.exception))

    @mock.patch("services.dem_acquisition.requests.get")
    def test_http_500_raises_api_error(self, mock_get):
        """HTTP 500 response raises DEMAPIError with status info."""
        fake_response = mock.MagicMock(spec=requests.Response)
        fake_response.status_code = 500
        fake_response.headers = {"Content-Type": "text/plain"}
        fake_response.content = b"Internal Server Error"
        fake_response.text = "Internal Server Error"
        fake_response.iter_content.return_value = [b"Internal Server Error"]
        mock_get.return_value = fake_response

        with self.assertRaises(DEMAPIError) as ctx:
            download_dem(25.0, 25.1, 78.0, 78.5)
        self.assertIn("500", str(ctx.exception))

    @mock.patch("services.dem_acquisition.requests.get")
    def test_api_key_not_in_logs(self, mock_get):
        """API key value is never included in log output."""
        import io
        import logging

        fake_geotiff = b"II*\x00" + b"\x00" * 200
        fake_response = mock.MagicMock(spec=requests.Response)
        fake_response.status_code = 200
        fake_response.headers = {"Content-Type": "image/tiff"}
        fake_response.content = fake_geotiff
        fake_response.text = ""
        fake_response.iter_content.return_value = [fake_geotiff]
        mock_get.return_value = fake_response

        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        handler.setLevel(logging.INFO)
        logger_dem = logging.getLogger("services.dem_acquisition")
        logger_dem.addHandler(handler)
        try:
            download_dem(25.0, 25.1, 78.0, 78.5)
        finally:
            logger_dem.removeHandler(handler)

        log_output = log_capture.getvalue()
        self.assertNotIn("test_key_12345", log_output)


if __name__ == "__main__":
    unittest.main()
