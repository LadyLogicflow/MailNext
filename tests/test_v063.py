"""v0.6.3 (catrin #19057): Die Testmail geht IMMER an die Testliste des Mandanten.

Belegt außerdem die Frage zum 403 adresse_nicht_in_testliste: Groß-/Kleinschreibung, Leerzeichen, Plus-Adressen und Doppelte in der gespeicherten Testliste führen NICHT zu einer
Ablehnung; abgelehnt wird nur, was keine Adresse der Liste ist (Mehrfacheingabe in einem Textfeld, 'Name <adresse>', Wort statt Adresse, Zeichen ohne Breite)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import betreiber_auth
import db
import mailer
import newsletter
from test_meilenstein_b import Basis


def codes(f):
    try:
        f()
    except newsletter.Fehler as e:
        return e.code, e.status
    return None


class TestmailAnTestliste(Basis):
    def an(self, slug="hilo"):
        return sorted(str(x["To"]) for x in self.eml(slug))

    def start(self, adressen):
        m = self.mandant("hilo")
        newsletter.testliste_setzen(m, adressen)
        return m, self.entwurf(m)["id"]

    def test_ohne_an_geht_sie_an_alle_adressen_der_liste(self):
        m, eid = self.start(["a@beispiel.de", "b@beispiel.de", "c@beispiel.de"])
        r = newsletter.testmail(m, eid)
        self.assertEqual((r["status"], r["gesendet"], r["fehler"]), ("gesendet", 3, 0))
        self.assertEqual(self.an(), ["a@beispiel.de", "b@beispiel.de", "c@beispiel.de"])
        self.assertEqual([e["adresse"] for e in r["ergebnisse"]], ["a@beispiel.de", "b@beispiel.de", "c@beispiel.de"])
        self.assertTrue(newsletter.lesen(m, eid)["testmail"]["passender_stand"])

    def test_die_ganze_liste_bis_50_adressen(self):
        m, eid = self.start(["t%02d@beispiel.de" % i for i in range(50)])
        r = newsletter.testmail(m, eid)
        self.assertEqual((r["gesendet"], len(self.mails("hilo"))), (50, 50))

    def test_leere_liste_400_testliste_leer_und_nichts_geht_raus(self):
        m = self.mandant("hilo")
        eid = self.entwurf(m)["id"]
        with self.assertRaises(newsletter.Fehler) as ctx:
            newsletter.testmail(m, eid, None, "betreiber@bst-next.de")                              # die alte Signatur ändert daran nichts
        self.assertEqual((ctx.exception.code, ctx.exception.status, ctx.exception.meldung), ("testliste_leer", 400, "Testliste ist leer"))
        self.assertEqual(self.mails("hilo"), [])
        self.assertFalse(newsletter.lesen(m, eid)["testmail"]["passender_stand"])

    def test_die_betreiberadresse_bekommt_nie_eine_testmail(self):
        m, eid = self.start(["a@beispiel.de"])
        with mock.patch.dict(os.environ, {"MAILNEXT_BETREIBER_OFFEN_EMAIL": "catrin@beispiel.de"}):
            newsletter.testmail(m, eid, None, "catrin@beispiel.de")
        self.assertEqual(self.an(), ["a@beispiel.de"])

    def test_an_ist_nur_eine_teilmenge_der_liste(self):
        m, eid = self.start(["a@beispiel.de", "b@beispiel.de", "c@beispiel.de"])
        r = newsletter.testmail(m, eid, ["b@beispiel.de", "c@beispiel.de"])
        self.assertEqual((r["gesendet"], self.an()), (2, ["b@beispiel.de", "c@beispiel.de"]))
        r = newsletter.testmail(m, eid, "a@beispiel.de")                                             # auch ein einzelner Text
        self.assertEqual(r["gesendet"], 1)
        self.assertEqual(codes(lambda: newsletter.testmail(m, eid, ["a@beispiel.de", "fremd@beispiel.de"])), ("adresse_nicht_in_testliste", 403))
        self.assertEqual(len(self.mails("hilo")), 3)                                                 # bei Ablehnung geht nichts davon raus

    def test_an_mit_doppelten_sendet_je_adresse_einmal(self):
        m, eid = self.start(["a@beispiel.de"])
        self.assertEqual(newsletter.testmail(m, eid, ["a@beispiel.de", "A@Beispiel.de", " a@beispiel.de "])["gesendet"], 1)

    def test_an_falscher_typ_oder_zu_lang_400(self):
        m, eid = self.start(["a@beispiel.de"])
        for falsch in (5, {"a": 1}, [1], ["a@beispiel.de"] * 51):
            self.assertEqual(codes(lambda: newsletter.testmail(m, eid, falsch)), ("an_ungueltig", 400), falsch)

    def test_teilfehler_wird_je_adresse_gemeldet_und_stand_zaehlt(self):
        m, eid = self.start(["a@beispiel.de", "kaputt@beispiel.de", "c@beispiel.de"])
        echt = mailer.senden

        def senden(mandant, an, *a, **k):
            return "abgelehnt" if an.startswith("kaputt") else echt(mandant, an, *a, **k)
        with mock.patch.object(mailer, "senden", senden):
            r = newsletter.testmail(m, eid)
        self.assertEqual((r["status"], r["gesendet"], r["fehler"]), ("teilweise", 2, 1))
        self.assertEqual([(e["adresse"], e["ergebnis"]) for e in r["ergebnisse"]], [("a@beispiel.de", "datei"), ("kaputt@beispiel.de", "fehler"), ("c@beispiel.de", "datei")])
        self.assertEqual(r["ergebnisse"][1]["grund"], "abgelehnt")
        self.assertTrue(newsletter.lesen(m, eid)["testmail"]["passender_stand"])

    def test_alle_fehlgeschlagen_409_und_stand_zaehlt_nicht(self):
        m, eid = self.start(["a@beispiel.de", "b@beispiel.de"])
        with mock.patch.object(mailer, "senden", return_value="fehler"):
            self.assertEqual(codes(lambda: newsletter.testmail(m, eid)), ("versand_nicht_moeglich", 409))
        self.assertFalse(newsletter.lesen(m, eid)["testmail"]["passender_stand"])

    def test_testlisten_sind_je_mandant_getrennt(self):
        a, b = self.mandant("a2"), self.mandant("b2")
        newsletter.testliste_setzen(a, ["nur-a@beispiel.de"])
        eb = self.entwurf(b)["id"]
        self.assertEqual(codes(lambda: newsletter.testmail(b, eb)), ("testliste_leer", 400))
        self.assertEqual(codes(lambda: newsletter.testmail(b, eb, "nur-a@beispiel.de")), ("testliste_leer", 400))              # die Liste von A gilt nicht für B
        newsletter.testliste_setzen(b, ["nur-b@beispiel.de"])
        self.assertEqual(codes(lambda: newsletter.testmail(b, eb, "nur-a@beispiel.de")), ("adresse_nicht_in_testliste", 403))
        self.assertEqual(self.mails("b2"), [])

    def test_freigegebener_entwurf_bleibt_gesperrt(self):
        m = self.mandant("hilo")
        newsletter.testliste_setzen(m, ["a@beispiel.de"])
        eid = self.freigegeben(m, "testliste")
        self.assertEqual(codes(lambda: newsletter.testmail(m, eid)), ("nicht_mehr_aenderbar", 409))


class FrageZum403(Basis):
    """Gespeicherte Testliste und Prüfung der Einzeladresse benutzen dieselbe Normalisierung: kein Fall, in dem eine Adresse der Liste abgelehnt wird."""

    def test_normalisierung_beim_speichern_und_beim_pruefen_ist_gleich(self):
        m = self.mandant("hilo")
        gespeichert = newsletter.testliste_setzen(m, ["  Catrin.Test@Beispiel.DE ", "plus+tag@Beispiel.de", "UPPER@BEISPIEL.DE", "upper@beispiel.de"])
        self.assertEqual(gespeichert, ["catrin.test@beispiel.de", "plus+tag@beispiel.de", "upper@beispiel.de"])
        self.assertEqual(newsletter.testliste(m), gespeichert)
        eid = self.entwurf(m)["id"]
        for eingabe in ("catrin.test@beispiel.de", "CATRIN.TEST@BEISPIEL.DE", "  Catrin.Test@Beispiel.DE  ", "\tcatrin.test@beispiel.de\n", "Plus+Tag@beispiel.de",
                        " upper@beispiel.de "):
            self.assertIsNone(codes(lambda: newsletter.testmail(m, eid, eingabe)), repr(eingabe))
        self.assertEqual(len(self.mails("hilo")), 6)

    def test_uebergabe_der_gespeicherten_liste_selbst_wird_nie_abgelehnt(self):
        m = self.mandant("hilo")
        newsletter.testliste_setzen(m, ["A@b.de", " c@D.de", "e+f@g.de"])
        eid = self.entwurf(m)["id"]
        self.assertIsNone(codes(lambda: newsletter.testmail(m, eid, newsletter.testliste(m))))
        self.assertIsNone(codes(lambda: newsletter.testmail(m, eid)))

    def test_nur_diese_eingaben_werden_abgelehnt_obwohl_die_adresse_in_der_liste_steht(self):
        """Das sind die Fälle, die wie 'aus der Testliste' aussehen, aber als Text keine Adresse der Liste sind (alle vorher wie nachher 403)."""
        m = self.mandant("hilo")
        newsletter.testliste_setzen(m, ["a@beispiel.de", "b@beispiel.de"])
        eid = self.entwurf(m)["id"]
        for eingabe in ("a@beispiel.de, b@beispiel.de", "a@beispiel.de;b@beispiel.de", "a@beispiel.de b@beispiel.de", "Catrin <a@beispiel.de>", "a@beispiel.de.",
                        "a\u200b@beispiel.de", "a@beispiel.de\u200b", "testliste", "Testliste"):
            self.assertEqual(codes(lambda: newsletter.testmail(m, eid, eingabe)), ("adresse_nicht_in_testliste", 403), repr(eingabe))
        self.assertEqual(self.mails("hilo"), [])

    def test_ungespeicherte_aenderung_der_liste_zaehlt_nicht(self):
        """Steht eine Adresse nur im Eingabefeld der Oberfläche, aber nicht in der gespeicherten Liste (nicht gespeichert), lehnt das Backend sie ab; die Liste ist die Quelle."""
        m = self.mandant("hilo")
        newsletter.testliste_setzen(m, ["alt@beispiel.de"])
        eid = self.entwurf(m)["id"]
        self.assertEqual(codes(lambda: newsletter.testmail(m, eid, "neu@beispiel.de")), ("adresse_nicht_in_testliste", 403))
        newsletter.testliste_setzen(m, ["alt@beispiel.de", "neu@beispiel.de"])
        self.assertIsNone(codes(lambda: newsletter.testmail(m, eid, "neu@beispiel.de")))


class TestmailApi(Basis):
    def als_betreiber(self):
        return mock.patch.object(betreiber_auth, "_bei_sortnext_fragen", return_value={"email": "catrin@bst-next.de", "betreiber": True})

    def aufruf(self, methode, pfad, **kw):
        self.c.set_cookie("bst_session", "tok")
        return getattr(self.c, methode)("/api/v1/betreiber" + pfad, **kw)

    def test_antwortform_und_audit_ohne_adressen(self):
        m = self.mandant("hilo")
        newsletter.testliste_setzen(m, ["a@beispiel.de", "b@beispiel.de"])
        eid = self.entwurf(m)["id"]
        with self.als_betreiber():
            r = self.aufruf("post", "/mandanten/%d/entwuerfe/%d/testmail" % (m["id"], eid), json={})
        j = r.get_json()
        self.assertEqual(r.status_code, 200, j)
        self.assertEqual(set(j), {"status", "content_hash", "gesendet", "fehler", "ergebnisse"})
        self.assertEqual((j["status"], j["gesendet"], j["fehler"]), ("gesendet", 2, 0))
        self.assertEqual([(e["adresse"], e["ergebnis"]) for e in j["ergebnisse"]], [("a@beispiel.de", "datei"), ("b@beispiel.de", "datei")])
        self.assertEqual(j["content_hash"], newsletter.lesen(m, eid)["content_hash"])
        with db.verbindung() as c:
            zeilen = [tuple(z) for z in c.execute("SELECT * FROM audit_log").fetchall()]
        audit = " ".join(str(x) for z in zeilen for x in z)
        self.assertTrue(any("testmail_gesendet" in str(z) for z in zeilen), zeilen)
        self.assertIn("gesendet=2 fehler=0", audit)
        self.assertNotIn("beispiel.de", audit)

    def test_leere_liste_400_mit_meldung_und_ohne_betreiber_rueckfall(self):
        m = self.mandant("hilo")
        eid = self.entwurf(m)["id"]
        with self.als_betreiber(), mock.patch.dict(os.environ, {"MAILNEXT_BETREIBER_OFFEN_EMAIL": "catrin@bst-next.de"}):
            r = self.aufruf("post", "/mandanten/%d/entwuerfe/%d/testmail" % (m["id"], eid), json={})
        self.assertEqual((r.status_code, r.get_json()["error"], r.get_json()["meldung"]), (400, "testliste_leer", "Testliste ist leer"))
        self.assertEqual(self.mails("hilo"), [])

    def test_teilmenge_per_liste_und_fremde_adresse_403(self):
        m = self.mandant("hilo")
        newsletter.testliste_setzen(m, ["a@beispiel.de", "b@beispiel.de"])
        eid = self.entwurf(m)["id"]
        pfad = "/mandanten/%d/entwuerfe/%d/testmail" % (m["id"], eid)
        with self.als_betreiber():
            r = self.aufruf("post", pfad, json={"an": ["b@beispiel.de"]})
            self.assertEqual((r.status_code, r.get_json()["gesendet"]), (200, 1))
            r = self.aufruf("post", pfad, json={"an": ["b@beispiel.de", "x@beispiel.de"]})
            self.assertEqual((r.status_code, r.get_json()["error"]), (403, "adresse_nicht_in_testliste"))
            r = self.aufruf("post", pfad, json={"an": 5})
            self.assertEqual((r.status_code, r.get_json()["error"]), (400, "an_ungueltig"))


if __name__ == "__main__":
    unittest.main()
