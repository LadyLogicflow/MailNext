"""Meilenstein A: Mandanten mit eigenem Design, Anmelden (Double-Opt-in), Bestätigen, Abmelden, Präferenzen, Betreiber-Verwaltung.

Jede Schutzregel hat eine Gegenprobe (der Normalfall funktioniert) und ist so geschrieben, dass sie rot wird, wenn die Regel entfernt wird."""
import email
import email.policy
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import abonnenten
import betreiber_auth
import config
import db
import mailer
import mandanten
import public
import schluessel
from app import create_app

SCHLUESSEL = "t" * 40
EINWILLIGUNG = "Ja, ich möchte den Newsletter per E-Mail erhalten und kann jederzeit widerrufen."
ROLLEN = [{"wert": "verein", "label": "Verein"}, {"wert": "beratungsstelle", "label": "Beratungsstelle"}]
INTERESSEN = [{"wert": "sortnext", "label": "SortNext"}, {"wert": "booknext", "label": "BookNext"}]


class Basis(unittest.TestCase):
    def setUp(self):
        self.verz = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"MAILNEXT_HAUPTSCHLUESSEL": SCHLUESSEL, "MAILNEXT_DATEN": self.verz.name,
                                                "MAILNEXT_BASIS_URL": "https://mailnext.test", "MAILNEXT_PROXIES": "1"})
        self.env.start()
        self.app = create_app(os.path.join(self.verz.name, "t.db"))
        self.c = self.app.test_client()
        betreiber_auth.cache_leeren()

    def tearDown(self):
        self.env.stop()
        self.verz.cleanup()

    def mandant(self, slug="hilo", name="HILO e. V.", modus="datei", **design):
        d = {"absender_name": name, "absender_adresse": "news@%s.test" % slug, "rollen": ROLLEN, "interessen": INTERESSEN,
             "impressum_url": "https://%s.test/impressum" % slug, "datenschutz_url": "https://%s.test/datenschutz" % slug,
             "firmenangaben": "%s, Musterstraße 1, 12345 Musterstadt" % name}
        d.update(design)
        m = mandanten.anlegen(slug, name, d, "test")
        mandanten.einwilligung_anlegen(m["id"], "EINW-1", EINWILLIGUNG)
        mandanten.versand_setzen(m["id"], {"versandmodus": modus}, "test")
        return mandanten.lesen(m["id"])

    def anmelden(self, slug, adresse, **extra):
        daten = {"email": adresse, "einwilligungs_version": "EINW-1"}
        daten.update(extra)
        return self.c.post("/api/%s/newsletter/anmelden" % slug, json=daten)

    def mails(self, slug):
        verz = config.ausgang_verzeichnis() / slug
        return sorted(verz.glob("*.eml")) if verz.exists() else []

    def letzte_mail(self, slug):
        dateien = self.mails(slug)
        self.assertTrue(dateien, "keine Mail im Ausgang")
        return email.message_from_bytes(dateien[-1].read_bytes(), policy=email.policy.default)

    def bestaetigungslink(self, slug):
        text = self.letzte_mail(slug).get_body(("plain",)).get_content()
        treffer = re.search(r"https://mailnext\.test/%s/newsletter/bestaetigen/([A-Za-z0-9_-]+)" % slug, text)
        self.assertIsNotNone(treffer, text)
        return treffer.group(1)

    def zeile(self, mandant_id, adresse):
        with db.verbindung() as c:
            return c.execute("SELECT * FROM abonnent WHERE mandant_id=? AND email_hmac=?",
                             (mandant_id, schluessel.email_hmac(mandant_id, adresse))).fetchone()

    def anmelden_und_bestaetigen(self, m, adresse):
        self.assertEqual(self.anmelden(m["slug"], adresse).status_code, 200)
        token = self.bestaetigungslink(m["slug"])
        self.assertEqual(self.c.post("/%s/newsletter/bestaetigen/%s" % (m["slug"], token)).status_code, 200)
        return token

    def pers_token(self, m, adresse):
        return abonnenten.persoenliches_token(self.zeile(m["id"], adresse))


class MandantenTests(Basis):
    def test_beliebig_viele_mandanten_mit_eigenem_design(self):
        a = self.mandant("hilo", "HILO", farbe_primaer="#112233")
        b = self.mandant("bstnext", "BSt Next", farbe_primaer="#445566", schrift="serif")
        c = self.mandant("dritter", "Dritter e. V.")
        self.assertEqual([m["slug"] for m in mandanten.alle()], ["hilo", "bstnext", "dritter"])
        self.assertEqual(a["design"]["farbe_primaer"], "#112233")
        self.assertEqual(b["design"]["farbe_primaer"], "#445566")
        self.assertEqual(c["design"]["farbe_primaer"], mandanten.STANDARD_DESIGN["farbe_primaer"])

    def test_design_wird_geprueft(self):
        schlecht = [{"farbe_primaer": "rot"}, {"farbe_text": "#12345"}, {"schrift": "comic"}, {"logo_url": "http://x.test/l.png"},
                    {"logo_url": "https://x.test/a b.png"}, {"absender_adresse": "kein-at"}, {"unbekannt": 1},
                    {"rollen": [{"wert": "GROSS", "label": "X"}]}, {"rollen": [{"wert": "a", "label": "A"}, {"wert": "a", "label": "B"}]},
                    {"cors_ursprunge": ["http://x.test"]}, {"firmenangaben": "x" * 1001}]
        for d in schlecht:
            with self.assertRaises(mandanten.Ungueltig, msg=str(d)):
                mandanten.anlegen("x%d" % len(str(d)), "X", d, "t")

    def test_slug_regeln_und_eindeutigkeit(self):
        for s in ("a", "mit leer", "ä-x", "x" * 40, "-x", "a_b"):
            with self.assertRaises(mandanten.Ungueltig, msg=s):
                mandanten.anlegen(s, "X", {}, "t")
        self.assertEqual(mandanten.anlegen("Ok-1", "X", {}, "t")["slug"], "ok-1")             # Großbuchstaben werden klein geschrieben
        with self.assertRaises(mandanten.Ungueltig):
            mandanten.anlegen("ok-1", "Y", {}, "t")

    def test_einwilligungstexte_je_mandant_und_unveraenderlich(self):
        a, b = self.mandant("a1"), self.mandant("b1")
        mandanten.einwilligung_anlegen(b["id"], "NUR-B", "Ein ganz anderer Text für den zweiten Mandanten, lang genug.")
        self.assertTrue(mandanten.einwilligung_vorhanden(b["id"], "NUR-B"))
        self.assertFalse(mandanten.einwilligung_vorhanden(a["id"], "NUR-B"))
        with self.assertRaises(mandanten.Ungueltig):
            mandanten.einwilligung_anlegen(a["id"], "EINW-1", "Neuer Text unter alter Version, lang genug zum Überschreiben.")
        with self.assertRaises(mandanten.Ungueltig):
            mandanten.einwilligung_anlegen(a["id"], "V2", "Erste Zeile lang genug\nzweite Zeile")
        self.assertEqual(mandanten.einwilligungen(a["id"])[0]["text"], EINWILLIGUNG)

    def test_versand_standard_ist_aus(self):
        m = mandanten.anlegen("still", "Still", {"absender_adresse": "x@still.test"}, "t")
        self.assertEqual(mandanten.versandmodus(m["id"]), "aus")

    def test_smtp_nur_mit_vollstaendiger_konfiguration(self):
        m = self.mandant("s1", modus="aus")
        with self.assertRaises(mandanten.Ungueltig):
            mandanten.versand_setzen(m["id"], {"versandmodus": "smtp"}, "t")
        mandanten.versand_setzen(m["id"], {"smtp_host": "smtp.test", "smtp_port": 465, "smtp_benutzer": "u", "smtp_passwort": "geheim-xyz",
                                           "smtp_verschluesselung": "ssl", "versandmodus": "smtp"}, "t")
        self.assertEqual(mandanten.versandmodus(m["id"]), "smtp")
        self.assertNotIn("geheim-xyz", json.dumps(mandanten.versand_zustand(m["id"])))

    def test_zugangsdaten_liegen_verschluesselt_und_je_mandant(self):
        a, b = self.mandant("a2", modus="aus"), self.mandant("b2", modus="aus")
        mandanten.versand_setzen(a["id"], {"smtp_passwort": "nur-fuer-a-12345"}, "t")
        with db.verbindung() as c:
            alle = " ".join(z["wert_verschluesselt"] for z in c.execute("SELECT wert_verschluesselt FROM einstellung").fetchall())
        self.assertNotIn("nur-fuer-a-12345", alle)
        self.assertEqual(mandanten.versand_lesen(a["id"])["smtp_passwort"], "nur-fuer-a-12345")
        self.assertIsNone(mandanten.versand_lesen(b["id"])["smtp_passwort"])


class AnmeldenTests(Basis):
    def test_formular_liefert_text_und_auswahl(self):
        self.mandant("hilo")
        d = self.c.get("/api/hilo/newsletter/formular").get_json()
        self.assertEqual((d["einwilligungs_version"], d["einwilligungs_text"]), ("EINW-1", EINWILLIGUNG))
        self.assertEqual([r["wert"] for r in d["rollen"]], ["verein", "beratungsstelle"])

    def test_normalfall_legt_unbestaetigt_an_und_sendet_bestaetigungsmail_im_design(self):
        m = self.mandant("hilo", "HILO e. V.", farbe_primaer="#0a0b0c", logo_url="https://hilo.test/logo.png")
        r = self.anmelden("hilo", "Anna@Beispiel.DE", rolle="verein", interessen=["sortnext"])
        self.assertEqual((r.status_code, r.get_json()), (200, {"status": "ok"}))
        z = self.zeile(m["id"], "anna@beispiel.de")
        self.assertEqual((z["status"], z["rolle"], z["einwilligung_version"], z["email"]), ("unbestaetigt", "verein", "EINW-1", "anna@beispiel.de"))
        self.assertEqual(json.loads(z["interessen"]), ["sortnext"])
        self.assertNotEqual(z["token_hash"], None)
        mail = self.letzte_mail("hilo")
        self.assertEqual(mail["To"], "anna@beispiel.de")
        self.assertIn("news@hilo.test", mail["From"])
        self.assertIn("HILO e. V.", mail["Subject"])
        html = mail.get_body(("html",)).get_content()
        self.assertIn("#0a0b0c", html)                                              # Design des Mandanten
        self.assertIn("https://hilo.test/logo.png", html)
        self.assertIn("https://hilo.test/impressum", html)
        self.assertNotIn("<img src=\"https://mailnext.test", html)                  # kein Tracking-Pixel
        self.assertNotIn("1x1", html)
        token = self.bestaetigungslink("hilo")
        self.assertEqual(schluessel.token_hash(token), z["token_hash"])
        self.assertNotIn(token, json.dumps(dict(z)))                                # in der Datenbank nur der Hash

    def test_immer_200_und_nichts_wird_verraten(self):
        m = self.mandant("hilo")
        for adresse in ("keine-adresse", "", "a@b", "x" * 300 + "@y.de"):
            self.assertEqual(self.anmelden("hilo", adresse).get_json(), {"status": "ok"})
        self.assertEqual(self.mails("hilo"), [])
        self.anmelden_und_bestaetigen(m, "fest@beispiel.de")
        anzahl = len(self.mails("hilo"))
        self.assertEqual(self.anmelden("hilo", "fest@beispiel.de").get_json(), {"status": "ok"})   # schon bestätigt: gleiche Antwort, keine Mail
        self.assertEqual(len(self.mails("hilo")), anzahl)

    def test_formfehler_sind_400_ohne_adressinfo(self):
        self.mandant("hilo")
        fall = [({"email": "a@b.de", "einwilligungs_version": "UNBEKANNT"}, "version_unbekannt"),
                ({"email": "a@b.de"}, "version_unbekannt"),
                ({"email": "a@b.de", "einwilligungs_version": "EINW-1", "rolle": "chef"}, "feld_ungueltig"),
                ({"email": "a@b.de", "einwilligungs_version": "EINW-1", "interessen": ["nix"]}, "feld_ungueltig"),
                ({"email": "a@b.de", "einwilligungs_version": "EINW-1", "interessen": "sortnext"}, "feld_ungueltig"),
                ({"email": 5, "einwilligungs_version": "EINW-1"}, "feld_ungueltig")]
        for daten, code in fall:
            r = self.c.post("/api/hilo/newsletter/anmelden", json=daten)
            self.assertEqual((r.status_code, r.get_json()["error"]), (400, code), daten)
        self.assertEqual(self.c.post("/api/hilo/newsletter/anmelden", data="kein json", content_type="application/json").status_code, 400)
        self.assertEqual(self.c.post("/api/hilo/newsletter/anmelden", json=[1]).get_json()["error"], "json_ungueltig")
        self.assertEqual(self.mails("hilo"), [])

    def test_unbekannter_oder_ruhender_mandant_404(self):
        m = self.mandant("hilo")
        self.assertEqual(self.anmelden("gibtsnicht", "a@b.de").status_code, 404)
        mandanten.aendern(m["id"], aktiv=False)
        self.assertEqual(self.anmelden("hilo", "a@b.de").status_code, 404)
        self.assertEqual(self.c.get("/api/hilo/newsletter/formular").status_code, 404)

    def test_modus_aus_sendet_nichts_speichert_aber(self):
        m = self.mandant("hilo", modus="aus")
        self.anmelden("hilo", "a@beispiel.de")
        self.assertEqual(self.mails("hilo"), [])
        self.assertEqual(self.zeile(m["id"], "a@beispiel.de")["status"], "unbestaetigt")

    def test_drosselung_je_adresse_und_je_ip_still(self):
        m = self.mandant("hilo")
        for _ in range(5):
            self.assertEqual(self.anmelden("hilo", "viel@beispiel.de").status_code, 200)
        self.assertEqual(len(self.mails("hilo")), abonnenten.MAX_MAILS_JE_ADRESSE_24H)
        n = len(self.mails("hilo"))
        for i in range(25):
            self.anmelden("hilo", "ip%d@beispiel.de" % i)
        self.assertEqual(len(self.mails("hilo")) - n, abonnenten.MAX_MAILS_JE_IP_STUNDE - n)

    def test_ip_aus_proxy_kopf_nicht_faelschbar(self):
        with self.app.test_request_context("/", headers={"X-Forwarded-For": "6.6.6.6, 1.2.3.4"}, environ_base={"REMOTE_ADDR": "10.0.0.1"}):
            self.assertEqual(public.client_ip(), "1.2.3.4")                         # ein vorgeschalteter Proxy: der rechte Eintrag zählt
        with mock.patch.dict(os.environ, {"MAILNEXT_PROXIES": "0"}):
            with self.app.test_request_context("/", headers={"X-Forwarded-For": "6.6.6.6"}, environ_base={"REMOTE_ADDR": "10.0.0.1"}):
                self.assertEqual(public.client_ip(), "10.0.0.1")

    def test_erneute_anmeldung_unbestaetigt_ersetzt_token(self):
        m = self.mandant("hilo")
        self.anmelden("hilo", "zwei@beispiel.de")
        alt = self.bestaetigungslink("hilo")
        self.anmelden("hilo", "zwei@beispiel.de", rolle="verein")
        neu = self.bestaetigungslink("hilo")
        self.assertNotEqual(alt, neu)
        self.assertEqual(self.c.post("/hilo/newsletter/bestaetigen/" + alt).status_code, 400)
        self.assertEqual(self.c.post("/hilo/newsletter/bestaetigen/" + neu).status_code, 200)
        self.assertEqual(self.zeile(m["id"], "zwei@beispiel.de")["rolle"], "verein")

    def test_mailfehler_stoert_die_anmeldung_nicht(self):
        m = self.mandant("hilo")
        with mock.patch.object(mailer, "senden", side_effect=RuntimeError("smtp kaputt")):
            with self.assertRaises(RuntimeError):
                abonnenten.anmelden(m, "x@beispiel.de", None, [], "EINW-1", "1.1.1.1")
        mandanten.versand_setzen(m["id"], {"versandmodus": "smtp"}, "t") if False else None
        with mock.patch("mailer.smtplib.SMTP_SSL", side_effect=OSError("down")):
            mandanten.versand_setzen(m["id"], {"smtp_host": "h.test", "smtp_port": 465, "smtp_benutzer": "u", "smtp_passwort": "p-xyz-123",
                                               "smtp_verschluesselung": "ssl", "versandmodus": "smtp"}, "t")
            r = self.anmelden("hilo", "y@beispiel.de")
        self.assertEqual(r.status_code, 200)                                        # SMTP-Fehler: weiter 200, nur ein Log-Eintrag


class BestaetigenTests(Basis):
    def test_get_aendert_nichts_post_bestaetigt_mehrfach_ok(self):
        m = self.mandant("hilo")
        self.anmelden("hilo", "a@beispiel.de")
        token = self.bestaetigungslink("hilo")
        r = self.c.get("/hilo/newsletter/bestaetigen/" + token)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.zeile(m["id"], "a@beispiel.de")["status"], "unbestaetigt")      # GET (Mail-Scanner) bestätigt nie
        self.assertEqual(self.c.post("/hilo/newsletter/bestaetigen/" + token).status_code, 200)
        z = self.zeile(m["id"], "a@beispiel.de")
        self.assertEqual(z["status"], "bestaetigt")
        self.assertIsNotNone(z["bestaetigt_am"])
        self.assertEqual(self.c.post("/hilo/newsletter/bestaetigen/" + token).status_code, 200)   # erneuter Klick

    def test_json_variante(self):
        self.mandant("hilo")
        self.anmelden("hilo", "a@beispiel.de")
        token = self.bestaetigungslink("hilo")
        r = self.c.post("/api/hilo/newsletter/bestaetigen", json={"token": token})
        self.assertEqual((r.status_code, r.get_json()), (200, {"status": "bestaetigt"}))
        self.assertEqual(self.c.post("/api/hilo/newsletter/bestaetigen", json={"token": "falsch"}).get_json()["error"], "token_ungueltig")

    def test_abgelaufener_token_410(self):
        m = self.mandant("hilo")
        self.anmelden("hilo", "a@beispiel.de")
        token = self.bestaetigungslink("hilo")
        with db.verbindung() as c:
            c.execute("UPDATE abonnent SET token_ablauf=? WHERE mandant_id=?", ((datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), m["id"]))
        self.assertEqual(self.c.post("/api/hilo/newsletter/bestaetigen", json={"token": token}).status_code, 410)
        self.assertEqual(self.c.post("/hilo/newsletter/bestaetigen/" + token).status_code, 410)
        self.assertEqual(self.zeile(m["id"], "a@beispiel.de")["status"], "unbestaetigt")

    def test_token_gilt_nur_im_eigenen_mandanten(self):
        a, b = self.mandant("a3"), self.mandant("b3")
        self.anmelden("a3", "x@beispiel.de")
        token = self.bestaetigungslink("a3")
        self.assertEqual(self.c.post("/b3/newsletter/bestaetigen/" + token).status_code, 400)
        self.assertEqual(self.zeile(a["id"], "x@beispiel.de")["status"], "unbestaetigt")

    def test_unbestaetigte_und_abgemeldete_tokens_funktionieren_nicht_wieder(self):
        m = self.mandant("hilo")
        token = self.anmelden_und_bestaetigen(m, "a@beispiel.de")
        abonnenten.abmelden(self.pers_token(m, "a@beispiel.de"))
        self.assertEqual(self.c.post("/hilo/newsletter/bestaetigen/" + token).status_code, 400)
        self.assertEqual(self.zeile(m["id"], "a@beispiel.de")["status"], "abgemeldet")


class AbmeldenTests(Basis):
    def test_abmelden_ersetzt_durch_minimaldatensatz(self):
        m = self.mandant("hilo")
        self.anmelden("hilo", "weg@beispiel.de", rolle="verein", interessen=["sortnext"])
        self.c.post("/hilo/newsletter/bestaetigen/" + self.bestaetigungslink("hilo"))
        t = self.pers_token(m, "weg@beispiel.de")
        r = self.c.post("/api/hilo/newsletter/abmelden", json={"t": t})
        self.assertEqual((r.status_code, r.get_json()), (200, {"status": "abgemeldet"}))
        z = self.zeile(m["id"], "weg@beispiel.de")
        self.assertEqual(z["status"], "abgemeldet")
        for feld in ("email", "rolle", "interessen", "einwilligung_version", "ip", "token_hash", "token_ablauf", "bestaetigt_am"):
            self.assertIsNone(z[feld], feld)
        self.assertEqual(z["email_hmac"], schluessel.email_hmac(m["id"], "weg@beispiel.de"))      # Pseudonym bleibt (Sperrliste)
        self.assertIsNotNone(z["angemeldet_am"])
        self.assertIsNotNone(z["abgemeldet_am"])
        with db.verbindung() as c:
            inhalt = json.dumps([tuple(x) for x in c.execute("SELECT * FROM abonnent").fetchall()])
        self.assertNotIn("weg@beispiel.de", inhalt)

    def test_idempotent(self):
        m = self.mandant("hilo")
        self.anmelden_und_bestaetigen(m, "a@beispiel.de")
        t = self.pers_token(m, "a@beispiel.de")
        for _ in range(2):
            self.assertEqual(self.c.post("/api/hilo/newsletter/abmelden", json={"t": t}).status_code, 200)

    def test_alter_aufruf_nur_mit_email_loescht_nichts(self):
        m = self.mandant("hilo")
        self.anmelden_und_bestaetigen(m, "a@beispiel.de")
        r = self.c.post("/api/hilo/newsletter/abmelden", json={"email": "a@beispiel.de"})
        self.assertEqual((r.status_code, r.get_json()["error"]), (400, "token_erforderlich"))
        self.assertEqual(self.zeile(m["id"], "a@beispiel.de")["status"], "bestaetigt")

    def test_gefaelschte_und_fremde_tokens(self):
        a, b = self.mandant("a4"), self.mandant("b4")
        self.anmelden_und_bestaetigen(a, "x@beispiel.de")
        t = self.pers_token(a, "x@beispiel.de")
        for schlecht in ("", "u1.abc.def", t[:-3] + "xxx", "u1." + t.split(".")[1] + "." + "A" * 43, "irgendwas"):
            self.assertEqual(self.c.post("/api/a4/newsletter/abmelden", json={"t": schlecht}).status_code, 400, schlecht)
        self.assertEqual(self.c.post("/api/b4/newsletter/abmelden", json={"t": t}).status_code, 400)     # Token aus Mandant A in Mandant B
        self.assertEqual(self.zeile(a["id"], "x@beispiel.de")["status"], "bestaetigt")

    def test_token_mit_umgeschriebenem_mandanten_wird_abgelehnt(self):
        a, b = self.mandant("a5"), self.mandant("b5")
        self.anmelden_und_bestaetigen(a, "x@beispiel.de")
        self.anmelden_und_bestaetigen(b, "x@beispiel.de")
        za = self.zeile(a["id"], "x@beispiel.de")
        falsch = schluessel.persoenliches_token(b["id"], za["id"], za["nonce"])                        # gültig signiert, aber Abonnent gehört zu A
        self.assertIsNone(abonnenten._per_token(falsch))

    def test_one_click_post_ja_get_nein(self):
        m = self.mandant("hilo")
        self.anmelden_und_bestaetigen(m, "a@beispiel.de")
        t = self.pers_token(m, "a@beispiel.de")
        for methode in ("get", "put", "delete"):
            r = getattr(self.c, methode)("/hilo/newsletter/abmelden-one-click/" + t)
            self.assertEqual(r.status_code, 405, methode)
        self.assertEqual(self.zeile(m["id"], "a@beispiel.de")["status"], "bestaetigt")
        self.assertEqual(self.c.post("/hilo/newsletter/abmelden-one-click/" + t, data="List-Unsubscribe=One-Click").status_code, 200)
        self.assertEqual(self.zeile(m["id"], "a@beispiel.de")["status"], "abgemeldet")
        self.assertEqual(self.c.post("/hilo/newsletter/abmelden-one-click/ungueltig").status_code, 400)

    def test_abmelden_geht_auch_bei_stillgelegtem_mandanten(self):
        m = self.mandant("hilo")
        self.anmelden_und_bestaetigen(m, "a@beispiel.de")
        t = self.pers_token(m, "a@beispiel.de")
        mandanten.aendern(m["id"], aktiv=False)
        self.assertEqual(self.c.post("/api/hilo/newsletter/abmelden", json={"t": t}).status_code, 200)

    def test_neuanmeldung_nach_abmeldung_mit_neuer_einwilligung(self):
        m = self.mandant("hilo")
        self.anmelden_und_bestaetigen(m, "a@beispiel.de")
        alt = self.pers_token(m, "a@beispiel.de")
        abonnenten.abmelden(alt)
        self.anmelden("hilo", "a@beispiel.de", rolle="verein")
        z = self.zeile(m["id"], "a@beispiel.de")
        self.assertEqual((z["status"], z["rolle"], z["email"], z["abgemeldet_am"]), ("unbestaetigt", "verein", "a@beispiel.de", None))
        self.assertEqual(self.c.post("/api/hilo/newsletter/abmelden", json={"t": alt}).status_code, 400)   # altes Token ist ungültig

    def test_seite_get_zeigt_formular_post_abmelden_meldet_ab(self):
        m = self.mandant("hilo")
        self.anmelden_und_bestaetigen(m, "a@beispiel.de")
        t = self.pers_token(m, "a@beispiel.de")
        seite = self.c.get("/hilo/newsletter/einstellungen?t=" + t)
        self.assertEqual(seite.status_code, 200)
        self.assertIn("a***@beispiel.de", seite.get_data(as_text=True))
        self.assertEqual(self.zeile(m["id"], "a@beispiel.de")["status"], "bestaetigt")
        r = self.c.post("/hilo/newsletter/einstellungen?t=" + t, data={"aktion": "abmelden"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.zeile(m["id"], "a@beispiel.de")["status"], "abgemeldet")


class PraeferenzenTests(Basis):
    def test_lesen_maskiert_setzen_pruefen_und_abgemeldet_409(self):
        m = self.mandant("hilo")
        self.anmelden_und_bestaetigen(m, "anna@beispiel.de")
        t = self.pers_token(m, "anna@beispiel.de")
        d = self.c.get("/api/hilo/newsletter/praeferenzen?t=" + t).get_json()
        self.assertEqual((d["email_maskiert"], d["status"]), ("a***@beispiel.de", "bestaetigt"))
        self.assertNotIn("anna@beispiel.de", json.dumps(d))
        r = self.c.post("/api/hilo/newsletter/praeferenzen", json={"t": t, "rolle": "beratungsstelle", "interessen": ["booknext", "sortnext"]})
        self.assertEqual(r.status_code, 200)
        z = self.zeile(m["id"], "anna@beispiel.de")
        self.assertEqual((z["rolle"], json.loads(z["interessen"])), ("beratungsstelle", ["booknext", "sortnext"]))
        self.assertEqual(self.c.post("/api/hilo/newsletter/praeferenzen", json={"t": t, "rolle": "chef"}).get_json()["error"], "feld_ungueltig")
        self.assertEqual(self.c.get("/api/hilo/newsletter/praeferenzen?t=falsch").status_code, 400)
        abonnenten.abmelden(t)
        self.assertEqual(self.c.post("/api/hilo/newsletter/praeferenzen", json={"t": t, "rolle": "verein"}).status_code, 409)

    def test_seite_setzt_auswahl(self):
        m = self.mandant("hilo")
        self.anmelden_und_bestaetigen(m, "a@beispiel.de")
        t = self.pers_token(m, "a@beispiel.de")
        r = self.c.post("/hilo/newsletter/einstellungen?t=" + t, data={"aktion": "speichern", "rolle": "verein", "interessen": ["sortnext"]})
        self.assertEqual(r.status_code, 200)
        z = self.zeile(m["id"], "a@beispiel.de")
        self.assertEqual((z["rolle"], json.loads(z["interessen"])), ("verein", ["sortnext"]))
        self.assertEqual(self.c.post("/hilo/newsletter/einstellungen?t=" + t, data={"aktion": "speichern", "rolle": "chef"}).status_code, 400)


class MandantentrennungTests(Basis):
    def test_gleiche_adresse_in_zwei_mandanten_getrennt(self):
        a, b = self.mandant("a6"), self.mandant("b6")
        self.anmelden_und_bestaetigen(a, "gleich@beispiel.de")
        self.anmelden("b6", "gleich@beispiel.de")
        za, zb = self.zeile(a["id"], "gleich@beispiel.de"), self.zeile(b["id"], "gleich@beispiel.de")
        self.assertNotEqual(za["email_hmac"], zb["email_hmac"])                      # kein gemeinsames Pseudonym
        self.assertEqual((za["status"], zb["status"]), ("bestaetigt", "unbestaetigt"))
        abonnenten.abmelden(abonnenten.persoenliches_token(za))
        self.assertEqual(self.zeile(a["id"], "gleich@beispiel.de")["status"], "abgemeldet")
        self.assertEqual(self.zeile(b["id"], "gleich@beispiel.de")["status"], "unbestaetigt")

    def test_abonnentenlisten_und_kennzahlen_je_mandant(self):
        a, b = self.mandant("a7"), self.mandant("b7")
        self.anmelden_und_bestaetigen(a, "nur-a@beispiel.de")
        self.anmelden_und_bestaetigen(b, "nur-b@beispiel.de")
        self.anmelden("b7", "offen-b@beispiel.de")
        self.assertEqual([x["email"] for x in abonnenten.liste(a["id"])], ["nur-a@beispiel.de"])
        self.assertEqual(sorted(x["email"] for x in abonnenten.liste(b["id"])), ["nur-b@beispiel.de", "offen-b@beispiel.de"])
        self.assertEqual(abonnenten.kennzahlen(a["id"])["bestaetigt"], 1)
        self.assertEqual(abonnenten.kennzahlen(b)["unbestaetigt"] if False else abonnenten.kennzahlen(b["id"])["unbestaetigt"], 1)

    def test_drosselung_zaehlt_je_mandant(self):
        a, b = self.mandant("a8"), self.mandant("b8")
        for _ in range(4):
            self.anmelden("a8", "viel@beispiel.de")
        self.anmelden("b8", "viel@beispiel.de")
        self.assertEqual(len(self.mails("a8")), 3)
        self.assertEqual(len(self.mails("b8")), 1)

    def test_versandeinstellungen_je_mandant(self):
        a, b = self.mandant("a9", modus="datei"), self.mandant("b9", modus="aus")
        self.anmelden("a9", "x@beispiel.de")
        self.anmelden("b9", "x@beispiel.de")
        self.assertEqual((len(self.mails("a9")), len(self.mails("b9"))), (1, 0))

    def test_hmac_schluessel_haengen_vom_hauptschluessel_ab(self):
        m = self.mandant("hilo")
        h1 = schluessel.email_hmac(m["id"], "a@beispiel.de")
        with mock.patch.dict(os.environ, {"MAILNEXT_HAUPTSCHLUESSEL": "x" * 40}):
            self.assertNotEqual(h1, schluessel.email_hmac(m["id"], "a@beispiel.de"))


class SeitenSicherheitTests(Basis):
    def test_kopfzeilen_noindex_csp_referrer(self):
        m = self.mandant("hilo")
        self.anmelden_und_bestaetigen(m, "a@beispiel.de")
        for pfad in ("/hilo/newsletter/bestaetigen/x", "/hilo/newsletter/einstellungen?t=" + self.pers_token(m, "a@beispiel.de")):
            r = self.c.get(pfad)
            self.assertIn("noindex", r.headers["X-Robots-Tag"], pfad)
            self.assertEqual(r.headers["Referrer-Policy"], "no-referrer")
            self.assertIn("default-src 'none'", r.headers["Content-Security-Policy"])
            self.assertEqual(r.headers["Cache-Control"], "no-store")
            self.assertNotIn("<script", r.get_data(as_text=True).lower())

    def test_mandantenname_und_texte_werden_maskiert(self):
        m = self.mandant("hilo", "<script>alert(1)</script> & Co", firmenangaben="Zeile <b>fett</b>")
        self.anmelden("hilo", "a@beispiel.de")
        token = self.bestaetigungslink("hilo")
        seite = self.c.get("/hilo/newsletter/bestaetigen/" + token).get_data(as_text=True)
        self.assertNotIn("<script>alert(1)", seite)
        self.assertIn("&lt;script&gt;", seite)
        self.assertNotIn("<b>fett</b>", seite)
        html = self.letzte_mail("hilo").get_body(("html",)).get_content()
        self.assertNotIn("<script>alert(1)", html)
        self.assertNotIn("<b>fett</b>", html)

    def test_cors_nur_fuer_hinterlegte_ursprunge(self):
        self.mandant("hilo", cors_ursprunge=["https://www.hilo.test"])
        r = self.c.post("/api/hilo/newsletter/anmelden", json={"email": "a@b.de", "einwilligungs_version": "EINW-1"}, headers={"Origin": "https://www.hilo.test"})
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "https://www.hilo.test")
        r = self.c.post("/api/hilo/newsletter/anmelden", json={"email": "a@b.de", "einwilligungs_version": "EINW-1"}, headers={"Origin": "https://boese.test"})
        self.assertNotIn("Access-Control-Allow-Origin", r.headers)
        r = self.c.open("/api/hilo/newsletter/anmelden", method="OPTIONS", headers={"Origin": "https://www.hilo.test"})
        self.assertEqual((r.status_code, r.headers.get("Access-Control-Allow-Origin")), (204, "https://www.hilo.test"))

    def test_ohne_hauptschluessel_nicht_bereit(self):
        self.mandant("hilo")
        env = {k: v for k, v in os.environ.items() if k != "MAILNEXT_HAUPTSCHLUESSEL"}
        with mock.patch.dict(os.environ, env, clear=True):
            r = self.anmelden("hilo", "a@beispiel.de")
        self.assertEqual((r.status_code, r.get_json()["error"]), (503, "nicht_bereit"))

    def test_zu_grosse_anfrage_413(self):
        self.mandant("hilo")
        r = self.c.post("/api/hilo/newsletter/anmelden", data=b"x" * 30000, content_type="application/json")
        self.assertEqual(r.status_code, 413)


class MailerTests(Basis):
    def test_datei_modus_rechte_und_aufraeumen(self):
        m = self.mandant("hilo")
        self.assertEqual(mailer.senden(m, "a@beispiel.de", "Betreff", "Text", "<p>x</p>"), "datei")
        pfad = self.mails("hilo")[0]
        self.assertEqual(oct(pfad.stat().st_mode & 0o777), "0o600")
        alt = pfad.with_name("alt.eml")
        alt.write_bytes(b"x")
        vor = datetime.now().timestamp() - 8 * 86400
        os.utime(alt, (vor, vor))
        mailer.senden(m, "b@beispiel.de", "Betreff", "Text", "<p>x</p>")
        self.assertFalse(alt.exists())

    def test_smtp_modus_nutzt_konto_des_mandanten(self):
        m = self.mandant("hilo", modus="aus")
        mandanten.versand_setzen(m["id"], {"smtp_host": "smtp.hilo.test", "smtp_port": 465, "smtp_benutzer": "news", "smtp_passwort": "pw-hilo-123",
                                           "smtp_verschluesselung": "ssl", "versandmodus": "smtp"}, "t")
        with mock.patch("mailer.smtplib.SMTP_SSL") as ssl_klasse:
            ergebnis = mailer.senden(mandanten.lesen(m["id"]), "a@beispiel.de", "Betreff", "Text", "<p>x</p>")
        self.assertEqual(ergebnis, "gesendet")
        ssl_klasse.assert_called_once()
        self.assertEqual(ssl_klasse.call_args[0][:2], ("smtp.hilo.test", 465))
        smtp = ssl_klasse.return_value
        smtp.login.assert_called_once_with("news", "pw-hilo-123")
        gesendet = smtp.send_message.call_args[0][0]
        self.assertIn("news@hilo.test", gesendet["From"])

    def test_smtp_fehler_liefert_fehler_und_wirft_nie(self):
        m = self.mandant("hilo", modus="aus")
        mandanten.versand_setzen(m["id"], {"smtp_host": "h.test", "smtp_port": 587, "smtp_benutzer": "u", "smtp_passwort": "p-xyz-123",
                                           "smtp_verschluesselung": "starttls", "versandmodus": "smtp"}, "t")
        with mock.patch("mailer.smtplib.SMTP", side_effect=OSError("down")):
            self.assertEqual(mailer.senden(mandanten.lesen(m["id"]), "a@beispiel.de", "B", "T", "<p>x</p>"), "fehler")

    def test_ohne_absender_keine_mail(self):
        m = mandanten.anlegen("ohne", "Ohne", {}, "t")
        mandanten.versand_setzen(m["id"], {"versandmodus": "datei"}, "t")
        self.assertEqual(mailer.senden(mandanten.lesen(m["id"]), "a@beispiel.de", "B", "T", "<p>x</p>"), "absender_fehlt")


class BetreiberApiTests(Basis):
    def als_betreiber(self):
        return mock.patch.object(betreiber_auth, "_bei_sortnext_fragen", return_value={"email": "catrin@bst-next.de", "betreiber": True})

    def als_nutzer(self):
        return mock.patch.object(betreiber_auth, "_bei_sortnext_fragen", return_value={"email": "x@y.de", "betreiber": False})

    def aufruf(self, methode, pfad, **kw):
        self.c.set_cookie("bst_session", "tok")
        return getattr(self.c, methode)("/api/v1/betreiber" + pfad, **kw)

    def audit(self):
        with db.verbindung() as c:
            return [dict(z) for z in c.execute("SELECT * FROM audit_log ORDER BY id").fetchall()]

    def test_zugriff(self):
        self.assertEqual(self.c.get("/api/v1/betreiber/mandanten").status_code, 401)
        with self.als_nutzer():
            self.assertEqual(self.aufruf("get", "/mandanten").status_code, 403)
        betreiber_auth.cache_leeren()                                                  # Ergebnis wird 30 s zwischengespeichert
        with self.als_betreiber():
            self.assertEqual(self.aufruf("get", "/mandanten").status_code, 200)

    def test_alle_routen_brauchen_betreiber(self):
        m = self.mandant("hilo")
        routen = [("get", "/mandanten"), ("post", "/mandanten"), ("get", "/mandanten/%d" % m["id"]), ("put", "/mandanten/%d" % m["id"]),
                  ("post", "/mandanten/%d/einwilligungen" % m["id"]), ("put", "/mandanten/%d/versand" % m["id"]), ("get", "/mandanten/%d/abonnenten" % m["id"])]
        with self.als_nutzer():
            for methode, pfad in routen:
                self.assertEqual(self.aufruf(methode, pfad, json={}).status_code, 403, pfad)
        for methode, pfad in routen:
            c = self.app.test_client()
            self.assertEqual(getattr(c, methode)("/api/v1/betreiber" + pfad, json={}).status_code, 401, pfad)

    def test_mandant_anlegen_aendern_mit_audit(self):
        with self.als_betreiber():
            r = self.aufruf("post", "/mandanten", json={"slug": "neu", "name": "Neu e. V.", "design": {"farbe_primaer": "#123456"}})
            self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
            mid = r.get_json()["id"]
            r = self.aufruf("put", "/mandanten/%d" % mid, json={"design": {"farbe_akzent": "#abcdef"}, "name": "Neu 2"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.get_json()["design"]["farbe_primaer"], "#123456")           # Rest des Designs bleibt
            self.assertEqual(r.get_json()["design"]["farbe_akzent"], "#abcdef")
            self.assertEqual(self.aufruf("put", "/mandanten/%d" % mid, json={"design": {"farbe_primaer": "blau"}}).status_code, 400)
            self.assertEqual(self.aufruf("put", "/mandanten/%d" % mid, json={"slug": "anders"}).status_code, 400)
            self.assertEqual(self.aufruf("put", "/mandanten/9999", json={"name": "x"}).status_code, 404)
            self.assertEqual(self.aufruf("post", "/mandanten", json={"slug": "neu", "name": "Doppelt"}).status_code, 400)
        aktionen = [a["aktion"] for a in self.audit()]
        self.assertIn("mandant_angelegt", aktionen)
        self.assertIn("mandant_geaendert", aktionen)
        self.assertEqual({a["akteur"] for a in self.audit()}, {"catrin@bst-next.de"})

    def test_einwilligung_und_versand_ohne_geheimnisse_in_antwort_und_audit(self):
        m = self.mandant("hilo", modus="aus")
        with self.als_betreiber():
            r = self.aufruf("post", "/mandanten/%d/einwilligungen" % m["id"], json={"version": "V2", "text": "Ein zweiter Einwilligungstext, lang genug und einzeilig."})
            self.assertEqual(r.status_code, 201)
            self.assertEqual(len(r.get_json()["sha256"]), 64)
            r = self.aufruf("put", "/mandanten/%d/versand" % m["id"], json={"smtp_host": "smtp.test", "smtp_port": 465, "smtp_benutzer": "u",
                                                                            "smtp_passwort": "SEHR-GEHEIM-987", "smtp_verschluesselung": "ssl", "versandmodus": "smtp"})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            self.assertTrue(r.get_json()["gesetzt"]["smtp_passwort"])
            gesamt = r.get_data(as_text=True) + self.aufruf("get", "/mandanten/%d" % m["id"]).get_data(as_text=True) + json.dumps(self.audit())
            self.assertNotIn("SEHR-GEHEIM-987", gesamt)
            self.assertIn("smtp_passwort", json.dumps(self.audit()))                          # Feldname ja, Wert nie
            self.assertEqual(self.aufruf("put", "/mandanten/%d/versand" % m["id"], json={"versandmodus": "egal"}).status_code, 400)
            self.assertEqual(self.aufruf("put", "/mandanten/%d/versand" % m["id"], json={"unbekannt": 1}).status_code, 400)

    def test_abonnentenliste_audit_und_trennung(self):
        a, b = self.mandant("a10"), self.mandant("b10")
        self.anmelden_und_bestaetigen(a, "a-nur@beispiel.de")
        self.anmelden_und_bestaetigen(b, "b-nur@beispiel.de")
        with self.als_betreiber():
            d = self.aufruf("get", "/mandanten/%d/abonnenten" % a["id"]).get_json()
        self.assertEqual([x["email"] for x in d["abonnenten"]], ["a-nur@beispiel.de"])
        self.assertNotIn("ip", d["abonnenten"][0])
        self.assertNotIn("token", json.dumps(d))
        eintrag = [x for x in self.audit() if x["aktion"] == "abonnenten_gelesen"]
        self.assertEqual(len(eintrag), 1)
        self.assertIn("anzahl=1", eintrag[0]["details"])
        self.assertNotIn("beispiel.de", eintrag[0]["details"])

    def test_ohne_audit_keine_antwort(self):
        with self.als_betreiber(), mock.patch.object(db, "audit", side_effect=RuntimeError("audit kaputt")):
            self.app.config["PROPAGATE_EXCEPTIONS"] = False
            r = self.aufruf("get", "/mandanten")
        self.assertEqual(r.status_code, 500)


if __name__ == "__main__":
    unittest.main()
