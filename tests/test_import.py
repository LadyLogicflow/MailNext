"""Import von Bestandsadressen (Mailchimp-Export): Leser, Zählung, Zusammenführen, Tags, Betreiber-Schnittstelle, manage.py. Nur erfundene Adressen."""
import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import abonnenten
import betreiber_auth
import config
import db
import import_csv
import manage
import schluessel
from tests.test_meilenstein_a import Basis


def mc(zeilen, kopf="Email Address,First Name,Last Name,TAGS,Status", trenn=","):
    """Mailchimp-ähnlicher Export; zeilen = Liste von Listen (Zellen)."""
    def zelle(z):
        z = str(z)
        return '"%s"' % z.replace('"', '""') if (trenn in z or '"' in z or "\n" in z) else z
    return "\n".join([kopf] + [trenn.join(zelle(z) for z in zeile) for zeile in zeilen]) + "\n"


class ImportBasis(Basis):
    def als_betreiber(self):
        return mock.patch.object(betreiber_auth, "_bei_sortnext_fragen", return_value={"email": "catrin@bst-next.de", "betreiber": True})

    def importiere(self, m, daten, quelle="Mailchimp-Export Test", nur_pruefen=False, bestaetigt=True, **extra):
        body = {"daten": daten, "quelle": quelle, "nur_pruefen": nur_pruefen}
        if bestaetigt:
            body["einwilligung_bestaetigt"] = True
        body.update(extra)
        with self.als_betreiber():
            betreiber_auth.cache_leeren()
            self.c.set_cookie("bst_session", "tok")
            return self.c.post("/api/v1/betreiber/mandanten/%d/abonnenten/import" % m["id"], json=body)

    def zahlen(self, m):
        with db.verbindung() as c:
            return {z["status"]: z["n"] for z in c.execute("SELECT status, COUNT(*) AS n FROM abonnent WHERE mandant_id=? GROUP BY status", (m["id"],))}

    def audit(self):
        with db.verbindung() as c:
            return [dict(z) for z in c.execute("SELECT * FROM audit_log ORDER BY id")]


class TestLeser(unittest.TestCase):
    def test_trennzeichen_bom_anfuehrungszeichen_zeilenenden(self):
        erwartet = [("a@example.org", None, None), ("b@example.org", None, None)]
        for trenn in (",", ";", "\t"):
            for ende in ("\n", "\r\n", "\r"):
                text = "﻿" + ende.join(["E-Mail-Adresse%sVorname" % trenn, 'a@example.org%s"Anna"' % trenn, '"b@example.org"%sBen' % trenn]) + ende
                self.assertEqual([(a, s, t) for a, s, t in import_csv.lesen(text)], erwartet, (trenn, ende))

    def test_kopfnamen_deutsch_englisch(self):
        for kopf in ("Email Address", "email address", "E-Mail-Adresse", "E-Mail", "Email", "EMAIL ADDRESS", " e-mail address ", "Mail"):
            self.assertEqual(import_csv.lesen("%s,Name\nx@example.org,Y\n" % kopf)[0][0], "x@example.org", kopf)

    def test_ohne_kopf_eine_adresse_je_zeile(self):
        self.assertEqual([a for a, _, _ in import_csv.lesen("a@example.org\n\nb@example.org\r\n   \n")], ["a@example.org", "b@example.org"])
        self.assertEqual([a for a, _, _ in import_csv.lesen("a@example.org; b@x.org\nc@example.org")], ["a@example.org", "c@example.org"])

    def test_nur_adresse_status_und_tags_werden_gelesen(self):
        zeilen = import_csv.lesen('Email Address,First Name,Last Name,Phone,TAGS,Status,Notes\nx@example.org,Max,Mustermann,0123,"""A"",""B""",subscribed,geheim\n')
        self.assertEqual(zeilen, [("x@example.org", "subscribed", '"A","B"')])
        self.assertNotIn("Max", repr(zeilen))
        self.assertNotIn("geheim", repr(zeilen))
        self.assertNotIn("0123", repr(zeilen))

    def test_fehler(self):
        for text, code in (("", "daten_fehlen"), ("   \n \n", "daten_fehlen"), ("Name,Vorname\nA,B\n", "spalte_nicht_gefunden"), ("x" * 3_000_001, "zu_gross"),
                           ("Email\n" + "a@example.org\n" * 20001, "zu_viele_zeilen")):
            with self.assertRaises(import_csv.ImportFehler, msg=code) as k:
                import_csv.lesen(text)
            self.assertEqual(k.exception.code, code)
        with self.assertRaises(import_csv.ImportFehler):
            import_csv.lesen(None)
        self.assertEqual(len(import_csv.lesen("Email\n" + "a@example.org\n" * 20000)), 20000)

    def test_tags_zerlegen(self):
        self.assertEqual(import_csv.tags_lesen('"Spender","Verein A"'), (["Spender", "Verein A"], 0))
        self.assertEqual(import_csv.tags_lesen("a;b|c, d"), (["a", "b", "c", "d"], 0))
        self.assertEqual(import_csv.tags_lesen("A, a, A"), (["A"], 0))                                  # doppelt ohne Groß-/Kleinschreibung
        self.assertEqual(import_csv.tags_lesen("x" * 41 + ",ok"), (["ok"], 1))                          # zu lang wird verworfen und gezählt
        self.assertEqual(import_csv.tags_lesen("ok,bad\x07"), (["ok"], 1))
        viele, verworfen = import_csv.tags_lesen(",".join("t%d" % i for i in range(30)))
        self.assertEqual((len(viele), verworfen), (20, 10))
        self.assertEqual(import_csv.tags_lesen(""), ([], 0))
        self.assertEqual(import_csv.tags_lesen(None), ([], 0))
        self.assertEqual(import_csv.tags_lesen("Müller-Büro, Ärzte"), (["Müller-Büro", "Ärzte"], 0))


class TestImport(ImportBasis):
    def test_import_ist_sofort_bestaetigt_mit_herkunft_und_ohne_mail(self):
        m = self.mandant("hilo")
        text = mc([["Anna@Example.org ", "Anna", "Müller", "", "subscribed"], ["ben@example.org", "Ben", "Ärger", "", ""]])
        r = self.importiere(m, text, quelle="Mailchimp-Export 13.11.2026")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        j = r.get_json()
        self.assertEqual((j["zeilen"], j["neu"], j["dublette"], j["ungueltig"], j["uebersprungen_gesamt"], j["nur_pruefen"]), (2, 2, 0, 0, 0, False))
        z = self.zeile(m["id"], "anna@example.org")
        self.assertEqual((z["status"], z["email"], z["herkunft"], z["quelle"], z["einwilligung_version"]), ("bestaetigt", "anna@example.org", "import", "Mailchimp-Export 13.11.2026", "import"))
        self.assertTrue(z["bestaetigt_am"] and z["import_am"] and z["angemeldet_am"])
        self.assertIsNone(z["ip"])
        self.assertIsNone(z["token_hash"])
        self.assertEqual(self.mails("hilo"), [])                                                       # keine Bestätigungsmail
        self.assertEqual(self.zahlen(m), {"bestaetigt": 2})
        self.assertEqual(j["kennzahlen"]["bestaetigt"], 2)

    def test_namen_und_andere_spalten_werden_nie_gespeichert(self):
        m = self.mandant("hilo")
        self.importiere(m, mc([["a@example.org", "Zoltan", "Qwertzuiop", "", "subscribed"]], kopf="Email Address,First Name,Last Name,TAGS,Status"))
        with db.verbindung() as c:
            roh = json.dumps([dict(z) for z in c.execute("SELECT * FROM abonnent")], default=str) + json.dumps([dict(z) for z in c.execute("SELECT * FROM audit_log")])
        pfad = os.path.join(self.verz.name, "t.db")
        daten = b""
        for endung in ("", "-wal"):
            if os.path.isfile(pfad + endung):
                daten += open(pfad + endung, "rb").read()
        for verboten in ("Zoltan", "Qwertzuiop"):
            self.assertNotIn(verboten, roh)
            self.assertNotIn(verboten.encode(), daten)

    def test_persoenliche_abmeldelinks_funktionieren(self):
        m = self.mandant("hilo")
        self.importiere(m, mc([["a@example.org", "", "", "", ""]]))
        token = abonnenten.persoenliches_token(self.zeile(m["id"], "a@example.org"))
        self.assertEqual(abonnenten.abmelden(token, m), "abgemeldet")
        self.assertEqual(self.zeile(m["id"], "a@example.org")["status"], "abgemeldet")
        self.assertIsNone(self.zeile(m["id"], "a@example.org")["email"])
        r = self.c.get("/hilo/newsletter/einstellungen?t=" + token)
        self.assertIn(r.status_code, (200, 404))

    def test_jeder_import_bekommt_eigene_nonce_und_eigenes_abmeldetoken(self):
        m = self.mandant("hilo")
        self.importiere(m, mc([["a@example.org", "", "", "", ""], ["b@example.org", "", "", "", ""], ["c@example.org", "", "", "", ""]]))
        with db.verbindung() as c:
            nonces = [z["nonce"] for z in c.execute("SELECT nonce FROM abonnent")]
        self.assertEqual(len(set(nonces)), 3)
        self.assertTrue(all(len(n) >= 12 for n in nonces))
        tokens = {abonnenten.persoenliches_token(self.zeile(m["id"], a)) for a in ("a@example.org", "b@example.org", "c@example.org")}
        self.assertEqual(len(tokens), 3)

    def test_zweiter_lauf_aendert_nichts(self):
        m = self.mandant("hilo")
        text = mc([["a@example.org", "", "", "", ""], ["b@example.org", "", "", "", ""]])
        self.importiere(m, text)
        with db.verbindung() as c:
            vorher = [dict(z) for z in c.execute("SELECT * FROM abonnent ORDER BY id")]
        j = self.importiere(m, text).get_json()
        self.assertEqual((j["neu"], j["dublette"], j["zusammengefuehrt"]), (0, 2, 0))
        self.assertEqual(self.zahlen(m), {"bestaetigt": 2})
        with db.verbindung() as c:
            nachher = [dict(z) for z in c.execute("SELECT * FROM abonnent ORDER BY id")]
        self.assertEqual(vorher, nachher)

    def test_dubletten_ungueltige_und_status(self):
        m = self.mandant("hilo")
        zeilen = [["a@example.org", "", "", "", "Subscribed"], ["A@EXAMPLE.ORG", "", "", "", "subscribed"], ["kaputt", "", "", "", ""], ["", "x", "", "", ""],
                  ["u@example.org", "", "", "", "unsubscribed"], ["c@example.org", "", "", "", "cleaned"], ["n@example.org", "", "", "", "non-subscribed"],
                  ["p@example.org", "", "", "", "pending"], ["g@example.org", "", "", "", "Abgemeldet"], ["h@example.org", "", "", "", "Abonniert"],
                  ["ümlaut@beispiel.de", "", "", "", ""], ["x@y", "", "", "", ""], ["a b@example.org", "", "", "", ""], ["lang" + "x" * 300 + "@example.org", "", "", "", ""]]
        j = self.importiere(m, mc(zeilen)).get_json()
        self.assertEqual(j["zeilen"], len(zeilen))
        self.assertEqual((j["neu"], j["dublette"], j["uebersprungen"]["status"]), (3, 1, 5))            # a, h, ümlaut@beispiel.de; Dublette A; 5 mit Status nicht abonniert
        self.assertEqual(j["ungueltig"], 5)                                                              # kaputt, leer, x@y, Leerzeichen, zu lang
        self.assertEqual(j["neu"] + j["dublette"] + j["ungueltig"] + j["uebersprungen_gesamt"], j["zeilen"])
        self.assertIsNone(self.zeile(m["id"], "u@example.org"))
        self.assertIsNone(self.zeile(m["id"], "p@example.org"))

    def test_bestehende_stati_werden_nie_veraendert(self):
        m = self.mandant("hilo")
        self.anmelden_und_bestaetigen(m, "best@example.org")
        self.anmelden("hilo", "offen@example.org")                                                       # unbestätigt
        self.anmelden_und_bestaetigen(m, "weg@example.org")
        abonnenten.abmelden(self.pers_token(m, "weg@example.org"), m)
        self.anmelden_und_bestaetigen(m, "kaputt@example.org")
        with db.verbindung() as c:
            c.execute("UPDATE abonnent SET status='unzustellbar' WHERE mandant_id=? AND email_hmac=?", (m["id"], schluessel.email_hmac(m["id"], "kaputt@example.org")))
        vorher = {a: dict(self.zeile(m["id"], a)) for a in ("best@example.org", "offen@example.org", "weg@example.org", "kaputt@example.org")}
        j = self.importiere(m, mc([[a, "", "", "", ""] for a in vorher]), rolle="verein", interessen=["sortnext"]).get_json()
        self.assertEqual((j["neu"], j["dublette"], j["uebersprungen"]), (0, 1, {"abgemeldet": 1, "unzustellbar": 1, "unbestaetigt": 1, "status": 0}))
        for a in ("offen@example.org", "weg@example.org", "kaputt@example.org"):
            self.assertEqual(dict(self.zeile(m["id"], a)), vorher[a], a)                                 # nichts angefasst, vor allem Abgemeldete nicht wieder aktiviert
        self.assertEqual(self.zeile(m["id"], "weg@example.org")["status"], "abgemeldet")

    def test_nur_pruefen_speichert_nichts_und_zaehlt_wie_echt(self):
        m = self.mandant("hilo")
        self.anmelden_und_bestaetigen(m, "best@example.org")
        text = mc([["best@example.org", "", "", "A", ""], ["neu1@example.org", "", "", "A,B", ""], ["neu2@example.org", "", "", "", ""], ["kaputt", "", "", "", ""]])
        vorher = self.zahlen(m)
        probe = self.importiere(m, text, nur_pruefen=True, bestaetigt=False).get_json()
        self.assertEqual(probe["nur_pruefen"], True)
        self.assertEqual(self.zahlen(m), vorher)
        with db.verbindung() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM abonnent WHERE herkunft='import'").fetchone()[0], 0)
        echt = self.importiere(m, text).get_json()
        for k in ("zeilen", "neu", "dublette", "ungueltig", "uebersprungen", "uebersprungen_gesamt", "zusammengefuehrt", "rolle_konflikt", "tags"):
            self.assertEqual(probe[k], echt[k], k)
        self.assertEqual(self.zahlen(m), {"bestaetigt": 3})

    def test_mandantentrennung(self):
        a, b = self.mandant("hilo"), self.mandant("andere", "Andere e. V.")
        self.importiere(a, mc([["x@example.org", "", "", "T1", ""]]))
        j = self.importiere(b, mc([["x@example.org", "", "", "T2", ""]])).get_json()
        self.assertEqual((j["neu"], j["dublette"]), (1, 0))                                              # gleiche Adresse in anderem Mandanten: eigener Datensatz
        self.assertEqual(json.loads(self.zeile(a["id"], "x@example.org")["tags"]), ["T1"])
        self.assertEqual(json.loads(self.zeile(b["id"], "x@example.org")["tags"]), ["T2"])
        self.assertEqual(self.zahlen(a), {"bestaetigt": 1})

    def test_1500_zeilen_umlaute_in_namen_und_geschwindigkeit(self):
        m = self.mandant("hilo")
        zeilen = [["person%04d@example.org" % i, "Jürgen", "Müßig-Öztürk", "Tag %d" % (i % 7), "subscribed"] for i in range(1500)]
        zeilen += [["person%04d@example.org" % i, "", "", "", ""] for i in range(0, 1500, 100)]            # 15 Dubletten in der Datei
        zeilen += [["ungueltig%d" % i, "", "", "", ""] for i in range(10)]
        start = time.time()
        j = self.importiere(m, mc(zeilen)).get_json()
        dauer = time.time() - start
        self.assertEqual((j["zeilen"], j["neu"], j["dublette"], j["ungueltig"]), (1525, 1500, 15, 10))
        self.assertLess(dauer, 10)
        self.assertEqual(self.zahlen(m), {"bestaetigt": 1500})
        self.assertEqual(j["tags"]["verschiedene"], 7)
        self.assertEqual(sum(t["anzahl"] for t in j["tags"]["haeufigste"]), 1500)
        for variante in ("﻿" + mc(zeilen[:5], trenn=";").replace(",", ";", 0), mc(zeilen[:5], trenn="\t")):
            self.assertEqual(self.importiere(m, variante).status_code, 200)

    def test_aufzaehlung_der_adressen_stimmt_mit_der_datenbank(self):
        m = self.mandant("hilo")
        self.importiere(m, mc([["a@example.org", "", "", "", ""], ["b@example.org", "", "", "", ""]]))
        self.assertEqual(sorted(z["email"] for z in abonnenten.liste(m["id"])), ["a@example.org", "b@example.org"])
        self.assertEqual(abonnenten.liste(m["id"])[0]["herkunft"], "import")
        self.assertEqual(abonnenten.liste(m["id"])[0]["quelle"], "Mailchimp-Export Test")


class TestGruppenUndTags(ImportBasis):
    def test_feste_auswahl_fuer_den_lauf(self):
        m = self.mandant("hilo")
        self.importiere(m, mc([["a@example.org", "", "", "", ""]]), rolle="verein", interessen=["sortnext", "booknext"])
        z = self.zeile(m["id"], "a@example.org")
        self.assertEqual((z["rolle"], json.loads(z["interessen"])), ("verein", ["booknext", "sortnext"]))
        self.importiere(m, mc([["b@example.org", "", "", "", ""]]), rolle="beratungsstelle")
        self.assertEqual(self.zeile(m["id"], "b@example.org")["rolle"], "beratungsstelle")
        self.assertEqual(json.loads(self.zeile(m["id"], "b@example.org")["interessen"]), [])

    def test_unbekannte_werte_sind_400_und_nichts_passiert(self):
        m = self.mandant("hilo")
        for extra in ({"rolle": "gibtsnicht"}, {"interessen": ["gibtsnicht"]}, {"interessen": ["sortnext", "x"]}, {"rolle": 5}, {"interessen": "sortnext"}, {"interessen": [1]}, {"rolle": ["verein"]}):
            r = self.importiere(m, mc([["a@example.org", "", "", "", ""]]), **extra)
            self.assertEqual(r.status_code, 400, extra)
            self.assertEqual(r.get_json()["error"], "eingabe_ungueltig", extra)
        self.assertEqual(self.zahlen(m), {})

    def test_werte_eines_anderen_mandanten_gelten_nicht(self):
        a = self.mandant("hilo")
        b = self.mandant("andere", "Andere", rollen=[{"wert": "nur-hier", "label": "Nur hier"}])
        self.assertEqual(self.importiere(a, mc([["a@example.org", "", "", "", ""]]), rolle="nur-hier").status_code, 400)
        self.assertEqual(self.importiere(b, mc([["a@example.org", "", "", "", ""]]), rolle="nur-hier").status_code, 200)

    def test_zusammenfuehren_bei_bekannter_adresse(self):
        m = self.mandant("hilo")
        self.anmelden_und_bestaetigen(m, "a@example.org")
        with db.verbindung() as c:
            c.execute("UPDATE abonnent SET interessen='[\"sortnext\"]' WHERE mandant_id=?", (m["id"],))
        j = self.importiere(m, mc([["a@example.org", "", "", "", ""]]), rolle="verein", interessen=["booknext"]).get_json()
        self.assertEqual((j["neu"], j["dublette"], j["zusammengefuehrt"], j["rolle_konflikt"]), (0, 1, 1, 0))
        z = self.zeile(m["id"], "a@example.org")
        self.assertEqual((z["rolle"], json.loads(z["interessen"])), ("verein", ["booknext", "sortnext"]))
        self.assertEqual(self.zahlen(m), {"bestaetigt": 1})                                              # kein zweiter Datensatz
        j = self.importiere(m, mc([["a@example.org", "", "", "", ""]]), rolle="beratungsstelle", interessen=["booknext"]).get_json()
        self.assertEqual((j["zusammengefuehrt"], j["rolle_konflikt"]), (0, 1))                            # Rolle bleibt, Konflikt gezählt, nichts Neues
        self.assertEqual(self.zeile(m["id"], "a@example.org")["rolle"], "verein")

    def test_zusammenfuehren_in_zwei_importen_ohne_doppelte(self):
        m = self.mandant("hilo")
        self.importiere(m, mc([["a@example.org", "", "", "Spender", ""]]), interessen=["sortnext"], quelle="Datei 1")
        j = self.importiere(m, mc([["a@example.org", "", "", "Verein A,SPENDER", ""], ["b@example.org", "", "", "", ""]]), interessen=["booknext"], quelle="Datei 2").get_json()
        self.assertEqual((j["neu"], j["dublette"], j["zusammengefuehrt"]), (1, 1, 1))
        z = self.zeile(m["id"], "a@example.org")
        self.assertEqual(json.loads(z["tags"]), ["Spender", "Verein A"])                                  # vorhandene Schreibweise bleibt, kein doppelter Tag
        self.assertEqual(json.loads(z["interessen"]), ["booknext", "sortnext"])
        self.assertEqual(z["quelle"], "Datei 1")                                                         # die erste Herkunft bleibt
        self.assertEqual(self.zahlen(m), {"bestaetigt": 2})

    def test_tags_werden_gespeichert_gezaehlt_und_angezeigt(self):
        m = self.mandant("hilo")
        text = mc([["a@example.org", "", "", '"Spender","Verein A"', ""], ["b@example.org", "", "", "Spender", ""], ["c@example.org", "", "", "", ""], ["d@example.org", "", "", "x" * 50 + ",Gut", ""]])
        j = self.importiere(m, text).get_json()
        self.assertEqual(json.loads(self.zeile(m["id"], "a@example.org")["tags"]), ["Spender", "Verein A"])
        self.assertEqual(json.loads(self.zeile(m["id"], "c@example.org")["tags"]), [])
        self.assertEqual(json.loads(self.zeile(m["id"], "d@example.org")["tags"]), ["Gut"])
        self.assertEqual(j["tags"]["verschiedene"], 3)
        self.assertEqual(j["tags"]["haeufigste"][0], {"tag": "Spender", "anzahl": 2})
        self.assertEqual(j["tags"]["verworfen"], 1)
        liste = {z["email"]: z for z in abonnenten.liste(m["id"])}
        self.assertEqual(liste["a@example.org"]["tags"], ["Spender", "Verein A"])
        with self.als_betreiber():
            betreiber_auth.cache_leeren()
            self.c.set_cookie("bst_session", "tok")
            r = self.c.get("/api/v1/betreiber/mandanten/%d/abonnenten" % m["id"])
        self.assertEqual({z["email"]: z["tags"] for z in r.get_json()["abonnenten"]}["b@example.org"], ["Spender"])

    def test_tags_ohne_spalte_und_mit_anderen_koepfen(self):
        m = self.mandant("hilo")
        self.importiere(m, "Email\na@example.org\n")
        self.assertEqual(json.loads(self.zeile(m["id"], "a@example.org")["tags"]), [])
        self.importiere(m, "E-Mail-Adresse;Tags\nb@example.org;Spender|Neu\n")
        self.assertEqual(json.loads(self.zeile(m["id"], "b@example.org")["tags"]), ["Spender", "Neu"])

    def test_tag_obergrenze_beim_zusammenfuehren(self):
        m = self.mandant("hilo")
        self.importiere(m, mc([["a@example.org", "", "", ",".join("a%d" % i for i in range(15)), ""]]))
        self.importiere(m, mc([["a@example.org", "", "", ",".join("b%d" % i for i in range(15)), ""]]))
        self.assertEqual(len(json.loads(self.zeile(m["id"], "a@example.org")["tags"])), 20)


class TestVersandFilterTags(ImportBasis):
    """Newsletter-Zielgruppe nach Tags: ODER als Standard, UND auf Wunsch, nur bestätigte Abonnentinnen, UND-Verknüpfung mit Rolle und Interessen."""

    def vorbereiten(self):
        m = self.mandant("hilo")
        zeilen = [["a@example.org", "", "", "Spender", ""], ["b@example.org", "", "", "Spender,Verein A", ""], ["c@example.org", "", "", "Verein A", ""], ["d@example.org", "", "", "", ""],
                  ["e@example.org", "", "", "SPENDER", ""], ["f@example.org", "", "", "Verein A,Spender,Neu", ""]]
        self.importiere(m, mc(zeilen))
        return m

    def segment(self, m, **segment):
        with self.als_betreiber():
            betreiber_auth.cache_leeren()
            self.c.set_cookie("bst_session", "tok")
            return self.c.post("/api/v1/betreiber/mandanten/%d/abonnenten/vorschau" % m["id"], json={"segment": segment})

    def anzahl(self, m, **segment):
        r = self.segment(m, **segment)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()["anzahl"]

    def test_tag_liste_mit_anzahl_ohne_adressen(self):
        m = self.vorbereiten()
        with self.als_betreiber():
            betreiber_auth.cache_leeren()
            self.c.set_cookie("bst_session", "tok")
            r = self.c.get("/api/v1/betreiber/mandanten/%d/abonnenten/tags" % m["id"])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["tags"], [{"tag": "Spender", "anzahl": 4}, {"tag": "Verein A", "anzahl": 3}, {"tag": "Neu", "anzahl": 1}])
        self.assertNotIn("@", r.get_data(as_text=True))
        self.assertEqual([a["aktion"] for a in self.audit() if a["aktion"] == "tags_gelesen"], ["tags_gelesen"])

    def test_tag_liste_zaehlt_nur_bestaetigte_und_nur_den_eigenen_mandanten(self):
        m = self.vorbereiten()
        andere = self.mandant("andere", "Andere")
        self.importiere(andere, mc([["x@example.org", "", "", "Fremd", ""]]))
        abonnenten.abmelden(abonnenten.persoenliches_token(self.zeile(m["id"], "a@example.org")), m)
        with db.verbindung() as c:
            c.execute("UPDATE abonnent SET status='unzustellbar' WHERE mandant_id=? AND email_hmac=?", (m["id"], schluessel.email_hmac(m["id"], "c@example.org")))
        tags = {e["tag"]: e["anzahl"] for e in abonnenten.tags_liste(m["id"])}
        self.assertEqual(tags, {"Spender": 3, "Verein A": 2, "Neu": 1})
        self.assertNotIn("Fremd", tags)
        self.assertEqual(abonnenten.tags_liste(andere["id"]), [{"tag": "Fremd", "anzahl": 1}])

    def test_oder_ist_der_standard_und_gross_klein_egal(self):
        m = self.vorbereiten()
        self.assertEqual(self.anzahl(m, tags=["Spender"]), 4)                                           # a, b, e, f
        self.assertEqual(self.anzahl(m, tags=["spender"]), 4)
        self.assertEqual(self.anzahl(m, tags=["Spender", "Verein A"]), 5)                               # a, b, c, e, f
        self.assertEqual(self.anzahl(m, tags=["Neu"]), 1)
        self.assertEqual(self.anzahl(m, tags=["Neu", "Spender"], tags_modus="oder"), 4)

    def test_und_auf_wunsch(self):
        m = self.vorbereiten()
        self.assertEqual(self.anzahl(m, tags=["Spender", "Verein A"], tags_modus="und"), 2)             # b, f
        self.assertEqual(self.anzahl(m, tags=["Spender", "Verein A", "Neu"], tags_modus="und"), 1)      # f
        self.assertEqual(self.anzahl(m, tags=["spender", "VEREIN a"], tags_modus="und"), 2)

    def test_segment_wird_in_kanonischer_schreibweise_zurueckgegeben(self):
        m = self.vorbereiten()
        j = self.segment(m, tags=["verein a", "SPENDER", "spender"]).get_json()
        self.assertEqual(j["segment"], {"rollen": None, "interessen": None, "tags": ["Spender", "Verein A"], "tags_modus": "oder"})

    def test_ungueltige_segmente(self):
        m = self.vorbereiten()
        for seg in ({"tags": ["Gibtsnicht"]}, {"tags": []}, {"tags": "Spender"}, {"tags": [1]}, {"tags": ["Spender"] * 21}, {"tags": ["Spender"], "tags_modus": "xor"},
                    {"tags_modus": "und"}, {"tags": ["Spender"], "extra": 1}, {"tags": [None]}):
            r = self.segment(m, **seg)
            self.assertEqual((r.status_code, r.get_json()["error"]), (400, "segment_ungueltig"), seg)

    def test_nie_abgemeldete_unzustellbare_oder_unbestaetigte(self):
        m = self.vorbereiten()
        abonnenten.abmelden(abonnenten.persoenliches_token(self.zeile(m["id"], "a@example.org")), m)
        with db.verbindung() as c:
            c.execute("UPDATE abonnent SET status='unzustellbar' WHERE mandant_id=? AND email_hmac=?", (m["id"], schluessel.email_hmac(m["id"], "b@example.org")))
            c.execute("UPDATE abonnent SET status='unbestaetigt' WHERE mandant_id=? AND email_hmac=?", (m["id"], schluessel.email_hmac(m["id"], "e@example.org")))
        self.assertEqual(self.anzahl(m, tags=["Spender"]), 1)                                           # nur f
        self.assertEqual(self.anzahl(m, tags=["Spender", "Verein A"], tags_modus="und"), 1)

    def test_und_verknuepfung_mit_rolle_und_interessen(self):
        m = self.vorbereiten()
        with db.verbindung() as c:
            c.execute("UPDATE abonnent SET rolle='verein', interessen='[\"sortnext\"]' WHERE mandant_id=? AND email_hmac IN (?,?)",
                      (m["id"], schluessel.email_hmac(m["id"], "a@example.org"), schluessel.email_hmac(m["id"], "c@example.org")))
        self.assertEqual(self.anzahl(m, tags=["Spender"], rollen=["verein"]), 1)                        # a
        self.assertEqual(self.anzahl(m, tags=["Spender", "Verein A"], interessen=["sortnext"]), 2)      # a, c
        self.assertEqual(self.anzahl(m, rollen=["verein"]), 2)                                          # ohne Tags wie bisher
        self.assertEqual(self.anzahl(m, tags=["Neu"], rollen=["verein"]), 0)

    def test_segmente_ohne_tags_bleiben_unveraendert(self):
        m = self.vorbereiten()
        self.assertEqual(newsletter_segment(m, None), {"rollen": None, "interessen": None})
        self.assertEqual(newsletter_segment(m, {"rollen": ["verein"]}), {"rollen": ["verein"], "interessen": None})
        j = self.segment(m).get_json()
        self.assertEqual((j["anzahl"], j["segment"]), (6, {"rollen": None, "interessen": None}))

    def test_vorschau_endpunkt_form_zugriff_und_nebenwirkungen(self):
        m = self.vorbereiten()
        pfad = "/api/v1/betreiber/mandanten/%d/abonnenten/vorschau" % m["id"]
        self.assertEqual(self.app.test_client().post(pfad, json={"segment": {}}).status_code, 401)
        with self.als_betreiber():
            betreiber_auth.cache_leeren()
            self.c.set_cookie("bst_session", "tok")
            self.assertEqual(self.c.post(pfad, json={"segment": {}, "x": 1}).status_code, 400)
            self.assertEqual(self.c.post(pfad, data="x", content_type="text/plain").status_code, 400)
            self.assertEqual(self.c.post("/api/v1/betreiber/mandanten/9999/abonnenten/vorschau", json={"segment": {}}).status_code, 404)
            self.assertEqual(self.c.get("/api/v1/betreiber/mandanten/9999/abonnenten/tags").status_code, 404)
        with db.verbindung() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM entwurf").fetchone()[0], 0)
        self.assertNotIn("@", json.dumps(self.segment(m, tags=["Spender"]).get_json()))

    def test_entwurf_mit_tags_freigabe_und_empfaenger(self):
        import newsletter
        m = self.vorbereiten()
        e = newsletter.anlegen(m, "Betreff", "Text https://beispiel.test/x", "abonnenten", {"tags": ["spender"], "tags_modus": "und"})
        self.assertEqual(e["segment"], {"rollen": None, "interessen": None, "tags": ["Spender"], "tags_modus": "und"})
        self.assertEqual(newsletter.vorschau(m, e["id"])["anzahl"], 4)
        abonnenten.abmelden(abonnenten.persoenliches_token(self.zeile(m["id"], "a@example.org")), m)
        self.assertEqual(newsletter.vorschau(m, e["id"])["anzahl"], 3)                                  # Abmeldung wirkt sofort
        e2 = newsletter.aendern(m, e["id"], None, None, None, {"tags": ["Neu"]})
        self.assertNotEqual(e["content_hash"], e2["content_hash"])                                      # anderes Segment = anderer Stand
        self.assertEqual(newsletter.vorschau(m, e["id"])["anzahl"], 1)


def newsletter_segment(m, segment):
    import newsletter
    return newsletter._segment_pruefen(m, segment)


class TestSchnittstelle(ImportBasis):
    def test_zugriff_und_form(self):
        m = self.mandant("hilo")
        pfad = "/api/v1/betreiber/mandanten/%d/abonnenten/import" % m["id"]
        self.assertEqual(self.app.test_client().post(pfad, json={}).status_code, 401)
        with mock.patch.object(betreiber_auth, "_bei_sortnext_fragen", return_value={"email": "x@y.de", "betreiber": False}):
            betreiber_auth.cache_leeren()
            self.c.set_cookie("bst_session", "tok")
            self.assertEqual(self.c.post(pfad, json={"daten": "a@example.org", "quelle": "q", "einwilligung_bestaetigt": True}).status_code, 403)
        daten = mc([["a@example.org", "", "", "", ""]])
        faelle = [({"quelle": "q", "einwilligung_bestaetigt": True}, "daten_fehlen"), ({"daten": "  ", "quelle": "q", "einwilligung_bestaetigt": True}, "daten_fehlen"),
                  ({"daten": 5, "quelle": "q", "einwilligung_bestaetigt": True}, "daten_fehlen"), ({"daten": daten, "einwilligung_bestaetigt": True}, "eingabe_ungueltig"),
                  ({"daten": daten, "quelle": "", "einwilligung_bestaetigt": True}, "eingabe_ungueltig"), ({"daten": daten, "quelle": "x" * 101, "einwilligung_bestaetigt": True}, "eingabe_ungueltig"),
                  ({"daten": daten, "quelle": "a\nb", "einwilligung_bestaetigt": True}, "eingabe_ungueltig"), ({"daten": daten, "quelle": 5, "einwilligung_bestaetigt": True}, "eingabe_ungueltig"),
                  ({"daten": daten, "quelle": "q", "nur_pruefen": "ja"}, "eingabe_ungueltig"), ({"daten": daten, "quelle": "q", "einwilligung_bestaetigt": True, "x": 1}, "eingabe_ungueltig"),
                  ({"daten": daten, "quelle": "q"}, "einwilligung_nicht_bestaetigt"), ({"daten": daten, "quelle": "q", "einwilligung_bestaetigt": "true"}, "einwilligung_nicht_bestaetigt"),
                  ({"daten": daten, "quelle": "q", "einwilligung_bestaetigt": False}, "einwilligung_nicht_bestaetigt"),
                  ({"daten": "Name\nA\n", "quelle": "q", "einwilligung_bestaetigt": True}, "spalte_nicht_gefunden")]
        with self.als_betreiber():
            betreiber_auth.cache_leeren()
            self.c.set_cookie("bst_session", "tok")
            for body, fehler in faelle:
                r = self.c.post(pfad, json=body)
                self.assertEqual((r.status_code, r.get_json()["error"]), (400, fehler), body)
            self.assertEqual(self.c.post(pfad, data="kein json", content_type="text/plain").status_code, 400)
            self.assertEqual(self.c.post("/api/v1/betreiber/mandanten/9999/abonnenten/import", json={"daten": daten, "quelle": "q", "einwilligung_bestaetigt": True}).status_code, 404)
        self.assertEqual(self.zahlen(m), {})

    def test_pruefung_braucht_keine_bestaetigung(self):
        m = self.mandant("hilo")
        r = self.importiere(m, mc([["a@example.org", "", "", "", ""]]), nur_pruefen=True, bestaetigt=False)
        self.assertEqual((r.status_code, r.get_json()["neu"]), (200, 1))

    def test_zu_gross_ist_413_und_normale_routen_bleiben_klein(self):
        m = self.mandant("hilo")
        gross = "a@example.org\n" * 300000                                                                # > 3,5 MB
        r = self.importiere(m, gross)
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.get_json(), {"error": "zu_gross"})
        mittel = "Email\n" + "".join("p%05d@example.org\n" % i for i in range(17000))                     # ca. 320 KB: nur der Import darf so groß sein
        self.assertGreater(len(mittel), 300000)
        self.assertEqual(self.importiere(m, mittel, nur_pruefen=True, bestaetigt=False).status_code, 200)
        with self.als_betreiber():
            betreiber_auth.cache_leeren()
            self.c.set_cookie("bst_session", "tok")
            r = self.c.post("/api/v1/betreiber/mandanten", json={"slug": "x" * 400000, "name": "Zu groß"})
        self.assertEqual(r.status_code, 413)

    def test_audit_hat_zahlen_und_quelle_aber_nie_adressen(self):
        m = self.mandant("hilo")
        self.importiere(m, mc([["geheim.person@example.org", "", "", "Spender", ""], ["zweite@example.org", "", "", "", ""]]), quelle="Mailchimp-Export Audit", nur_pruefen=True, bestaetigt=False)
        self.importiere(m, mc([["geheim.person@example.org", "", "", "Spender", ""], ["zweite@example.org", "", "", "", ""]]), quelle="Mailchimp-Export Audit")
        eintraege = [a for a in self.audit() if a["aktion"].startswith("abonnenten_import")]
        self.assertEqual([a["aktion"] for a in eintraege], ["abonnenten_import_geprueft", "abonnenten_import"])
        self.assertIn("quelle=Mailchimp-Export Audit", eintraege[1]["details"])
        self.assertIn("neu=2", eintraege[1]["details"])
        self.assertEqual(eintraege[1]["akteur"], "catrin@bst-next.de")
        alles = json.dumps(self.audit())
        for verboten in ("geheim.person", "zweite@", "@example.org", "Spender"):
            self.assertNotIn(verboten, alles)

    def test_antwort_enthaelt_keine_adressen(self):
        m = self.mandant("hilo")
        r = self.importiere(m, mc([["geheim.person@example.org", "", "", "Spender", ""], ["kaputt", "", "", "", ""]]))
        self.assertNotIn("geheim.person", r.get_data(as_text=True))
        self.assertNotIn("kaputt", r.get_data(as_text=True))


class TestManage(ImportBasis):
    def manage(self, *args):
        puffer = io.StringIO()
        with redirect_stdout(puffer), mock.patch.object(manage, "_start"):                              # die Testdatenbank ist schon geöffnet
            code = manage.main(list(args))
        return code, puffer.getvalue()

    def datei(self, text, kodierung="utf-8"):
        pfad = os.path.join(self.verz.name, "liste.csv")
        with open(pfad, "wb") as f:
            f.write(text.encode(kodierung))
        return pfad

    def test_ohne_zusatz_nur_pruefung(self):
        m = self.mandant("hilo")
        pfad = self.datei(mc([["a@example.org", "", "", "A", ""], ["kaputt", "", "", "", ""]]))
        code, aus = self.manage("import", "hilo", pfad, "Test-Quelle")
        self.assertEqual(code, 0, aus)
        self.assertIn("PRÜFUNG (nichts gespeichert)", aus)
        self.assertIn("neu 1", aus)
        self.assertIn("einwilligung-liegt-vor", aus)
        self.assertEqual(self.zahlen(m), {})
        code, aus = self.manage("import", "hilo", pfad, "Test-Quelle", "einwilligung-liegt-vor", "nur-pruefen")
        self.assertIn("PRÜFUNG", aus)
        self.assertEqual(self.zahlen(m), {})

    def test_echter_import_mit_zusatz_rolle_interessen_tags(self):
        m = self.mandant("hilo")
        pfad = self.datei(mc([["a@example.org", "", "", "Spender", ""]]))
        code, aus = self.manage("import", "hilo", pfad, "Test-Quelle", "einwilligung-liegt-vor", "rolle=verein", "interessen=sortnext,booknext")
        self.assertEqual(code, 0, aus)
        self.assertIn("IMPORTIERT", aus)
        self.assertIn("Tags: 1 verschiedene, häufigste: Spender (1)", aus)
        z = self.zeile(m["id"], "a@example.org")
        self.assertEqual((z["status"], z["rolle"], json.loads(z["interessen"]), json.loads(z["tags"])), ("bestaetigt", "verein", ["booknext", "sortnext"], ["Spender"]))
        a = [x for x in self.audit() if x["aktion"] == "abonnenten_import"][0]
        self.assertEqual(a["akteur"], "manage")
        self.assertNotIn("@", a["details"])

    def test_windows_kodierung_und_bom(self):
        m = self.mandant("hilo")
        pfad = self.datei("E-Mail-Adresse;Name\r\nmüller@beispiel.de;Jürgen\r\n", "cp1252")
        code, aus = self.manage("import", "hilo", pfad, "cp1252", "einwilligung-liegt-vor")
        self.assertEqual(code, 0, aus)
        pfad = self.datei("﻿Email Address,Name\nb@example.org,Ä\n", "utf-8")
        self.assertEqual(self.manage("import", "hilo", pfad, "bom", "einwilligung-liegt-vor")[0], 0)
        self.assertEqual(self.zahlen(m), {"bestaetigt": 2})

    def test_fehler(self):
        self.mandant("hilo")
        pfad = self.datei(mc([["a@example.org", "", "", "", ""]]))
        for args, text in ((("import", "gibtsnicht", pfad, "q"), "gibt es nicht"), (("import", "hilo", pfad + "x", "q"), "kann nicht gelesen"), (("import", "hilo", pfad, ""), "Quelle"),
                           (("import", "hilo", pfad, "x" * 101), "Quelle"), (("import", "hilo", pfad, "q", "rolle=gibtsnicht"), "gehören nicht zu diesem Mandanten"),
                           (("import", "hilo", self.datei("Name\nA\n"), "q"), "keine Spalte")):
            try:
                code, aus = self.manage(*args)
            except SystemExit as e:
                code, aus = 1, str(e)
            self.assertEqual(code, 1, args)
            self.assertIn(text, aus, args)
        self.assertEqual(self.manage("import", "hilo")[0], 2)


class TestMigration(unittest.TestCase):
    def test_alte_datenbank_bekommt_die_neuen_spalten(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as t:
            pfad = os.path.join(t, "alt.db")
            c = sqlite3.connect(pfad)
            c.executescript(db.SCHEMA.replace("    herkunft TEXT,\n    quelle TEXT,\n    import_am TEXT,\n    tags TEXT,\n", ""))
            c.commit()
            self.assertNotIn("tags", {r[1] for r in c.execute("PRAGMA table_info(abonnent)")})
            c.close()
            db.init(pfad)
            c = sqlite3.connect(pfad)
            self.assertLessEqual({"herkunft", "quelle", "import_am", "tags"}, {r[1] for r in c.execute("PRAGMA table_info(abonnent)")})
            c.close()
            db.init(pfad)                                                                                  # idempotent


if __name__ == "__main__":
    unittest.main()
