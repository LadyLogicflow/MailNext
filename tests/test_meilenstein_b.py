"""Meilenstein B: Entwürfe, Testmail, Freigabe, Empfängerzeilen, Versandlauf, Protokoll, Betreiber-Schnittstelle (alles je Mandant).

Jede Schutzregel hat eine Gegenprobe (der Normalfall geht) und wird rot, wenn die Regel entfernt wird (Sabotageproben liegen im Arbeitsprotokoll)."""
import email
import email.policy
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import abonnenten
import betreiber_auth
import config
import db
import mailer
import mandanten
import newsletter
from tests.hilfen_testmail import testmail_liste
import schluessel
from test_meilenstein_a import Basis as BasisA


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class Basis(BasisA):
    def abo(self, m, adresse, status="bestaetigt", rolle=None, interessen=()):
        """Legt eine Abonnentin direkt an (ohne Bestätigungsmail); gibt die Zeile zurück."""
        with db.verbindung() as c:
            c.execute("INSERT INTO abonnent(mandant_id, email, email_hmac, status, rolle, interessen, einwilligung_version, angemeldet_am, bestaetigt_am, nonce) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (m["id"], adresse if status != "abgemeldet" else None, schluessel.email_hmac(m["id"], adresse), status, rolle,
                       json.dumps(sorted(interessen)), "EINW-1", "2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z" if status == "bestaetigt" else None,
                       schluessel.neue_nonce()))
        return self.zeile(m["id"], adresse)

    def entwurf(self, m, ziel="testliste", segment=None, betreff="Neues von uns", text="Hallo!\n\nHier ist der Newsletter mit Link https://beispiel.test/x ."):
        return newsletter.anlegen(m, betreff, text, ziel, segment)

    def freigegeben(self, m, ziel="testliste", segment=None, **kw):
        if ziel == "abonnenten":
            newsletter.echtversand_setzen(m["id"], True, "t")
        e = self.entwurf(m, ziel, segment, **kw)
        testmail_liste(m, e["id"])
        e = newsletter.lesen(m, e["id"])
        newsletter.freigeben(m, e["id"], e["content_hash"], True, "betreiber@bst-next.de")
        return e["id"]

    def eml(self, slug):
        return [email.message_from_bytes(p.read_bytes(), policy=email.policy.default) for p in self.mails(slug)]

    def an_adressen(self, slug):
        return sorted(str(x["To"]) for x in self.eml(slug) if not str(x["Subject"]).startswith("[TEST] "))          # Testmails zählen nicht als Versand

    def zeilen(self, entwurf_id):
        with db.verbindung() as c:
            return [dict(z) for z in c.execute("SELECT * FROM empfaenger WHERE entwurf_id=? ORDER BY id", (entwurf_id,)).fetchall()]


class DarstellungTests(Basis):
    def test_text_zu_html_maskiert_und_verlinkt_nur_https(self):
        h = newsletter.text_zu_html("Erster <b>Absatz</b> & mehr\nzweite Zeile\n\nZweiter <i>vor</i> Link: https://a.test/p?x=1&y=2, <u>danach</u>.\nhttp://unsicher.test javascript:alert(1)")
        self.assertNotIn("<b>", h)
        self.assertNotIn("<i>", h)                                              # Maskierung auch vor einem Link
        self.assertNotIn("<u>", h)                                              # und danach
        self.assertIn("&lt;b&gt;", h)
        self.assertEqual(h.count("<p>"), 2)
        self.assertIn("zweite Zeile", h.replace("<br>", " "))
        self.assertIn('<a href="https://a.test/p?x=1&amp;y=2">', h)
        self.assertNotIn('href="http://', h)
        self.assertNotIn('href="javascript', h)
        self.assertIn("</a>,", h)                                              # Satzzeichen gehört nicht zum Link

    def test_darstellen_kopfzeilen_links_und_design(self):
        m = self.mandant("hilo", "HILO", farbe_primaer="#0a0b0c")
        z = self.abo(m, "a@beispiel.de")
        token = abonnenten.persoenliches_token(z)
        betreff, text, html_text, header = newsletter.darstellen(m, "Betreff", "Hallo", token)
        self.assertIn("/hilo/newsletter/abmelden-one-click/" + token, header["List-Unsubscribe"])
        self.assertEqual(header["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        self.assertIn("/hilo/newsletter/einstellungen?t=" + token, text)
        self.assertIn("/hilo/newsletter/einstellungen?t=" + token, html_text)
        self.assertIn("Musterstraße 1", text)
        self.assertIn("https://hilo.test/impressum", text)
        self.assertIn("#0a0b0c", html_text)
        self.assertNotIn("<img", html_text)                                    # kein Logo, kein Tracking-Pixel
        self.assertEqual(schluessel.token_pruefen(token)[:2], (m["id"], z["id"]))


class EntwurfTests(Basis):
    def test_anlegen_aendern_und_validierung(self):
        m = self.mandant("hilo")
        e = self.entwurf(m)
        self.assertEqual((e["status"], e["ziel"], e["testmail"]["passender_stand"]), ("entwurf", "testliste", False))
        self.assertEqual(len(e["content_hash"]), 64)
        neu = newsletter.aendern(m, e["id"], "Anderer Betreff", None, None, None)
        self.assertNotEqual(neu["content_hash"], e["content_hash"])
        self.assertEqual(newsletter.lesen(m, e["id"])["betreff"], "Anderer Betreff")
        for betreff, text, ziel, segment in (("", "x", "testliste", None), ("a\nb", "x", "testliste", None), ("x" * 151, "x", "testliste", None),
                                             ("B", "", "testliste", None), ("B", "x", "alle", None), ("B", "x", "testliste", {"rollen": ["chef"]}),
                                             ("B", "x", "testliste", {"unbekannt": 1}), ("B", "x", "testliste", {"rollen": []})):
            with self.assertRaises(newsletter.Fehler, msg=str((betreff, ziel, segment))):
                newsletter.anlegen(m, betreff, text, ziel, segment)

    def test_entwuerfe_sind_je_mandant_getrennt(self):
        a, b = self.mandant("a1"), self.mandant("b1")
        e = self.entwurf(a)
        self.assertIsNone(newsletter.lesen(b, e["id"]))
        for f in (lambda: newsletter.aendern(b, e["id"], "x", None, None, None), lambda: testmail_liste(b, e["id"]),
                  lambda: newsletter.vorschau(b, e["id"]), lambda: newsletter.status(b, e["id"]), lambda: newsletter.protokoll(b, e["id"]),
                  lambda: newsletter.stoppen(b, e["id"]), lambda: newsletter.freigeben(b, e["id"], e["content_hash"], True, "x")):
            with self.assertRaises(newsletter.Fehler) as ctx:
                f()
            self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(newsletter.liste(b), [])
        self.assertEqual(len(newsletter.liste(a)), 1)


class TestmailTests(Basis):
    def test_testmail_geht_an_die_ganze_testliste_betreff_und_stand(self):
        m = self.mandant("hilo")
        newsletter.testliste_setzen(m, ["a@beispiel.de", "b@beispiel.de"])
        e = self.entwurf(m)
        r = newsletter.testmail(m, e["id"])
        self.assertEqual((r["status"], r["gesendet"], r["fehler"]), ("gesendet", 2, 0))
        self.assertEqual([(x["adresse"], x["ergebnis"]) for x in r["ergebnisse"]], [("a@beispiel.de", "datei"), ("b@beispiel.de", "datei")])
        self.assertEqual(sorted(str(x["To"]) for x in self.eml("hilo")), ["a@beispiel.de", "b@beispiel.de"])
        mail = self.eml("hilo")[0]
        self.assertTrue(str(mail["Subject"]).startswith("[TEST] "))
        self.assertTrue(newsletter.lesen(m, e["id"])["testmail"]["passender_stand"])
        self.assertIsNotNone(mail["List-Unsubscribe"])

    def test_versand_aus_gibt_keine_testmail(self):
        m = self.mandant("hilo", modus="aus")
        e = self.entwurf(m)
        with self.assertRaises(newsletter.Fehler) as ctx:
            testmail_liste(m, e["id"])
        self.assertEqual(ctx.exception.code, "versand_nicht_moeglich")
        self.assertFalse(newsletter.lesen(m, e["id"])["testmail"]["passender_stand"])
        self.assertEqual(self.mails("hilo"), [])

    def test_aenderung_macht_testmail_ungueltig(self):
        m = self.mandant("hilo")
        e = self.entwurf(m)
        testmail_liste(m, e["id"])
        newsletter.aendern(m, e["id"], None, "Ganz anderer Text", None, None)
        self.assertFalse(newsletter.lesen(m, e["id"])["testmail"]["passender_stand"])


class FreigabeTests(Basis):
    def test_regeln_der_freigabe(self):
        m = self.mandant("hilo")
        newsletter.testliste_setzen(m, ["test@beispiel.de"])
        e = self.entwurf(m)
        h = e["content_hash"]

        def versuche(**kw):
            daten = {"content_hash": h, "bestaetigt": True}
            daten.update(kw)
            with self.assertRaises(newsletter.Fehler) as ctx:
                newsletter.freigeben(m, e["id"], daten["content_hash"], daten["bestaetigt"], "x@y.de")
            return ctx.exception.code
        self.assertEqual(versuche(), "testmail_fehlt")
        testmail_liste(m, e["id"])
        self.assertEqual(versuche(bestaetigt=False), "bestaetigung_fehlt")
        self.assertEqual(versuche(bestaetigt="ja"), "bestaetigung_fehlt")
        self.assertEqual(versuche(content_hash="0" * 64), "entwurf_geaendert")
        newsletter.aendern(m, e["id"], None, "Neuer Text", None, None)                     # Stand weicht von der Testmail ab
        self.assertEqual(versuche(content_hash=newsletter.lesen(m, e["id"])["content_hash"]), "entwurf_geaendert")
        testmail_liste(m, e["id"])
        h = newsletter.lesen(m, e["id"])["content_hash"]
        self.assertEqual(newsletter.freigeben(m, e["id"], h, True, "x@y.de"), {"status": "freigegeben", "empfaenger": 1})
        self.assertEqual(versuche(content_hash=h), "bereits_freigegeben")
        with self.assertRaises(newsletter.Fehler) as ctx:
            newsletter.aendern(m, e["id"], "Spaet", None, None, None)
        self.assertEqual(ctx.exception.code, "nicht_mehr_aenderbar")
        with self.assertRaises(newsletter.Fehler):
            testmail_liste(m, e["id"])

    def test_echtversand_ist_gesperrt_bis_ein_betreiber_freigibt(self):
        m = self.mandant("hilo")
        self.abo(m, "a@beispiel.de")
        e = self.entwurf(m, "abonnenten")
        testmail_liste(m, e["id"])
        h = newsletter.lesen(m, e["id"])["content_hash"]
        with self.assertRaises(newsletter.Fehler) as ctx:
            newsletter.freigeben(m, e["id"], h, True, "x@y.de")
        self.assertEqual(ctx.exception.code, "echtversand_gesperrt")
        self.assertEqual(self.zeilen(e["id"]), [])
        newsletter.echtversand_setzen(m["id"], True, "catrin")
        self.assertEqual(newsletter.freigeben(m, e["id"], h, True, "x@y.de")["empfaenger"], 1)

    def test_echtversand_freigabe_gilt_nur_im_eigenen_mandanten(self):
        a, b = self.mandant("a3"), self.mandant("b3")
        newsletter.echtversand_setzen(a["id"], True, "t")
        self.assertTrue(newsletter.echtversand_freigegeben(a["id"]))
        self.assertFalse(newsletter.echtversand_freigegeben(b["id"]))

    def test_keine_empfaenger_422(self):
        m = self.mandant("hilo")
        e = self.entwurf(m)
        testmail_liste(m, e["id"])
        newsletter.testliste_setzen(m, [])                                                # Testliste wieder leer: der Versand an sie hat keine Empfänger
        with self.assertRaises(newsletter.Fehler) as ctx:
            newsletter.freigeben(m, e["id"], newsletter.lesen(m, e["id"])["content_hash"], True, "x@y.de")
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("keine_empfaenger", 422))

    def test_nur_bestaetigte_nicht_abgemeldete_nicht_unzustellbare(self):
        m = self.mandant("hilo")
        self.abo(m, "ja@beispiel.de")
        self.abo(m, "offen@beispiel.de", status="unbestaetigt")
        self.abo(m, "weg@beispiel.de", status="abgemeldet")
        self.abo(m, "bounce@beispiel.de", status="unzustellbar")
        e = self.entwurf(m, "abonnenten")
        newsletter.echtversand_setzen(m["id"], True, "t")
        self.assertEqual(newsletter.vorschau(m, e["id"])["anzahl"], 1)
        testmail_liste(m, e["id"])
        newsletter.freigeben(m, e["id"], newsletter.lesen(m, e["id"])["content_hash"], True, "x@y.de")
        self.assertEqual([z["abonnent_id"] for z in self.zeilen(e["id"])], [self.zeile(m["id"], "ja@beispiel.de")["id"]])

    def test_segment_rolle_und_interesse(self):
        m = self.mandant("hilo")
        self.abo(m, "v-s@beispiel.de", rolle="verein", interessen=["sortnext"])
        self.abo(m, "v-b@beispiel.de", rolle="verein", interessen=["booknext"])
        self.abo(m, "b-s@beispiel.de", rolle="beratungsstelle", interessen=["sortnext", "booknext"])
        self.abo(m, "ohne@beispiel.de")
        newsletter.echtversand_setzen(m["id"], True, "t")

        def anzahl(segment):
            e = self.entwurf(m, "abonnenten", segment)
            return newsletter.vorschau(m, e["id"])["anzahl"]
        self.assertEqual(anzahl(None), 4)
        self.assertEqual(anzahl({"rollen": ["verein"]}), 2)
        self.assertEqual(anzahl({"interessen": ["sortnext"]}), 2)
        self.assertEqual(anzahl({"rollen": ["verein"], "interessen": ["booknext"]}), 1)
        self.assertEqual(anzahl({"rollen": ["verein", "beratungsstelle"], "interessen": ["booknext"]}), 2)

    def test_empfaengerliste_wird_festgeschrieben(self):
        m = self.mandant("hilo")
        self.abo(m, "frueh@beispiel.de")
        e = self.freigegeben(m, "abonnenten")
        self.abo(m, "spaet@beispiel.de")                                                  # nach der Freigabe dazugekommen
        newsletter.lauf()
        self.assertEqual(self.an_adressen("hilo"), ["frueh@beispiel.de"])
        self.assertEqual(len(self.zeilen(e)), 1)


class VersandTests(Basis):
    def test_je_lauf_hoechstens_fuenf_und_nie_doppelt(self):
        m = self.mandant("hilo")
        for i in range(12):
            self.abo(m, "a%02d@beispiel.de" % i)
        e = self.freigegeben(m, "abonnenten")
        vor = len(self.mails("hilo"))                                                       # eine Testmail liegt schon im Ausgang
        newsletter.lauf()
        self.assertEqual(len(self.mails("hilo")) - vor, newsletter.LIMIT_PRO_LAUF)
        for _ in range(5):
            newsletter.lauf()
        an = [a for a in self.an_adressen("hilo") if a.startswith("a")]
        self.assertEqual(len(an), 12)
        self.assertEqual(len(set(an)), 12)                                                  # keine Zeile zweimal
        self.assertEqual(newsletter.status(m, e)["status"], "fertig")
        self.assertEqual(newsletter.status(m, e)["gesendet"], 12)

    def test_stundenlimit_ueber_mehrere_laeufe(self):
        m = self.mandant("hilo")
        for i in range(9):
            self.abo(m, "l%02d@beispiel.de" % i)
        e = self.freigegeben(m, "abonnenten")
        with mock.patch.object(newsletter, "LIMIT_PRO_STUNDE", 7):
            for _ in range(5):
                newsletter.lauf()
        st = newsletter.status(m, e)
        self.assertEqual((st["gesendet"], st["offen"]), (7, 2))
        self.assertEqual(newsletter.LIMIT_PRO_STUNDE, 100)

    def test_jede_mail_hat_persoenlichen_link_und_one_click_der_funktioniert(self):
        m = self.mandant("hilo")
        z = self.abo(m, "a@beispiel.de")
        self.abo(m, "b@beispiel.de")
        self.freigegeben(m, "abonnenten")
        newsletter.lauf()
        mails = [x for x in self.eml("hilo") if str(x["To"]) == "a@beispiel.de"]
        self.assertEqual(len(mails), 1)
        mail = mails[0]
        self.assertEqual(mail["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        self.assertIn("news@hilo.test", mail["From"])
        self.assertIsNotNone(mail.get_body(("plain",)))
        self.assertIsNotNone(mail.get_body(("html",)))
        url = str(mail["List-Unsubscribe"]).strip("<>")
        self.assertEqual(self.c.post(url.replace("https://mailnext.test", "")).status_code, 200)       # Abmelden per One-Click
        self.assertEqual(self.zeile(m["id"], "a@beispiel.de")["status"], "abgemeldet")
        self.assertEqual(self.zeile(m["id"], "b@beispiel.de")["status"], "bestaetigt")
        self.assertNotIn("<img", mail.get_body(("html",)).get_content())

    def test_abmeldung_nach_freigabe_wirkt_beim_naechsten_lauf(self):
        m = self.mandant("hilo")
        z = self.abo(m, "weg@beispiel.de")
        self.abo(m, "bleibt@beispiel.de")
        e = self.freigegeben(m, "abonnenten")
        abonnenten.abmelden(abonnenten.persoenliches_token(z))
        newsletter.lauf()
        self.assertEqual(self.an_adressen("hilo"), ["bleibt@beispiel.de"])
        st = newsletter.status(m, e)
        self.assertEqual((st["gesendet"], st["uebersprungen_abgemeldet"]), (1, 1))

    def test_versand_aus_haelt_alles_zurueck_und_holt_es_nach(self):
        m = self.mandant("hilo")
        self.abo(m, "a@beispiel.de")
        e = self.freigegeben(m, "abonnenten")
        mandanten.versand_setzen(m["id"], {"versandmodus": "aus"}, "t")
        vor = len(self.mails("hilo"))
        self.assertEqual(newsletter.lauf()["wartet"], 1)
        self.assertEqual(len(self.mails("hilo")), vor)
        self.assertEqual(newsletter.status(m, e)["offen"], 1)
        mandanten.versand_setzen(m["id"], {"versandmodus": "datei"}, "t")
        newsletter.lauf()
        self.assertEqual(newsletter.status(m, e)["gesendet"], 1)

    def test_echtversand_sperre_gilt_auch_im_lauf(self):
        m = self.mandant("hilo")
        self.abo(m, "a@beispiel.de")
        e = self.freigegeben(m, "abonnenten")
        newsletter.echtversand_setzen(m["id"], False, "t")                                   # nach der Freigabe wieder gesperrt
        vor = len(self.mails("hilo"))
        newsletter.lauf()
        self.assertEqual(len(self.mails("hilo")), vor)
        self.assertEqual(newsletter.status(m, e)["offen"], 1)

    def test_stoppen_bricht_offene_zeilen_ab_gesendetes_bleibt(self):
        m = self.mandant("hilo")
        for i in range(8):
            self.abo(m, "s%d@beispiel.de" % i)
        e = self.freigegeben(m, "abonnenten")
        newsletter.lauf()
        newsletter.stoppen(m, e)
        newsletter.lauf()
        newsletter.lauf()
        st = newsletter.status(m, e)
        self.assertEqual((st["gesendet"], st["abgebrochen"], st["offen"], st["status"]), (5, 3, 0, "gestoppt"))

    def test_haengende_zeilen_werden_unklar_und_nie_automatisch_wiederholt(self):
        m = self.mandant("hilo")
        self.abo(m, "a@beispiel.de")
        self.abo(m, "b@beispiel.de")
        e = self.freigegeben(m, "abonnenten")
        zeilen = self.zeilen(e)
        alt = _iso(datetime.now(timezone.utc) - timedelta(minutes=newsletter.UNKLAR_NACH_MINUTEN + 1))
        jung = _iso(datetime.now(timezone.utc) - timedelta(minutes=1))
        with db.verbindung() as c:
            c.execute("UPDATE empfaenger SET status='sending', zeit=? WHERE id=?", (alt, zeilen[0]["id"]))
            c.execute("UPDATE empfaenger SET status='sending', zeit=? WHERE id=?", (jung, zeilen[1]["id"]))
        vor = len(self.mails("hilo"))
        newsletter.lauf()
        newsletter.lauf()
        status = {z["id"]: z["status"] for z in self.zeilen(e)}
        self.assertEqual(status[zeilen[0]["id"]], "unklar")
        self.assertEqual(status[zeilen[1]["id"]], "sending")                                # zu jung: noch nicht anfassen
        self.assertEqual(len(self.mails("hilo")), vor)                                       # nichts wird (noch einmal) gesendet

    def test_vorubergehende_fehler_drei_versuche_dann_fehlgeschlagen(self):
        m = self.mandant("hilo")
        self.abo(m, "a@beispiel.de")
        e = self.freigegeben(m, "abonnenten")
        def zeit_vergeht():
            alt = _iso(datetime.now(timezone.utc) - timedelta(minutes=newsletter.WIEDERHOLUNG_ABSTAND_MINUTEN + 1))
            with db.verbindung() as c:
                c.execute("UPDATE empfaenger SET zeit=? WHERE entwurf_id=?", (alt, e))
        with mock.patch.object(mailer, "senden", return_value="fehler") as senden:
            newsletter.lauf()
            newsletter.lauf()                                                                  # gleich danach: noch nicht erneut versuchen
            self.assertEqual((senden.call_count, self.zeilen(e)[0]["status"]), (1, "queued"))
            zeit_vergeht()
            newsletter.lauf()
            self.assertEqual((senden.call_count, self.zeilen(e)[0]["status"]), (2, "queued"))
            zeit_vergeht()
            newsletter.lauf()
        z = self.zeilen(e)[0]
        self.assertEqual((z["status"], z["versuche"]), ("fehlgeschlagen", 3))
        self.assertEqual(newsletter.status(m, e)["fehlgeschlagen"], 1)
        with mock.patch.object(mailer, "senden", return_value="datei") as senden:
            newsletter.lauf()
        self.assertEqual(senden.call_count, 0)                                                 # fehlgeschlagen wird nie von selbst wiederholt

    def test_harte_ablehnung_markiert_unzustellbar(self):
        m = self.mandant("hilo")
        self.abo(m, "tot@beispiel.de")
        e = self.freigegeben(m, "abonnenten")
        with mock.patch.object(mailer, "senden", return_value="abgelehnt"):
            newsletter.lauf()
        self.assertEqual(self.zeilen(e)[0]["status"], "unzustellbar")
        self.assertEqual(self.zeile(m["id"], "tot@beispiel.de")["status"], "unzustellbar")
        e2 = self.entwurf(m, "abonnenten")
        self.assertEqual(newsletter.vorschau(m, e2["id"])["anzahl"], 0)                       # künftig nicht mehr angeschrieben

    def test_testliste_versand_braucht_keine_echtversand_freigabe(self):
        m = self.mandant("hilo")
        newsletter.testliste_setzen(m, ["t1@beispiel.de", "t2@beispiel.de"])
        self.abo(m, "kunde@beispiel.de")
        self.freigegeben(m, "testliste")
        vor = len(self.mails("hilo"))
        newsletter.lauf()
        self.assertEqual(sorted(a for a in self.an_adressen("hilo") if a.startswith("t")), ["t1@beispiel.de", "t2@beispiel.de"])
        self.assertNotIn("kunde@beispiel.de", self.an_adressen("hilo"))

    def test_mandanten_bekommen_nur_ihre_eigenen_mails(self):
        a, b = self.mandant("a4", "Alpha"), self.mandant("b4", "Beta")
        self.abo(a, "gemeinsam@beispiel.de")
        self.abo(b, "gemeinsam@beispiel.de")
        self.abo(b, "nur-b@beispiel.de")
        ea = self.freigegeben(a, "abonnenten", betreff="Nur für Alpha")
        eb = self.freigegeben(b, "abonnenten", betreff="Nur für Beta")
        for _ in range(3):
            newsletter.lauf()
        a_mails = [x for x in self.eml("a4") if not str(x["Subject"]).startswith("[TEST]")]
        b_mails = [x for x in self.eml("b4") if not str(x["Subject"]).startswith("[TEST]")]
        self.assertEqual([str(x["To"]) for x in a_mails], ["gemeinsam@beispiel.de"])
        self.assertEqual(sorted(str(x["To"]) for x in b_mails), ["gemeinsam@beispiel.de", "nur-b@beispiel.de"])
        self.assertTrue(all("Alpha" in str(x["Subject"]) for x in a_mails))
        self.assertTrue(all("Beta" in str(x["Subject"]) for x in b_mails))
        self.assertTrue(all("news@a4.test" in str(x["From"]) for x in a_mails))
        self.assertTrue(all("news@b4.test" in str(x["From"]) for x in b_mails))
        self.assertEqual({z["mandant_id"] for z in self.zeilen(ea)}, {a["id"]})

    def test_stillgelegter_mandant_sendet_nicht(self):
        m = self.mandant("hilo")
        self.abo(m, "a@beispiel.de")
        e = self.freigegeben(m, "abonnenten")
        mandanten.aendern(m["id"], aktiv=False)
        vor = len(self.mails("hilo"))
        newsletter.lauf()
        self.assertEqual(len(self.mails("hilo")), vor)

    def test_versandjob_laeuft_nur_wenn_gewollt(self):
        import app as app_modul
        self.assertFalse(app_modul._job_gestartet)                                          # Tests starten keinen Hintergrundthread


class ProtokollTests(Basis):
    def test_protokoll_und_csv_mit_formelschutz(self):
        m = self.mandant("hilo")
        self.abo(m, "=1+1@beispiel.de")
        self.abo(m, "+x@beispiel.de")
        self.abo(m, "normal@beispiel.de")
        e = self.freigegeben(m, "abonnenten")
        newsletter.lauf()
        zeilen = newsletter.protokoll(m, e)
        self.assertEqual(sorted(z["email"] for z in zeilen), ["+x@beispiel.de", "=1+1@beispiel.de", "normal@beispiel.de"])
        csv_text = newsletter.protokoll_csv(zeilen)
        self.assertIn("'=1+1@beispiel.de", csv_text)
        self.assertIn("'+x@beispiel.de", csv_text)
        self.assertNotIn("\n=1+1", csv_text)
        self.assertTrue(csv_text.startswith("email,status,zeitpunkt,fehler"))

    def test_abgemeldete_erscheinen_ohne_adresse(self):
        m = self.mandant("hilo")
        z = self.abo(m, "weg@beispiel.de")
        e = self.freigegeben(m, "abonnenten")
        abonnenten.abmelden(abonnenten.persoenliches_token(z))
        self.assertEqual(newsletter.protokoll(m, e)[0]["email"], "(abgemeldet)")


class BetreiberNewsletterApiTests(Basis):
    def als_betreiber(self):
        return mock.patch.object(betreiber_auth, "_bei_sortnext_fragen", return_value={"email": "catrin@bst-next.de", "betreiber": True})

    def aufruf(self, methode, pfad, **kw):
        self.c.set_cookie("bst_session", "tok")
        return getattr(self.c, methode)("/api/v1/betreiber" + pfad, **kw)

    def audit(self):
        with db.verbindung() as c:
            return [dict(z) for z in c.execute("SELECT * FROM audit_log ORDER BY id").fetchall()]

    def test_alle_routen_brauchen_betreiber(self):
        m = self.mandant("hilo")
        e = self.entwurf(m)
        basis = "/mandanten/%d" % m["id"]
        routen = [("get", "/entwuerfe"), ("post", "/entwuerfe"), ("get", "/entwuerfe/%d" % e["id"]), ("put", "/entwuerfe/%d" % e["id"]),
                  ("post", "/entwuerfe/%d/testmail" % e["id"]), ("get", "/entwuerfe/%d/empfaengervorschau" % e["id"]), ("post", "/entwuerfe/%d/freigeben" % e["id"]),
                  ("post", "/entwuerfe/%d/stoppen" % e["id"]), ("get", "/entwuerfe/%d/status" % e["id"]), ("get", "/entwuerfe/%d/protokoll" % e["id"]),
                  ("get", "/entwuerfe/%d/protokoll.csv" % e["id"]), ("get", "/testliste"), ("put", "/testliste"), ("get", "/echtversand"), ("put", "/echtversand")]
        for methode, pfad in routen:
            c = self.app.test_client()
            self.assertEqual(getattr(c, methode)("/api/v1/betreiber" + basis + pfad, json={}).status_code, 401, pfad)
            c.set_cookie("bst_session", "x")
            with mock.patch.object(betreiber_auth, "_bei_sortnext_fragen", return_value={"email": "x@y.de", "betreiber": False}):
                betreiber_auth.cache_leeren()
                self.assertEqual(getattr(c, methode)("/api/v1/betreiber" + basis + pfad, json={}).status_code, 403, pfad)

    def test_ganzer_ablauf_ueber_die_schnittstelle(self):
        m = self.mandant("hilo")
        self.abo(m, "a@beispiel.de")
        basis = "/mandanten/%d" % m["id"]
        with self.als_betreiber():
            self.assertEqual(self.aufruf("put", basis + "/echtversand", json={"freigegeben": True}).status_code, 200)
            r = self.aufruf("post", basis + "/entwuerfe", json={"betreff": "Hallo Welt", "text": "Inhalt", "ziel": "abonnenten"})
            self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
            eid, h = r.get_json()["id"], r.get_json()["content_hash"]
            self.assertEqual(self.aufruf("post", basis + "/entwuerfe/%d/freigeben" % eid, json={"content_hash": h, "bestaetigt": True}).get_json()["error"], "testmail_fehlt")
            leer = self.aufruf("post", basis + "/entwuerfe/%d/testmail" % eid, json={})                  # Testliste noch leer
            self.assertEqual((leer.status_code, leer.get_json()["error"]), (400, "testliste_leer"))
            newsletter.testliste_setzen(m, ["test@beispiel.de"])
            t = self.aufruf("post", basis + "/entwuerfe/%d/testmail" % eid, json={})
            self.assertEqual((t.status_code, t.get_json()["gesendet"], t.get_json()["ergebnisse"][0]["adresse"]), (200, 1, "test@beispiel.de"))
            self.assertEqual(self.aufruf("get", basis + "/entwuerfe/%d/empfaengervorschau" % eid).get_json()["anzahl"], 1)
            r = self.aufruf("post", basis + "/entwuerfe/%d/freigeben" % eid, json={"content_hash": h, "bestaetigt": True})
            self.assertEqual((r.status_code, r.get_json()), (200, {"status": "freigegeben", "empfaenger": 1}))
            self.assertEqual(self.aufruf("put", basis + "/entwuerfe/%d" % eid, json={"betreff": "x"}).get_json()["error"], "nicht_mehr_aenderbar")
            newsletter.lauf()
            s = self.aufruf("get", basis + "/entwuerfe/%d/status" % eid).get_json()
            self.assertEqual((s["gesendet"], s["status"], s["limit_pro_stunde"]), (1, "fertig", 100))
            p = self.aufruf("get", basis + "/entwuerfe/%d/protokoll" % eid).get_json()
            self.assertEqual(p["empfaenger"][0]["email"], "a@beispiel.de")
            csv_antwort = self.aufruf("get", basis + "/entwuerfe/%d/protokoll.csv" % eid)
            self.assertEqual(csv_antwort.mimetype, "text/csv")
            self.assertIn("a@beispiel.de,sent", csv_antwort.get_data(as_text=True))

    def test_fremder_mandant_im_pfad_404_und_fehlercodes(self):
        a, b = self.mandant("a5"), self.mandant("b5")
        e = self.entwurf(a)
        with self.als_betreiber():
            self.assertEqual(self.aufruf("get", "/mandanten/%d/entwuerfe/%d" % (b["id"], e["id"])).status_code, 404)
            self.assertEqual(self.aufruf("get", "/mandanten/9999/entwuerfe").status_code, 404)
            self.assertEqual(self.aufruf("post", "/mandanten/%d/entwuerfe" % a["id"], json={"betreff": "", "text": "x"}).get_json()["error"], "betreff_ungueltig")
            self.assertEqual(self.aufruf("put", "/mandanten/%d/echtversand" % a["id"], json={"freigegeben": "ja"}).status_code, 400)
            self.assertEqual(self.aufruf("put", "/mandanten/%d/testliste" % a["id"], json={"adressen": ["kaputt"]}).get_json()["error"], "adressen_ungueltig")

    def test_audit_ohne_adressen_texte_und_geheimnisse(self):
        m = self.mandant("hilo")
        self.abo(m, "kunde@beispiel.de")
        basis = "/mandanten/%d" % m["id"]
        with self.als_betreiber():
            self.aufruf("put", basis + "/testliste", json={"adressen": ["intern@beispiel.de"]})
            self.aufruf("put", basis + "/echtversand", json={"freigegeben": True})
            r = self.aufruf("post", basis + "/entwuerfe", json={"betreff": "Streng geheimer Betreff", "text": "Streng geheimer Text", "ziel": "abonnenten"})
            eid, h = r.get_json()["id"], r.get_json()["content_hash"]
            self.aufruf("post", basis + "/entwuerfe/%d/testmail" % eid, json={"an": "intern@beispiel.de"})
            self.aufruf("post", basis + "/entwuerfe/%d/freigeben" % eid, json={"content_hash": h, "bestaetigt": True})
            self.aufruf("get", basis + "/entwuerfe/%d/protokoll" % eid)
        text = json.dumps(self.audit())
        for geheim in ("kunde@beispiel.de", "intern@beispiel.de", "Streng geheimer", "beispiel.de"):
            self.assertNotIn(geheim, text, geheim)
        aktionen = [a["aktion"] for a in self.audit()]
        for erwartet in ("testliste_gesetzt", "echtversand_geaendert", "entwurf_angelegt", "testmail_gesendet", "entwurf_freigegeben", "protokoll_gelesen"):
            self.assertIn(erwartet, aktionen)
        self.assertIn("empfaenger=1", [a["details"] for a in self.audit() if a["aktion"] == "entwurf_freigegeben"][0])

    def test_ohne_audit_keine_antwort(self):
        m = self.mandant("hilo")
        with self.als_betreiber(), mock.patch.object(db, "audit", side_effect=RuntimeError("audit kaputt")):
            self.app.config["PROPAGATE_EXCEPTIONS"] = False
            r = self.aufruf("get", "/mandanten/%d/entwuerfe" % m["id"])
        self.assertEqual(r.status_code, 500)


if __name__ == "__main__":
    unittest.main()
