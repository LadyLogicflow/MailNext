"""Layout-Newsletter (Etappe 2, v0.6.1): Blöcke prüfen, bereinigen und als Mail darstellen.

Blockschema (version 1): ``balken`` {text 0-60 Zeichen, url https oder null} (leerer Text = kein Balken), ``text_html`` (erlaubte HTML-Teilmenge, siehe textformat.py,
höchstens 20 000 Zeichen), ``bilder`` 0 bis 6 Einträge {bild_id (Bild des Mandanten), alt 1-150, bildunterschrift 0-200, url https oder null}. Logo und Fuß kommen aus dem
Mandanten. Die Mail ist ein Tabellen-Layout (600 px, Mail-Programme brauchen das): Kopf mit Logo, Balken, zwei Spalten (Text links, Bilder rechts), Fuß; auf schmalen Bildschirmen
stapeln die Spalten, Dunkelmodus per color-scheme. Bilder nur vom eigenen Host (Auslieferung bilder.py), kein Tracking."""
import html
import re

import bilder
import mailer
import textformat

MAX_BILDER = 6
BALKEN_MAX = 60
UNTERSCHRIFT_MAX = 200
URL_MAX = 300
SPALTE_BILD_PX = 216
KEYS = {"version", "balken", "text_html", "bilder"}


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


def pruefen(mandant: dict, blocks) -> tuple:
    """Prüft die Blöcke und gibt ``(bereinigte Blöcke, Klartext)`` zurück. Wirft LayoutFehler. Der Klartext ist die abgeleitete Fassung für den Text-Teil der Mail."""
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
        feld = "bilder[%d]" % i
        if not isinstance(e, dict) or set(e) - {"bild_id", "alt", "bildunterschrift", "url"}:
            raise LayoutFehler("blocks_ungueltig", "%s: nur bild_id, alt, bildunterschrift und url erlaubt" % feld, feld)
        bid = e.get("bild_id")
        if isinstance(bid, bool) or not isinstance(bid, int) or not bilder.gehoert_zu(mandant["id"], bid):
            raise LayoutFehler("bild_unbekannt", "%s: Dieses Bild gibt es für diesen Mandanten nicht" % feld, feld + ".bild_id")
        alt = e.get("alt")
        if alt is None:                                                              # Vorbelegung aus dem Bild
            alt = bilder.lesen(mandant, bid)["alt"]
        try:
            alt = bilder.alt_pruefen(alt)
        except bilder.BildFehler:
            raise LayoutFehler("alt_fehlt", "%s: Alternativtext fehlt oder ist zu lang (1 bis %d Zeichen)" % (feld, bilder.ALT_MAX), feld + ".alt")
        ergebnis_bilder.append({"bild_id": bid, "alt": alt, "bildunterschrift": _einzeilig(e.get("bildunterschrift"), feld + ".bildunterschrift", UNTERSCHRIFT_MAX),
                                "url": _url(e.get("url"), feld + ".url")})
    sauber_blocks = {"version": 1, "balken": {"text": b_text, "url": b_url}, "text_html": sauber, "bilder": ergebnis_bilder}
    return sauber_blocks, klartext_aus(sauber_blocks)


def klartext_aus(blocks: dict) -> str:
    """Abgeleiteter Klartext (Text-Teil der Mail): Balken, Text, Bilder mit Alt-Text und Unterschrift."""
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


def _bild_html(mandant: dict, bild: dict) -> str:
    adresse = bilder.oeffentliche_adresse(bild["bild_id"])
    if not adresse:
        return ""
    with_info = bilder.lesen(mandant, bild["bild_id"])
    src = "%s/%s/bild/%s.%s" % (mailer._basis(mandant), adresse[0], adresse[1], adresse[2])
    breite = min(with_info["breite"], SPALTE_BILD_PX)
    hoehe = max(1, round(with_info["hoehe"] * breite / with_info["breite"]))
    img = ('<img src="%s" alt="%s" width="%d" height="%d" border="0" style="display:block;border:0;outline:none;text-decoration:none;'
           'width:100%%;max-width:%dpx;height:auto">' % (html.escape(src, quote=True), html.escape(bild["alt"], quote=True), breite, hoehe, SPALTE_BILD_PX))
    if bild.get("url"):
        img = '<a href="%s" style="text-decoration:none">%s</a>' % (html.escape(bild["url"], quote=True), img)
    unterschrift = ""
    if bild.get("bildunterschrift"):
        unterschrift = '<p class="unterschrift" style="margin:6px 0 0;font-size:13px;line-height:1.4;color:#6b7280">%s</p>' % html.escape(bild["bildunterschrift"])
    return '<tr><td style="padding:0 0 18px">%s%s</td></tr>' % (img, unterschrift)


def html_rendern(mandant: dict, betreff: str, blocks: dict, einstellungen_url: str | None, ansicht_url: str | None = None) -> str:
    """Vollständiges Mail-HTML des Layout-Newsletters. ``blocks`` müssen aus ``pruefen`` stammen (bereinigt)."""
    d = mandant["design"]
    primaer = d["farbe_primaer"]
    balken_farbe = d.get("balken_farbe") or primaer
    schrift = mailer.mandanten.SCHRIFTEN[d["schrift"]]
    logo_adresse = d["logo_url"]
    if d.get("logo_bild_id"):
        b = bilder.oeffentliche_adresse(d["logo_bild_id"])
        if b:
            logo_adresse = "%s/%s/bild/%s.%s" % (mailer._basis(mandant), b[0], b[1], b[2])
    if logo_adresse:
        logo = ('<img src="%s" alt="%s" style="max-height:48px;max-width:240px;display:block;border:0">'
                % (html.escape(logo_adresse, quote=True), html.escape(mandant["name"], quote=True)))
    else:
        logo = '<span style="font-size:20px;font-weight:bold;color:%s">%s</span>' % (_kontrast(primaer), html.escape(mandant["name"]))
    oben = ""
    if ansicht_url:
        oben = ('<tr><td align="center" style="padding:0 0 10px;font-size:12px;color:#6b7280"><a href="%s" style="color:#6b7280;text-decoration:underline">'
                'Im Browser ansehen</a></td></tr>' % html.escape(ansicht_url, quote=True))
    balken = ""
    bal = blocks.get("balken") or {}
    if bal.get("text"):
        farbe_text = _kontrast(balken_farbe)
        inhalt = html.escape(bal["text"])
        if bal.get("url"):
            inhalt = '<a href="%s" style="color:%s;text-decoration:none;display:block">%s</a>' % (html.escape(bal["url"], quote=True), farbe_text, inhalt)
        balken = ('<tr><td bgcolor="%s" align="center" class="balken" style="background:%s;color:%s;padding:14px 24px;font-size:17px;font-weight:bold;'
                  'line-height:1.3">%s</td></tr>' % (balken_farbe, balken_farbe, farbe_text, inhalt))
    text_html = textformat.rendern(blocks["text_html"], primaer, primaer)
    bild_zeilen = "".join(_bild_html(mandant, b) for b in blocks.get("bilder") or [])
    if bild_zeilen:
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
            '<tr><td bgcolor="%s" style="background:%s;padding:16px 24px">%s</td></tr>%s%s'
            '<tr><td style="padding:16px 24px;border-top:1px solid #e5e7eb;font-size:12px;color:#6b7280;line-height:1.5">%s</td></tr>'
            '</table></td></tr></table></td></tr></table></body></html>'
            % (html.escape(betreff), d["farbe_hintergrund"], schrift, d["farbe_text"], d["farbe_hintergrund"], oben, primaer, primaer, logo, balken, inhalt_zeile, fuss))
