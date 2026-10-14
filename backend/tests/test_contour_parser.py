
"""Unit tests for contour_parser.py"""
import io
import unittest
import zipfile

from services.contour_parser import (
    parse_contour_file, ContourParserError,
    _is_numeric_token, _is_valid_coordinate,
    _is_suspicious_numeric_value, _parse_elevation_from_name
)

NS = "http://www.opengis.net/kml/2.2"

def mk(body):
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            + "<kml xmlns=\"" + NS + "\">\n"
            + body + "\n</kml>").encode("utf-8")

def mkz(body, name="doc.kml"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, mk(body))
    return buf.getvalue()


class TestHelpers(unittest.TestCase):
    def test_numeric_token(self):
        self.assertTrue(_is_numeric_token("277"))
        self.assertTrue(_is_numeric_token("277.0"))
        self.assertFalse(_is_numeric_token("abc"))

    def test_valid_coord(self):
        self.assertTrue(_is_valid_coordinate(0.0, 0.0))
        self.assertTrue(_is_valid_coordinate(81.0, 21.0))
        self.assertFalse(_is_valid_coordinate(181.0, 0.0))
        self.assertFalse(_is_valid_coordinate(0.0, 91.0))
        self.assertFalse(_is_valid_coordinate(float("inf"), 0.0))

    def test_suspicious_value(self):
        self.assertTrue(_is_suspicious_numeric_value("2024"))
        self.assertTrue(_is_suspicious_numeric_value("999999"))
        self.assertFalse(_is_suspicious_numeric_value("277"))

    def test_elevation_from_name(self):
        self.assertEqual(_parse_elevation_from_name("277.0"), 277.0)
        self.assertEqual(_parse_elevation_from_name("Elevation: 282.5m"), 282.5)
        self.assertEqual(_parse_elevation_from_name("Contour 300"), 300.0)
        self.assertEqual(_parse_elevation_from_name("Elev: 100"), 100.0)


class TestNumericName(unittest.TestCase):
    def test_simple_numeric(self):
        body = ("<Placemark><name>277.0</name><LineString>"
                + "<coordinates>81.28,21.26 81.29,21.27</coordinates>"
                + "</LineString></Placemark>")
        c = parse_contour_file("t.kml", mk(body))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].elevation, 277.0)
        self.assertEqual(len(c[0].points), 2)

    def test_integer(self):
        body = ("<Placemark><name>300</name><LineString>"
                + "<coordinates>0,0 1,1</coordinates></LineString></Placemark>")
        c = parse_contour_file("t.kml", mk(body))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].elevation, 300.0)


class TestLabeledName(unittest.TestCase):
    def test_elevation_label(self):
        body = ("<Placemark><name>Elevation: 282.5m</name><LineString>"
                + "<coordinates>0,0 1,1</coordinates></LineString></Placemark>")
        c = parse_contour_file("t.kml", mk(body))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].elevation, 282.5)

    def test_contour_label(self):
        body = ("<Placemark><name>Contour 300</name><LineString>"
                + "<coordinates>0,0 1,1</coordinates></LineString></Placemark>")
        c = parse_contour_file("t.kml", mk(body))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].elevation, 300.0)



class TestExtendedData(unittest.TestCase):
    def test_data_element(self):
        body = ("<Placemark><name>Some</name><ExtendedData>"
                + '<Data name="elevation"><value>277.0</value></Data>'
                + "</ExtendedData><LineString>"
                + "<coordinates>0,0 1,1</coordinates></LineString></Placemark>")
        c = parse_contour_file("t.kml", mk(body))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].elevation, 277.0)

    def test_data_height(self):
        body = ("<Placemark><name>Some</name><ExtendedData>"
                + '<Data name="height"><value>150.5</value></Data>'
                + "</ExtendedData><LineString>"
                + "<coordinates>0,0 1,1</coordinates></LineString></Placemark>")
        c = parse_contour_file("t.kml", mk(body))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].elevation, 150.5)

    def test_schemadata(self):
        body = ("<Placemark><name>Some</name><ExtendedData>"
                + '<SchemaData schemaUrl="#c">'
                + '<SimpleData name="elevation">277.0</SimpleData>'
                + "</SchemaData></ExtendedData><LineString>"
                + "<coordinates>0,0 1,1</coordinates></LineString></Placemark>")
        c = parse_contour_file("t.kml", mk(body))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].elevation, 277.0)


class TestDescription(unittest.TestCase):
    def test_description_elevation(self):
        body = ("<Placemark><name>Some</name>"
                + "<description>Elevation: 282.5 m</description>"
                + "<LineString><coordinates>0,0 1,1</coordinates></LineString></Placemark>")
        c = parse_contour_file("t.kml", mk(body))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].elevation, 282.5)


class TestMultiLine(unittest.TestCase):
    def test_multilinestring(self):
        body = ("<Placemark><name>100</name><MultiLineString>"
                + "<LineString><coordinates>0,0 1,1</coordinates></LineString>"
                + "<LineString><coordinates>2,2 3,3</coordinates></LineString>"
                + "</MultiLineString></Placemark>")
        c = parse_contour_file("t.kml", mk(body))
        self.assertEqual(len(c), 1)
        self.assertEqual(len(c[0].points), 4)


class TestMultiGeometry(unittest.TestCase):
    def test_multigeometry(self):
        body = ("<Placemark><name>100</name><MultiGeometry>"
                + "<LineString><coordinates>0,0 1,1</coordinates></LineString>"
                + "<LineString><coordinates>2,2 3,3</coordinates></LineString>"
                + "</MultiGeometry></Placemark>")
        c = parse_contour_file("t.kml", mk(body))
        self.assertEqual(len(c), 1)
        self.assertEqual(len(c[0].points), 4)


class TestNestedFolders(unittest.TestCase):
    def test_deeply_nested(self):
        body = ("<Folder><Folder><Folder>"
                + "<Placemark><name>100</name>"
                + "<LineString><coordinates>0,0 1,1</coordinates></LineString>"
                + "</Placemark></Folder></Folder></Folder>")
        c = parse_contour_file("t.kml", mk(body))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].elevation, 100.0)



class TestKMZ(unittest.TestCase):
    def test_doc_kml(self):
        body = ("<Placemark><name>100</name>"
                + "<LineString><coordinates>0,0 1,1</coordinates></LineString>"
                + "</Placemark>")
        c = parse_contour_file("t.kmz", mkz(body, "doc.kml"))
        self.assertEqual(len(c), 1)

    def test_prefers_doc_kml(self):
        body1 = ("<Placemark><name>999</name>"
                 + "<LineString><coordinates>0,0 1,1</coordinates></LineString>"
                 + "</Placemark>")
        body2 = ("<Placemark><name>100</name>"
                 + "<LineString><coordinates>0,0 1,1</coordinates></LineString>"
                 + "</Placemark>")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("other.kml", mk(body1))
            zf.writestr("doc.kml", mk(body2))
        c = parse_contour_file("t.kmz", buf.getvalue())
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].elevation, 100.0)

    def test_prefers_root_level(self):
        body1 = ("<Placemark><name>999</name>"
                 + "<LineString><coordinates>0,0 1,1</coordinates></LineString>"
                 + "</Placemark>")
        body2 = ("<Placemark><name>100</name>"
                 + "<LineString><coordinates>0,0 1,1</coordinates></LineString>"
                 + "</Placemark>")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("subdir/x.kml", mk(body1))
            zf.writestr("root.kml", mk(body2))
        c = parse_contour_file("t.kmz", buf.getvalue())
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].elevation, 100.0)


class TestInvalidKMZ(unittest.TestCase):
    def test_invalid_zip(self):
        with self.assertRaises(ContourParserError) as ctx:
            parse_contour_file("t.kmz", b"not zip")
        self.assertIn("Invalid KMZ", str(ctx.exception))

    def test_no_kml_in_archive(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("readme.txt", b"x")
        with self.assertRaises(ContourParserError) as ctx:
            parse_contour_file("t.kmz", buf.getvalue())
        self.assertIn("no KML", str(ctx.exception))


class TestMissingElevation(unittest.TestCase):
    def test_no_elevation(self):
        body = ("<Placemark><name>NoNumeric</name>"
                + "<LineString><coordinates>0,0 1,1</coordinates></LineString></Placemark>")
        # Parser raises error when no valid contours found
        with self.assertRaises(ContourParserError) as ctx:
            parse_contour_file("t.kml", mk(body))
        self.assertIn("No valid contour", str(ctx.exception))


class TestInvalidCoords(unittest.TestCase):
    def test_out_of_range(self):
        body = ("<Placemark><name>100</name>"
                + "<LineString><coordinates>200,100 300,200</coordinates></LineString></Placemark>")
        with self.assertRaises(ContourParserError) as ctx:
            parse_contour_file("t.kml", mk(body))
        self.assertIn("No valid contour", str(ctx.exception))

    def test_single_point(self):
        body = ("<Placemark><name>100</name>"
                + "<LineString><coordinates>0,0</coordinates></LineString></Placemark>")
        with self.assertRaises(ContourParserError) as ctx:
            parse_contour_file("t.kml", mk(body))
        self.assertIn("No valid contour", str(ctx.exception))



class TestPolygon(unittest.TestCase):
    def test_polygon_ignored(self):
        body = ("<Placemark><name>100</name>"
                + "<Polygon><outerBoundaryIs><LinearRing>"
                + "<coordinates>0,0 1,0 1,1 0,1 0,0</coordinates>"
                + "</LinearRing></outerBoundaryIs></Polygon></Placemark>")
        with self.assertRaises(ContourParserError):
            parse_contour_file("t.kml", mk(body))


class TestMalformedSkip(unittest.TestCase):
    def test_skips_invalid(self):
        body = ("<Placemark><name>100</name>"
                + "<LineString><coordinates>0,0 1,1</coordinates></LineString></Placemark>"
                + "<Placemark><name>NoNumeric</name>"
                + "<LineString><coordinates>0,0 1,1</coordinates></LineString></Placemark>"
                + "<Placemark><name>200</name>"
                + "<LineString><coordinates>2,2 3,3</coordinates></LineString></Placemark>")
        c = parse_contour_file("t.kml", mk(body))
        self.assertEqual(len(c), 2)
        self.assertEqual(sorted([x.elevation for x in c]), [100.0, 200.0])


class TestInvalidXML(unittest.TestCase):
    def test_bad_xml(self):
        with self.assertRaises(ContourParserError) as ctx:
            parse_contour_file("t.kml", b"<bad>")
        self.assertIn("Invalid KML XML", str(ctx.exception))


class TestProfessorSample(unittest.TestCase):
    def test_py_namespaced_tags(self):
        body = ("<Folder><Folder>"
                + '<name xmlns:py="http://x" py:pytype="str">lines</name>'
                + "<Placemark>"
                + '<name xmlns:py="http://x" py:pytype="str">277.0</name>'
                + '<ExtendedData><SchemaData schemaUrl="#c">'
                + '<SimpleData name="ID">0</SimpleData>'
                + "</SchemaData></ExtendedData>"
                + "<LineString><coordinates>81.28,21.26 81.29,21.27</coordinates></LineString>"
                + "</Placemark></Folder></Folder>")
        c = parse_contour_file("t.kml", mk(body))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].elevation, 277.0)
        self.assertEqual(len(c[0].points), 2)


class TestUnsupported(unittest.TestCase):
    def test_unsupported(self):
        with self.assertRaises(ContourParserError) as ctx:
            parse_contour_file("t.txt", b"x")
        self.assertIn("Unsupported file type", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

