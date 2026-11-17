"""v0.8.0 (catrin #19220/#19221): Layout-Newsletter Version 2 - zwei Spalten, frei gemischte Blöcke (text/bild), Ausrichtung, Textfarbe, Kontrastwarnung.

Version 1 bleibt unverändert (siehe test_etappe2/3). Farben nur als exakter Hex-Wert, Stile entstehen ausschließlich beim Rendern."""
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bilder
import layout
import mandanten
import newsletter
import textformat
from test_etappe3 import Basis


def text(t="<p>Hallo</p>", **kw):
    return {"typ": "text", "text_html": t, **kw}


def bild(bid, **kw):
    return {"typ": "bild", "bild_id": bid, **kw}


def v2(links=(), rechts=(), balken=None):
    return {"version": 2, "balken": balken if balken is not None else {"text": "Titel", "url": None}, "spalten": {"links": list(links), "rechts": list(rechts)}}


class Basis080(Basis):
    def vorbereiten(self, n=3):
        m, ids = self.start(n)
        return mandanten.lesen(m["id"]), ids

    def pruefen(self, m, blocks):
        return layout.pruefen(m, blocks)

    def fehler(self, m, blocks):
        with self.assertRaises(layout.LayoutFehler) as r:
            layout.pruefen(m, blocks)
        return r.exception.code, r.exception.feld

    def html(self, m, blocks):
        sauber, _ = layout.pruefen(m, blocks)
        return layout.html_rendern(m, "Betreff", sauber, None, None)


class TestSchema(Basis080):
    def test_gueltig_normalisiert_und_klein_geschrieben(self):
        m, ids = self.vorbereiten()
        sauber, klartext = self.pruefen(m, v2([text(farbe="#AA0000", ausrichtung="blocksatz"), bild(ids[0], alt="", bildunterschrift="U", bildunterschrift_farbe="#00FF00")], [text()],
                                              balken={"text": "T", "url": None, "farbe": "#112233"}))
        self.assertEqual(sauber["version"], 2)
        self.assertEqual(sauber["spalten"]["links"][0], {"typ": "text", "text_html": "<p>Hallo</p>", "ausrichtung": "blocksatz", "farbe": "#aa0000"})
        b = sauber["spalten"]["links"][1]
        self.assertEqual((b["typ"], b["bild_id"], b["bildunterschrift_farbe"], b["url"]), ("bild", ids[0], "#00ff00", None))
        self.assertTrue(b["alt"])                                                          # leer = aus dem Bild vorbelegt
        self.assertEqual(sauber["spalten"]["rechts"][0]["ausrichtung"], "links")           # Standard
        self.assertIsNone(sauber["spalten"]["rechts"][0]["farbe"])
        self.assertEqual(sauber["balken"], {"text": "T", "url": None, "farbe": "#112233"})
        self.assertIn("Hallo", klartext)

    def test_nur_eine_spalte_oder_nur_bilder_geht(self):
        m, ids = self.vorbereiten()
        self.pruefen(m, v2([], [text()]))
        self.pruefen(m, v2([bild(ids[0])], []))

    def test_fehlercodes_und_felder(self):
        m, ids = self.vorbereiten()
        zu_lang = "<p>%s</p>" % ("x" * 25000)
        faelle = [
            (v2([], []), ("blocks_ungueltig", "spalten")),
            ({"version": 2, "balken": {}, "spalten": {"links": []}}, ("blocks_ungueltig", "spalten")),
            ({"version": 2, "balken": {}, "spalten": "x"}, ("blocks_ungueltig", "spalten")),
            ({"version": 2, "balken": {}, "spalten": {"links": [text()], "rechts": [], "mitte": []}}, ("blocks_ungueltig", "spalten")),
            ({"version": 2, "spalten": {"links": [text()], "rechts": []}, "text_html": "x"}, ("blocks_ungueltig", "blocks")),
            (v2([text()], balken={"text": "T", "url": None, "stil": "x"}), ("blocks_ungueltig", "balken")),
            (v2([text()] * 21), ("zu_viele_bloecke", "spalten.links")),
            (v2([], [text()] * 21), ("zu_viele_bloecke", "spalten.rechts")),
            (v2([bild(ids[0])] * 7, [bild(ids[0])] * 6), ("zu_viele_bilder", "spalten")),
            (v2([{"typ": "video"}]), ("block_typ_ungueltig", "spalten.links[0].typ")),
            (v2([text(), "kein objekt"]), ("block_typ_ungueltig", "spalten.links[1].typ")),
            (v2([text(ausrichtung="rechts")]), ("ausrichtung_ungueltig", "spalten.links[0].ausrichtung")),
            (v2([text("<script>x</script>")]), ("blocks_ungueltig", "spalten.links[0].text_html")),
            (v2([text(zu_lang)]), ("blocks_ungueltig", "spalten.links[0].text_html")),
            (v2([text(stil="x")]), ("blocks_ungueltig", "spalten.links[0]")),
            (v2([bild(ids[0], farbe="#000000")]), ("blocks_ungueltig", "spalten.links[0]")),
            (v2([text()], [bild(999999)]), ("bild_unbekannt", "spalten.rechts[0].bild_id")),
            (v2([bild(True)]), ("bild_unbekannt", "spalten.links[0].bild_id")),
            (v2([bild(ids[0], alt="x" * 500)]), ("alt_fehlt", "spalten.links[0].alt")),
            (v2([bild(ids[0], url="http://beispiel.test")]), ("url_ungueltig", "spalten.links[0].url")),
            (v2([bild(ids[0], bildunterschrift="x" * 201)]), ("blocks_ungueltig", "spalten.links[0].bildunterschrift")),
            (v2([text()], balken={"text": "x" * 61, "url": None}), ("blocks_ungueltig", "balken.text")),
            (v2([text()], balken={"text": "T", "url": "http://x.test"}), ("url_ungueltig", "balken.url")),
        ]
        for blocks, erwartet in faelle:
            self.assertEqual(self.fehler(m, blocks), erwartet, json.dumps(blocks)[:120])

    def test_gesamttext_grenze(self):
        m, ids = self.vorbereiten()
        block = text("<p>%s</p>" % ("x" * 19000))
        self.assertEqual(self.fehler(m, v2([block] * 4)), ("blocks_ungueltig", "spalten"))                       # 76 000 > 60 000
        self.pruefen(m, v2([block] * 3))

    def test_farbe_nur_exakter_hex_sonst_farbe_ungueltig(self):
        m, ids = self.vorbereiten()
        for schlecht in ("red", "#fff", "#1234567", "#12345g", "rgb(0,0,0)", "url(x)", "#ff0000;background:url(x)", "#ff0000\" onclick=\"x", " #ff0000x", 5, ["#ff0000"]):
            for blocks, feld in ((v2([text(farbe=schlecht)]), "spalten.links[0].farbe"),
                                 (v2([bild(ids[0], bildunterschrift_farbe=schlecht)]), "spalten.links[0].bildunterschrift_farbe"),
                                 (v2([text()], balken={"text": "T", "url": None, "farbe": schlecht}), "balken.farbe")):
                self.assertEqual(self.fehler(m, blocks), ("farbe_ungueltig", feld), repr(schlecht))

    def test_leere_farbe_ist_standard(self):
        m, ids = self.vorbereiten()
        sauber, _ = self.pruefen(m, v2([text(farbe=""), text(farbe=None)]))
        self.assertEqual([b["farbe"] for b in sauber["spalten"]["links"]], [None, None])

    def test_bild_anderer_mandanten_ist_unbekannt(self):
        m, ids = self.vorbereiten()
        andere = self.mandant("andere", "Andere")
        r = self.hochladen(andere, __import__("tests.test_etappe1", fromlist=["jpg"]).jpg(), alt="Fremd")
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertEqual(self.fehler(m, v2([bild(r.get_json()["id"])]))[0], "bild_unbekannt")

    def test_version_1_bleibt_wie_sie_war(self):
        m, ids = self.vorbereiten()
        sauber, klartext = self.pruefen(m, {"version": 1, "balken": {"text": "T", "url": None}, "text_html": "<p>Alt</p>", "bilder": [{"bild_id": ids[0], "alt": "A"}]})
        self.assertEqual(sauber["version"], 1)
        self.assertIn("text_html", sauber)
        self.assertEqual(self.fehler(m, {"version": 3, "balken": {}, "spalten": {}}), ("blocks_ungueltig", "blocks"))


class TestTextfarbeImText(unittest.TestCase):
    def test_span_nur_mit_gueltiger_farbe(self):
        self.assertEqual(textformat.bereinigen('<p>a <span data-farbe="#AA0000">b</span></p>'), '<p>a <span data-farbe="#aa0000">b</span></p>')
        for schlecht in ('<span style="color:red">', '<span data-farbe="red">', '<span data-farbe="#fff">', '<span data-farbe="#ff0000;x">', '<span>'):
            self.assertEqual(textformat.bereinigen("<p>a %sb</span></p>" % schlecht), "<p>a b</p>", schlecht)

    def test_keine_weiteren_attribute_am_span(self):
        s = textformat.bereinigen('<p><span data-farbe="#123456" onclick="x" style="y" class="z">k</span></p>')
        self.assertEqual(s, '<p><span data-farbe="#123456">k</span></p>')

    def test_verschachtelte_ungueltige_spans_schliessen_das_aeussere_nicht(self):
        s = textformat.bereinigen('<p><span data-farbe="#ff0000">a<span>b</span>c</span>d</p>')
        self.assertEqual(s, '<p><span data-farbe="#ff0000">abc</span>d</p>')

    def test_leeres_span_entfaellt_und_span_ausserhalb_eines_absatzes_wird_absatz(self):
        self.assertEqual(textformat.bereinigen('<p><span data-farbe="#ff0000"></span>x</p>'), "<p>x</p>")
        self.assertEqual(textformat.bereinigen('<span data-farbe="#ff0000">lose</span>'), '<p><span data-farbe="#ff0000">lose</span></p>')

    def test_rendern_setzt_den_stil_selbst(self):
        html = textformat.rendern('<p>a <span data-farbe="#aa0000">b</span></p>', "#0000ff", "#000000", "blocksatz", "#112233")
        self.assertIn('<span style="color:#aa0000;">b</span>', html)
        self.assertIn("text-align:justify;", html)
        self.assertIn("color:#112233;", html)
        self.assertNotIn("data-farbe", html)

    def test_rendern_ignoriert_ungueltige_farbe_des_aufrufers(self):
        html = textformat.rendern("<p>a</p>", "#0000ff", "#000000", "links", "red; background:url(x)")
        self.assertNotIn("url(", html)
        self.assertNotIn("red", html)


class TestDarstellung(Basis080):
    def test_zwei_spalten_reihenfolge_und_gemischte_bloecke(self):
        m, ids = self.vorbereiten()
        h = self.html(m, v2([bild(ids[0], alt="LB1"), text("<p>LT1</p>"), bild(ids[1], alt="LB2"), text("<p>LT2</p>")], [text("<p>RT1</p>"), bild(ids[2], alt="RB1")]))
        reihenfolge = [h.index(x) for x in ('alt="LB1"', "LT1", 'alt="LB2"', "LT2", "RT1", 'alt="RB1"')]
        self.assertEqual(reihenfolge, sorted(reihenfolge))                                    # links von oben nach unten, dann rechts
        self.assertEqual(h.count('class="sp"'), 2)
        self.assertEqual(h.count('width="50%"'), 2)
        self.assertIn("max-width:264px", h)
        self.assertNotIn("max-width:552px", h)

    def test_leere_spalte_gibt_die_volle_breite(self):
        m, ids = self.vorbereiten()
        h = self.html(m, v2([], [text("<p>Nur rechts</p>"), bild(ids[0])]))
        self.assertEqual(h.count('class="sp"'), 1)
        self.assertIn('width="100%" valign="top"', h)
        self.assertIn("max-width:552px", h)

    def test_ausrichtung_je_block(self):
        m, ids = self.vorbereiten()
        h = self.html(m, v2([text("<p>AAA</p>", ausrichtung="blocksatz"), text("<p>BBB</p>", ausrichtung="zentriert"), text("<p>CCC</p>")]))
        a, b, c = (re.search(r'<p style="([^"]*)">%s' % x, h).group(1) for x in ("AAA", "BBB", "CCC"))
        self.assertIn("text-align:justify", a)
        self.assertIn("text-align:center", b)
        self.assertNotIn("text-align", c)

    def test_textfarben_ueberall(self):
        m, ids = self.vorbereiten()
        h = self.html(m, v2([text("<p>BLOCK</p>", farbe="#aa0000"), text('<p>mit <span data-farbe="#00aa00">GRUEN</span></p>'), bild(ids[0], bildunterschrift="UNTER", bildunterschrift_farbe="#0000aa")],
                            balken={"text": "TITEL", "url": None, "farbe": "#ff00ff"}))
        self.assertRegex(h, r'<p style="[^"]*color:#aa0000;[^"]*">BLOCK')
        self.assertIn('<span style="color:#00aa00;">GRUEN</span>', h)
        self.assertRegex(h, r'class="unterschrift" style="[^"]*color:#0000aa">UNTER')
        self.assertRegex(h, r'class="balken" style="[^"]*color:#ff00ff;[^"]*">TITEL')

    def test_standardfarben_bleiben_ohne_auswahl(self):
        m, ids = self.vorbereiten()
        h = self.html(m, v2([bild(ids[0], bildunterschrift="UNTER"), text("<p>TXT</p>")]))
        self.assertRegex(h, r'class="unterschrift" style="[^"]*color:#6b7280">UNTER')
        self.assertRegex(h, r'class="balken" style="[^"]*color:#(ffffff|111111);')

    def test_nie_ein_stil_aus_dem_client(self):
        m, ids = self.vorbereiten()
        boese = ['<p>x <span data-farbe="#ff0000&quot; onmouseover=&quot;alert(1)">y</span></p>', '<p style="color:red" onclick="x">z</p>',
                 '<p>a <span style="background:url(javascript:x)">b</span></p>', '<p><img src=x onerror=y>c</p>']
        h = self.html(m, v2([text(b) for b in boese]))
        for verboten in ("onmouseover", "onclick", "onerror", "javascript:", "alert(1)", "url(", "<img src=x"):
            self.assertNotIn(verboten, h, verboten)
        for stil in re.findall(r'style="([^"]*)"', h):                                          # alle Stile stammen aus dem Renderer
            self.assertNotRegex(stil, r"url\(|expression|javascript")

    def test_klartext_links_dann_rechts_in_blockreihenfolge(self):
        m, ids = self.vorbereiten()
        _, klar = self.pruefen(m, v2([text("<p>L1</p>"), bild(ids[0], alt="BildL", bildunterschrift="UL"), text("<p>L2</p>")], [bild(ids[1], alt="BildR"), text("<p>R1</p>")],
                                     balken={"text": "TITEL", "url": None}))
        stellen = [klar.index(x) for x in ("TITEL", "L1", "[Bild: BildL]", "UL", "L2", "[Bild: BildR]", "R1")]
        self.assertEqual(stellen, sorted(stellen))

    def test_version_1_html_ist_unveraendert_die_alte_zwei_spalten_form(self):
        m, ids = self.vorbereiten()
        sauber, _ = self.pruefen(m, {"version": 1, "balken": {"text": "T", "url": None}, "text_html": "<p>Alt</p>", "bilder": [{"bild_id": ids[0], "alt": "A"}]})
        h = layout.html_rendern(m, "B", sauber, None, None)
        self.assertIn('width="62%"', h)
        self.assertIn('width="38%"', h)
        self.assertIn("max-width:216px", h)


class TestKontrastwarnung(Basis080):
    def warnungen(self, m, blocks):
        sauber, _ = layout.pruefen(m, blocks)
        return layout.kontrast_warnungen(m, sauber)

    def test_verhaeltnis_nach_wcag(self):
        self.assertAlmostEqual(layout.kontrastverhaeltnis("#000000", "#ffffff"), 21.0, places=1)
        self.assertAlmostEqual(layout.kontrastverhaeltnis("#ffffff", "#ffffff"), 1.0, places=2)
        self.assertAlmostEqual(layout.kontrastverhaeltnis("#767676", "#ffffff"), 4.54, places=1)

    def test_warnung_bei_schwachem_kontrast_in_allen_textbereichen(self):
        m, ids = self.vorbereiten()
        w = self.warnungen(m, v2([text(farbe="#ffff00"), text('<p><span data-farbe="#eeeeee">hell</span></p>'), bild(ids[0], bildunterschrift="U", bildunterschrift_farbe="#dddddd")],
                                 balken={"text": "T", "url": None, "farbe": m["design"].get("balken_farbe") or m["design"]["farbe_primaer"]}))
        self.assertEqual(len(w), 4, w)
        self.assertTrue(any("Textfarbe" in x for x in w))
        self.assertTrue(any("markierte Textstelle" in x for x in w))
        self.assertTrue(any("Bildunterschrift" in x for x in w))
        self.assertTrue(any("Balkens" in x for x in w))
        self.assertTrue(all("4,5 : 1" in x for x in w))

    def test_keine_warnung_bei_gutem_kontrast_und_ohne_auswahl(self):
        m, ids = self.vorbereiten()
        self.assertEqual(self.warnungen(m, v2([text(farbe="#000000"), text('<p><span data-farbe="#7a0000">x</span></p>'), bild(ids[0], bildunterschrift_farbe="#333333")],
                                              balken={"text": "T", "url": None, "farbe": "#ffffff"})), [])
        self.assertEqual(self.warnungen(m, v2([text()])), [])

    def test_version_1_hat_keine_kontrastwarnungen(self):
        m, ids = self.vorbereiten()
        sauber, _ = layout.pruefen(m, {"version": 1, "balken": {"text": "T", "url": None}, "text_html": "<p>x</p>", "bilder": []})
        self.assertEqual(layout.kontrast_warnungen(m, sauber), [])


class TestSchnittstelleUndVersand(Basis080):
    def test_entwurf_vorschau_testmail_und_hash(self):
        m, ids = self.vorbereiten()
        newsletter.testliste_setzen(m, ["t@beispiel.de"])
        b = v2([text("<p>Links</p>", farbe="#ffff00"), bild(ids[0])], [text("<p>Rechts</p>", ausrichtung="zentriert")])
        r = self.anfrage("post", "/mandanten/%d/entwuerfe/vorschau" % m["id"], json={"betreff": "B", "blocks": b})
        j = r.get_json()
        self.assertEqual(r.status_code, 200, j)
        self.assertEqual(j["blocks"]["version"], 2)
        self.assertIn("Links", j["html"])
        self.assertIn("[Bild:", j["text"])
        self.assertTrue(any("Textfarbe" in w for w in j["warnungen"]))
        e = self.anlegen(m, b)
        self.assertEqual(e["blocks"]["version"], 2)
        e2 = self.anlegen(m, v2([text("<p>Anders</p>")]))
        self.assertNotEqual(e["content_hash"], e2["content_hash"])
        t = newsletter.testmail(mandanten.lesen(m["id"]), e["id"])
        self.assertEqual(t["gesendet"], 1)
        html, klar, _ = self.mail_html("hilo")
        self.assertIn("Links", html)
        self.assertIn("Rechts", klar)

    def test_fehlerantwort_mit_code_und_feld(self):
        m, ids = self.vorbereiten()
        r = self.anfrage("post", "/mandanten/%d/entwuerfe/vorschau" % m["id"], json={"betreff": "B", "blocks": v2([text(farbe="rot")])})
        self.assertEqual((r.status_code, r.get_json()["error"], r.get_json().get("feld")), (400, "farbe_ungueltig", "spalten.links[0].farbe"))

    def test_bild_in_version_2_ist_in_verwendung_und_409_beim_loeschen(self):
        m, ids = self.vorbereiten()
        self.anlegen(m, v2([text()], [bild(ids[1])]))
        mm = mandanten.lesen(m["id"])
        self.assertTrue(bilder.in_verwendung(mm, ids[1]))
        self.assertFalse(bilder.in_verwendung(mm, ids[2]))
        r = self.anfrage("delete", "/mandanten/%d/bilder/%d" % (m["id"], ids[1]))
        self.assertEqual(r.status_code, 409, r.get_data(as_text=True))
        r = self.anfrage("delete", "/mandanten/%d/bilder/%d" % (m["id"], ids[2]))
        self.assertEqual(r.status_code, 204, r.get_data(as_text=True))

    def test_version_1_entwurf_rendert_und_speichert_weiter(self):
        m, ids = self.vorbereiten()
        e = self.anlegen(m, {"version": 1, "balken": {"text": "T", "url": None}, "text_html": "<p>Alt</p>", "bilder": [{"bild_id": ids[0], "alt": "A"}]})
        self.assertEqual(e["blocks"]["version"], 1)
        r = self.anfrage("put", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"]), json={"betreff": "Neu"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(bilder.in_verwendung(mandanten.lesen(m["id"]), ids[0]))


if __name__ == "__main__":
    unittest.main()
