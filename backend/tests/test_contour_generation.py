"""
Unit tests for backend/services/contour_generation.py

Tests cover:
- valid GeoJSON LineString conversion
- MultiLineString conversion
- missing elevation handling
- malformed features
- empty output
- GDAL failure
- invalid contour interval
- DEM file validation

All tests mock subprocess.run and file I/O to avoid calling actual
GDAL tools or reading/writing real files.
"""

import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from services.contour_generation import (
    generate_contours,
    cleanup_contour_result,
    _parse_geojson_features,
    _build_contour,
    ContourGenerationResult,
    ContourGenerationError,
    ContourValidationError,
    GDALNotFoundError,
    DEFAULT_CONTOUR_INTERVAL_M,
)
from models import ContourLine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_subprocess_result(returncode=0, stdout="", stderr="", timeout=False):
    """Create a fake subprocess.CompletedProcess or raise TimeoutExpired."""
    if timeout:
        raise subprocess.TimeoutExpired("gdal_contour", 300)
    result = mock.MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


# ---------------------------------------------------------------------------
# _parse_geojson_features unit tests
# ---------------------------------------------------------------------------


class TestParseGeoJsonFeatures(unittest.TestCase):
    """Test the GeoJSON-to-ContourLine conversion logic."""

    def test_linestring_basic(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [78.1, 25.1, 100.0],
                            [78.2, 25.1, 100.0],
                            [78.2, 25.2, 100.0],
                        ]
                    },
                    "properties": {"elevation": 100.0},
                }
            ],
        }
        contours = _parse_geojson_features(geojson)
        self.assertEqual(len(contours), 1)
        self.assertIsInstance(contours[0], ContourLine)
        self.assertEqual(contours[0].elevation, 100.0)
        self.assertEqual(len(contours[0].points), 3)

    def test_multilinestring(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "MultiLineString",
                        "coordinates": [
                            [[78.1, 25.1, 100.0], [78.2, 25.1, 100.0]],
                            [[78.3, 25.1, 100.0], [78.4, 25.1, 100.0]],
                        ]
                    },
                    "properties": {"elevation": 100.0},
                }
            ],
        }
        contours = _parse_geojson_features(geojson)
        # MultiLineString should produce 2 contours
        self.assertEqual(len(contours), 2)
        for c in contours:
            self.assertEqual(c.elevation, 100.0)

    def test_missing_elevation_skipped(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[78.1, 25.1, 100.0]],
                    },
                    "properties": {},
                }
            ],
        }
        contours = _parse_geojson_features(geojson)
        self.assertEqual(len(contours), 0)

    def test_empty_coordinates(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [],
                    },
                    "properties": {"elevation": 100.0},
                }
            ],
        }
        contours = _parse_geojson_features(geojson)
        self.assertEqual(len(contours), 0)

    def test_invalid_elevation_type(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[78.1, 25.1, 100.0]],
                    },
                    "properties": {"elevation": "not_a_number"},
                }
            ],
        }
        contours = _parse_geojson_features(geojson)
        self.assertEqual(len(contours), 0)

    def test_unsupported_geometry_type(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[78.1, 25.1], [78.2, 25.1], [78.2, 25.2], [78.1, 25.1]]],
                    },
                    "properties": {"elevation": 100.0},
                }
            ],
        }
        contours = _parse_geojson_features(geojson)
        self.assertEqual(len(contours), 0)

    def test_mixed_valid_and_invalid_features(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[78.1, 25.1, 100.0], [78.2, 25.1, 100.0]],
                    },
                    "properties": {"elevation": 100.0},
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [],
                    },
                    "properties": {"elevation": 101.0},
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[78.3, 25.1, 102.0]],
                    },
                    "properties": {},
                },
            ],
        }
        contours = _parse_geojson_features(geojson)
        self.assertEqual(len(contours), 1)
        self.assertEqual(contours[0].elevation, 100.0)

    def test_empty_feature_collection(self):
        geojson = {"type": "FeatureCollection", "features": []}
        contours = _parse_geojson_features(geojson)
        self.assertEqual(len(contours), 0)


# ---------------------------------------------------------------------------
# _build_contour unit tests
# ---------------------------------------------------------------------------


class TestBuildContour(unittest.TestCase):
    """Test the _build_contour helper."""

    def test_with_elevation_tuple_coords(self):
        coords = [[78.1, 25.1, 100.0], [78.2, 25.2, 100.0]]
        contour = _build_contour(100.0, coords)
        self.assertIsNotNone(contour)
        self.assertEqual(len(contour.points), 2)
        self.assertEqual(contour.points[0].lon, 78.1)
        self.assertEqual(contour.points[0].lat, 25.1)
        self.assertEqual(contour.points[0].elevation, 100.0)

    def test_with_2d_coords(self):
        coords = [[78.1, 25.1], [78.2, 25.2]]
        contour = _build_contour(50.0, coords)
        self.assertIsNotNone(contour)
        self.assertEqual(len(contour.points), 2)
        self.assertEqual(contour.points[0].elevation, 50.0)

    def test_empty_coords_returns_none(self):
        contour = _build_contour(100.0, [])
        self.assertIsNone(contour)

    def test_skips_non_numeric_coords(self):
        coords = [["a", "b"], [78.2, 25.2]]
        contour = _build_contour(100.0, coords)
        self.assertIsNotNone(contour)
        self.assertEqual(len(contour.points), 1)


# ---------------------------------------------------------------------------
# generate_contours validation tests (no subprocess)
# ---------------------------------------------------------------------------


class TestContourValidation(unittest.TestCase):
    """Test input validation without calling subprocess."""

    def test_invalid_interval_zero(self):
        with self.assertRaises(ContourValidationError):
            generate_contours(dem_path="/tmp/dem.tif", interval_m=0.0)

    def test_invalid_interval_negative(self):
        with self.assertRaises(ContourValidationError):
            generate_contours(dem_path="/tmp/dem.tif", interval_m=-1.0)

    def test_empty_dem_path(self):
        with self.assertRaises(ContourValidationError):
            generate_contours(dem_path="", interval_m=1.0)

    def test_nonexistent_dem_path(self):
        with self.assertRaises(ContourValidationError) as ctx:
            generate_contours(dem_path="/tmp/does_not_exist.tif", interval_m=1.0)
        self.assertIn("does not exist", str(ctx.exception))


# ---------------------------------------------------------------------------
# generate_contours GDAL failure tests
# ---------------------------------------------------------------------------


class TestContourGdalFailure(unittest.TestCase):
    """Test GDAL subprocess failure handling."""

    def setUp(self):
        # Create a real temporary DEM file to pass validation
        fd, self._temp_dem = tempfile.mkstemp(suffix=".tif")
        os.close(fd)
        with open(self._temp_dem, "wb") as f:
            f.write(b"fake dem content")

    def tearDown(self):
        if os.path.exists(self._temp_dem):
            os.unlink(self._temp_dem)

    @mock.patch("services.contour_generation.shutil.which")
    def test_gdal_not_found(self, mock_which):
        mock_which.return_value = None
        with self.assertRaises(GDALNotFoundError):
            generate_contours(dem_path=self._temp_dem, interval_m=1.0)

    @mock.patch("services.contour_generation.shutil.which")
    @mock.patch("services.contour_generation.subprocess.run")
    def test_gdal_returns_nonzero(self, mock_run, mock_which):
        mock_which.return_value = "/usr/bin/gdal_contour"
        mock_run.return_value = _make_subprocess_result(
            returncode=1,
            stderr="ERROR 1: Something went wrong",
        )
        with self.assertRaises(ContourGenerationError) as ctx:
            generate_contours(dem_path=self._temp_dem, interval_m=1.0)
        self.assertIn("gdal_contour failed", str(ctx.exception))

    @mock.patch("services.contour_generation.shutil.which")
    @mock.patch("services.contour_generation.subprocess.run")
    def test_gdal_timeout(self, mock_run, mock_which):
        mock_which.return_value = "/usr/bin/gdal_contour"
        mock_run.side_effect = subprocess.TimeoutExpired("gdal_contour", 300)
        with self.assertRaises(ContourGenerationError) as ctx:
            generate_contours(dem_path=self._temp_dem, interval_m=1.0)
        self.assertIn("timed out", str(ctx.exception))

    @mock.patch("services.contour_generation.shutil.which")
    @mock.patch("services.contour_generation.subprocess.run")
    def test_no_output_file(self, mock_run, mock_which):
        mock_which.return_value = "/usr/bin/gdal_contour"
        mock_run.return_value = _make_subprocess_result(returncode=0)
        # The tempfile geojson path does not exist
        with self.assertRaises(ContourGenerationError) as ctx:
            generate_contours(dem_path=self._temp_dem, interval_m=1.0)
        # When using a fresh mkstemp path, gdal_contour is expected to create
        # the file. If it doesn't, we now report a "did not produce output"
        # error (the file was successfully unlinked before invocation).
        self.assertIn("did not produce output", str(ctx.exception))


# ---------------------------------------------------------------------------
# generate_contours success / JSON parsing tests
# ---------------------------------------------------------------------------


class TestContourGenerationSuccess(unittest.TestCase):
    """Test successful contour generation with mocked subprocess and JSON."""

    def setUp(self):
        fd, self._temp_dem = tempfile.mkstemp(suffix=".tif")
        os.close(fd)
        with open(self._temp_dem, "wb") as f:
            f.write(b"fake dem content")
        fd, self._temp_geojson = tempfile.mkstemp(suffix=".geojson")
        os.close(fd)

    def tearDown(self):
        for path in [self._temp_dem, self._temp_geojson]:
            if os.path.exists(path):
                os.unlink(path)

    @mock.patch("services.contour_generation.shutil.which")
    @mock.patch("services.contour_generation.subprocess.run")
    def test_valid_geojson_produces_contours(self, mock_run, mock_which):
        mock_which.return_value = "/usr/bin/gdal_contour"

        # Build the valid GeoJSON that the mocked gdal_contour will write.
        geojson_data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [78.1, 25.1, 100.0],
                            [78.2, 25.1, 100.0],
                        ],
                    },
                    "properties": {"elevation": 100.0},
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [78.1, 25.2, 101.0],
                            [78.2, 25.2, 101.0],
                        ],
                    },
                    "properties": {"elevation": 101.0},
                },
            ],
        }
        mock_file_content = json.dumps(geojson_data)

        # The mocked subprocess.run must *create* the output file (which is
        # what the real gdal_contour does). Otherwise the service will
        # correctly report that gdal_contour did not produce output.
        def _fake_run(cmd, *args, **kwargs):
            # The output path is the last argument in the gdal_contour command.
            output_path = cmd[-1]
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(mock_file_content)
            return _make_subprocess_result(returncode=0)

        mock_run.side_effect = _fake_run

        result = generate_contours(
            dem_path=self._temp_dem,
            interval_m=1.0,
            output_geojson_path=self._temp_geojson,
        )

        self.assertIsInstance(result, ContourGenerationResult)
        self.assertEqual(result.contour_count, 2)
        self.assertEqual(len(result.contours), 2)
        self.assertEqual(result.interval_m, 1.0)
        self.assertEqual(result.num_features, 2)

    @mock.patch("services.contour_generation.shutil.which")
    @mock.patch("services.contour_generation.subprocess.run")
    def test_malformed_json_raises(self, mock_run, mock_which):
        mock_which.return_value = "/usr/bin/gdal_contour"

        # The mocked gdal_contour writes invalid JSON to the output file.
        def _fake_run(cmd, *args, **kwargs):
            output_path = cmd[-1]
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("{ not valid json }")
            return _make_subprocess_result(returncode=0)

        mock_run.side_effect = _fake_run

        with self.assertRaises(ContourGenerationError) as ctx:
            generate_contours(
                dem_path=self._temp_dem,
                interval_m=1.0,
                output_geojson_path=self._temp_geojson,
            )
        self.assertIn("Failed to read GeoJSON", str(ctx.exception))


# ---------------------------------------------------------------------------
# ContourGenerationResult dataclass tests
# ---------------------------------------------------------------------------


class TestContourGenerationResult(unittest.TestCase):
    """Test the ContourGenerationResult dataclass."""

    def test_contour_count_property(self):
        from services.contour_generation import ContourGenerationResult
        from models import ContourLine, ContourPoint

        # Create dummy contours
        points = [ContourPoint(lon=78.1, lat=25.1, elevation=100.0)]
        contours = [ContourLine(elevation=100.0, points=points)]

        result = ContourGenerationResult(
            contours=contours,
            dem_path="/tmp/dem.tif",
            output_geojson_path="/tmp/c.geojson",
            interval_m=1.0,
            num_features=1,
        )
        self.assertEqual(result.contour_count, 1)


if __name__ == "__main__":
    unittest.main()
