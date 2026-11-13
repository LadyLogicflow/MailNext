"""Betreiber-Oberfläche: statische Auslieferung unter /betreiber (nur flache Dateinamen, strenge Kopfzeilen)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import betreiber_ui
from app import create_app


class UiTests(unittest.TestCase):
    def setUp(self):
        self.verz = tempfile.TemporaryDirectory()
        self.c = create_app(os.path.join(self.verz.name, "t.db")).test_client()

    def tearDown(self):
        self.verz.cleanup()

    def test_startseite_und_kopfzeilen(self):
        for pfad in ("/betreiber", "/betreiber/", "/betreiber/index.html"):
            r = self.c.get(pfad)
            self.assertEqual(r.status_code, 200, pfad)
            self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
            self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
            self.assertEqual(r.headers["Referrer-Policy"], "no-referrer")
            self.assertEqual(r.headers["Cache-Control"], "no-store")
            self.assertIn("noindex", r.headers["X-Robots-Tag"])

    def test_pfadtricks_und_fremde_dateien_404(self):
        for pfad in ("/betreiber/..%2Fapp.py", "/betreiber/../app.py", "/betreiber/%2e%2e/app.py", "/betreiber/app.py", "/betreiber/.env",
                     "/betreiber/nichtda.js", "/betreiber/a/b.js", "/betreiber/index.html%00.js"):
            self.assertIn(self.c.get(pfad).status_code, (404, 308, 400), pfad)
        self.assertEqual(self.c.get("/betreiber/app.py").status_code, 404)

    def test_dateinamen_regel(self):
        for gut in ("index.html", "app.js", "stil.css", "logo.svg"):
            self.assertTrue(betreiber_ui.DATEINAME.match(gut), gut)
        for schlecht in ("../x.js", "a/b.js", ".versteckt.js", "x.py", "x.html.py", "x" * 70 + ".js"):
            self.assertFalse(betreiber_ui.DATEINAME.match(schlecht), schlecht)

    def test_api_bleibt_geschuetzt(self):
        self.assertEqual(self.c.get("/api/v1/betreiber/mandanten").status_code, 401)


if __name__ == "__main__":
    unittest.main()
