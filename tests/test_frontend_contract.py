import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.javascript = (ROOT / "static" / "app.js").read_text()
        cls.html = (ROOT / "static" / "index.html").read_text()
        cls.css = (ROOT / "static" / "operations.css").read_text()

    def test_chart_has_legacy_round_rect_fallback(self):
        self.assertIn("typeof context.roundRect==='function'", self.javascript)
        self.assertIn("quadraticCurveTo", self.javascript)

    def test_column_resize_has_pointer_lifecycle_and_minimum_width(self):
        for expected in ("mousedown", "mousemove", "mouseup", "Math.max(54", "resizing-column"):
            self.assertIn(expected, self.javascript)

    def test_all_breach_fields_are_visible(self):
        for expected in ("Deadline", "Last Customer Comment", "Subject"):
            self.assertIn(expected, self.html)
        self.assertIn("x['SLA Deadline']", self.javascript)
        self.assertIn("x['Last Customer Comment']", self.javascript)
        self.assertIn("x.Subject", self.javascript)

    def test_warnings_and_horizontal_overflow_are_present(self):
        self.assertIn('id="warnings"', self.html)
        self.assertIn("overflow-x: auto", self.css)


if __name__ == "__main__":
    unittest.main()
