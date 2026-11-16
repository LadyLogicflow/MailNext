"""Formatierter Text für Newsletter: erlaubte HTML-Teilmenge (Allowlist), serverseitig bereinigt, ohne Bibliothek.

Erlaubt sind p, br, strong (auch b), em (auch i), h2, h3, ul, ol, li und a mit href (https oder mailto). Zentrierung steht als Attribut
``data-ausrichtung="zentriert"`` an p, h2 und h3. Alles andere wird entfernt: Skripte und Stile samt Inhalt, alle übrigen Tags nur als Hülle (der Text bleibt),
Attribute (Stil, Klasse, Ereignis-Handler, ...) immer, Bilder im Text, Kommentare, Verarbeitungsanweisungen. Die Ausgabe ist die KANONISCHE Fassung und wird
gespeichert; ``rendern`` macht daraus das mail-taugliche HTML mit Inline-Stilen, ``als_text`` den Klartext-Teil. Nie Roh-HTML des Betreibers in der Mail."""
import html
import re
from html.parser import HTMLParser

MAX_EINGABE = 20000
MAX_TIEFE = 8
MAX_HREF = 500

BLOECKE = ("p", "h2", "h3")
LISTEN = ("ul", "ol")
INLINE = ("strong", "em", "a")
ALIAS = {"b": "strong", "i": "em"}
ERLAUBT = set(BLOECKE) | set(LISTEN) | set(INLINE) | {"li", "br"}
MIT_INHALT_ENTFERNEN = {"script", "style", "iframe", "object", "embed", "noscript", "template", "textarea", "title", "head", "svg", "math", "select", "option"}
AUSRICHTUNG = "data-ausrichtung"


def href_pruefen(wert) -> str | None:
    """Gibt die bereinigte Adresse zurück (https:// oder mailto:), sonst None."""
    w = (wert or "").strip()
    if not w or len(w) > MAX_HREF or re.search(r"[\s\x00-\x1f\x7f<>\"'`\\]", w):
        return None
    kleiner = w.lower()
    if kleiner.startswith("https://") and len(w) > 8 and "@" not in w.split("/", 3)[2]:                  # keine Zugangsdaten in der Adresse
        return "https://" + w[8:]
    if kleiner.startswith("mailto:") and re.fullmatch(r"mailto:[^@\s?#]{1,64}@[A-Za-z0-9.-]{1,200}\.[A-Za-z]{2,}", w, re.I):
        return "mailto:" + w[7:]
    return None


class _Bereiniger(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.teile: list = []
        self.stack: list = []                     # offene erlaubte Tags
        self.verwerfen = 0                        # Tiefe in Tags, deren Inhalt entfällt
        self.in_a = False

    # --- Hilfen ---
    def _oeffne(self, tag, attribute=""):
        self.teile.append("<%s%s>" % (tag, attribute))
        self.stack.append(tag)

    def _schliesse_bis(self, tag):
        while self.stack:
            t = self.stack.pop()
            self.teile.append("</%s>" % t)
            if t == "a":
                self.in_a = False
            if t == tag:
                return

    def _schliesse_inline(self):
        while self.stack and self.stack[-1] in INLINE:
            t = self.stack.pop()
            self.teile.append("</%s>" % t)
            if t == "a":
                self.in_a = False

    def _block_offen(self):
        return any(t in BLOECKE or t == "li" for t in self.stack)

    def _absatz_sicherstellen(self):
        """Text oder Inline-Tag ohne umgebenden Block: impliziter Absatz."""
        if any(t in BLOECKE or t == "li" for t in self.stack):
            return
        if self.stack and self.stack[-1] in LISTEN:                  # Text direkt in ul/ol: gehört in kein li, wird verworfen
            return
        if len(self.stack) < MAX_TIEFE:
            self._oeffne("p")

    # --- Parser-Ereignisse ---
    def handle_starttag(self, tag, attrs):
        tag = ALIAS.get(tag.lower(), tag.lower())
        if self.verwerfen or tag in MIT_INHALT_ENTFERNEN:
            if tag in MIT_INHALT_ENTFERNEN:
                self.verwerfen += 1
            return
        if tag not in ERLAUBT or len(self.stack) >= MAX_TIEFE:
            return
        werte = {k.lower(): v for k, v in attrs}
        if tag == "br":
            if self._block_offen():
                self.teile.append("<br>")
            return
        if tag in BLOECKE:
            self._schliesse_inline()
            while self.stack and self.stack[-1] in BLOECKE:
                self._schliesse_bis(self.stack[-1])
            if "li" in self.stack:                                    # Block in li: als Inline-Text behandeln (Hülle weg)
                return
            ausr = ' %s="zentriert"' % AUSRICHTUNG if (werte.get(AUSRICHTUNG) or "").strip().lower() == "zentriert" else ""
            self._oeffne(tag, ausr)
        elif tag in LISTEN:
            self._schliesse_inline()
            while self.stack and self.stack[-1] in BLOECKE:
                self._schliesse_bis(self.stack[-1])
            if "li" in self.stack:
                return
            self._oeffne(tag)
        elif tag == "li":
            self._schliesse_inline()
            if "li" in self.stack:
                self._schliesse_bis("li")
            if self.stack and self.stack[-1] in LISTEN:
                self._oeffne("li")
        elif tag == "a":
            ziel = href_pruefen(werte.get("href"))
            if ziel is None or self.in_a:
                return
            self._absatz_sicherstellen()
            if any(t in BLOECKE or t == "li" for t in self.stack):
                self.in_a = True
                self._oeffne("a", ' href="%s"' % html.escape(ziel, quote=True))
        else:                                                         # strong, em
            self._absatz_sicherstellen()
            if any(t in BLOECKE or t == "li" for t in self.stack):
                self._oeffne(tag)

    def handle_endtag(self, tag):
        tag = ALIAS.get(tag.lower(), tag.lower())
        if tag in MIT_INHALT_ENTFERNEN:
            if self.verwerfen:
                self.verwerfen -= 1
            return
        if self.verwerfen or tag not in ERLAUBT or tag == "br":
            return
        if tag in self.stack:
            self._schliesse_bis(tag)

    def handle_data(self, data):
        if self.verwerfen:
            return
        if not data.strip() and not self._block_offen():
            return
        self._absatz_sicherstellen()
        if self.stack and self.stack[-1] in LISTEN:
            return
        if any(t in BLOECKE or t == "li" for t in self.stack):
            self.teile.append(html.escape(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", data), quote=False))

    def handle_comment(self, data):
        pass

    def handle_decl(self, decl):
        pass

    def handle_pi(self, data):
        pass

    def unknown_decl(self, data):
        pass


def bereinigen(eingabe) -> str:
    """Kanonische, bereinigte Fassung. Leerer Rest ist ein leerer String."""
    if not isinstance(eingabe, str):
        return ""
    parser = _Bereiniger()
    parser.feed(eingabe[:MAX_EINGABE * 2])
    parser.close()
    while parser.stack:
        parser._schliesse_bis(parser.stack[-1])
    ergebnis = "".join(parser.teile)
    for _ in range(MAX_TIEFE + 2):                                    # leere Hüllen bis nichts mehr übrig ist (auch verschachtelt)
        vorher = ergebnis
        ergebnis = re.sub(r"<(p|h2|h3)( data-ausrichtung=\"zentriert\")?>(\s|<br>)*</\1>", "", ergebnis)      # leere Absätze
        ergebnis = re.sub(r"<li>(\s|<br>)*</li>", "", ergebnis)
        ergebnis = re.sub(r"<(ul|ol)>\s*</\1>", "", ergebnis)
        if ergebnis == vorher:
            break
    ergebnis = re.sub(r"<p( data-ausrichtung=\"zentriert\")?>(\s|<br>)+", lambda m: "<p%s>" % (m.group(1) or ""), ergebnis)
    ergebnis = re.sub(r"(\s|<br>)+</p>", "</p>", ergebnis)
    return ergebnis.strip()


def als_text(sauber: str) -> str:
    """Klartext aus der bereinigten Fassung: Absätze durch Leerzeilen, Listen mit '- ' bzw. '1. ', Links als 'Text (Adresse)'."""
    ausgabe, link, zaehler, liste = [], [], [0], []

    class _P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)

        def handle_starttag(self, tag, attrs):
            if tag in ("ul", "ol"):
                liste.append(tag)
                zaehler.append(0)
            elif tag == "li":
                zaehler[-1] += 1
                ausgabe.append("\n" + ("- " if liste and liste[-1] == "ul" else "%d. " % zaehler[-1]))
            elif tag == "br":
                ausgabe.append("\n")
            elif tag == "a":
                link.append((dict(attrs).get("href", ""), len(ausgabe)))

        def handle_endtag(self, tag):
            if tag in ("p", "h2", "h3"):
                ausgabe.append("\n\n")
            elif tag in ("ul", "ol"):
                if liste:
                    liste.pop()
                    zaehler.pop()
                ausgabe.append("\n\n")
            elif tag == "a" and link:
                href, ab = link.pop()
                sichtbar = "".join(ausgabe[ab:]).strip()
                ziel = href[7:] if href.startswith("mailto:") else href
                if sichtbar != ziel and ziel:
                    ausgabe.append(" (%s)" % ziel)

        def handle_data(self, data):
            ausgabe.append(data)

    p = _P()
    p.feed(sauber or "")
    p.close()
    text = "".join(ausgabe)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def rendern(sauber: str, farbe_link: str, farbe_ueberschrift: str) -> str:
    """Mail-taugliches HTML (nur Inline-Stile) aus der bereinigten Fassung. Eingabe MUSS bereinigt sein (``bereinigen``)."""
    stile = {
        "p": "margin:0 0 14px;line-height:1.55;", "h2": "margin:0 0 12px;font-size:22px;line-height:1.3;color:%s;" % farbe_ueberschrift,
        "h3": "margin:0 0 10px;font-size:18px;line-height:1.3;color:%s;" % farbe_ueberschrift,
        "ul": "margin:0 0 14px;padding-left:22px;", "ol": "margin:0 0 14px;padding-left:22px;", "li": "margin:0 0 6px;line-height:1.5;",
    }
    ausgabe = []

    class _P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)

        def handle_starttag(self, tag, attrs):
            werte = dict(attrs)
            if tag in stile:
                zentriert = "text-align:center;" if werte.get(AUSRICHTUNG) == "zentriert" else ""
                ausgabe.append('<%s style="%s%s">' % (tag, stile[tag], zentriert))
            elif tag == "a":
                ausgabe.append('<a href="%s" style="color:%s;text-decoration:underline;">' % (html.escape(werte.get("href", ""), quote=True), farbe_link))
            else:
                ausgabe.append("<%s>" % tag)

        def handle_endtag(self, tag):
            ausgabe.append("</%s>" % tag)

        def handle_data(self, data):
            ausgabe.append(data)

        def handle_entityref(self, name):
            ausgabe.append("&%s;" % name)

        def handle_charref(self, name):
            ausgabe.append("&#%s;" % name)

    p = _P()
    p.feed(sauber or "")
    p.close()
    return "".join(ausgabe)
