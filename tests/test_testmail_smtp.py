"""Testmail über den SMTP-Pfad (catrin #19155): Mandant mit Logo-Bild, Text- und Layout-Entwurf, Testliste mit mehreren Adressen, smtplib gemockt.

Belegt, dass der Mail-Aufbau (_nachricht, Kopf, Header, Ansicht-Link) in den Versionen 0.6.x keinen Fehler auslöst und die Mail je Adresse an den SMTP-Server geht."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mailer
import mandanten
import newsletter
from test_etappe2 import blocks
from test_etappe3 import Basis


class FalscherSmtp:
    """Ersatz für smtplib.SMTP/SMTP_SSL: merkt sich Anmeldung und Nachrichten."""
    nachrichten = []

    def __init__(self, *a, **k):
        self.a = a

    def __enter__(self):
        return self

    def __exit__(self, *e):
        return False

    def starttls(self, **k):
        pass

    def login(self, benutzer, passwort):
        pass

    def send_message(self, nachricht, *a, **k):
        bytes(nachricht)                                                    # serialisieren wie smtplib es tut
        FalscherSmtp.nachrichten.append(nachricht)


class TestTestmailSmtp(Basis):
    def smtp_einrichten(self, m, verschluesselung="starttls"):
        mandanten.versand_setzen(m["id"], {"versandmodus": "smtp", "smtp_host": "smtp.beispiel.test", "smtp_port": 587 if verschluesselung == "starttls" else 465,
                                           "smtp_benutzer": "news@hilo.test", "smtp_passwort": "geheim-test", "smtp_verschluesselung": verschluesselung}, "test")

    def logo_setzen(self, m, bild_id):
        r = self.anfrage("put", "/mandanten/%d" % m["id"], json={"design": {"logo_bild_id": bild_id}})
        self.assertEqual(r.status_code, 200, r.get_json())
        return mandanten.lesen(m["id"])

    def lauf(self, m, entwurf_id, **kw):
        FalscherSmtp.nachrichten = []
        with mock.patch.object(mailer.smtplib, "SMTP", FalscherSmtp), mock.patch.object(mailer.smtplib, "SMTP_SSL", FalscherSmtp):
            return newsletter.testmail(mandanten.lesen(m["id"]), entwurf_id, **kw)

    def test_layout_entwurf_mit_logo_bild_geht_an_alle_adressen_der_testliste(self):
        m, ids = self.start(1)
        m = self.logo_setzen(m, ids[0])
        self.smtp_einrichten(m)
        newsletter.testliste_setzen(m, ["a@beispiel.de", "b@beispiel.de", "c+tag@beispiel.de"])
        e = self.anlegen(m, blocks(ids))
        r = self.lauf(m, e["id"])
        self.assertEqual((r["status"], r["gesendet"], r["fehler"]), ("gesendet", 3, 0), r)
        self.assertEqual(sorted(n["To"] for n in FalscherSmtp.nachrichten), ["a@beispiel.de", "b@beispiel.de", "c+tag@beispiel.de"])
        html = FalscherSmtp.nachrichten[0].get_body(("html",)).get_content()
        self.assertIn("/bild/", html)                                          # Logo und Bilder aus dem eigenen Bestand
        self.assertIsNotNone(FalscherSmtp.nachrichten[0]["List-Unsubscribe"])

    def _text_entwurf(self, verschluesselung):
        m, ids = self.start(1)
        m = self.logo_setzen(m, ids[0])
        self.smtp_einrichten(m, verschluesselung)
        newsletter.testliste_setzen(m, ["a@beispiel.de"])
        e = newsletter.anlegen(m, "Betreff mit Umlauten äöü", "Hallo!\n\nText mit Link https://beispiel.test/x .", "testliste", None)
        r = self.lauf(m, e["id"])
        self.assertEqual((r["status"], r["gesendet"]), ("gesendet", 1), r)
        self.assertIn("Umlauten", str(FalscherSmtp.nachrichten[0]["Subject"]))

    def test_text_entwurf_mit_logo_bild_starttls(self):
        self._text_entwurf("starttls")

    def test_text_entwurf_mit_logo_bild_ssl(self):
        self._text_entwurf("ssl")

    def test_alle_fehlgeschlagen_409_nennt_den_ausnahmetyp_ohne_meldungstext_und_adresse(self):
        m, ids = self.start(1)
        self.smtp_einrichten(m)
        newsletter.testliste_setzen(m, ["a@beispiel.de"])
        e = newsletter.anlegen(m, "Betreff", "Text", "testliste", None)

        class Kaputt(FalscherSmtp):
            def login(self, *a):
                raise mailer.smtplib.SMTPAuthenticationError(535, b"geheimer-servertext")
        with mock.patch.object(mailer.smtplib, "SMTP", Kaputt):
            with self.assertRaises(newsletter.Fehler) as ctx:
                newsletter.testmail(mandanten.lesen(m["id"]), e["id"])
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("versand_nicht_moeglich", 409))
        self.assertIn("(SMTPAuthenticationError)", ctx.exception.meldung)
        for nie in ("geheimer-servertext", "535", "a@beispiel.de", "geheim-test"):
            self.assertNotIn(nie, ctx.exception.meldung)

    def test_teilweise_meldung_und_grund_je_adresse(self):
        m, ids = self.start(1)
        self.smtp_einrichten(m)
        newsletter.testliste_setzen(m, ["a@beispiel.de", "kaputt@beispiel.de"])
        e = newsletter.anlegen(m, "Betreff", "Text", "testliste", None)

        class Halb(FalscherSmtp):
            def send_message(self, nachricht, *a, **k):
                if nachricht["To"].startswith("kaputt"):
                    raise mailer.smtplib.SMTPDataError(554, b"Inhalt abgelehnt")
                super().send_message(nachricht)
        with mock.patch.object(mailer.smtplib, "SMTP", Halb):
            r = newsletter.testmail(mandanten.lesen(m["id"]), e["id"])
        self.assertEqual((r["status"], r["gesendet"], r["fehler"]), ("teilweise", 1, 1))
        self.assertEqual([(x["adresse"], x["ergebnis"], x.get("grund")) for x in r["ergebnisse"]],
                         [("a@beispiel.de", "gesendet", None), ("kaputt@beispiel.de", "fehler", "SMTPDataError")])
        self.assertIn("1 von 2", r["meldung"])
        self.assertIn("SMTPDataError", r["meldung"])
        self.assertNotIn("Inhalt abgelehnt", r["meldung"])
        self.assertNotIn("beispiel.de", r["meldung"])

    def test_ohne_fehler_keine_meldung(self):
        m, ids = self.start(1)
        self.smtp_einrichten(m)
        newsletter.testliste_setzen(m, ["a@beispiel.de"])
        e = newsletter.anlegen(m, "Betreff", "Text", "testliste", None)
        self.assertNotIn("meldung", self.lauf(m, e["id"]))

    def test_fehlertyp_wird_je_aufruf_zurueckgesetzt(self):
        m, ids = self.start(1)
        self.smtp_einrichten(m)

        class Kaputt(FalscherSmtp):
            def login(self, *a):
                raise TimeoutError("x")
        with mock.patch.object(mailer.smtplib, "SMTP", Kaputt):
            self.assertEqual(mailer.senden(mandanten.lesen(m["id"]), "a@beispiel.de", "B", "T", "<p>T</p>"), "fehler")
        self.assertEqual(mailer.letzter_fehlertyp(), "TimeoutError")
        with mock.patch.object(mailer.smtplib, "SMTP", FalscherSmtp):
            self.assertEqual(mailer.senden(mandanten.lesen(m["id"]), "a@beispiel.de", "B", "T", "<p>T</p>"), "gesendet")
        self.assertIsNone(mailer.letzter_fehlertyp())

    def test_ohne_bekannten_typ_bleibt_grund_fehler(self):
        m, ids = self.start(1)
        newsletter.testliste_setzen(m, ["a@beispiel.de", "b@beispiel.de"])
        e = newsletter.anlegen(m, "Betreff", "Text", "testliste", None)
        antworten = iter(["gesendet", "fehler"])
        with mock.patch.object(mailer, "senden", side_effect=lambda *a, **k: next(antworten)), mock.patch.object(mailer, "letzter_fehlertyp", return_value=None):
            r = newsletter.testmail(mandanten.lesen(m["id"]), e["id"])
        self.assertEqual(r["ergebnisse"][1]["grund"], "fehler")
        self.assertIn("(fehler)", r["meldung"])


class TestFehlerKurz(Basis):
    """Diagnose (v0.8.1-Stand, catrin #19155): bei Betriebssystemfehlern nennt die Meldung errno und Systemtext, nie Servertext, Adresse oder Pfad."""

    def kurz(self, exc):
        return mailer.fehler_kurz(exc)

    def test_betriebssystemfehler_mit_errno_und_systemtext(self):
        self.assertEqual(self.kurz(OSError(101, "Network is unreachable")), "OSError[Errno 101: Network is unreachable]")
        self.assertEqual(self.kurz(OSError(113, "No route to host")), "OSError[Errno 113: No route to host]")
        self.assertEqual(self.kurz(OSError(24, "Too many open files")), "OSError[Errno 24: Too many open files]")
        self.assertEqual(self.kurz(ConnectionRefusedError(111, "Connection refused")), "ConnectionRefusedError[Errno 111: Connection refused]")
        self.assertEqual(self.kurz(mailer.smtplib.socket.gaierror(-2, "Name or service not known")), "gaierror[Errno -2: Name or service not known]")

    def test_smtp_und_tls_fehler_nur_mit_namen(self):
        self.assertEqual(self.kurz(mailer.smtplib.SMTPAuthenticationError(535, b"geheimer-servertext")), "SMTPAuthenticationError")
        self.assertEqual(self.kurz(mailer.smtplib.SMTPServerDisconnected("x")), "SMTPServerDisconnected")
        self.assertEqual(self.kurz(mailer.ssl.SSLError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate for geheim.example")), "SSLError")
        self.assertEqual(self.kurz(mailer.ssl.SSLCertVerificationError(1, "Hostname mismatch geheim.example")), "SSLCertVerificationError")

    def test_ohne_errno_oder_kein_oserror_nur_name(self):
        self.assertEqual(self.kurz(TimeoutError("x")), "TimeoutError")
        self.assertEqual(self.kurz(OSError("nur text")), "OSError")
        self.assertEqual(self.kurz(ValueError("x")), "ValueError")

    def test_kein_pfad_keine_adresse_kein_steuerzeichen_und_begrenzt(self):
        k = self.kurz(FileNotFoundError(2, "No such file or directory", "/data/geheim/a@beispiel.de"))
        self.assertEqual(k, "FileNotFoundError[Errno 2: No such file or directory]")
        self.assertNotIn("/data", k)
        self.assertNotIn("@", k)
        self.assertLessEqual(len(self.kurz(OSError(5, "x" * 500))), len("OSError[Errno 5: ]") + 80)
        self.assertEqual(self.kurz(OSError(5, "a\nb\x00c")), "OSError[Errno 5: abc]")                   # Steuerzeichen raus

    def test_in_der_testmail_antwort_und_im_log(self):
        m, ids = self.start(1)
        mandanten.versand_setzen(m["id"], {"versandmodus": "smtp", "smtp_host": "smtp.beispiel.test", "smtp_port": 587, "smtp_benutzer": "news@hilo.test",
                                           "smtp_passwort": "geheim-test", "smtp_verschluesselung": "starttls"}, "test")
        newsletter.testliste_setzen(m, ["a@beispiel.de", "b@beispiel.de"])
        e = newsletter.anlegen(m, "Betreff", "Text", "testliste", None)

        class Netz(FalscherSmtp):
            def __init__(self, *a, **k):
                raise OSError(101, "Network is unreachable")
        with mock.patch.object(mailer.smtplib, "SMTP", Netz), self.assertLogs(mailer.LOG, level="WARNING") as log:
            with self.assertRaises(newsletter.Fehler) as ctx:
                newsletter.testmail(mandanten.lesen(m["id"]), e["id"])
        self.assertIn("(OSError[Errno 101: Network is unreachable])", ctx.exception.meldung)
        self.assertEqual(ctx.exception.status, 409)
        self.assertTrue(any("OSError[Errno 101: Network is unreachable]" in z for z in log.output))
        for nie in ("a@beispiel.de", "geheim-test", "smtp.beispiel.test"):
            self.assertNotIn(nie, ctx.exception.meldung)
            self.assertFalse(any(nie in z for z in log.output), nie)


if __name__ == "__main__":
    unittest.main()
