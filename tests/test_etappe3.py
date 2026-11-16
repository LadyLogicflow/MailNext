"""Etappe 3 (v0.6.2): Vorschau (ohne Speichern) und 'Im Browser ansehen' (dauerhaft, ohne Anmeldung, ohne Tracking). Alle Daten und Bilder sind erfunden."""
import os
import re
import unittest
from unittest import mock

import db
import newsletter
from tests.hilfen_testmail import testmail_liste
from tests.test_etappe1 import Basis as BasisBild, jpg
from tests.test_etappe2 import blocks
from tests.test_meilenstein_b import Basis as BasisMail


class Basis(BasisBild, BasisMail):
    def start(self, n_bilder=1, **design):
        design.setdefault("impressum_url", "https://hilo.test/impressum")
        m = self.mandant("hilo", "HILO e. V.", basis_url="https://news.example", farbe_primaer="#1f3a5f", **design)
        ids = [self.hochladen(m, jpg(groesse=(400, 300), farbe=(20 * k, 80, 80)), alt="Alt %d" % k).get_json()["id"] for k in range(n_bilder)]
        return m, ids

    def anlegen(self, m, b, **kw):
        r = self.anfrage("post", "/mandanten/%d/entwuerfe" % m["id"], json={"betreff": "Neues von HILO", "format": "layout", "blocks": b, **kw})
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def mail_html(self, slug):
        mails = self.eml(slug)
        self.assertTrue(mails)
        return mails[-1].get_body(("html",)).get_content(), mails[-1].get_body(("plain",)).get_content(), mails[-1]

    def vorschau(self, m, **body):
        return self.anfrage("post", "/mandanten/%d/entwuerfe/vorschau" % m["id"], json=body)

    def ansicht(self, pfad):
        self.c.delete_cookie("bst_session")
        return self.c.get(pfad)

    def alle_entwuerfe(self):
        with db.verbindung() as c:
            return c.execute("SELECT COUNT(*) AS n FROM entwurf").fetchone()["n"]

    def ansicht_pfad(self, e):
        return "/" + e["ansicht_url"].split("/", 3)[3]


class TestVorschau(Basis):
    def test_liefert_das_echte_mail_html_den_klartext_und_speichert_nichts(self):
        m, ids = self.start(2)
        vorher = self.alle_entwuerfe()
        r = self.vorschau(m, betreff="Mein Betreff", blocks=blocks(ids, text_html="<p onclick=\"x\">Hallo <b>Welt</b></p><script>x</script>"))
        self.assertEqual(r.status_code, 200, r.get_json())
        j = r.get_json()
        self.assertEqual(set(j), {"html", "text", "warnungen", "blocks"})
        self.assertIn("Hallo <strong>Welt</strong>", j["html"])
        self.assertNotIn("<script", j["html"].lower())
        self.assertEqual(j["blocks"]["text_html"], "<p>Hallo <strong>Welt</strong></p>")                   # bereinigte Fassung
        self.assertIn("Mein Betreff", j["html"])
        self.assertTrue(j["text"].startswith("Im Browser ansehen: "))
        self.assertIn("Jetzt anmelden", j["text"])
        self.assertEqual(self.alle_entwuerfe(), vorher)                                                       # nichts gespeichert
        self.assertEqual(self.mails("hilo"), [])                                                              # nichts gesendet

    def test_html_ist_dasselbe_wie_in_der_testmail(self):
        m, ids = self.start(1)
        b = blocks(ids)
        vorschau = self.vorschau(m, betreff="[TEST] Neues von HILO", blocks=b).get_json()["html"]
        e = self.anlegen(m, b)
        testmail_liste(m, e["id"])
        testmail = self.mail_html("hilo")[0]
        norm = lambda h: re.sub(r"/ansicht/[A-Za-z0-9_-]+", "/ansicht/X", h)
        self.assertEqual(norm(vorschau).strip(), norm(testmail).strip())

    def test_fehler_wie_beim_speichern(self):
        m, ids = self.start(1)
        for body, code in (({"blocks": blocks([99999])}, "bild_unbekannt"), ({"blocks": blocks(text_html="<script>x</script>")}, "blocks_ungueltig"),
                           ({"blocks": blocks(bilder=[{"bild_id": ids[0], "alt": ""}])}, "alt_fehlt"), ({"blocks": "kein objekt"}, "blocks_ungueltig"),
                           ({"blocks": blocks(balken={"text": "x", "url": "http://x.example"})}, "url_ungueltig"), ({"betreff": "a\nb", "blocks": blocks()}, "betreff_ungueltig")):
            r = self.vorschau(m, **body)
            self.assertEqual((r.status_code, r.get_json()["error"]), (400, code), body)

    def test_betreff_ist_optional(self):
        m, ids = self.start(0)
        self.assertEqual(self.vorschau(m, blocks=blocks()).status_code, 200)

    def test_nur_fuer_betreiber_und_nicht_auf_dem_oeffentlichen_port(self):
        m, ids = self.start(0)
        betreiber = __import__("betreiber_auth")
        betreiber.cache_leeren()
        self.c.delete_cookie("bst_session")
        self.assertIn(self.c.post("/api/v1/betreiber/mandanten/%d/entwuerfe/vorschau" % m["id"], json={"blocks": blocks()}).status_code, (401, 403))
        with mock.patch.dict(os.environ, {"MAILNEXT_OEFFENTLICHER_PORT": "8001"}):
            r = self.c.post("/api/v1/betreiber/mandanten/%d/entwuerfe/vorschau" % m["id"], json={"blocks": blocks()}, environ_overrides={"SERVER_PORT": "8001"})
            self.assertEqual(r.status_code, 404)

    def test_warnungen(self):
        m, ids = self.start(1)
        w = self.vorschau(m, blocks=blocks(balken={"text": "", "url": None})).get_json()["warnungen"]
        self.assertTrue(any("kein Logo" in x for x in w))
        self.assertTrue(any("Balken" in x for x in w))
        m2 = self.mandant("voll", "Voll e. V.", basis_url="https://news.example", logo_url="https://extern.example/l.png", impressum_url="https://voll.test/impressum",
                          firmenangaben="Voll e. V., Straße 1")
        w2 = self.vorschau(m2, blocks=blocks()).get_json()["warnungen"]
        self.assertEqual(w2, [])

    def test_warnung_bei_zu_grossen_bildern_und_http_basis(self):
        patcher = mock.patch.dict(os.environ, {"MAILNEXT_BASIS_URL": "http://192.168.1.50:8001"})            # Pi-Testinstanz: Basis-Adresse über die Umgebung, http
        patcher.start()
        self.addCleanup(patcher.stop)
        m = self.mandant("pi", "Pi e. V.", logo_url="https://extern.example/l.png", impressum_url="https://pi.test/impressum", firmenangaben="Pi e. V.")
        import io
        import os as _os
        from PIL import Image
        rausch = Image.frombytes("RGB", (1600, 1000), _os.urandom(1600 * 1000 * 3))
        puffer = io.BytesIO()
        rausch.save(puffer, "PNG")
        self.assertLess(len(puffer.getvalue()), 5 * 1024 * 1024 + 1)
        ids = [self.hochladen(m, puffer.getvalue(), name="r.png").get_json()["id"] for _ in range(1)]
        w = self.vorschau(m, blocks=blocks(ids)).get_json()["warnungen"]
        self.assertTrue(any("nicht https" in x for x in w), w)
        self.assertTrue(any("MB groß" in x for x in w), w)


class TestBrowserAnsicht(Basis):
    def test_erreichbar_ohne_anmeldung_mit_festen_kopfzeilen(self):
        m, ids = self.start(2)
        e = self.anlegen(m, blocks(ids))
        g = self.anfrage("get", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"])).get_json()
        self.assertTrue(g["ansicht_url"].startswith("https://news.example/hilo/newsletter/ansicht/"), g["ansicht_url"])
        r = self.ansicht(self.ansicht_pfad(g))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Content-Type"].split(";")[0], "text/html")
        self.assertIn("default-src 'none'", r.headers["Content-Security-Policy"])
        self.assertNotIn("script-src", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("noindex", r.headers["X-Robots-Tag"])
        self.assertEqual(r.headers["Referrer-Policy"], "no-referrer")
        self.assertNotIn("Set-Cookie", r.headers)
        h = r.get_data(as_text=True)
        self.assertIn("Jetzt anmelden", h)
        self.assertEqual(h.count("<img "), 2)
        self.assertIn("Hallo <strong>Welt</strong>", h)

    def test_keine_persoenlichen_links_und_kein_tracking(self):
        m, ids = self.start(1)
        e = self.anlegen(m, blocks(ids))
        g = self.anfrage("get", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"])).get_json()
        h = self.ansicht(self.ansicht_pfad(g)).get_data(as_text=True)
        self.assertNotIn("einstellungen?t=", h)
        self.assertNotIn("abmelden-one-click", h)
        self.assertNotIn("Im Browser ansehen", h)                                           # sich selbst nicht verlinken
        self.assertIn("nutzen Sie bitte den Link in Ihrer E-Mail", h)
        self.assertNotRegex(h, r'width="1"\s+height="1"')                                    # kein Zählpixel
        self.assertNotIn("<script", h.lower())
        for quelle in re.findall(r'<img [^>]*src="([^"]+)"', h):
            self.assertTrue(quelle.startswith("https://news.example/hilo/bild/"), quelle)

    def test_kennung_ist_lang_zufaellig_und_stabil(self):
        m, ids = self.start(1)
        a = self.anlegen(m, blocks(ids))
        b = self.anlegen(m, blocks(ids))
        ga, gb = (self.anfrage("get", "/mandanten/%d/entwuerfe/%d" % (m["id"], x["id"])).get_json() for x in (a, b))
        ka, kb = ga["ansicht_url"].rsplit("/", 1)[1], gb["ansicht_url"].rsplit("/", 1)[1]
        self.assertNotEqual(ka, kb)
        self.assertGreaterEqual(len(ka), 20)
        self.anfrage("put", "/mandanten/%d/entwuerfe/%d" % (m["id"], a["id"]), json={"blocks": blocks(ids, text_html="<p>Geändert</p>")})
        g2 = self.anfrage("get", "/mandanten/%d/entwuerfe/%d" % (m["id"], a["id"])).get_json()
        self.assertEqual(g2["ansicht_url"].rsplit("/", 1)[1], ka)                           # bleibt beim Ändern gleich
        self.assertIn("Geändert", self.ansicht(self.ansicht_pfad(g2)).get_data(as_text=True))   # und zeigt den neuen Stand

    def test_auch_freigegeben_und_versendet_dauerhaft_erreichbar(self):
        m, ids = self.start(1)
        newsletter.testliste_setzen(m, ["test@example.org"])
        e = self.anlegen(m, blocks(ids))
        testmail_liste(m, e["id"])
        newsletter.freigeben(m, e["id"], newsletter.lesen(m, e["id"])["content_hash"], True, "betreiber@bst-next.de")
        newsletter.lauf()
        g = self.anfrage("get", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"])).get_json()
        self.assertIn(g["status"], ("freigegeben", "sendet", "gesendet", "fertig"))
        self.assertEqual(self.ansicht(self.ansicht_pfad(g)).status_code, 200)

    def test_jede_abweichung_ist_ein_404(self):
        m, ids = self.start(1)
        self.mandant("anders", "Anders e. V.")
        e = self.anlegen(m, blocks(ids))
        g = self.anfrage("get", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"])).get_json()
        kennung = g["ansicht_url"].rsplit("/", 1)[1]
        text_entwurf = self.anfrage("post", "/mandanten/%d/entwuerfe" % m["id"], json={"betreff": "x", "text": "Nur Text"}).get_json()
        for pfad in ("/anders/newsletter/ansicht/%s" % kennung, "/hilo/newsletter/ansicht/%sx" % kennung, "/hilo/newsletter/ansicht/kurz", "/hilo/newsletter/ansicht/vorschau",
                     "/unbekannt/newsletter/ansicht/%s" % kennung, "/hilo/newsletter/ansicht/%s/" % kennung, "/hilo/newsletter/ansicht/" + "a" * 65):
            self.assertEqual(self.ansicht(pfad).status_code, 404, pfad)
        self.assertEqual(self.ansicht("/hilo/newsletter/ansicht/%s" % kennung).status_code, 200)
        with db.verbindung() as c:
            self.assertIsNone(c.execute("SELECT ansicht_token FROM entwurf WHERE id=?", (text_entwurf["id"],)).fetchone()["ansicht_token"])          # Textentwürfe haben keine

    def test_inaktiver_mandant_zeigt_nichts(self):
        m, ids = self.start(1)
        e = self.anlegen(m, blocks(ids))
        g = self.anfrage("get", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"])).get_json()
        import mandanten
        mandanten.aendern(m["id"], aktiv=False)
        self.assertEqual(self.ansicht(self.ansicht_pfad(g)).status_code, 404)

    def test_nur_lesen_und_auf_dem_oeffentlichen_port_erreichbar(self):
        m, ids = self.start(1)
        e = self.anlegen(m, blocks(ids))
        g = self.anfrage("get", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"])).get_json()
        pfad = self.ansicht_pfad(g)
        self.assertEqual(self.c.post(pfad).status_code, 405)
        with mock.patch.dict(os.environ, {"MAILNEXT_OEFFENTLICHER_PORT": "8001"}):
            self.assertEqual(self.c.get(pfad, environ_overrides={"SERVER_PORT": "8001"}).status_code, 200)

    def test_mail_enthaelt_den_link_und_er_fuehrt_zur_ansicht(self):
        m, ids = self.start(1)
        e = self.anlegen(m, blocks(ids))
        testmail_liste(m, e["id"])
        h, text, mail = self.mail_html("hilo")
        g = self.anfrage("get", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"])).get_json()
        self.assertIn('href="%s"' % g["ansicht_url"], h)
        self.assertIn("Im Browser ansehen</a>", h)
        self.assertTrue(text.startswith("Im Browser ansehen: %s" % g["ansicht_url"]))
        self.assertEqual(self.ansicht(self.ansicht_pfad(g)).status_code, 200)

    def test_versandmail_hat_den_link_des_entwurfs(self):
        m, ids = self.start(1)
        self.abo(m, "a@example.org")
        newsletter.echtversand_setzen(m["id"], True, "t")
        e = self.anlegen(m, blocks(ids), ziel="abonnenten")
        testmail_liste(m, e["id"])
        newsletter.freigeben(m, e["id"], newsletter.lesen(m, e["id"])["content_hash"], True, "betreiber@bst-next.de")
        newsletter.lauf()
        g = self.anfrage("get", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"])).get_json()
        h = self.eml("hilo")[-1].get_body(("html",)).get_content()
        self.assertIn('href="%s"' % g["ansicht_url"], h)

    def test_text_entwuerfe_bleiben_wie_sie_waren(self):
        m = self.mandant("hilo", "HILO e. V.")
        e = newsletter.anlegen(m, "Betreff", "Nur Text", "testliste", None)
        self.assertIsNone(e["ansicht_url"])
        testmail_liste(m, e["id"])
        h, text, _ = self.mail_html("hilo")
        self.assertNotIn("Im Browser ansehen", h)
        self.assertNotIn("Im Browser ansehen", text)


class TestMigration(Basis):
    def test_aeltere_zeile_ohne_kennung_bekommt_beim_lesen_eine(self):
        m, ids = self.start(0)
        e = self.anlegen(m, blocks())
        with db.verbindung() as c:
            c.execute("UPDATE entwurf SET ansicht_token=NULL WHERE id=?", (e["id"],))
        g1 = self.anfrage("get", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"])).get_json()
        g2 = self.anfrage("get", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"])).get_json()
        self.assertTrue(g1["ansicht_url"])
        self.assertEqual(g1["ansicht_url"], g2["ansicht_url"])
        self.assertEqual(self.ansicht(self.ansicht_pfad(g1)).status_code, 200)

    def test_spalte_wird_in_bestehenden_datenbanken_ergaenzt(self):
        with db.verbindung() as c:
            spalten = {z["name"] for z in c.execute("PRAGMA table_info(entwurf)")}
        self.assertTrue({"format", "blocks", "ansicht_token"} <= spalten)
        with db.verbindung() as c:
            c.execute("DROP INDEX IF EXISTS entwurf_ansicht")
            c.execute("ALTER TABLE entwurf DROP COLUMN ansicht_token")
        db.init(db._pfad)                                                                       # wie ein Neustart auf einer älteren Datenbank
        with db.verbindung() as c:
            self.assertIn("ansicht_token", {z["name"] for z in c.execute("PRAGMA table_info(entwurf)")})


if __name__ == "__main__":
    unittest.main()
