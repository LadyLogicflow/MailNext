import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import betreiber_auth
import config
import db
import einstellungen
from app import create_app

SCHLUESSEL = "t" * 40


class Basis(unittest.TestCase):
    def setUp(self):
        self.verz = tempfile.TemporaryDirectory()
        self.app = create_app(os.path.join(self.verz.name, "t.db"))
        self.c = self.app.test_client()
        betreiber_auth.cache_leeren()

    def tearDown(self):
        self.verz.cleanup()

    def mit_schluessel(self, wert=SCHLUESSEL):
        return mock.patch.dict(os.environ, {"MAILNEXT_HAUPTSCHLUESSEL": wert})

    def ohne_schluessel(self):
        env = {k: v for k, v in os.environ.items() if k != "MAILNEXT_HAUPTSCHLUESSEL"}
        return mock.patch.dict(os.environ, env, clear=True)


class HealthTests(Basis):
    def test_ohne_schluessel_fail_closed_sichtbar(self):
        with self.ohne_schluessel():
            r = self.c.get("/health")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json()["hauptschluessel"], "hauptschluessel_fehlt")
        self.assertEqual(r.get_json()["status"], "fehler")

    def test_zu_kurzer_schluessel_zaehlt_als_fehlend(self):
        with self.mit_schluessel("kurz"):
            self.assertEqual(self.c.get("/health").status_code, 503)

    def test_mit_schluessel_gesund(self):
        with self.mit_schluessel():
            r = self.c.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["datenbank"], "ok")

    def test_health_ohne_personendaten_und_schluessel(self):
        with self.mit_schluessel():
            text = self.c.get("/health").get_data(as_text=True)
        self.assertNotIn(SCHLUESSEL, text)

    def test_version(self):
        r = self.c.get("/api/version")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["version"], config.version())


class EinstellungenTests(Basis):
    def test_ohne_schluessel_kein_zugriff_und_kein_ersatzschluessel(self):
        with self.ohne_schluessel():
            with self.assertRaises(einstellungen.HauptschluesselFehlt):
                einstellungen.setzen("x", "y", "t@example.org")
        self.assertFalse(einstellungen.ist_gesetzt("x"))

    def test_rundreise_und_verschluesselt_abgelegt(self):
        with self.mit_schluessel():
            einstellungen.setzen("mail_passwort", "geheim-123", "t@example.org")
            self.assertEqual(einstellungen.lesen("mail_passwort"), "geheim-123")
        with db.verbindung() as c:
            roh = c.execute("SELECT wert_verschluesselt FROM einstellung").fetchone()[0]
        self.assertNotIn("geheim-123", roh)

    def test_anderer_schluessel_taeuscht_keinen_standard_vor(self):
        with self.mit_schluessel():
            einstellungen.setzen("a", "b", "t@example.org")
        with self.mit_schluessel("x" * 40):
            with self.assertRaises(einstellungen.HauptschluesselFehlt):
                einstellungen.lesen("a", "standard")

    def test_standardwert_wenn_nicht_gesetzt(self):
        with self.mit_schluessel():
            self.assertEqual(einstellungen.lesen("fehlt", "std"), "std")

    def test_ueberschreiben(self):
        with self.mit_schluessel():
            einstellungen.setzen("a", "1", "t@example.org")
            einstellungen.setzen("a", "2", "t@example.org")
            self.assertEqual(einstellungen.lesen("a"), "2")


class BetreiberTests(Basis):
    def _geschuetzt(self):
        @self.app.get("/_test/geschuetzt")
        @betreiber_auth.betreiber_pflicht
        def _g():
            return {"ok": True}

    def _antwort(self, status=200, daten=None):
        m = mock.Mock(status_code=status)
        m.json.return_value = daten
        return m

    def test_ohne_cookie_401(self):
        self._geschuetzt()
        self.assertEqual(self.c.get("/_test/geschuetzt").status_code, 401)

    def test_betreiber_ok_und_cache(self):
        self._geschuetzt()
        self.c.set_cookie("bst_session", "tok")
        ok = self._antwort(200, {"email": "B@Example.org", "betreiber": True, "onboarding_incomplete": False})
        with mock.patch("betreiber_auth.requests.get", return_value=ok) as g:
            self.assertEqual(self.c.get("/_test/geschuetzt").status_code, 200)
            self.assertEqual(self.c.get("/_test/geschuetzt").status_code, 200)
        self.assertEqual(g.call_count, 1)

    def test_kein_betreiber_403(self):
        self._geschuetzt()
        self.c.set_cookie("bst_session", "tok")
        r = self._antwort(200, {"email": "a@example.org", "betreiber": False, "onboarding_incomplete": False})
        with mock.patch("betreiber_auth.requests.get", return_value=r):
            self.assertEqual(self.c.get("/_test/geschuetzt").status_code, 403)

    def test_onboarding_offen_403(self):
        self._geschuetzt()
        self.c.set_cookie("bst_session", "tok")
        r = self._antwort(200, {"email": "a@example.org", "betreiber": True, "onboarding_incomplete": True})
        with mock.patch("betreiber_auth.requests.get", return_value=r):
            self.assertEqual(self.c.get("/_test/geschuetzt").status_code, 403)

    def test_sortnext_nicht_erreichbar_ist_verboten_nicht_offen(self):
        import requests
        self._geschuetzt()
        self.c.set_cookie("bst_session", "tok")
        with mock.patch("betreiber_auth.requests.get", side_effect=requests.ConnectionError()):
            self.assertEqual(self.c.get("/_test/geschuetzt").status_code, 403)

    def test_sortnext_401_ist_403(self):
        self._geschuetzt()
        self.c.set_cookie("bst_session", "tok")
        with mock.patch("betreiber_auth.requests.get", return_value=self._antwort(401, {})):
            self.assertEqual(self.c.get("/_test/geschuetzt").status_code, 403)


class AuditTests(Basis):
    def test_audit_schreiben(self):
        db.audit("b@example.org", "test", "d", "1.2.3.4")
        with db.verbindung() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
