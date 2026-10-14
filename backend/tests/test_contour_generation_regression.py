"""Regression tests for the GeoJSON driver overwrite bug."""

import json, os, subprocess, tempfile, unittest
from unittest import mock
from services.contour_generation import (
    generate_contours, cleanup_contour_result, ContourGenerationError,
)

TRIVIAL_GEOJSON = json.dumps({
    "type": "FeatureCollection",
    "features": [{"type": "Feature", "geometry": {
        "type": "LineString", "coordinates": [[78.1, 25.1, 100.0], [78.2, 25.1, 100.0]]},
        "properties": {"elevation": 100.0}}]
})

def _make_result(returncode=0, stdout="", stderr=""):
    r = mock.MagicMock()
    r.returncode = returncode; r.stdout = stdout; r.stderr = stderr
    return r

class TestContourRegression(unittest.TestCase):
    def setUp(self):
        fd, self._dem = tempfile.mkstemp(suffix=".tif")
        os.close(fd)
        with open(self._dem, "wb") as f: f.write(b"fake dem content")
        fd, self._explicit = tempfile.mkstemp(suffix=".geojson")
        os.close(fd)

    def tearDown(self):
        for p in (self._dem, self._explicit):
            if os.path.exists(p): os.unlink(p)

    @mock.patch("services.contour_generation.shutil.which")
    @mock.patch("services.contour_generation.subprocess.run")
    def test_existing_output_file(self, mock_run, mock_which):
        """Pre-existing file at output_geojson_path must not cause overwrite error."""
        mock_which.return_value = "/usr/bin/gdal_contour"
        def fake_run(cmd, *a, **kw):
            self.assertFalse(os.path.exists(cmd[-1]))
            with open(cmd[-1], "w") as f: f.write(TRIVIAL_GEOJSON)
            return _make_result()
        mock_run.side_effect = fake_run
        r = generate_contours(self._dem, 1.0, output_geojson_path=self._explicit)
        self.assertEqual(r.contour_count, 1)

    @mock.patch("services.contour_generation.shutil.which")
    @mock.patch("services.contour_generation.subprocess.run")
    def test_repeated_generation(self, mock_run, mock_which):
        """Two calls with same output path must both succeed."""
        mock_which.return_value = "/usr/bin/gdal_contour"
        def fake_run(cmd, *a, **kw):
            self.assertFalse(os.path.exists(cmd[-1]))
            with open(cmd[-1], "w") as f: f.write(TRIVIAL_GEOJSON)
            return _make_result()
        mock_run.side_effect = fake_run
        r1 = generate_contours(self._dem, 1.0, output_geojson_path=self._explicit)
        r2 = generate_contours(self._dem, 1.0, output_geojson_path=self._explicit)
        self.assertEqual(r1.contour_count, 1)
        self.assertEqual(r2.contour_count, 1)

    @mock.patch("services.contour_generation.shutil.which")
    @mock.patch("services.contour_generation.subprocess.run")
    def test_two_implicit_paths_dont_collide(self, mock_run, mock_which):
        """Two implicit calls must use distinct temp paths."""
        mock_which.return_value = "/usr/bin/gdal_contour"
        paths = []
        def fake_run(cmd, *a, **kw):
            paths.append(cmd[-1])
            with open(cmd[-1], "w") as f: f.write(TRIVIAL_GEOJSON)
            return _make_result()
        mock_run.side_effect = fake_run
        r1 = generate_contours(self._dem, 1.0)
        r2 = generate_contours(self._dem, 1.0)
        self.assertNotEqual(paths[0], paths[1])
        for p in paths:
            self.assertFalse(os.path.exists(p))

    @mock.patch("services.contour_generation.shutil.which")
    @mock.patch("services.contour_generation.subprocess.run")
    def test_cleanup_after_success(self, mock_run, mock_which):
        """Implicit temp file is removed on success."""
        mock_which.return_value = "/usr/bin/gdal_contour"
        path = {}
        def fake_run(cmd, *a, **kw):
            path["p"] = cmd[-1]
            with open(cmd[-1], "w") as f: f.write(TRIVIAL_GEOJSON)
            return _make_result()
        mock_run.side_effect = fake_run
        r = generate_contours(self._dem, 1.0)
        self.assertFalse(os.path.exists(path["p"]))
        self.assertEqual(r.output_geojson_path, "")

    @mock.patch("services.contour_generation.shutil.which")
    @mock.patch("services.contour_generation.subprocess.run")
    def test_cleanup_after_failure(self, mock_run, mock_which):
        """Implicit temp file is removed after gdal_contour failure."""
        mock_which.return_value = "/usr/bin/gdal_contour"
        path = {}
        def fake_run(cmd, *a, **kw):
            path["p"] = cmd[-1]
            return _make_result(returncode=1, stderr="error")
        mock_run.side_effect = fake_run
        with self.assertRaises(ContourGenerationError):
            generate_contours(self._dem, 1.0)
        self.assertFalse(os.path.exists(path["p"]))

    @mock.patch("services.contour_generation.shutil.which")
    @mock.patch("services.contour_generation.subprocess.run")
    def test_cleanup_after_timeout(self, mock_run, mock_which):
        """Implicit temp file is removed after gdal_contour timeout."""
        mock_which.return_value = "/usr/bin/gdal_contour"
        path = {}
        def fake_run(cmd, *a, **kw):
            path["p"] = cmd[-1]
            raise subprocess.TimeoutExpired("gdal_contour", 300)
        mock_run.side_effect = fake_run
        with self.assertRaises(ContourGenerationError):
            generate_contours(self._dem, 1.0)
        self.assertFalse(os.path.exists(path["p"]))

    @mock.patch("services.contour_generation.shutil.which")
    @mock.patch("services.contour_generation.subprocess.run")
    def test_normal_success_caller_path(self, mock_run, mock_which):
        """Normal happy path with explicit output path."""
        mock_which.return_value = "/usr/bin/gdal_contour"
        def fake_run(cmd, *a, **kw):
            with open(cmd[-1], "w") as f: f.write(TRIVIAL_GEOJSON)
            return _make_result()
        mock_run.side_effect = fake_run
        r = generate_contours(self._dem, 1.0, output_geojson_path=self._explicit)
        self.assertEqual(r.contour_count, 1)
        self.assertEqual(r.output_geojson_path, self._explicit)

    @mock.patch("services.contour_generation.shutil.which")
    @mock.patch("services.contour_generation.subprocess.run")
    def test_normal_success_implicit(self, mock_run, mock_which):
        """Normal happy path with implicit temp path (auto-cleanup)."""
        mock_which.return_value = "/usr/bin/gdal_contour"
        def fake_run(cmd, *a, **kw):
            with open(cmd[-1], "w") as f: f.write(TRIVIAL_GEOJSON)
            return _make_result()
        mock_run.side_effect = fake_run
        r = generate_contours(self._dem, 1.0)
        self.assertEqual(r.contour_count, 1)
        self.assertEqual(r.output_geojson_path, "")

    @mock.patch("services.contour_generation.shutil.which")
    @mock.patch("services.contour_generation.subprocess.run")
    def test_keep_geojson(self, mock_run, mock_which):
        """keep_geojson=True preserves the implicit temp file."""
        mock_which.return_value = "/usr/bin/gdal_contour"
        p = {}
        def fake_run(cmd, *a, **kw):
            p["v"] = cmd[-1]
            with open(cmd[-1], "w") as f: f.write(TRIVIAL_GEOJSON)
            return _make_result()
        mock_run.side_effect = fake_run
        r = generate_contours(self._dem, 1.0, keep_geojson=True)
        self.assertEqual(r.output_geojson_path, p["v"])
        cleanup_contour_result(r)
        self.assertFalse(os.path.exists(p["v"]))

if __name__ == "__main__":
    unittest.main()
