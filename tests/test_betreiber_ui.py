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


class TestOberflaecheStatisch(unittest.TestCase):
    """Wächter über ui/betreiber/betreiber.js (ersetzt keine Prüfung im Browser, siehe tools/ui_pruefung)."""

    def quelle(self):
        pfad = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui", "betreiber", "betreiber.js")
        with open(pfad, encoding="utf-8") as f:
            return f.read()

    def test_keine_unscharfe_knopfsuche(self):
        """document.querySelector('.btn-secondary') greift den ersten beliebigen Knopf der Seite, nicht den gemeinten."""
        q = self.quelle()
        for muster in ("querySelector('.btn-secondary')", "querySelector('.btn-primary')", 'querySelector(".btn-secondary")', 'querySelector("button")', "querySelector('button')"):
            self.assertNotIn(muster, q, muster)

    def test_rollen_und_interessen_werden_als_wert_und_bezeichnung_benutzt(self):
        q = self.quelle()
        for muster in ("checkbox.value = rolle;", "checkbox.value = interesse;", "option.value = rolle;", "' ' + rolle)", "' ' + interesse)"):
            self.assertNotIn(muster, q, muster)

    def test_keine_inline_stile_als_attribut_und_kein_eval(self):
        q = self.quelle()
        for muster in ("setAttribute('style'", 'setAttribute("style"', "style=\"", "cssText", "eval(", "new Function("):
            self.assertNotIn(muster, q, muster)


if __name__ == "__main__":
    unittest.main()
