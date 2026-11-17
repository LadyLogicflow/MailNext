"""Layout-Newsletter (Etappe 2, v0.6.1): Blöcke prüfen, bereinigen und als Mail darstellen.

Blockschema (version 1): ``balken`` {text 0-60 Zeichen, url https oder null} (leerer Text = kein Balken), ``text_html`` (erlaubte HTML-Teilmenge, siehe textformat.py,
höchstens 20 000 Zeichen), ``bilder`` 0 bis 6 Einträge {bild_id (Bild des Mandanten), alt 1-150, bildunterschrift 0-200, url https oder null}. Logo und Fuß kommen aus dem
Mandanten. Die Mail ist ein Tabellen-Layout (600 px, Mail-Programme brauchen das): Kopf mit Logo, Balken, zwei Spalten (Text links, Bilder rechts), Fuß; auf schmalen Bildschirmen
stapeln die Spalten, Dunkelmodus per color-scheme. Bilder nur vom eigenen Host (Auslieferung bilder.py), kein Tracking.

Blockschema version 2 (ab 0.8.0): ``balken`` {text 0-60, url, farbe #rrggbb|null}, ``spalten`` {links: [Block], rechts: [Block]} mit frei gemischten Blöcken je Spalte:
Textblock {typ "text", text_html, ausrichtung links|blocksatz|zentriert, farbe #rrggbb|null} und Bildblock {typ "bild", bild_id, alt, bildunterschrift, bildunterschrift_farbe, url}.
Grenzen: höchstens 20 Blöcke je Spalte, 12 Bilder, 60 000 Zeichen Text insgesamt. Farben nur als exakter Hex-Wert; Stile entstehen ausschließlich hier beim Rendern. Version 1 bleibt unverändert."""
import html
import re

import bilder
import mailer
import textformat

MAX_BILDER = 6
MAX_BLOECKE_JE_SPALTE = 20
MAX_BILDER_V2 = 12
MAX_TEXT_GESAMT = 60000
SPALTE_HALB_PX = 264
SPALTE_VOLL_PX = 552
AUSRICHTUNGEN = ("links", "blocksatz", "zentriert")
BALKEN_MAX = 60
UNTERSCHRIFT_MAX = 200
URL_MAX = 300
SPALTE_BILD_PX = 216
KEYS = {"version", "balken", "text_html", "bilder"}
KEYS_V2 = {"version", "balken", "spalten"}
BILD_KEYS = {"bild_id", "alt", "bildunterschrift", "url"}


class LayoutFehler(Exception):
    """Eingabefehler in den Blöcken: code wie in der Spezifikation (blocks_ungueltig, bild_unbekannt, zu_viele_bilder, alt_fehlt, url_ungueltig)."""

    def __init__(self, code: str, meldung: str, feld: str | None = None):
        super().__init__(code)
        self.code, self.meldung, self.feld = code, meldung, feld


def _einzeilig(wert, feld, maximum, leer_ok=True) -> str:
    if wert is None:
        wert = ""
    if not isinstance(wert, str):
        raise LayoutFehler("blocks_ungueltig", "%s muss Text sein" % feld, feld)
    wert = " ".join(wert.split())
    if len(wert) > maximum or any(ord(z) < 32 for z in wert):
        raise LayoutFehler("blocks_ungueltig", "%s: höchstens %d Zeichen, ohne Steuerzeichen" % (feld, maximum), feld)
    if not wert and not leer_ok:
        raise LayoutFehler("blocks_ungueltig", "%s darf nicht leer sein" % feld, feld)
    return wert


def _url(wert, feld) -> str | None:
    if wert is None or wert == "":
        return None
    if not isinstance(wert, str) or len(wert) > URL_MAX or not wert.strip().lower().startswith("https://") or textformat.href_pruefen(wert) is None:
        raise LayoutFehler("url_ungueltig", "%s muss eine https-Adresse sein (ohne Leerzeichen, höchstens %d Zeichen)" % (feld, URL_MAX), feld)
    return textformat.href_pruefen(wert)


def _farbe(wert, feld) -> str | None:
    """``#rrggbb`` (klein geschrieben) oder ``None`` (= Standardfarbe). Alles andere ist ein Fehler, nie ein durchgereichter Stil."""
    if wert is None or wert == "":
        return None
    farbe = textformat.hex_farbe(wert)
    if farbe is None:
        raise LayoutFehler("farbe_ungueltig", "%s muss ein Farbwert der Form #rrggbb sein (oder leer für die Standardfarbe)" % feld, feld)
    return farbe


def _bild_pruefen(mandant: dict, e, feld: str, erlaubt: set, leer_vorbelegen: bool = False) -> dict:
    """Gemeinsame Prüfung eines Bildeintrags (Version 1 und 2): Bild gehört dem Mandanten, Alt-Text, Unterschrift, Link."""
    if not isinstance(e, dict) or set(e) - erlaubt:
        raise LayoutFehler("blocks_ungueltig", "%s: nur %s erlaubt" % (feld, ", ".join(sorted(erlaubt - {"typ"}))), feld)
    bid = e.get("bild_id")
    if isinstance(bid, bool) or not isinstance(bid, int) or not bilder.gehoert_zu(mandant["id"], bid):
        raise LayoutFehler("bild_unbekannt", "%s: Dieses Bild gibt es für diesen Mandanten nicht" % feld, feld + ".bild_id")
    alt = e.get("alt")
    if alt is None or (leer_vorbelegen and alt == ""):                              # Vorbelegung aus dem Bild (Version 2: auch bei leerem Feld)
        alt = bilder.lesen(mandant, bid)["alt"]
    try:
        alt = bilder.alt_pruefen(alt)
    except bilder.BildFehler:
        raise LayoutFehler("alt_fehlt", "%s: Alternativtext fehlt oder ist zu lang (1 bis %d Zeichen)" % (feld, bilder.ALT_MAX), feld + ".alt")
    return {"bild_id": bid, "alt": alt, "bildunterschrift": _einzeilig(e.get("bildunterschrift"), feld + ".bildunterschrift", UNTERSCHRIFT_MAX),
            "url": _url(e.get("url"), feld + ".url")}


def _pruefen_v2(mandant: dict, blocks: dict) -> tuple:
    if set(blocks) - KEYS_V2:
        raise LayoutFehler("blocks_ungueltig", "blocks (version 2): nur version, balken und spalten erlaubt", "blocks")
    balken = blocks.get("balken") or {}
    if not isinstance(balken, dict) or set(balken) - {"text", "url", "farbe"}:
        raise LayoutFehler("blocks_ungueltig", "balken: nur text, url und farbe erlaubt", "balken")
    spalten = blocks.get("spalten")
    if not isinstance(spalten, dict) or set(spalten) != {"links", "rechts"} or not all(isinstance(spalten[k], list) for k in spalten):
        raise LayoutFehler("blocks_ungueltig", "spalten muss {links: [...], rechts: [...]} sein", "spalten")
    ergebnis = {"links": [], "rechts": []}
    bilder_gesamt = text_gesamt = 0
    for name in ("links", "rechts"):
        if len(spalten[name]) > MAX_BLOECKE_JE_SPALTE:
            raise LayoutFehler("zu_viele_bloecke", "Höchstens %d Blöcke je Spalte" % MAX_BLOECKE_JE_SPALTE, "spalten." + name)
        for i, e in enumerate(spalten[name]):
            feld = "spalten.%s[%d]" % (name, i)
            typ = e.get("typ") if isinstance(e, dict) else None
            if typ == "text":
                if set(e) - {"typ", "text_html", "ausrichtung", "farbe"}:
                    raise LayoutFehler("blocks_ungueltig", "%s: nur typ, text_html, ausrichtung und farbe erlaubt" % feld, feld)
                roh = e.get("text_html")
                if not isinstance(roh, str) or len(roh) > textformat.MAX_EINGABE:
                    raise LayoutFehler("blocks_ungueltig", "%s.text_html fehlt oder ist länger als %d Zeichen" % (feld, textformat.MAX_EINGABE), feld + ".text_html")
                sauber = textformat.bereinigen(roh)
                if not textformat.als_text(sauber):
                    raise LayoutFehler("blocks_ungueltig", "%s: Der Text ist leer (nach dem Bereinigen bleibt nichts übrig)" % feld, feld + ".text_html")
                text_gesamt += len(sauber)
                if text_gesamt > MAX_TEXT_GESAMT:
                    raise LayoutFehler("blocks_ungueltig", "Der Text ist insgesamt länger als %d Zeichen" % MAX_TEXT_GESAMT, "spalten")
                ausrichtung = e.get("ausrichtung") or "links"
                if ausrichtung not in AUSRICHTUNGEN:
                    raise LayoutFehler("ausrichtung_ungueltig", "%s.ausrichtung muss links, blocksatz oder zentriert sein" % feld, feld + ".ausrichtung")
                ergebnis[name].append({"typ": "text", "text_html": sauber, "ausrichtung": ausrichtung, "farbe": _farbe(e.get("farbe"), feld + ".farbe")})
            elif typ == "bild":
                bilder_gesamt += 1
                if bilder_gesamt > MAX_BILDER_V2:
                    raise LayoutFehler("zu_viele_bilder", "Höchstens %d Bilder" % MAX_BILDER_V2, "spalten")
                gepruefte = _bild_pruefen(mandant, {k: v for k, v in e.items() if k not in ("typ", "bildunterschrift_farbe")}, feld, BILD_KEYS, True)
                if set(e) - (BILD_KEYS | {"typ", "bildunterschrift_farbe"}):
                    raise LayoutFehler("blocks_ungueltig", "%s: nur typ, bild_id, alt, bildunterschrift, bildunterschrift_farbe und url erlaubt" % feld, feld)
                gepruefte["typ"] = "bild"
                gepruefte["bildunterschrift_farbe"] = _farbe(e.get("bildunterschrift_farbe"), feld + ".bildunterschrift_farbe")
                ergebnis[name].append(gepruefte)
            else:
                raise LayoutFehler("block_typ_ungueltig", "%s: typ muss text oder bild sein" % feld, feld + ".typ")
    if not ergebnis["links"] and not ergebnis["rechts"]:
        raise LayoutFehler("blocks_ungueltig", "Mindestens ein Block ist nötig", "spalten")
    sauber_blocks = {"version": 2, "balken": {"text": _einzeilig(balken.get("text"), "balken.text", BALKEN_MAX), "url": _url(balken.get("url"), "balken.url"),
                                               "farbe": _farbe(balken.get("farbe"), "balken.farbe")}, "spalten": ergebnis}
    return sauber_blocks, klartext_aus(sauber_blocks)


def alle_bilder(blocks: dict) -> list:
    """Alle Bildeinträge eines Entwurfs (Version 1: ``bilder``; Version 2: die Bildblöcke beider Spalten in Lesereihenfolge)."""
    if blocks.get("version") == 2:
        return [b for s in ("links", "rechts") for b in blocks["spalten"][s] if b["typ"] == "bild"]
    return list(blocks.get("bilder") or [])


def pruefen(mandant: dict, blocks) -> tuple:
    """Prüft die Blöcke und gibt ``(bereinigte Blöcke, Klartext)`` zurück. Wirft LayoutFehler. Der Klartext ist die abgeleitete Fassung für den Text-Teil der Mail."""
    if isinstance(blocks, dict) and blocks.get("version") == 2:
        return _pruefen_v2(mandant, blocks)
    if not isinstance(blocks, dict) or set(blocks) - KEYS or blocks.get("version", 1) != 1:
        raise LayoutFehler("blocks_ungueltig", "blocks muss ein Objekt mit version 1, balken, text_html und bilder sein", "blocks")
    balken = blocks.get("balken") or {}
    if not isinstance(balken, dict) or set(balken) - {"text", "url"}:
        raise LayoutFehler("blocks_ungueltig", "balken: nur text und url erlaubt", "balken")
    b_text = _einzeilig(balken.get("text"), "balken.text", BALKEN_MAX)
    b_url = _url(balken.get("url"), "balken.url")
    roh = blocks.get("text_html")
    if not isinstance(roh, str) or len(roh) > textformat.MAX_EINGABE:
        raise LayoutFehler("blocks_ungueltig", "text_html fehlt oder ist länger als %d Zeichen" % textformat.MAX_EINGABE, "text_html")
    sauber = textformat.bereinigen(roh)
    klartext = textformat.als_text(sauber)
    if not klartext:
        raise LayoutFehler("blocks_ungueltig", "Der Text ist leer (nach dem Bereinigen bleibt nichts übrig)", "text_html")
    eingabe_bilder = blocks.get("bilder") or []
    if not isinstance(eingabe_bilder, list):
        raise LayoutFehler("blocks_ungueltig", "bilder muss eine Liste sein", "bilder")
    if len(eingabe_bilder) > MAX_BILDER:
        raise LayoutFehler("zu_viele_bilder", "Höchstens %d Bilder" % MAX_BILDER, "bilder")
    ergebnis_bilder = []
    for i, e in enumerate(eingabe_bilder):
        ergebnis_bilder.append(_bild_pruefen(mandant, e, "bilder[%d]" % i, BILD_KEYS))
    sauber_blocks = {"version": 1, "balken": {"text": b_text, "url": b_url}, "text_html": sauber, "bilder": ergebnis_bilder}
    return sauber_blocks, klartext_aus(sauber_blocks)


def klartext_aus(blocks: dict) -> str:
    """Abgeleiteter Klartext (Text-Teil der Mail): Balken, Text, Bilder mit Alt-Text und Unterschrift. Version 2: linke Spalte, dann rechte Spalte, je in Blockreihenfolge."""
    if blocks.get("version") == 2:
        teile = []
        b = blocks.get("balken") or {}
        if b.get("text"):
            teile.append("%s%s" % (b["text"], " (%s)" % b["url"] if b.get("url") else ""))
        for name in ("links", "rechts"):
            for blk in blocks["spalten"][name]:
                if blk["typ"] == "text":
                    teile.append(textformat.als_text(blk["text_html"]))
                else:
                    zeile = "[Bild: %s]" % blk["alt"]
                    if blk.get("bildunterschrift"):
                        zeile += "\n" + blk["bildunterschrift"]
                    if blk.get("url"):
                        zeile += "\n" + blk["url"]
                    teile.append(zeile)
        return "\n\n".join(t for t in teile if t).strip()
    teile = []
    b = blocks.get("balken") or {}
    if b.get("text"):
        teile.append("%s%s" % (b["text"], " (%s)" % b["url"] if b.get("url") else ""))
    teile.append(textformat.als_text(blocks.get("text_html", "")))
    for bild in blocks.get("bilder") or []:
        zeile = "[Bild: %s]" % bild["alt"]
        if bild.get("bildunterschrift"):
            zeile += "\n" + bild["bildunterschrift"]
        if bild.get("url"):
            zeile += "\n" + bild["url"]
        teile.append(zeile)
    return "\n\n".join(t for t in teile if t).strip()


# ----- Darstellung -----

def _kontrast(farbe: str) -> str:
    """Weiß oder fast Schwarz, je nachdem, was auf der Farbe lesbarer ist (#rrggbb)."""
    r, g, b = (int(farbe[i:i + 2], 16) for i in (1, 3, 5))
    helligkeit = (299 * r + 587 * g + 114 * b) / 1000
    return "#111111" if helligkeit > 150 else "#ffffff"


def logo_adresse(mandant: dict) -> str | None:
    """Öffentliche Adresse des Logos (hochgeladenes Bild hat Vorrang vor der externen Adresse) oder ``None``."""
    d = mandant["design"]
    adresse = d["logo_url"]
    if d.get("logo_bild_id"):
        b = bilder.oeffentliche_adresse(d["logo_bild_id"])
        if b:
            adresse = "%s/%s/bild/%s.%s" % (mailer._basis(mandant), b[0], b[1], b[2])
    return adresse or None


def kopf_html(mandant: dict, balken_text: str | None = None, balken_url: str | None = None, text_farbe: str | None = None) -> str:
    """Kopf aller MailNext-Mails (catrin #19144): Zeile 1 das Logo, zentriert auf dem weißen Kartengrund (kein Hintergrund um das Logo), Zeile 2 der Balken
    in Balken- bzw. Primärfarbe UNTER dem Logo. Ohne Logo steht nur der Balken; fehlt dann auch der Balkentext, trägt er den Namen des Mandanten, damit der
    Kopf nicht ganz fehlt. Ohne Logo und mit Balkentext gibt es nur den Balken, mit Logo aber ohne Balkentext nur das Logo."""
    d = mandant["design"]
    balken_farbe = d.get("balken_farbe") or d["farbe_primaer"]
    logo = logo_adresse(mandant)
    zeilen = ""
    if logo:
        zeilen += ('<tr><td align="center" class="kopf-logo-zeile" style="padding:20px 24px 14px;text-align:center">'
                   '<img src="%s" alt="%s" class="kopf-logo" style="display:inline-block;max-height:48px;max-width:240px;border:0"></td></tr>'
                   % (html.escape(logo, quote=True), html.escape(mandant["name"], quote=True)))
    text = balken_text
    klasse = "balken"
    if not text and not logo:                                    # Ersatz-Kopf (Name des Mandanten), kein Balken im Sinne des Entwurfs
        text, klasse = mandant["name"], "kopf-name"
    if text:
        farbe_text = textformat.hex_farbe(text_farbe) or _kontrast(balken_farbe)      # gewählte Titelfarbe (geprüft) oder automatisch lesbar
        inhalt = html.escape(text)
        if balken_url:
            inhalt = '<a href="%s" style="color:%s;text-decoration:none;display:block">%s</a>' % (html.escape(balken_url, quote=True), farbe_text, inhalt)
        zeilen += ('<tr><td bgcolor="%s" align="center" class="%s" style="background:%s;color:%s;padding:14px 24px;font-size:17px;font-weight:bold;'
                   'line-height:1.3;text-align:center">%s</td></tr>' % (balken_farbe, klasse, balken_farbe, farbe_text, inhalt))
    return zeilen


def _bild_html(mandant: dict, bild: dict, max_px: int = SPALTE_BILD_PX) -> str:
    adresse = bilder.oeffentliche_adresse(bild["bild_id"])
    if not adresse:
        return ""
    with_info = bilder.lesen(mandant, bild["bild_id"])
    src = "%s/%s/bild/%s.%s" % (mailer._basis(mandant), adresse[0], adresse[1], adresse[2])
    breite = min(with_info["breite"], max_px)
    hoehe = max(1, round(with_info["hoehe"] * breite / with_info["breite"]))
    img = ('<img src="%s" alt="%s" width="%d" height="%d" border="0" style="display:block;border:0;outline:none;text-decoration:none;'
           'width:100%%;max-width:%dpx;height:auto">' % (html.escape(src, quote=True), html.escape(bild["alt"], quote=True), breite, hoehe, max_px))
    if bild.get("url"):
        img = '<a href="%s" style="text-decoration:none">%s</a>' % (html.escape(bild["url"], quote=True), img)
    unterschrift = ""
    if bild.get("bildunterschrift"):
        unterschrift = ('<p class="unterschrift" style="margin:6px 0 0;font-size:13px;line-height:1.4;color:%s">%s</p>'
                        % (textformat.hex_farbe(bild.get("bildunterschrift_farbe")) or "#6b7280", html.escape(bild["bildunterschrift"])))
    return '<tr><td style="padding:0 0 18px">%s%s</td></tr>' % (img, unterschrift)


def _spalten_zeile(mandant: dict, blocks: dict) -> str:
    """Inhaltszeile der Version 2: zwei gleich breite Spalten mit den Blöcken in Listenreihenfolge; ist eine Spalte leer, nimmt die andere die volle Breite.
    Auf schmalen Bildschirmen stapeln die Zellen (Klasse sp): links, dann rechts."""
    d = mandant["design"]
    primaer = d["farbe_primaer"]
    spalten = blocks["spalten"]
    belegt = [n for n in ("links", "rechts") if spalten[n]]
    breit = SPALTE_VOLL_PX if len(belegt) == 1 else SPALTE_HALB_PX

    def spalte(name):
        zeilen = []
        for b in spalten[name]:
            if b["typ"] == "text":
                zeilen.append('<tr><td class="txt" style="padding:0 0 18px;font-size:16px;color:%s">%s</td></tr>'
                              % (d["farbe_text"], textformat.rendern(b["text_html"], primaer, primaer, b.get("ausrichtung"), b.get("farbe"))))
            else:
                zeilen.append(_bild_html(mandant, b, breit))
        return '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0">%s</table>' % "".join(zeilen)
    if len(belegt) == 1:
        zellen = '<td class="sp" width="100%%" valign="top" style="padding:0">%s</td>' % spalte(belegt[0])
    else:
        zellen = ('<td class="sp" width="50%%" valign="top" style="padding:0 12px 0 0">%s</td><td class="sp" width="50%%" valign="top" style="padding:0 0 0 12px">%s</td>'
                  % (spalte("links"), spalte("rechts")))
    return '<tr><td style="padding:24px"><table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0"><tr>%s</tr></table></td></tr>' % zellen


def kontrastverhaeltnis(farbe1: str, farbe2: str) -> float:
    """WCAG-Kontrastverhältnis zweier ``#rrggbb``-Farben (1 bis 21)."""
    def leuchtdichte(farbe):
        kanaele = []
        for i in (1, 3, 5):
            c = int(farbe[i:i + 2], 16) / 255
            kanaele.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * kanaele[0] + 0.7152 * kanaele[1] + 0.0722 * kanaele[2]
    a, b = sorted((leuchtdichte(farbe1), leuchtdichte(farbe2)), reverse=True)
    return (a + 0.05) / (b + 0.05)


KONTRAST_MIN = 4.5


def kontrast_warnungen(mandant: dict, blocks: dict) -> list:
    """Hinweise (keine Fehler) bei schwachem Kontrast der gewählten Textfarben zum Hintergrund (Karte weiß, Balken in Balken-/Primärfarbe). Nur Version 2."""
    if blocks.get("version") != 2:
        return []
    d = mandant["design"]
    paare = []
    bal = blocks.get("balken") or {}
    if bal.get("farbe"):
        paare.append(("Die Titelfarbe des Balkens", bal["farbe"], d.get("balken_farbe") or d["farbe_primaer"]))
    for name in ("links", "rechts"):
        for i, b in enumerate(blocks["spalten"][name], 1):
            ort = "%s Spalte, Block %d" % ("Linke" if name == "links" else "Rechte", i)
            if b["typ"] == "text":
                if b.get("farbe"):
                    paare.append(("Die Textfarbe (%s)" % ort, b["farbe"], "#ffffff"))
                for f in sorted(set(re.findall(r'data-farbe="(#[0-9a-f]{6})"', b["text_html"]))):
                    paare.append(("Eine markierte Textstelle (%s)" % ort, f, "#ffffff"))
            elif b.get("bildunterschrift_farbe"):
                paare.append(("Die Farbe der Bildunterschrift (%s)" % ort, b["bildunterschrift_farbe"], "#ffffff"))
    ausgabe = []
    for was, farbe, grund in paare:
        v = kontrastverhaeltnis(farbe, grund)
        if v < KONTRAST_MIN:
            ausgabe.append("%s (%s) hat nur schwachen Kontrast zum Hintergrund (%.1f : 1, empfohlen mindestens 4,5 : 1) und ist schwer lesbar." % (was, farbe, v))
    return ausgabe


def html_rendern(mandant: dict, betreff: str, blocks: dict, einstellungen_url: str | None, ansicht_url: str | None = None) -> str:
    """Vollständiges Mail-HTML des Layout-Newsletters. ``blocks`` müssen aus ``pruefen`` stammen (bereinigt)."""
    d = mandant["design"]
    primaer = d["farbe_primaer"]
    schrift = mailer.mandanten.SCHRIFTEN[d["schrift"]]
    oben = ""
    if ansicht_url:
        oben = ('<tr><td align="center" style="padding:0 0 10px;font-size:12px;color:#6b7280"><a href="%s" style="color:#6b7280;text-decoration:underline">'
                'Im Browser ansehen</a></td></tr>' % html.escape(ansicht_url, quote=True))
    bal = blocks.get("balken") or {}
    kopf = kopf_html(mandant, bal.get("text"), bal.get("url"), bal.get("farbe"))
    if blocks.get("version") == 2:
        text_html = bild_zeilen = None
    else:
        text_html = textformat.rendern(blocks["text_html"], primaer, primaer)
        bild_zeilen = "".join(_bild_html(mandant, b) for b in blocks.get("bilder") or [])
    if blocks.get("version") == 2:
        inhalt_zeile = _spalten_zeile(mandant, blocks)
    elif bild_zeilen:
        inhalt_zeile = ('<tr><td style="padding:24px"><table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0"><tr>'
                        '<td class="sp txt" width="62%%" valign="top" style="padding:0 18px 0 0;font-size:16px;color:%s">%s</td>'
                        '<td class="sp" width="38%%" valign="top" style="padding:0"><table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0">%s</table></td>'
                        '</tr></table></td></tr>' % (d["farbe_text"], text_html, bild_zeilen))
    else:
        inhalt_zeile = '<tr><td class="txt" style="padding:24px;font-size:16px;color:%s">%s</td></tr>' % (d["farbe_text"], text_html)
    if einstellungen_url:
        fuss = ('<p style="margin:0 0 8px">Sie erhalten diese Mail, weil Sie sich zum Newsletter angemeldet haben. '
                '<a href="%s" style="color:%s">Einstellungen ändern oder abmelden</a></p>%s'
                % (html.escape(einstellungen_url, quote=True), primaer, mailer._fusszeile_html(mandant)))
    else:                                                    # Browser-Ansicht: für alle gleich, deshalb kein persönlicher Link
        fuss = ('<p style="margin:0 0 8px">Zum Abmelden oder Ändern Ihrer Einstellungen nutzen Sie bitte den Link in Ihrer E-Mail.</p>%s'
                % mailer._fusszeile_html(mandant))
    return ('<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark"><title>%s</title>'
            '<style>'
            '@media only screen and (max-width:480px){.sp{display:block!important;width:100%%!important;padding:0 0 12px!important}.kopf-logo{max-width:200px!important}}'
            '@media (prefers-color-scheme:dark){.karte{background:#1e232a!important}.aussen{background:#12161b!important}.txt{color:#e6e8eb!important}'
            '.txt a{color:#9ec5ff!important}.unterschrift{color:#aab2bd!important}}'
            '</style></head>'
            '<body style="margin:0;padding:0;background:%s;font-family:%s;color:%s" class="aussen">'
            '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0" class="aussen" style="background:%s"><tr><td align="center" style="padding:24px 12px">'
            '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%%">%s'
            '<tr><td style="padding:0"><table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0" class="karte" '
            'style="background:#ffffff;border-radius:8px;overflow:hidden">'
            '%s%s'
            '<tr><td style="padding:16px 24px;border-top:1px solid #e5e7eb;font-size:12px;color:#6b7280;line-height:1.5">%s</td></tr>'
            '</table></td></tr></table></td></tr></table></body></html>'
            % (html.escape(betreff), d["farbe_hintergrund"], schrift, d["farbe_text"], d["farbe_hintergrund"], oben, kopf, inhalt_zeile, fuss))
