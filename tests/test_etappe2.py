"""Etappe 2 (v0.6.1): erlaubte HTML-Teilmenge (Sanitizer), Layout-Entwürfe, Mail-HTML und Klartext-Teil. Alle Daten und Bilder sind erfunden."""
import io
import json
import random
import unittest
from html.parser import HTMLParser

from PIL import Image

import bilder
import db
import layout
import mailer
import newsletter
import textformat
from tests.test_etappe1 import Basis as BasisBild, jpg, png
from tests.test_meilenstein_b import Basis as BasisMail

ERLAUBTE_TAGS = {"p", "br", "strong", "em", "h2", "h3", "ul", "ol", "li", "a"}


class _Pruefer(HTMLParser):
    """Prüft die kanonische Ausgabe: nur erlaubte Tags, nur erlaubte Attribute, Links nur https/mailto, Tags ausgewogen."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fehler, self.stack = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in ERLAUBTE_TAGS:
            self.fehler.append("Tag " + tag)
        if tag != "br":
            self.stack.append(tag)
        for k, v in attrs:
            if tag == "a" and k == "href":
                if not (v.startswith("https://") or v.startswith("mailto:")) or any(c in v for c in ' <>"\'`\\'):
                    self.fehler.append("href " + v)
            elif k == "data-ausrichtung" and v == "zentriert" and tag in ("p", "h2", "h3"):
                pass
            else:
                self.fehler.append("Attribut %s an %s" % (k, tag))

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            self.fehler.append("Unausgewogen " + tag)

    def handle_comment(self, data):
        self.fehler.append("Kommentar")


def pruefe(sauber):
    p = _Pruefer()
    p.feed(sauber)
    p.close()
    if p.stack:
        p.fehler.append("offen: %s" % p.stack)
    return p.fehler


class TestSanitizer(unittest.TestCase):
    ANGRIFFE = [
        "<script>alert(1)</script><p>x</p>", "<p onclick=\"alert(1)\">x</p>", "<p style=\"background:url(javascript:alert(1))\">x</p>",
        "<a href=\"javascript:alert(1)\">x</a>", "<a href=\" JaVaScRiPt:alert(1)\">x</a>", "<a href=\"java\tscript:alert(1)\">x</a>",
        "<a href=\"data:text/html;base64,PHNjcmlwdD4=\">x</a>", "<a href=\"vbscript:msgbox(1)\">x</a>", "<a href=\"//evil.example/\">x</a>",
        "<a href=\"http://unsicher.example/\">x</a>", "<a href=\"https://user:pw@evil.example/\">x</a>", "<a href='https://x.example/\" onmouseover=\"alert(1)'>x</a>",
        "<img src=x onerror=alert(1)>", "<svg onload=alert(1)><p>x</p></svg>", "<iframe src=\"https://evil.example\"></iframe>", "<object data=\"x\"></object>",
        "<embed src=\"x\">", "<math><mi xlink:href=\"javascript:alert(1)\">x</mi></math>", "<form action=\"https://evil.example\"><input name=a></form>",
        "<base href=\"https://evil.example/\"><p>x</p>", "<meta http-equiv=\"refresh\" content=\"0;url=https://evil.example\">", "<link rel=stylesheet href=\"https://evil.example/x.css\">",
        "<style>p{background:url(https://evil.example/x)}</style><p>x</p>", "<!--[if mso]><script>alert(1)</script><![endif]--><p>x</p>", "<?php echo 1 ?><p>x</p>",
        "<!DOCTYPE html><p>x</p>", "<p>a</p><template><script>alert(1)</script></template>", "<textarea><script>alert(1)</script></textarea>",
        "<p>x</p><noscript><p>y</p></noscript>", "<p srcdoc=\"<script>alert(1)</script>\">x</p>", "<p data-x=\"1\" class=\"c\" id=\"i\" title=\"t\">x</p>",
        "<a href=\"https://ok.example\" target=\"_blank\" rel=\"opener\" onclick=\"x\">x</a>", "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>", "<p>\x00<b>x</b>\x07</p>",
        "<b><i><b><i>" * 40 + "tief", "<ul>" * 30 + "<li>x</li>" + "</ul>" * 30, "<p>" + "<a href=\"https://a.example\">" * 20 + "x</p>", "<scr<script>ipt>alert(1)</scr</script>ipt>",
        "<p>x</p></p></div></a></strong>", "<a href=\"https://ok.example\"><script>alert(1)</script>text</a>", "<IMG SRC=\"jav&#x09;ascript:alert(1)\">",
        "<a href=\"&#106;avascript:alert(1)\">x</a>", "<a href=\"https://a.example/?x=<script>\">x</a>", "<li>lose</li><br><br>",
    ]

    def test_ausgabe_enthaelt_nur_erlaubtes(self):
        for roh in self.ANGRIFFE:
            sauber = textformat.bereinigen(roh)
            self.assertEqual(pruefe(sauber), [], "%r -> %r" % (roh[:60], sauber[:120]))
            for verboten in ("<script", "onclick", "onerror", "onload", "javascript:", "style=", "class=", "<img", "<iframe", "srcdoc", "vbscript"):
                self.assertNotIn(verboten, sauber.lower(), roh[:60])

    def test_idempotent(self):
        for roh in self.ANGRIFFE + ["<p>Hallo <b>Welt</b></p>", "<ul><li>a<li>b</ul>", "Text <em>ohne</em> Absatz"]:
            einmal = textformat.bereinigen(roh)
            self.assertEqual(textformat.bereinigen(einmal), einmal, roh[:60])

    def test_zufallseingaben_halten_die_invarianten(self):
        fragmente = ["<p>", "</p>", "<b>", "</b>", "<a href=\"https://ok.example/x\">", "<a href=\"javascript:x\">", "</a>", "<ul>", "<li>", "</li>", "</ul>", "<h2>", "</h2>", "text",
                     " ", "&amp;", "&lt;", "<br>", "<script>", "</script>", "<img src=x>", "<p style=\"x\">", "<h3 data-ausrichtung=\"zentriert\">", "<!--", "-->", "\"", "'", "<", ">"]
        zufall = random.Random(20261116)
        for _ in range(400):
            roh = "".join(zufall.choice(fragmente) for _ in range(zufall.randint(1, 25)))
            sauber = textformat.bereinigen(roh)
            self.assertEqual(pruefe(sauber), [], "%r -> %r" % (roh, sauber))
            self.assertEqual(textformat.bereinigen(sauber), sauber, roh)

    def test_erlaubtes_bleibt_und_wird_normalisiert(self):
        self.assertEqual(textformat.bereinigen("<p>Hallo <b>fett</b> und <i>schräg</i> &amp; mehr</p>"), "<p>Hallo <strong>fett</strong> und <em>schräg</em> &amp; mehr</p>")
        self.assertEqual(textformat.bereinigen("<h2 data-ausrichtung=\"zentriert\">Titel</h2><h3>Unter</h3>"), "<h2 data-ausrichtung=\"zentriert\">Titel</h2><h3>Unter</h3>")
        self.assertEqual(textformat.bereinigen("<ul><li>Eins<li>Zwei</ul><ol><li>A</li></ol>"), "<ul><li>Eins</li><li>Zwei</li></ul><ol><li>A</li></ol>")
        self.assertEqual(textformat.bereinigen("<a href=\"HTTPS://Beispiel.example/a?b=1&c=2\">Link</a>"), "<p><a href=\"https://Beispiel.example/a?b=1&amp;c=2\">Link</a></p>")
        self.assertEqual(textformat.bereinigen("<a href=\"mailto:info@beispiel.example\">Mail</a>"), "<p><a href=\"mailto:info@beispiel.example\">Mail</a></p>")
        self.assertEqual(textformat.bereinigen("Text ohne Absatz"), "<p>Text ohne Absatz</p>")
        self.assertEqual(textformat.bereinigen("<p data-ausrichtung=\"rechts\">x</p>"), "<p>x</p>")
        self.assertEqual(textformat.bereinigen("<p></p><p>  </p><p><br></p>"), "")
        self.assertEqual(textformat.bereinigen(None), "")

    def test_gefaehrliche_links_werden_zu_text(self):
        for href in ("javascript:alert(1)", "data:text/html,x", "http://x.example", "//x.example", "https://u:p@x.example", "ftp://x.example", "mailto:nicht gültig"):
            self.assertEqual(textformat.bereinigen("<a href=\"%s\">Text</a>" % href), "<p>Text</p>", href)

    def test_klartext(self):
        sauber = textformat.bereinigen("<h2>Titel</h2><p>Hallo <a href=\"https://e.example/x\">Link</a> und <a href=\"https://e.example\">https://e.example</a></p>"
                                       "<ul><li>a</li><li>b</li></ul><ol><li>x</li><li>y</li></ol><p>Zeile<br>zwei</p>")
        self.assertEqual(textformat.als_text(sauber), "Titel\n\nHallo Link (https://e.example/x) und https://e.example\n\n- a\n- b\n\n1. x\n2. y\n\nZeile\nzwei")

    def test_rendern_setzt_nur_inline_stile_und_zentrierung(self):
        h = textformat.rendern(textformat.bereinigen("<h2 data-ausrichtung=\"zentriert\">T</h2><p>x <a href=\"https://a.example\">l</a></p>"), "#112233", "#445566")
        self.assertIn('<h2 style="margin:0 0 12px;font-size:22px;line-height:1.3;color:#445566;text-align:center;">T</h2>', h)
        self.assertIn('<a href="https://a.example" style="color:#112233;text-decoration:underline;">l</a>', h)
        self.assertNotIn("data-ausrichtung", h)
        self.assertNotIn("class=", h)

    def test_zu_lange_eingabe_wird_gekuerzt_nicht_zum_absturz(self):
        sauber = textformat.bereinigen("<p>" + "wort " * 100000 + "</p>")
        self.assertLessEqual(len(sauber), textformat.MAX_EINGABE * 2 + 20)


def blocks(bild_ids=(), **extra):
    b = {"version": 1, "balken": {"text": "Jetzt anmelden", "url": "https://anmeldung.example/x"}, "text_html": "<h2>Neues</h2><p>Hallo <b>Welt</b></p>",
         "bilder": [{"bild_id": i, "alt": "Bild %d" % i, "bildunterschrift": "Unterschrift %d" % i, "url": "https://ziel.example/%d" % i} for i in bild_ids]}
    b.update(extra)
    return b


class TestBlocksPruefen(BasisBild):
    def vorbereiten(self, n=1):
        m = self.mandant("hilo", "HILO e. V.")
        ids = [self.hochladen(m, jpg(farbe=(10 * k, 50, 50)), alt="Alt %d" % k).get_json()["id"] for k in range(n)]
        return m, ids

    def test_gueltig_liefert_bereinigte_bloecke_und_klartext(self):
        m, ids = self.vorbereiten(2)
        b, text = layout.pruefen(m, blocks(ids, text_html="<h2>Neues</h2><p onclick=\"x\">Hallo <b>Welt</b></p><script>x</script>"))
        self.assertEqual(b["text_html"], "<h2>Neues</h2><p>Hallo <strong>Welt</strong></p>")
        self.assertEqual([x["bild_id"] for x in b["bilder"]], ids)
        self.assertIn("Jetzt anmelden (https://anmeldung.example/x)", text)
        self.assertIn("Neues\n\nHallo Welt", text)
        self.assertIn("[Bild: Bild %d]\nUnterschrift %d\nhttps://ziel.example/%d" % (ids[0], ids[0], ids[0]), text)

    def test_alt_wird_aus_dem_bild_vorbelegt(self):
        m, ids = self.vorbereiten(1)
        b, _ = layout.pruefen(m, {"version": 1, "text_html": "<p>x</p>", "bilder": [{"bild_id": ids[0]}]})
        self.assertEqual(b["bilder"][0]["alt"], "Alt 0")
        self.assertEqual(b["bilder"][0]["bildunterschrift"], "")
        self.assertIsNone(b["bilder"][0]["url"])
        self.assertEqual(b["balken"], {"text": "", "url": None})

    def test_fehlercodes_der_spezifikation(self):
        m, ids = self.vorbereiten(1)
        def code(b):
            with self.assertRaises(layout.LayoutFehler) as r:
                layout.pruefen(m, b)
            return r.exception.code, r.exception.feld
        self.assertEqual(code("kein objekt")[0], "blocks_ungueltig")
        self.assertEqual(code(blocks(version=2))[0], "blocks_ungueltig")
        self.assertEqual(code(blocks(zusatz=1))[0], "blocks_ungueltig")
        self.assertEqual(code(blocks(text_html=""))[0], "blocks_ungueltig")
        self.assertEqual(code(blocks(text_html="<script>x</script>"))[0], "blocks_ungueltig")
        self.assertEqual(code(blocks(text_html="<p>" + "x" * 20001 + "</p>"))[0], "blocks_ungueltig")
        self.assertEqual(code(blocks(balken={"text": "x" * 61}))[0], "blocks_ungueltig")
        self.assertEqual(code(blocks(balken={"text": "ok", "farbe": "rot"}))[0], "blocks_ungueltig")
        self.assertEqual(code(blocks(balken={"text": "ok", "url": "http://x.example"})), ("url_ungueltig", "balken.url"))
        self.assertEqual(code(blocks(balken={"text": "ok", "url": "javascript:alert(1)"}))[0], "url_ungueltig")
        self.assertEqual(code(blocks([ids[0]] * 7))[0], "zu_viele_bilder")
        self.assertEqual(code(blocks([99999])), ("bild_unbekannt", "bilder[0].bild_id"))
        self.assertEqual(code(blocks(bilder=[{"bild_id": True}]))[0], "bild_unbekannt")
        self.assertEqual(code(blocks(bilder=[{"bild_id": ids[0], "alt": ""}])), ("alt_fehlt", "bilder[0].alt"))
        self.assertEqual(code(blocks(bilder=[{"bild_id": ids[0], "alt": "x" * 151}]))[0], "alt_fehlt")
        self.assertEqual(code(blocks(bilder=[{"bild_id": ids[0], "alt": "ok", "url": "http://x.example"}]))[0], "url_ungueltig")
        self.assertEqual(code(blocks(bilder=[{"bild_id": ids[0], "alt": "ok", "bildunterschrift": "x" * 201}]))[0], "blocks_ungueltig")
        self.assertEqual(code(blocks(bilder=[{"bild_id": ids[0], "alt": "ok", "extra": 1}]))[0], "blocks_ungueltig")

    def test_sechs_bilder_gehen_sieben_nicht(self):
        m, ids = self.vorbereiten(1)
        self.assertEqual(len(layout.pruefen(m, blocks([ids[0]] * 6))[0]["bilder"]), 6)

    def test_fremdes_bild_ist_unbekannt(self):
        m, ids = self.vorbereiten(1)
        m2 = self.mandant("anders", "Anders e. V.")
        with self.assertRaises(layout.LayoutFehler) as r:
            layout.pruefen(m2, blocks(ids))
        self.assertEqual(r.exception.code, "bild_unbekannt")


class TestLayoutMail(BasisBild, BasisMail):
    """Entwurf über die echte Schnittstelle, Testmail im Modus 'datei', Versandlauf."""

    def start(self, n_bilder=2, **design):
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

    def test_anlegen_antwortet_mit_bereinigter_fassung_und_lesen_zeigt_alles(self):
        m, ids = self.start()
        e = self.anlegen(m, blocks(ids, text_html="<p onclick=\"x\">Hallo</p><script>x</script>"))
        self.assertEqual(e["blocks"]["text_html"], "<p>Hallo</p>")
        g = self.anfrage("get", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"])).get_json()
        self.assertEqual((g["format"], g["blocks"]["text_html"]), ("layout", "<p>Hallo</p>"))
        self.assertIn("Hallo", g["text"])                                                      # abgeleiteter Klartext
        liste = self.anfrage("get", "/mandanten/%d/entwuerfe" % m["id"]).get_json()["entwuerfe"]
        self.assertEqual(liste[0]["format"], "layout")

    def test_format_regeln(self):
        m, ids = self.start(1)
        for body in ({"betreff": "x", "format": "layout", "text": "Text", "blocks": blocks(ids)}, {"betreff": "x", "text": "Text", "blocks": blocks(ids)},
                     {"betreff": "x", "format": "kaputt", "text": "Text"}):
            r = self.anfrage("post", "/mandanten/%d/entwuerfe" % m["id"], json=body)
            self.assertEqual(r.status_code, 400, body)
        r = self.anfrage("post", "/mandanten/%d/entwuerfe" % m["id"], json={"betreff": "x", "format": "layout", "blocks": blocks([99999])})
        self.assertEqual((r.status_code, r.get_json()["error"], r.get_json()["feld"]), (400, "bild_unbekannt", "bilder[0].bild_id"))
        e = self.anlegen(m, blocks(ids))
        r = self.anfrage("put", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"]), json={"text": "Klartext"})
        self.assertEqual((r.status_code, r.get_json()["error"]), (400, "format_passt_nicht"))
        t = self.anfrage("post", "/mandanten/%d/entwuerfe" % m["id"], json={"betreff": "x", "text": "Nur Text"}).get_json()
        r = self.anfrage("put", "/mandanten/%d/entwuerfe/%d" % (m["id"], t["id"]), json={"blocks": blocks(ids)})
        self.assertEqual((r.status_code, r.get_json()["error"]), (400, "format_passt_nicht"))

    def test_aendern_aktualisiert_hash_und_bereinigt(self):
        m, ids = self.start(1)
        e = self.anlegen(m, blocks(ids))
        r = self.anfrage("put", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"]), json={"blocks": blocks(ids, text_html="<p>Neu</p><img src=x>")})
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.get_json()["content_hash"], e["content_hash"])
        self.assertEqual(r.get_json()["blocks"]["text_html"], "<p>Neu</p>")
        r2 = self.anfrage("put", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"]), json={"betreff": "Anderer Betreff"})                      # Blöcke bleiben
        self.assertEqual(r2.get_json()["blocks"]["text_html"], "<p>Neu</p>")

    def test_hash_bindet_bloecke_und_bild_nummern(self):
        m, ids = self.start(2)
        a = self.anlegen(m, blocks([ids[0]]))
        b = self.anlegen(m, blocks([ids[1]]))
        self.assertNotEqual(a["content_hash"], b["content_hash"])
        gleich = lambda bild: blocks(bilder=[{"bild_id": bild, "alt": "Gleich", "bildunterschrift": "Gleich", "url": None}])               # gleicher Klartext, anderes Bild
        c, d = self.anlegen(m, gleich(ids[0])), self.anlegen(m, gleich(ids[1]))
        self.assertEqual(c["text"] if "text" in c else None, d["text"] if "text" in d else None)
        self.assertNotEqual(c["content_hash"], d["content_hash"])                                                      # die Freigabe bindet auch die Bild-Nummern
        self.assertNotEqual(self.anlegen(m, blocks([ids[0]], balken={"text": "Anderer Balken", "url": None}))["content_hash"], a["content_hash"])

    def test_textentwuerfe_behalten_ihren_hash(self):
        m = self.mandant("hilo", "HILO e. V.")
        e = newsletter.anlegen(m, "Betreff", "Text", "testliste", None)
        self.assertEqual(e["content_hash"], newsletter._hash("Betreff", "Text", "testliste", e["segment"]))              # wie vor der Etappe: 4 Teile, keine Blöcke
        self.assertEqual((e["format"], e["blocks"]), ("text", None))

    def test_testmail_hat_tabellenlayout_zwei_spalten_balken_und_bilder(self):
        m, ids = self.start(2)
        e = self.anlegen(m, blocks(ids))
        newsletter.testmail(m, e["id"], None, "betreiber@bst-next.de")
        h, text, mail = self.mail_html("hilo")
        self.assertIn('width="600"', h)
        self.assertIn("max-width:600px", h)
        self.assertGreaterEqual(h.count('role="presentation"'), 3)
        self.assertIn("Jetzt anmelden", h)
        self.assertIn('href="https://anmeldung.example/x"', h)
        self.assertEqual(h.count("<img "), 2)
        self.assertEqual(h.count('class="sp'), 2)                                              # zwei Spalten
        self.assertIn("@media only screen and (max-width:480px)", h)                          # mobil stapeln
        self.assertIn('name="color-scheme" content="light dark"', h)                          # Dunkelmodus
        self.assertIn("prefers-color-scheme:dark", h)
        self.assertIn("Unterschrift %d" % ids[0], h)
        self.assertIn("Einstellungen ändern oder abmelden", h)
        self.assertIn("List-Unsubscribe", mail)                                                # One-Click bleibt
        self.assertIn("Jetzt anmelden (https://anmeldung.example/x)", text)
        self.assertIn("[Bild: Bild %d]" % ids[0], text)
        self.assertIn("Einstellungen ändern oder abmelden: https://news.example/hilo/newsletter/einstellungen", text)
        self.assertNotIn("<", text.replace("<https", ""))                                      # keine Tags im Textteil

    def test_jedes_bild_hat_alt_groesse_und_nur_eigenen_host(self):
        m, ids = self.start(3)
        e = self.anlegen(m, blocks(ids))
        newsletter.testmail(m, e["id"], None, "betreiber@bst-next.de")
        h = self.mail_html("hilo")[0]
        bilder_tags = [t for t in h.split("<img ")[1:]]
        self.assertEqual(len(bilder_tags), 3)
        for t in bilder_tags:
            tag = t.split(">", 1)[0]
            self.assertIn(' alt="Bild ', tag)
            self.assertIn(' width="', tag)
            self.assertIn(' height="', tag)
            self.assertIn('src="https://news.example/hilo/bild/', tag)
        import re
        for quelle in re.findall(r'(?:src|href)="([^"]+)"', h):
            self.assertTrue(quelle.startswith(("https://news.example/", "https://anmeldung.example/", "https://ziel.example/", "https://hilo.test/", "mailto:")), quelle)

    def test_ohne_bilder_einspaltig_ohne_balken_kein_balken(self):
        m, _ = self.start(0)
        e = self.anlegen(m, {"version": 1, "text_html": "<p>Nur Text</p>"})
        newsletter.testmail(m, e["id"], None, "betreiber@bst-next.de")
        h = self.mail_html("hilo")[0]
        self.assertEqual(h.count('class="sp'), 0)
        self.assertNotIn('class="balken"', h)
        self.assertNotIn("<img ", h)

    def test_balken_ohne_link_und_farbe_aus_dem_mandanten(self):
        m, ids = self.start(0)
        from tests.test_etappe1 import Basis
        self.anfrage("put", "/mandanten/%d" % m["id"], json={"design": {"balken_farbe": "#ffee00"}})
        e = self.anlegen(m, {"version": 1, "balken": {"text": "Nur Hinweis", "url": None}, "text_html": "<p>x</p>"})
        newsletter.testmail(mandanten_lesen(m), e["id"], None, "betreiber@bst-next.de")
        h = self.mail_html("hilo")[0]
        balken = h.split('class="balken"')[1].split("</td>")[0]
        self.assertIn("Nur Hinweis", balken)
        self.assertNotIn("<a ", balken)
        self.assertIn("#ffee00", h.split('class="balken"')[0].rsplit("<td", 1)[1])
        self.assertIn("color:#111111", balken)                                                  # dunkle Schrift auf hellem Gelb

    def test_balkenfarbe_leer_nimmt_die_primaerfarbe(self):
        m, _ = self.start(0)
        e = self.anlegen(m, {"version": 1, "balken": {"text": "Balken", "url": None}, "text_html": "<p>x</p>"})
        newsletter.testmail(m, e["id"], None, "betreiber@bst-next.de")
        h = self.mail_html("hilo")[0]
        self.assertIn('bgcolor="#1f3a5f"', h.split('class="balken"')[0].rsplit("<td", 1)[1])

    def test_html_ist_wohlgeformt(self):
        m, ids = self.start(3)
        e = self.anlegen(m, blocks(ids, text_html="<h2 data-ausrichtung=\"zentriert\">T</h2><p>a <b>b</b> <a href=\"https://e.example\">l</a></p><ul><li>x</li></ul><ol><li>y</li></ol>"))
        newsletter.testmail(m, e["id"], None, "betreiber@bst-next.de")
        h = self.mail_html("hilo")[0]

        class P(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack, self.fehler = [], []

            def handle_starttag(self, tag, attrs):
                if tag not in ("meta", "br", "img"):
                    self.stack.append(tag)

            def handle_endtag(self, tag):
                if not self.stack or self.stack.pop() != tag:
                    self.fehler.append(tag)
        p = P()
        p.feed(h)
        self.assertEqual((p.fehler, p.stack), ([], []))

    def test_mail_enthaelt_nie_aktive_inhalte(self):
        m, ids = self.start(1)
        boese = "<script>alert(1)</script><p onclick=\"x\">Hallo <a href=\"javascript:alert(1)\">Klick</a><img src=x onerror=alert(1)></p><iframe src=\"https://evil.example\"></iframe>"
        e = self.anlegen(m, blocks(ids, text_html=boese, balken={"text": "<b>Balken</b> & mehr", "url": "https://x.example/?a=1&b=2"}))
        newsletter.testmail(m, e["id"], None, "betreiber@bst-next.de")
        h = self.mail_html("hilo")[0].lower()
        for verboten in ("<script", "onclick", "onerror", "javascript:", "<iframe", "evil.example"):
            self.assertNotIn(verboten, h)
        self.assertIn("&lt;b&gt;balken&lt;/b&gt; &amp; mehr", h)                                 # Balkentext maskiert
        self.assertIn("a=1&amp;b=2", h)

    def test_versandlauf_nutzt_das_layout_und_personalisierte_links(self):
        m, ids = self.start(1)
        self.abo(m, "a@example.org")
        newsletter.echtversand_setzen(m["id"], True, "t")
        e = self.anlegen(m, blocks(ids), ziel="abonnenten")
        newsletter.testmail(m, e["id"], None, "betreiber@bst-next.de")
        eintrag = newsletter.lesen(m, e["id"])
        newsletter.freigeben(m, e["id"], eintrag["content_hash"], True, "betreiber@bst-next.de")
        vorher = len(self.mails("hilo"))
        newsletter.lauf()
        mails = self.eml("hilo")
        self.assertGreater(len(mails), vorher)
        h = mails[-1].get_body(("html",)).get_content()
        self.assertIn('class="sp', h)
        self.assertIn("einstellungen?t=", h)
        self.assertNotIn("vorschau.vorschau", h)                                                 # echter persönlicher Link, nicht der Vorschau-Link
        self.assertTrue(mails[-1]["List-Unsubscribe"])

    def test_bild_in_verwendung_bis_der_entwurf_es_nicht_mehr_nutzt(self):
        m, ids = self.start(1)
        e = self.anlegen(m, blocks(ids))
        r = self.anfrage("delete", "/mandanten/%d/bilder/%d" % (m["id"], ids[0]))
        self.assertEqual((r.status_code, r.get_json()["error"]), (409, "bild_in_verwendung"))
        liste = self.anfrage("get", "/mandanten/%d/bilder" % m["id"]).get_json()
        self.assertTrue(liste[0]["in_verwendung"])
        self.anfrage("put", "/mandanten/%d/entwuerfe/%d" % (m["id"], e["id"]), json={"blocks": blocks([])})
        self.assertEqual(self.anfrage("delete", "/mandanten/%d/bilder/%d" % (m["id"], ids[0])).status_code, 204)

    def test_freigegebener_entwurf_haelt_sein_bild_fest(self):
        m, ids = self.start(1)
        newsletter.testliste_setzen(m, ["test@example.org"])
        e = self.anlegen(m, blocks(ids))
        newsletter.testmail(m, e["id"], None, "betreiber@bst-next.de")
        newsletter.freigeben(m, e["id"], newsletter.lesen(m, e["id"])["content_hash"], True, "betreiber@bst-next.de")
        self.assertEqual(self.anfrage("delete", "/mandanten/%d/bilder/%d" % (m["id"], ids[0])).status_code, 409)

    def test_bilder_anderer_mandanten_nicht_nutzbar_ueber_die_schnittstelle(self):
        m, ids = self.start(1)
        m2 = self.mandant("anders", "Anders e. V.")
        r = self.anfrage("post", "/mandanten/%d/entwuerfe" % m2["id"], json={"betreff": "x", "format": "layout", "blocks": blocks(ids)})
        self.assertEqual((r.status_code, r.get_json()["error"]), (400, "bild_unbekannt"))


def mandanten_lesen(m):
    import mandanten
    return mandanten.lesen(m["id"])


if __name__ == "__main__":
    unittest.main()
