"""Etappe 1 (v0.6.0): Bilder und Logo je Mandant. Upload nur für Betreiber, Prüfung am Inhalt, Neu-Kodierung ohne Metadaten, Zufallsdateiname, Auslieferung nur
lesend über den öffentlichen Port, Logo im Mail-Kopf. Alle Bilder sind erzeugt, keine echten Personen oder Orte."""
import io
import os
import struct
import unittest
from unittest import mock

from PIL import Image

import betreiber_auth
import bilder
import config
import db
import mailer
import mandanten
from tests.test_import import ImportBasis


def jpg(groesse=(120, 80), farbe=(200, 30, 30), **extra):
    puffer = io.BytesIO()
    Image.new("RGB", groesse, farbe).save(puffer, "JPEG", **extra)
    return puffer.getvalue()


def png(groesse=(120, 80), farbe=(30, 30, 200, 255), modus="RGBA"):
    puffer = io.BytesIO()
    Image.new(modus, groesse, farbe).save(puffer, "PNG")
    return puffer.getvalue()


def webp(groesse=(120, 80), farbe=(30, 200, 30)):
    puffer = io.BytesIO()
    Image.new("RGB", groesse, farbe).save(puffer, "WEBP")
    return puffer.getvalue()


def gif():
    puffer = io.BytesIO()
    Image.new("P", (10, 10)).save(puffer, "GIF")
    return puffer.getvalue()


class Basis(ImportBasis):
    def anfrage(self, methode, pfad, **kw):
        with self.als_betreiber():
            betreiber_auth.cache_leeren()
            self.c.set_cookie("bst_session", "tok")
            return getattr(self.c, methode)("/api/v1/betreiber" + pfad, **kw)

    def hochladen(self, m, daten, alt="Ein rotes Rechteck", name="bild.jpg", mime="image/jpeg"):
        form = {"file": (io.BytesIO(daten), name, mime)}
        if alt is not None:
            form["alt"] = alt
        return self.anfrage("post", "/mandanten/%d/bilder" % m["id"], data=form, content_type="multipart/form-data")

    def oeffentlich(self, pfad, **kw):
        self.c.delete_cookie("bst_session")
        return self.c.get(pfad, **kw)


class TestUpload(Basis):
    def test_jpg_png_webp_werden_angenommen_und_ueber_den_oeffentlichen_pfad_geliefert(self):
        m = self.mandant("hilo", "HILO e. V.")
        for daten, endung, typ in ((jpg(), "jpg", "image/jpeg"), (png(), "png", "image/png"), (webp(), "webp", "image/webp")):
            r = self.hochladen(m, daten, name="egal.xyz", mime="application/octet-stream")
            self.assertEqual(r.status_code, 201, r.get_json())
            b = r.get_json()
            self.assertEqual((b["content_type"], b["breite"], b["hoehe"]), (typ, 120, 80))
            self.assertEqual(b["alt"], "Ein rotes Rechteck")
            self.assertTrue(b["url"].startswith("/hilo/bild/") and b["url"].endswith("." + endung), b["url"])
            self.assertGreater(b["groesse_bytes"], 0)
            o = self.oeffentlich(b["url"])
            self.assertEqual(o.status_code, 200)
            self.assertEqual(o.headers["Content-Type"], typ)
            self.assertEqual(o.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(Image.open(io.BytesIO(o.data)).size, (120, 80))

    def test_typ_wird_am_inhalt_erkannt_nicht_an_endung_oder_content_type(self):
        m = self.mandant("hilo", "HILO e. V.")
        for daten, name, mime in ((gif(), "x.jpg", "image/jpeg"), (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "x.png", "image/png"),
                                  (b"einfacher text", "x.jpg", "image/jpeg"), (b"%PDF-1.4 ...", "x.png", "image/png")):
            r = self.hochladen(m, daten, name=name, mime=mime)
            self.assertEqual((r.status_code, r.get_json()["error"]), (400, "typ_nicht_erlaubt"), name)
        r = self.hochladen(m, png(), name="harmlos.jpg", mime="image/jpeg")                      # PNG unter falschem Namen: Endung folgt dem Inhalt
        self.assertEqual((r.status_code, r.get_json()["content_type"]), (201, "image/png"))
        self.assertTrue(r.get_json()["url"].endswith(".png"))

    def test_alt_text_ist_pflicht(self):
        m = self.mandant("hilo", "HILO e. V.")
        for alt in (None, "", "   ", "x" * 151, "mit\x07steuerzeichen"):
            r = self.hochladen(m, jpg(), alt=alt)
            self.assertEqual((r.status_code, r.get_json()["error"]), (400, "alt_fehlt"), repr(alt))
        self.assertEqual(self.hochladen(m, jpg(), alt="x" * 150).status_code, 201)

    def test_datei_fehlt(self):
        m = self.mandant("hilo", "HILO e. V.")
        r = self.anfrage("post", "/mandanten/%d/bilder" % m["id"], data={"alt": "Text"}, content_type="multipart/form-data")
        self.assertEqual((r.status_code, r.get_json()["error"]), (400, "datei_fehlt"))

    def test_zu_gross_wird_abgelehnt(self):
        m = self.mandant("hilo", "HILO e. V.")
        r = self.hochladen(m, os.urandom(5 * 1024 * 1024 + 2000))
        self.assertEqual(r.status_code, 413)

    def test_zu_viele_bildpunkte_ohne_dekodieren_abgelehnt(self):
        m = self.mandant("hilo", "HILO e. V.")
        gross = png(groesse=(6000, 5000), farbe=(255, 255, 255, 255), modus="RGBA")                # 30 Megapixel, nur wenige KB groß
        self.assertLess(len(gross), 1_000_000)
        r = self.hochladen(m, gross, name="b.png")
        self.assertEqual((r.status_code, r.get_json()["error"]), (400, "zu_viele_pixel"))

    def test_animierte_bilder_werden_abgelehnt(self):
        m = self.mandant("hilo", "HILO e. V.")
        puffer = io.BytesIO()
        a, b = Image.new("RGB", (20, 20), (255, 0, 0)), Image.new("RGB", (20, 20), (0, 0, 255))
        a.save(puffer, "WEBP", save_all=True, append_images=[b], duration=100)
        r = self.hochladen(m, puffer.getvalue(), name="a.webp")
        self.assertEqual((r.status_code, r.get_json()["error"]), (400, "bild_ungueltig"))

    def test_beschaedigtes_bild_wird_abgelehnt(self):
        m = self.mandant("hilo", "HILO e. V.")
        kaputt = jpg()[:60] + os.urandom(40)
        r = self.hochladen(m, kaputt)
        self.assertEqual(r.status_code, 400)
        self.assertIn(r.get_json()["error"], ("bild_ungueltig", "typ_nicht_erlaubt"))


class TestNeuKodierung(Basis):
    def gespeichert(self, m, antwort):
        b = antwort.get_json()
        pfad = config.daten_verzeichnis() / "bilder" / str(m["id"]) / ("%s.%s" % (b["token"], b["url"].rsplit(".", 1)[1]))
        return b, pfad.read_bytes()

    def test_exif_gps_und_farbprofil_fallen_weg(self):
        m = self.mandant("hilo", "HILO e. V.")
        exif = Image.Exif()
        exif[0x010F] = "GeheimeKamera"                                                              # Hersteller
        exif[0x8825] = {1: "N", 2: (51.0, 14.0, 12.0), 3: "E", 4: (6.0, 41.0, 5.0)}                  # GPS
        orig = jpg(exif=exif.tobytes(), icc_profile=b"profil-daten" * 20)
        self.assertIn(b"GeheimeKamera", orig)
        r = self.hochladen(m, orig)
        self.assertEqual(r.status_code, 201)
        _, daten = self.gespeichert(m, r)
        self.assertNotIn(b"GeheimeKamera", daten)
        self.assertNotIn(b"Exif", daten[:2000])
        self.assertNotIn(b"profil-daten", daten)
        neu = Image.open(io.BytesIO(daten))
        self.assertEqual(len(neu.getexif()), 0)
        self.assertNotIn("icc_profile", neu.info)

    def test_ausrichtung_wird_angewandt(self):
        m = self.mandant("hilo", "HILO e. V.")
        exif = Image.Exif()
        exif[0x0112] = 6                                                                            # 90 Grad
        r = self.hochladen(m, jpg(groesse=(100, 50), exif=exif.tobytes()))
        b = r.get_json()
        self.assertEqual((b["breite"], b["hoehe"]), (50, 100))

    def test_grosse_bilder_werden_verkleinert_kleine_nicht_vergroessert(self):
        m = self.mandant("hilo", "HILO e. V.")
        b = self.hochladen(m, jpg(groesse=(3000, 2000))).get_json()
        self.assertEqual(max(b["breite"], b["hoehe"]), bilder.MAX_KANTE)
        self.assertEqual((b["breite"], b["hoehe"]), (1600, 1067))
        k = self.hochladen(m, jpg(groesse=(60, 40))).get_json()
        self.assertEqual((k["breite"], k["hoehe"]), (60, 40))

    def test_transparenz_bleibt_bei_png(self):
        m = self.mandant("hilo", "HILO e. V.")
        r = self.hochladen(m, png(farbe=(10, 20, 30, 0)), name="t.png")
        _, daten = self.gespeichert(m, r)
        self.assertEqual(Image.open(io.BytesIO(daten)).mode, "RGBA")

    def test_dateiname_ist_ein_zufallstoken_ohne_namen(self):
        m = self.mandant("hilo", "HILO e. V.")
        a = self.hochladen(m, jpg(), name="Mustermann-Max-Passfoto.jpg").get_json()
        b = self.hochladen(m, jpg(), name="Mustermann-Max-Passfoto.jpg").get_json()
        self.assertNotEqual(a["token"], b["token"])
        self.assertNotIn("Mustermann", a["url"])
        self.assertGreaterEqual(len(a["token"]), 20)
        verz = config.daten_verzeichnis() / "bilder" / str(m["id"])
        self.assertEqual(sorted(p.name for p in verz.iterdir()), sorted(["%s.jpg" % a["token"], "%s.jpg" % b["token"]]))


class TestAuslieferung(Basis):
    def test_jede_abweichung_ist_ein_404(self):
        m = self.mandant("hilo", "HILO e. V.")
        self.mandant("anders", "Anders e. V.")
        b = self.hochladen(m, jpg()).get_json()
        token = b["token"]
        for pfad in ("/anders/bild/%s.jpg" % token,                       # anderer Mandant
                     "/hilo/bild/%s.png" % token,                          # falsche Endung
                     "/hilo/bild/%sx.jpg" % token,                         # unbekannter Token
                     "/hilo/bild/..%2f..%2fetc%2fpasswd",                  # Pfadsprung
                     "/hilo/bild/%s.jpg/" % token,
                     "/hilo/bild/%s" % token,                              # ohne Endung
                     "/hilo/bild/kurz.jpg"):
            r = self.oeffentlich(pfad)
            self.assertEqual(r.status_code, 404, pfad)
        for pfad in ("/anders/bild/%s.jpg" % token, "/hilo/bild/%s.png" % token, "/hilo/bild/%sx.jpg" % token):          # unsere Route: einheitlicher Text
            self.assertEqual(self.oeffentlich(pfad).get_data(as_text=True), "Nicht gefunden", pfad)

    def test_inaktiver_mandant_liefert_nichts(self):
        m = self.mandant("hilo", "HILO e. V.")
        b = self.hochladen(m, jpg()).get_json()
        mandanten.aendern(m["id"], aktiv=False)
        self.assertEqual(self.oeffentlich(b["url"]).status_code, 404)

    def test_nur_lesen_und_feste_kopfzeilen(self):
        m = self.mandant("hilo", "HILO e. V.")
        b = self.hochladen(m, png(), name="x.png").get_json()
        self.assertEqual(self.c.post(b["url"]).status_code, 405)
        self.assertEqual(self.c.delete(b["url"]).status_code, 405)
        r = self.oeffentlich(b["url"])
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", r.headers["Content-Security-Policy"])
        self.assertIn("max-age", r.headers["Cache-Control"])
        self.assertNotIn("Set-Cookie", r.headers)

    def test_oeffentlicher_port_liefert_bilder_aber_keinen_upload(self):
        m = self.mandant("hilo", "HILO e. V.")
        b = self.hochladen(m, jpg()).get_json()
        with mock.patch.dict(os.environ, {"MAILNEXT_OEFFENTLICHER_PORT": "8001"}):
            ok = self.c.get(b["url"], environ_overrides={"SERVER_PORT": "8001"})
            self.assertEqual(ok.status_code, 200)
            for methode, pfad in (("post", "/api/v1/betreiber/mandanten/%d/bilder" % m["id"]), ("get", "/api/v1/betreiber/mandanten/%d/bilder" % m["id"])):
                r = getattr(self.c, methode)(pfad, environ_overrides={"SERVER_PORT": "8001"})
                self.assertEqual(r.status_code, 404, (methode, pfad))


class TestVerwaltung(Basis):
    def test_ohne_betreiber_anmeldung_nichts(self):
        m = self.mandant("hilo", "HILO e. V.")
        b = self.hochladen(m, jpg()).get_json()
        betreiber_auth.cache_leeren()
        self.c.delete_cookie("bst_session")
        for methode, pfad in (("post", "/mandanten/%d/bilder"), ("get", "/mandanten/%d/bilder"), ("delete", "/mandanten/%d/bilder/" + str(b["id"]))):
            r = getattr(self.c, methode)("/api/v1/betreiber" + (pfad % m["id"] if "%d" in pfad else pfad.replace("%d", str(m["id"]))))
            self.assertIn(r.status_code, (401, 403), (methode, pfad))

    def test_liste_loeschen_und_verwendung(self):
        m = self.mandant("hilo", "HILO e. V.")
        a = self.hochladen(m, jpg(), alt="Erstes").get_json()
        b = self.hochladen(m, png(), alt="Zweites", name="b.png").get_json()
        liste = self.anfrage("get", "/mandanten/%d/bilder" % m["id"]).get_json()
        self.assertEqual([x["id"] for x in liste], [b["id"], a["id"]])                          # neueste zuerst
        self.assertEqual({k for k in liste[0]}, {"id", "token", "url", "breite", "hoehe", "content_type", "groesse_bytes", "alt", "erstellt", "in_verwendung"})
        self.assertFalse(any(x["in_verwendung"] for x in liste))
        r = self.anfrage("put", "/mandanten/%d" % m["id"], json={"design": {"logo_bild_id": a["id"]}})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["design"]["logo_bild_id"], a["id"])
        liste = self.anfrage("get", "/mandanten/%d/bilder" % m["id"]).get_json()
        self.assertEqual({x["id"]: x["in_verwendung"] for x in liste}, {a["id"]: True, b["id"]: False})
        r = self.anfrage("delete", "/mandanten/%d/bilder/%d" % (m["id"], a["id"]))
        self.assertEqual((r.status_code, r.get_json()["error"]), (409, "bild_in_verwendung"))
        self.assertEqual(self.oeffentlich(a["url"]).status_code, 200)                               # noch da
        self.assertEqual(self.anfrage("delete", "/mandanten/%d/bilder/%d" % (m["id"], b["id"])).status_code, 204)
        self.assertEqual(self.oeffentlich(b["url"]).status_code, 404)
        self.assertFalse((config.daten_verzeichnis() / "bilder" / str(m["id"]) / ("%s.png" % b["token"])).exists())
        self.anfrage("put", "/mandanten/%d" % m["id"], json={"design": {"logo_bild_id": None}})
        self.assertEqual(self.anfrage("delete", "/mandanten/%d/bilder/%d" % (m["id"], a["id"])).status_code, 204)

    def test_mandanten_sind_getrennt(self):
        m1 = self.mandant("hilo", "HILO e. V.")
        m2 = self.mandant("anders", "Anders e. V.")
        b = self.hochladen(m1, jpg()).get_json()
        self.assertEqual(self.anfrage("get", "/mandanten/%d/bilder" % m2["id"]).get_json(), [])
        self.assertEqual(self.anfrage("delete", "/mandanten/%d/bilder/%d" % (m2["id"], b["id"])).status_code, 404)
        r = self.anfrage("put", "/mandanten/%d" % m2["id"], json={"design": {"logo_bild_id": b["id"]}})          # fremdes Bild als Logo
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.anfrage("get", "/mandanten/%d/bilder" % 9999).status_code, 404)

    def test_audit_enthaelt_nur_zahlen_nie_alt_text_oder_dateiname(self):
        m = self.mandant("hilo", "HILO e. V.")
        self.hochladen(m, jpg(), alt="Geheimer Alttext Mustermann", name="Mustermann-Foto.jpg")
        with db.verbindung() as c:
            zeilen = [dict(z) for z in c.execute("SELECT aktion, details FROM audit_log WHERE aktion='bild_hochgeladen'")]
        self.assertEqual(len(zeilen), 1)
        self.assertNotIn("Mustermann", zeilen[0]["details"])
        self.assertNotIn("Alttext", zeilen[0]["details"])
        self.assertIn("mandant=hilo", zeilen[0]["details"])


class TestDesignFelder(Basis):
    def test_logo_bild_id_und_balkenfarbe_werden_geprueft(self):
        m = self.mandant("hilo", "HILO e. V.")
        b = self.hochladen(m, jpg()).get_json()
        def put(design):
            return self.anfrage("put", "/mandanten/%d" % m["id"], json={"design": design})
        for falsch in ({"logo_bild_id": 99999}, {"logo_bild_id": "1"}, {"logo_bild_id": True}, {"logo_bild_id": 0}, {"logo_bild_id": -3}, {"balken_farbe": "rot"},
                       {"balken_farbe": "#12345"}, {"balken_farbe": "#12345g"}):
            self.assertEqual(put(falsch).status_code, 400, falsch)
        ok = put({"logo_bild_id": b["id"], "balken_farbe": "#112233"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual((ok.get_json()["design"]["logo_bild_id"], ok.get_json()["design"]["balken_farbe"]), (b["id"], "#112233"))
        self.assertEqual(put({"balken_farbe": ""}).get_json()["design"]["balken_farbe"], "")             # leer = Primärfarbe
        self.assertEqual(put({"logo_bild_id": None}).get_json()["design"]["logo_bild_id"], None)

    def test_standard_bleibt_ohne_bild_und_ohne_balkenfarbe(self):
        m = self.mandant("hilo", "HILO e. V.")
        self.assertEqual((m["design"]["logo_bild_id"], m["design"]["balken_farbe"]), (None, ""))

    def test_beim_anlegen_kein_logo_bild(self):
        r = self.anfrage("post", "/mandanten", json={"slug": "neu", "name": "Neu e. V.", "design": {"logo_bild_id": 1}})
        self.assertEqual(r.status_code, 400)


class TestLogoInDerMail(Basis):
    def test_hochgeladenes_logo_hat_vorrang_vor_der_externen_adresse(self):
        m = self.mandant("hilo", "HILO e. V.", logo_url="https://extern.example/logo.png", basis_url="https://news.example")
        b = self.hochladen(m, png(), name="l.png").get_json()
        vorher = mailer.html_rahmen(mandanten.lesen(m["id"]), "Betreff", "<p>x</p>")
        self.assertIn("https://extern.example/logo.png", vorher)
        self.anfrage("put", "/mandanten/%d" % m["id"], json={"design": {"logo_bild_id": b["id"]}})
        nachher = mailer.html_rahmen(mandanten.lesen(m["id"]), "Betreff", "<p>x</p>")
        self.assertIn("https://news.example/hilo/bild/%s.png" % b["token"], nachher)
        self.assertNotIn("extern.example", nachher)
        self.anfrage("put", "/mandanten/%d" % m["id"], json={"design": {"logo_bild_id": None}})
        self.assertIn("https://extern.example/logo.png", mailer.html_rahmen(mandanten.lesen(m["id"]), "Betreff", "<p>x</p>"))

    def test_ohne_beides_bleibt_der_name_im_kopf(self):
        m = self.mandant("hilo", "HILO e. V.")
        html = mailer.html_rahmen(m, "Betreff", "<p>x</p>")
        self.assertNotIn("<img", html)
        self.assertIn("HILO e. V.", html)


if __name__ == "__main__":
    unittest.main()
