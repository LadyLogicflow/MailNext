"""v0.6.6 (catrin #19144): Kopf aller MailNext-Mails: Logo IMMER zentriert auf weißem Kartengrund, der farbige Balken beginnt erst UNTER dem Logo.

Geprüft wird die Struktur beider Renderer (layout.html_rendern für Layout-Mails, mailer.html_rahmen für Text-, Test- und Bestätigungsmails), jeweils mit und ohne
Logo, mit und ohne Balkentext."""
import os
import sys
import unittest
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import layout
import mailer
from test_meilenstein_b import Basis

LOGO = "https://extern.example/logo.png"
BLOCKS = {"version": 1, "balken": {"text": "Freischaltung Mitgliederportal", "url": None}, "text_html": "<p>Inhalt</p>", "bilder": []}
BLOCKS_OHNE_BALKEN = {"version": 1, "balken": {"text": "", "url": None}, "text_html": "<p>Inhalt</p>", "bilder": []}


class Baum(HTMLParser):
    """Sammelt je Element Tag, Attribute, Vorfahren und die Reihenfolge im Dokument."""

    def __init__(self, text):
        super().__init__()
        self.stapel, self.elemente = [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        nr = len(self.elemente)
        self.elemente.append({"tag": tag, "attrs": a, "vorfahren": [dict(x) for x in self.stapel], "nr": nr})
        if tag not in ("img", "meta", "br", "hr", "link"):
            self.stapel.append({"tag": tag, "attrs": a, "nr": nr})

    def handle_endtag(self, tag):
        for i in range(len(self.stapel) - 1, -1, -1):
            if self.stapel[i]["tag"] == tag:
                del self.stapel[i:]
                break


def hintergrund(attrs):
    """Hintergrundangabe eines Elements (bgcolor oder background im Stil) oder ''."""
    stil = (attrs.get("style") or "").replace(" ", "")
    treffer = [t.split(":", 1)[1] for t in stil.split(";") if t.startswith(("background:", "background-color:"))]
    return (attrs.get("bgcolor") or (treffer[0] if treffer else "")).lower()


class Basis066(Basis):
    def mandant_mit(self, logo):
        if not hasattr(self, "_m"):
            self._m = {}
        if logo not in self._m:
            self._m[logo] = self.mandant("hilo", "HILO e. V.", farbe_primaer="#1f3a5f", logo_url=LOGO if logo else None)
        return self._m[logo]

    def renderer(self, art, m, balken=True):
        if art == "layout":
            return layout.html_rendern(m, "Betreff", BLOCKS if balken else BLOCKS_OHNE_BALKEN, None)
        return mailer.html_rahmen(m, "Betreff", "<p>Inhalt</p>")


ARTEN = ("layout", "text")


class TestMitLogo(Basis066):
    def pruefen(self, art):
        m = self.mandant_mit(True)
        baum = Baum(self.renderer(art, m))
        logos = [e for e in baum.elemente if e["tag"] == "img" and LOGO in e["attrs"].get("src", "")]
        self.assertEqual(len(logos), 1, art)
        logo = logos[0]
        zelle = logo["vorfahren"][-1]
        self.assertEqual(zelle["tag"], "td", art)
        self.assertEqual(zelle["attrs"].get("align"), "center", art)
        self.assertIn("text-align:center", zelle["attrs"].get("style", ""), art)
        # kein Hintergrund um das Logo: weder an der Zelle noch an der Zeile noch an Tabellen darüber, ausser dem weissen Kartengrund
        karte_gefunden = False
        for v in reversed(logo["vorfahren"]):                              # von der Logo-Zelle nach aussen bis zur weissen Karte
            if hintergrund(v["attrs"]) == "#ffffff":
                karte_gefunden = True
                break
            self.assertEqual(hintergrund(v["attrs"]), "", "%s: Hintergrund um das Logo: %s" % (art, v))
        self.assertTrue(karte_gefunden, "%s: das Logo liegt nicht auf dem weissen Kartengrund" % art)
        self.assertEqual(hintergrund(logo["attrs"]), "", art)
        return baum, logo

    def test_logo_zentriert_ohne_hintergrund_in_beiden_renderern(self):
        for art in ARTEN:
            self.pruefen(art)

    def test_layout_balken_kommt_nach_dem_logo_nicht_im_selben_block(self):
        baum, logo = self.pruefen("layout")
        balken = [e for e in baum.elemente if e["attrs"].get("class") == "balken"]
        self.assertEqual(len(balken), 1)
        self.assertGreater(balken[0]["nr"], logo["nr"])
        self.assertNotIn(balken[0], logo["vorfahren"])
        zeile_logo, zeile_balken = logo["vorfahren"][-2], balken[0]["vorfahren"][-1]
        self.assertNotEqual(zeile_logo["nr"], zeile_balken["nr"])                       # eigene Zeilen
        self.assertEqual(hintergrund(balken[0]["attrs"]), "#1f3a5f")
        self.assertIn("Freischaltung Mitgliederportal", self.renderer("layout", self.mandant_mit(True)))

    def test_layout_ohne_balkentext_nur_logo(self):
        html = self.renderer("layout", self.mandant_mit(True), balken=False)
        self.assertNotIn('class="balken"', html)
        self.assertNotIn('class="kopf-name"', html)
        self.assertIn(LOGO, html)

    def test_textmail_mit_logo_hat_nur_das_logo_im_kopf_kein_farbiger_block_um_das_logo(self):
        html = self.renderer("text", self.mandant_mit(True))
        self.assertNotIn('bgcolor="#1f3a5f"', html)
        self.assertIn(LOGO, html)
        self.assertLess(html.index(LOGO), html.index(">Inhalt<"))


class TestOhneLogo(Basis066):
    def test_nur_balken_kein_logo(self):
        for art in ARTEN:
            html = self.renderer(art, self.mandant_mit(False), balken=False)
            baum = Baum(html)
            self.assertEqual([e for e in baum.elemente if e["tag"] == "img"], [], art)
            leiste = [e for e in baum.elemente if e["attrs"].get("class") == "kopf-name"]
            self.assertEqual(len(leiste), 1, art)
            self.assertEqual(hintergrund(leiste[0]["attrs"]), "#1f3a5f", art)
            self.assertLess(html.index('class="kopf-name"'), html.index(">Inhalt<"), art)
            self.assertIn("HILO e. V.", html, art)

    def test_layout_ohne_logo_mit_balkentext_nur_der_entwurfsbalken(self):
        html = self.renderer("layout", self.mandant_mit(False))
        self.assertIn('class="balken"', html)
        self.assertNotIn('class="kopf-name"', html)
        self.assertIn("Freischaltung Mitgliederportal", html)


class TestKopfFunktion(Basis066):
    def test_reihenfolge_logo_dann_balken(self):
        m = self.mandant_mit(True)
        kopf = layout.kopf_html(m, "Titel", None)
        self.assertLess(kopf.index("<img"), kopf.index('class="balken"'))
        self.assertEqual(kopf.count("<tr>"), 2)

    def test_balken_mit_link_bleibt_verlinkt(self):
        m = self.mandant_mit(True)
        kopf = layout.kopf_html(m, "Titel", "https://beispiel.test/x")
        self.assertIn('<a href="https://beispiel.test/x"', kopf)

    def test_beide_renderer_nutzen_dieselbe_kopffunktion(self):
        m = self.mandant_mit(True)
        logo_zeile = layout.kopf_html(m).split("</tr>")[0]
        self.assertIn(logo_zeile, mailer.html_rahmen(m, "T", "<p>x</p>"))
        self.assertIn(logo_zeile, layout.html_rendern(m, "T", BLOCKS_OHNE_BALKEN, None))


if __name__ == "__main__":
    unittest.main()
