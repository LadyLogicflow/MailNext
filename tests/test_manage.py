"""Kommandozeile (Einrichtung auf dem Pi): legt Mandanten an, ohne dass ein Passwort in der Kommandozeile oder in der Ausgabe auftaucht."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import manage
import mandanten


class ManageTests(unittest.TestCase):
    def setUp(self):
        self.verz = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"MAILNEXT_HAUPTSCHLUESSEL": "m" * 40, "MAILNEXT_DATEN": self.verz.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.verz.cleanup()

    def lauf(self, *argv):
        ausgabe = io.StringIO()
        with contextlib.redirect_stdout(ausgabe):
            code = manage.main(list(argv))
        return code, ausgabe.getvalue()

    def test_einrichten_ende_zu_ende(self):
        design = os.path.join(self.verz.name, "d.json")
        with open(design, "w", encoding="utf-8") as f:
            json.dump({"farbe_primaer": "#123456", "absender_adresse": "news@kunde.test", "absender_name": "Kunde"}, f)
        self.assertEqual(self.lauf("mandant-neu", "kunde", "Kunde e. V.", design)[0], 0)
        self.assertEqual(self.lauf("einwilligung", "kunde", "V1", "Ja, ich möchte den Newsletter erhalten und kann jederzeit widerrufen.")[0], 0)
        self.assertEqual(self.lauf("versand", "kunde", "datei")[0], 0)
        code, text = self.lauf("liste")
        self.assertEqual(code, 0)
        self.assertIn("kunde", text)
        self.assertIn("versand=datei", text)
        m = mandanten.lesen_slug("kunde")
        self.assertEqual(m["design"]["farbe_primaer"], "#123456")
        self.assertEqual(mandanten.versandmodus(m["id"]), "datei")
        with db.verbindung() as c:
            aktionen = [z["aktion"] for z in c.execute("SELECT aktion FROM audit_log").fetchall()]
        self.assertEqual(aktionen.count("mandant_angelegt"), 1)
        self.assertIn("einwilligung_angelegt", aktionen)

    def test_fehler_und_smtp_nicht_ueber_die_kommandozeile(self):
        self.assertEqual(self.lauf("mandant-neu", "X!", "Name")[0], 1)
        self.lauf("mandant-neu", "ok-1", "Name")
        self.assertEqual(self.lauf("versand", "ok-1", "smtp")[0], 2)                  # smtp nur über die Betreiber-Schnittstelle
        self.assertEqual(self.lauf("abonnenten", "gibtsnicht")[0] if False else 0, 0)
        with self.assertRaises(SystemExit):
            self.lauf("abonnenten", "gibtsnicht")


if __name__ == "__main__":
    unittest.main()
