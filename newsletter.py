"""Newsletter: Entwurf, Testmail, Freigabe, Empfängerzeilen, Versandlauf, Protokoll (Meilenstein B). Alles je Mandant.

Schutzregeln (jede hat einen Test mit Gegenprobe):
- Freigabe nur nach einer Testmail zum aktuellen Stand (SHA-256 über Betreff, Text, Ziel, Segment). Jede Änderung macht die Testmail ungültig.
- Echtversand (Ziel 'abonnenten') ist je Mandant gesperrt, bis ein Betreiber ihn ausdrücklich freigibt; auch der Versandlauf prüft es nochmals.
- Die Empfängerliste wird bei der Freigabe festgeschrieben: nur bestätigte Adressen (nicht abgemeldet, nicht unzustellbar), passend zum Segment.
- Höchstens einmal je Person und Entwurf (UNIQUE) und nie automatisch wiederholt, wenn der Ausgang unklar ist.
- Vor jedem Senden wird der Abmeldestatus nochmals geprüft. Höchstens 100 Mails je Stunde und Mandant, höchstens 5 je Lauf.
- Jede Mail: persönlicher Abmelde- und Einstellungslink, List-Unsubscribe mit One-Click, Text und HTML, kein Tracking."""
import csv
import hashlib
import html
import io
import json
import re
from datetime import datetime, timedelta, timezone

import abonnenten
import db
import mailer
import mandanten
import schluessel

LIMIT_PRO_STUNDE = 100                                                                    # Standard je Mandant, einstellbar (limit_pro_stunde)
LIMIT_PRO_STUNDE_MIN, LIMIT_PRO_STUNDE_MAX = 1, 600
LIMIT_PRO_LAUF = 5                                                                        # Mindestzahl je Minute; bei höherem Stundenlimit wächst sie mit
PFLICHTANGABEN = ("impressum_url", "datenschutz_url", "firmenangaben", "absender_adresse")      # Design-Felder, ohne die kein Echtversand freigegeben wird
VERSUCHE_MAX = 3
WIEDERHOLUNG_ABSTAND_MINUTEN = 5                                                          # nach einem vorübergehenden Fehler wird die Zeile erst später erneut versucht
UNKLAR_NACH_MINUTEN = 10
ZIELE = ("testliste", "abonnenten")
URL = re.compile(r"https://[^\s<>\"']+")


class Fehler(Exception):
    """Fehler mit Code für die Betreiber-Antwort (status = HTTP-Status)."""

    def __init__(self, code, meldung, status=409, feld=None):
        super().__init__(code)
        self.code, self.meldung, self.status, self.feld = code, meldung, status, feld


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _jetzt():
    return datetime.now(timezone.utc)


# ----- Darstellung -----

def text_zu_html(text: str) -> str:
    """Klartext → HTML: maskiert, Leerzeilen sind Absätze, https-Adressen werden Links. Es gibt kein Roh-HTML des Betreibers."""
    absaetze = []
    for block in re.split(r"\n\s*\n", text.strip()):
        teile, rest = [], block
        while rest:
            m = URL.search(rest)
            if not m:
                teile.append(html.escape(rest))
                break
            teile.append(html.escape(rest[:m.start()]))
            url = m.group(0).rstrip(".,;:!?)")
            teile.append('<a href="%s">%s</a>' % (html.escape(url, quote=True), html.escape(url)))
            rest = rest[m.start() + len(url):]
        absaetze.append("<p>%s</p>" % "".join(teile).replace("\n", "<br>"))
    return "\n".join(absaetze)


def darstellen(mandant: dict, betreff: str, text: str, persoenliches_token: str | None, blocks: dict | None = None, ansicht_token: str | None = None):
    """(Betreff, Text, HTML, Kopfzeilen). Ohne Token (Testmail, Vorschau) zeigen die Links auf eine ungültige Vorschau."""
    token = persoenliches_token or "u1.vorschau.vorschau"
    einstellungen = mailer.link_einstellungen(mandant, token)
    eins_klick = "%s/%s/newsletter/abmelden-one-click/%s" % (mailer._basis(mandant), mandant["slug"], token)
    fuss_text = "\n\n--\nEinstellungen ändern oder abmelden: %s\n\n%s" % (einstellungen, mailer._fusszeile_text(mandant))
    farbe = mandant["design"]["farbe_primaer"]
    fuss_html = ('<p style="font-size:13px;margin-top:24px">Sie erhalten diese Mail, weil Sie sich zum Newsletter angemeldet haben. '
                 '<a href="%s" style="color:%s">Einstellungen ändern oder abmelden</a></p>' % (html.escape(einstellungen, quote=True), farbe))
    if blocks is not None:                                    # Layout-Newsletter (Etappe 2): text ist die abgeleitete Klartext-Fassung
        import layout
        ansicht = ansicht_adresse(mandant, ansicht_token or "vorschau")          # ohne gespeicherten Entwurf (Vorschau): Platzhalter-Link
        html_text = layout.html_rendern(mandant, betreff, blocks, einstellungen, ansicht)
        text = "Im Browser ansehen: %s\n\n%s" % (ansicht, text.strip())
    else:
        html_text = mailer.html_rahmen(mandant, betreff, text_zu_html(text) + fuss_html)
    header = {"List-Unsubscribe": "<%s>" % eins_klick, "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    return betreff, text.strip() + fuss_text, html_text, header


def ansicht_adresse(mandant: dict, kennung: str) -> str:
    """Adresse der Browser-Ansicht ('Im Browser ansehen'): dauerhaft erreichbar, ohne Anmeldung und ohne Tracking."""
    return "%s/%s/newsletter/ansicht/%s" % (mailer._basis(mandant), mandant["slug"], kennung)


def _ansicht_kennung(z) -> str:
    """Kennung der Browser-Ansicht eines Layout-Entwurfs; fehlt sie (ältere Zeile), wird sie einmalig vergeben."""
    if z["ansicht_token"]:
        return z["ansicht_token"]
    import secrets
    neu = secrets.token_urlsafe(18)
    with db.verbindung() as c:
        c.execute("UPDATE entwurf SET ansicht_token=? WHERE id=? AND ansicht_token IS NULL", (neu, z["id"]))
        return c.execute("SELECT ansicht_token FROM entwurf WHERE id=?", (z["id"],)).fetchone()["ansicht_token"]


def ansicht_html(slug: str, kennung: str) -> str | None:
    """HTML der Browser-Ansicht für /<slug>/newsletter/ansicht/<kennung>, sonst None. Für alle gleich: ohne persönliche Links."""
    mandant = mandanten.lesen_slug(slug)
    if mandant is None or not isinstance(kennung, str) or not 16 <= len(kennung) <= 64:
        return None
    with db.verbindung() as c:
        z = c.execute("SELECT * FROM entwurf WHERE mandant_id=? AND ansicht_token=? AND format='layout'", (mandant["id"], kennung)).fetchone()
    if z is None:
        return None
    import layout
    return layout.html_rendern(mandant, z["betreff"], _blocks_von(z), None, None)


def layout_vorschau(mandant: dict, betreff, blocks) -> dict:
    """Vorschau eines noch nicht gespeicherten Layout-Entwurfs: das echte Mail-HTML (dieselbe Funktion wie beim Versand) und der Klartext-Teil.
    Speichert nichts. Wirft Fehler (400) bei ungültigen Blöcken."""
    betreff = (betreff or "Vorschau").strip() if isinstance(betreff, str) else "Vorschau"
    if not 1 <= len(betreff) <= 150 or "\n" in betreff or "\r" in betreff:
        raise Fehler("betreff_ungueltig", "Der Betreff muss eine Zeile mit 1 bis 150 Zeichen sein", 400)
    sauber, klartext = _blocks_pruefen(mandant, blocks)
    _, text, html_text, _ = darstellen(mandant, betreff, klartext, None, blocks=sauber)
    return {"html": html_text, "text": text, "warnungen": _warnungen(mandant, sauber), "blocks": sauber}


def _warnungen(mandant: dict, blocks: dict) -> list:
    d = mandant["design"]
    w = []
    if not d.get("logo_bild_id") and not d.get("logo_url"):
        w.append("Es ist kein Logo hinterlegt, im Kopf steht nur der Name des Mandanten.")
    if not d.get("firmenangaben") or not d.get("impressum_url"):
        w.append("Die Fußzeile hat keine vollständigen Firmenangaben oder kein Impressum (Pflichtangaben).")
    if not mailer._basis(mandant).startswith("https://"):
        w.append("Die Basis-Adresse (%s) ist nicht https: Bilder und Links funktionieren in echten Mails nur, wenn sie von außen erreichbar ist." % mailer._basis(mandant))
    import bilder
    summe = 0
    for b in blocks.get("bilder") or []:
        info = bilder.lesen(mandant, b["bild_id"])
        summe += info["groesse_bytes"] if info else 0
    if summe > 1_500_000:
        w.append("Die Bilder sind zusammen %.1f MB groß; das kann das Laden der Mail verlangsamen." % (summe / 1_000_000))
    if not (blocks.get("balken") or {}).get("text"):
        w.append("Es ist kein Balken gesetzt.")
    return w


# ----- Entwürfe -----

def _hash(betreff, text, ziel, segment, blocks=None) -> str:
    # Textentwürfe behalten ihren bisherigen Hash; Layout-Entwürfe binden die Blöcke (inkl. Bild-Nummern) in die Freigabe ein
    roh = json.dumps([betreff, text, ziel, segment] if blocks is None else [betreff, text, ziel, segment, blocks], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()


def _segment_pruefen(mandant: dict, segment) -> dict:
    segment = segment or {}
    if not isinstance(segment, dict) or set(segment) - {"rollen", "interessen", "tags", "tags_modus"}:
        raise Fehler("segment_ungueltig", "segment darf nur rollen, interessen, tags und tags_modus enthalten", 400)
    ergebnis = {}
    for feld, erlaubt in (("rollen", {e["wert"] for e in mandant["design"]["rollen"]}),
                          ("interessen", {e["wert"] for e in mandant["design"]["interessen"]})):
        werte = segment.get(feld)
        if werte is None:
            ergebnis[feld] = None
            continue
        if not isinstance(werte, list) or not werte or any(not isinstance(w, str) or w not in erlaubt for w in werte):
            raise Fehler("segment_ungueltig", "%s: unbekannter oder leerer Wert" % feld, 400)
        ergebnis[feld] = sorted(set(werte))
    tags = segment.get("tags")
    if tags is not None:
        # Tags sind frei vergeben (Import): erlaubt sind die Tags, die bei bestätigten Abonnentinnen dieses Mandanten vorkommen (Schreibweise wie dort).
        if not isinstance(tags, list) or not tags or len(tags) > 20 or any(not isinstance(t, str) for t in tags):
            raise Fehler("segment_ungueltig", "tags: leer, zu viele (höchstens 20) oder kein Text", 400)
        import abonnenten
        vorhanden = {e["tag"].lower(): e["tag"] for e in abonnenten.tags_liste(mandant["id"])}
        if any(t.strip().lower() not in vorhanden for t in tags):
            raise Fehler("segment_ungueltig", "tags: unbekannter Tag", 400)
        ergebnis["tags"] = sorted({vorhanden[t.strip().lower()] for t in tags})
        modus = segment.get("tags_modus", "oder")
        if modus not in ("oder", "und"):
            raise Fehler("segment_ungueltig", "tags_modus muss oder oder und sein", 400)
        ergebnis["tags_modus"] = modus
    elif segment.get("tags_modus") is not None:
        raise Fehler("segment_ungueltig", "tags_modus gehört nur zusammen mit tags", 400)
    return ergebnis


def _inhalt_pruefen(mandant, betreff, text, ziel, segment):
    betreff = (betreff or "").strip() if isinstance(betreff, str) else ""
    if not 1 <= len(betreff) <= 150 or "\n" in betreff or "\r" in betreff:
        raise Fehler("betreff_ungueltig", "Der Betreff muss eine Zeile mit 1 bis 150 Zeichen sein", 400)
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 50000:
        raise Fehler("text_ungueltig", "Der Text muss 1 bis 50000 Zeichen haben", 400)
    if ziel not in ZIELE:
        raise Fehler("ziel_ungueltig", "ziel muss testliste oder abonnenten sein", 400)
    return betreff, text.strip(), ziel, _segment_pruefen(mandant, segment)


def _blocks_pruefen(mandant, blocks):
    """Layout-Blöcke prüfen; Fehler als newsletter.Fehler (400) mit Feld. Gibt (bereinigte Blöcke, Klartext) zurück."""
    import layout
    try:
        return layout.pruefen(mandant, blocks)
    except layout.LayoutFehler as f:
        raise Fehler(f.code, f.meldung, 400, f.feld)


def _blocks_von(z):
    """Gespeicherte Blöcke eines Layout-Entwurfs, sonst None."""
    return json.loads(z["blocks"]) if z["format"] == "layout" and z["blocks"] else None


def _zeile(mandant_id, entwurf_id):
    with db.verbindung() as c:
        return c.execute("SELECT * FROM entwurf WHERE id=? AND mandant_id=?", (int(entwurf_id), int(mandant_id))).fetchone()


def _entwurf_dict(z, mandant=None) -> dict:
    return {"ansicht_url": (ansicht_adresse(mandant, _ansicht_kennung(z)) if mandant is not None and z["format"] == "layout" else None), "id": z["id"], "betreff": z["betreff"], "format": z["format"], "blocks": _blocks_von(z), "text": z["text"], "ziel": z["ziel"],
            "segment": json.loads(z["segment"]), "status": z["status"],
            "content_hash": z["content_hash"], "erstellt": z["erstellt"], "geaendert": z["geaendert"],
            "testmail": {"gesendet_am": z["testmail_am"], "passender_stand": bool(z["testmail_hash"] and z["testmail_hash"] == z["content_hash"])}}


def anlegen(mandant: dict, betreff, text, ziel, segment, format="text", blocks=None) -> dict:
    if format not in ("text", "layout"):
        raise Fehler("format_ungueltig", "format muss text oder layout sein", 400, "format")
    if format == "layout":
        if text is not None:
            raise Fehler("format_passt_nicht", "Ein Layout-Entwurf hat blocks statt text", 400, "text")
        blocks, text = _blocks_pruefen(mandant, blocks)
        betreff, text, ziel, segment = _inhalt_pruefen(mandant, betreff, text, ziel, segment)
        blocks_json = json.dumps(blocks, ensure_ascii=False)
    else:
        if blocks is not None:
            raise Fehler("format_passt_nicht", "Ein Text-Entwurf hat text statt blocks", 400, "blocks")
        betreff, text, ziel, segment = _inhalt_pruefen(mandant, betreff, text, ziel, segment)
        blocks_json = None
    zeit = _iso(_jetzt())
    with db.verbindung() as c:
        import secrets
        cur = c.execute("INSERT INTO entwurf(mandant_id, betreff, text, ziel, segment, content_hash, erstellt, geaendert, format, blocks, ansicht_token) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (mandant["id"], betreff, text, ziel, json.dumps(segment), _hash(betreff, text, ziel, segment, blocks if format == "layout" else None), zeit, zeit,
                         format, blocks_json, secrets.token_urlsafe(18) if format == "layout" else None))
    return lesen(mandant, cur.lastrowid)


def lesen(mandant: dict, entwurf_id: int) -> dict | None:
    z = _zeile(mandant["id"], entwurf_id)
    return _entwurf_dict(z, mandant) if z else None


def liste(mandant: dict) -> list:
    with db.verbindung() as c:
        zeilen = c.execute("SELECT * FROM entwurf WHERE mandant_id=? ORDER BY id DESC", (mandant["id"],)).fetchall()
    return [{k: _entwurf_dict(z)[k] for k in ("id", "betreff", "format", "status", "ziel", "erstellt", "geaendert")} for z in zeilen]


def aendern(mandant: dict, entwurf_id: int, betreff, text, ziel, segment, blocks=None) -> dict:
    z = _zeile(mandant["id"], entwurf_id)
    if z is None:
        raise Fehler("nicht_gefunden", "Entwurf nicht gefunden", 404)
    if z["status"] != "entwurf":
        raise Fehler("nicht_mehr_aenderbar", "Der Entwurf ist freigegeben und nicht mehr änderbar")
    layout_entwurf = z["format"] == "layout"
    if layout_entwurf and text is not None:
        raise Fehler("format_passt_nicht", "Ein Layout-Entwurf hat blocks statt text", 400, "text")
    if not layout_entwurf and blocks is not None:
        raise Fehler("format_passt_nicht", "Ein Text-Entwurf hat text statt blocks", 400, "blocks")
    neue_blocks = _blocks_von(z)
    if layout_entwurf:
        neue_blocks, text = _blocks_pruefen(mandant, blocks if blocks is not None else neue_blocks)
    betreff, text, ziel, segment = _inhalt_pruefen(mandant, betreff if betreff is not None else z["betreff"], text if text is not None else z["text"],
                                                   ziel if ziel is not None else z["ziel"], segment if segment is not None else json.loads(z["segment"]))
    with db.verbindung() as c:
        c.execute("UPDATE entwurf SET betreff=?, text=?, ziel=?, segment=?, content_hash=?, blocks=?, geaendert=? WHERE id=? AND mandant_id=?",
                  (betreff, text, ziel, json.dumps(segment), _hash(betreff, text, ziel, segment, neue_blocks if layout_entwurf else None),
                   json.dumps(neue_blocks, ensure_ascii=False) if layout_entwurf else None, _iso(_jetzt()), z["id"], mandant["id"]))
    return lesen(mandant, entwurf_id)


# ----- Versandrate je Mandant -----

def limit_pro_stunde(mandant_id: int) -> int:
    import einstellungen
    try:
        wert = int(einstellungen.lesen("m%d/versand_limit_pro_stunde" % int(mandant_id), str(LIMIT_PRO_STUNDE)))
    except (TypeError, ValueError):
        return LIMIT_PRO_STUNDE
    return wert if LIMIT_PRO_STUNDE_MIN <= wert <= LIMIT_PRO_STUNDE_MAX else LIMIT_PRO_STUNDE


def limit_pro_stunde_setzen(mandant_id: int, wert, akteur: str) -> int:
    if isinstance(wert, bool) or not isinstance(wert, int) or not LIMIT_PRO_STUNDE_MIN <= wert <= LIMIT_PRO_STUNDE_MAX:
        raise Fehler("limit_ungueltig", "limit_pro_stunde muss eine ganze Zahl von %d bis %d sein" % (LIMIT_PRO_STUNDE_MIN, LIMIT_PRO_STUNDE_MAX), 400)
    import einstellungen
    einstellungen.setzen("m%d/versand_limit_pro_stunde" % int(mandant_id), str(wert), akteur)
    return wert


def mails_pro_lauf(limit: int) -> int:
    """Wie viele Mails ein Durchgang (jede Minute) höchstens sendet: mindestens 5, bei hohem Stundenlimit entsprechend mehr."""
    return max(LIMIT_PRO_LAUF, -(-int(limit) // 60))


# ----- Testliste und Echtversand-Sperre -----

def testliste(mandant: dict) -> list:
    with db.verbindung() as c:
        return [z["email"] for z in c.execute("SELECT email FROM testadresse WHERE mandant_id=? ORDER BY id", (mandant["id"],)).fetchall()]


def testliste_setzen(mandant: dict, adressen) -> list:
    if not isinstance(adressen, list) or len(adressen) > 50:
        raise Fehler("adressen_ungueltig", "adressen muss eine Liste mit höchstens 50 Adressen sein", 400)
    sauber = []
    for a in adressen:
        a = schluessel.normalisiere_email(a) if isinstance(a, str) else ""
        if not schluessel.email_gueltig(a):
            raise Fehler("adressen_ungueltig", "Eine Adresse in der Testliste ist ungültig", 400)
        if a not in sauber:
            sauber.append(a)
    with db.verbindung() as c:
        c.execute("DELETE FROM testadresse WHERE mandant_id=?", (mandant["id"],))
        c.executemany("INSERT INTO testadresse(mandant_id, email) VALUES (?,?)", [(mandant["id"], a) for a in sauber])
    return sauber


def echtversand_freigegeben(mandant_id: int) -> bool:
    import einstellungen
    return einstellungen.lesen("m%d/echtversand_freigegeben" % int(mandant_id), "nein") == "ja"


def echtversand_setzen(mandant_id: int, freigegeben: bool, akteur: str) -> None:
    import einstellungen
    einstellungen.setzen("m%d/echtversand_freigegeben" % int(mandant_id), "ja" if freigegeben else "nein", akteur)


# ----- Testmail, Vorschau, Freigabe -----

def testmail(mandant: dict, entwurf_id: int, an=None, betreiber_email=None) -> dict:
    """Testmail an die TESTLISTE des Mandanten (v0.6.3, catrin #19057): ohne ``an`` an alle Adressen der Testliste (höchstens 50), sonst nur an die genannte Teilmenge
    (Text oder Liste von Adressen, jede muss in der Testliste stehen). Eine leere Testliste ist ein Fehler (400 testliste_leer); es gibt keinen Rückfall auf die Adresse des
    Betreibers (``betreiber_email`` bleibt nur der alten Signatur wegen und wird nicht benutzt). Antwort: Ergebnis je Adresse und Zähler; der Stand zählt als getestet, sobald
    mindestens eine Mail rausging."""
    z = _zeile(mandant["id"], entwurf_id)
    if z is None:
        raise Fehler("nicht_gefunden", "Entwurf nicht gefunden", 404)
    if z["status"] != "entwurf":
        raise Fehler("nicht_mehr_aenderbar", "Der Entwurf ist freigegeben")
    liste_ = testliste(mandant)
    if not liste_:
        raise Fehler("testliste_leer", "Testliste ist leer", 400)
    if an is None or an == "" or an == []:
        ziele = list(liste_)
    else:
        angefordert = [an] if isinstance(an, str) else an
        if not isinstance(angefordert, list) or not angefordert or len(angefordert) > 50 or any(not isinstance(a, str) for a in angefordert):
            raise Fehler("an_ungueltig", "an muss eine Adresse oder eine Liste von höchstens 50 Adressen aus der Testliste sein", 400)
        ziele = []
        for a in angefordert:
            n = schluessel.normalisiere_email(a)
            if n not in liste_:
                raise Fehler("adresse_nicht_in_testliste", "Diese Adresse steht nicht in der Testliste", 403)
            if n not in ziele:
                ziele.append(n)
    blocks, ansicht = _blocks_von(z), (_ansicht_kennung(z) if z["format"] == "layout" else None)
    betreff, text, html_text, header = darstellen(mandant, "[TEST] " + z["betreff"], z["text"], None, blocks=blocks, ansicht_token=ansicht)
    ergebnisse, erster_grund = [], None
    for adresse in ziele:
        roh = mailer.senden(mandant, adresse, betreff, text, html_text, header)
        if roh in ("gesendet", "datei"):
            ergebnisse.append({"adresse": adresse, "ergebnis": roh})
        else:
            grund = (mailer.letzter_fehlertyp() or roh) if roh == "fehler" else roh          # bei 'fehler' der Ausnahmetyp (z. B. SMTPAuthenticationError)
            erster_grund = erster_grund or grund
            ergebnisse.append({"adresse": adresse, "ergebnis": "fehler", "grund": grund})
    ok = sum(1 for e in ergebnisse if e["ergebnis"] != "fehler")
    if ok == 0:
        raise Fehler("versand_nicht_moeglich", "Die Testmail konnte nicht gesendet werden (%s). Versandmodus und Konto des Mandanten prüfen." % erster_grund, 409)
    with db.verbindung() as c:
        c.execute("UPDATE entwurf SET testmail_hash=?, testmail_am=? WHERE id=? AND mandant_id=?", (z["content_hash"], _iso(_jetzt()), z["id"], mandant["id"]))
    antwort = {"status": "gesendet" if ok == len(ergebnisse) else "teilweise", "content_hash": z["content_hash"], "gesendet": ok, "fehler": len(ergebnisse) - ok,
               "ergebnisse": ergebnisse}
    if antwort["fehler"]:                                    # die Oberfläche zeigt meldung an
        gruende = sorted({e["grund"] for e in ergebnisse if e["ergebnis"] == "fehler"})
        antwort["meldung"] = "Testmail an %d von %d Adressen gesendet, %d fehlgeschlagen (%s)." % (ok, len(ergebnisse), antwort["fehler"], ", ".join(gruende))
    return antwort


def _empfaenger_ermitteln(mandant: dict, z) -> list:
    """[(schluessel, abonnent_id|None, email)] für diesen Entwurf zum jetzigen Zeitpunkt."""
    if z["ziel"] == "testliste":
        return [("t" + schluessel.email_hmac(mandant["id"], a), None, a) for a in testliste(mandant)]
    segment = json.loads(z["segment"])
    with db.verbindung() as c:
        zeilen = c.execute("SELECT id, email, rolle, interessen, tags FROM abonnent WHERE mandant_id=? AND status='bestaetigt' AND email IS NOT NULL ORDER BY id",
                           (mandant["id"],)).fetchall()
    ergebnis = []
    for r in zeilen:
        if segment.get("rollen") and r["rolle"] not in segment["rollen"]:
            continue
        if segment.get("interessen") and not set(json.loads(r["interessen"] or "[]")) & set(segment["interessen"]):
            continue
        if segment.get("tags"):
            gewaehlt = {t.lower() for t in segment["tags"]}
            hat = {t.lower() for t in json.loads(r["tags"] or "[]")}
            if not (gewaehlt <= hat if segment.get("tags_modus") == "und" else gewaehlt & hat):
                continue
        ergebnis.append(("a%d" % r["id"], r["id"], r["email"]))
    return ergebnis


def segment_anzahl(mandant: dict, segment) -> dict:
    """Wie viele bestätigte Abonnentinnen würde dieses Segment treffen (ohne Entwurf, für die Auswahl in der Oberfläche). Wirft Fehler bei ungültigem Segment."""
    geprueft = _segment_pruefen(mandant, segment)
    z = {"ziel": "alle", "segment": json.dumps(geprueft)}
    return {"anzahl": len(_empfaenger_ermitteln(mandant, z)), "segment": geprueft}


def vorschau(mandant: dict, entwurf_id: int) -> dict:
    z = _zeile(mandant["id"], entwurf_id)
    if z is None:
        raise Fehler("nicht_gefunden", "Entwurf nicht gefunden", 404)
    return {"anzahl": len(_empfaenger_ermitteln(mandant, z)), "segment": json.loads(z["segment"]), "ziel": z["ziel"]}


def pflichtangaben_fehlend(mandant: dict) -> list:
    """Namen der Design-Felder, die für den Echtversand fehlen (Impressum, Datenschutz, Firmenangaben, Absender). Nie Werte."""
    design = mandant.get("design") or {}
    return [f for f in PFLICHTANGABEN if not str(design.get(f) or "").strip()]


def freigeben(mandant: dict, entwurf_id: int, content_hash, bestaetigt, betreiber_email: str) -> dict:
    z = _zeile(mandant["id"], entwurf_id)
    if z is None:
        raise Fehler("nicht_gefunden", "Entwurf nicht gefunden", 404)
    if bestaetigt is not True:
        raise Fehler("bestaetigung_fehlt", "Die Freigabe muss ausdrücklich bestätigt werden (bestaetigt: true)", 400)
    if z["status"] != "entwurf":
        raise Fehler("bereits_freigegeben", "Der Entwurf ist schon freigegeben")
    if z["ziel"] == "abonnenten" and not echtversand_freigegeben(mandant["id"]):
        raise Fehler("echtversand_gesperrt", "Der Echtversand ist für diesen Mandanten noch nicht freigegeben")
    if z["ziel"] == "abonnenten":
        fehlend = pflichtangaben_fehlend(mandant)
        if fehlend:
            raise Fehler("pflichtangaben_fehlen", "Vor dem Echtversand müssen im Design gesetzt sein: " + ", ".join(fehlend), 409)
    if not z["testmail_hash"]:
        raise Fehler("testmail_fehlt", "Es gibt noch keine Testmail zu diesem Entwurf")
    if content_hash != z["content_hash"] or z["testmail_hash"] != z["content_hash"]:
        raise Fehler("entwurf_geaendert", "Die Testmail gehört nicht zum aktuellen Stand des Entwurfs")
    empfaenger = _empfaenger_ermitteln(mandant, z)
    if not empfaenger:
        raise Fehler("keine_empfaenger", "Es gibt keine Empfänger für diesen Entwurf", 422)
    zeit = _iso(_jetzt())
    with db.verbindung() as c:
        # atomar: nur ein Entwurf im Status 'entwurf' wird freigegeben (kein doppeltes Anlegen der Zeilen bei zwei gleichzeitigen Freigaben)
        cur = c.execute("UPDATE entwurf SET status='freigegeben', freigegeben_am=?, freigegeben_von=? WHERE id=? AND mandant_id=? AND status='entwurf'",
                        (zeit, betreiber_email, z["id"], mandant["id"]))
        if cur.rowcount != 1:
            raise Fehler("bereits_freigegeben", "Der Entwurf ist schon freigegeben")
        c.executemany("INSERT INTO empfaenger(entwurf_id, mandant_id, abonnent_id, email, schluessel, status, zeit) VALUES (?,?,?,?,?,'queued',?)",
                      [(z["id"], mandant["id"], aid, email if aid is None else None, key, zeit) for key, aid, email in empfaenger])
    return {"status": "freigegeben", "empfaenger": len(empfaenger)}


def stoppen(mandant: dict, entwurf_id: int) -> dict:
    z = _zeile(mandant["id"], entwurf_id)
    if z is None:
        raise Fehler("nicht_gefunden", "Entwurf nicht gefunden", 404)
    zeit = _iso(_jetzt())
    with db.verbindung() as c:
        c.execute("UPDATE empfaenger SET status='abgebrochen', zeit=? WHERE entwurf_id=? AND mandant_id=? AND status='queued'", (zeit, z["id"], mandant["id"]))
        c.execute("UPDATE entwurf SET status='gestoppt', gestoppt_am=? WHERE id=? AND mandant_id=? AND status IN ('freigegeben','sendet')", (zeit, z["id"], mandant["id"]))
    return {"status": "gestoppt"}


def status(mandant: dict, entwurf_id: int) -> dict:
    z = _zeile(mandant["id"], entwurf_id)
    if z is None:
        raise Fehler("nicht_gefunden", "Entwurf nicht gefunden", 404)
    with db.verbindung() as c:
        zeilen = c.execute("SELECT status, COUNT(*) AS n FROM empfaenger WHERE entwurf_id=? AND mandant_id=? GROUP BY status", (z["id"], mandant["id"])).fetchall()
    zahlen = {s["status"]: s["n"] for s in zeilen}
    return {"status": z["status"], "gesamt": sum(zahlen.values()), "gesendet": zahlen.get("sent", 0), "offen": zahlen.get("queued", 0) + zahlen.get("sending", 0),
            "fehlgeschlagen": zahlen.get("fehlgeschlagen", 0), "unzustellbar": zahlen.get("unzustellbar", 0), "uebersprungen_abgemeldet": zahlen.get("uebersprungen", 0),
            "unklar": zahlen.get("unklar", 0), "abgebrochen": zahlen.get("abgebrochen", 0), "limit_pro_stunde": limit_pro_stunde(mandant["id"]),
            "versandmodus": mandanten.versandmodus(mandant["id"]), "echtversand_freigegeben": echtversand_freigegeben(mandant["id"])}


def protokoll(mandant: dict, entwurf_id: int) -> list:
    z = _zeile(mandant["id"], entwurf_id)
    if z is None:
        raise Fehler("nicht_gefunden", "Entwurf nicht gefunden", 404)
    with db.verbindung() as c:
        zeilen = c.execute("SELECT e.id, e.status, e.zeit, e.fehler, e.email AS test_email, a.email AS abo_email FROM empfaenger e "
                           "LEFT JOIN abonnent a ON a.id = e.abonnent_id AND a.mandant_id = e.mandant_id WHERE e.entwurf_id=? AND e.mandant_id=? ORDER BY e.id",
                           (z["id"], mandant["id"])).fetchall()
    return [{"email": r["test_email"] or r["abo_email"] or "(abgemeldet)", "status": r["status"], "zeitpunkt": r["zeit"], "fehler": r["fehler"]} for r in zeilen]


def protokoll_csv(zeilen: list) -> str:
    """CSV mit Schutz gegen Formeln in Tabellenprogrammen (Zellen, die mit = + - @ beginnen, bekommen ein vorangestelltes ')."""
    def zelle(wert):
        wert = "" if wert is None else str(wert)
        return "'" + wert if wert[:1] in ("=", "+", "-", "@", "\t", "\r") else wert
    ausgabe = io.StringIO()
    w = csv.writer(ausgabe, lineterminator="\r\n")
    w.writerow(["email", "status", "zeitpunkt", "fehler"])
    for r in zeilen:
        w.writerow([zelle(r["email"]), zelle(r["status"]), zelle(r["zeitpunkt"]), zelle(r["fehler"])])
    return ausgabe.getvalue()


# ----- Versandlauf -----

def _gesendet_letzte_stunde(c, mandant_id: int) -> int:
    return c.execute("SELECT COUNT(*) FROM empfaenger WHERE mandant_id=? AND status IN ('sent','sending') AND zeit>=?",
                     (mandant_id, _iso(_jetzt() - timedelta(hours=1)))).fetchone()[0]


def lauf() -> dict:
    """Ein Durchgang (jede Minute vom Hintergrundjob): hängende Zeilen auf 'unklar', dann je Mandant bis zu 5 Mails im Rahmen des Stundenlimits."""
    bilanz = {"gesendet": 0, "uebersprungen": 0, "fehler": 0, "unklar": 0, "wartet": 0}
    grenze = _iso(_jetzt() - timedelta(minutes=UNKLAR_NACH_MINUTEN))
    with db.verbindung() as c:
        cur = c.execute("UPDATE empfaenger SET status='unklar', fehler='Ausgang unklar (Absturz während des Sendens), nicht automatisch wiederholt' "
                        "WHERE status='sending' AND zeit<?", (grenze,))
        bilanz["unklar"] = cur.rowcount
    for m in mandanten.alle():
        if not m["aktiv"]:
            continue
        modus = mandanten.versandmodus(m["id"])
        with db.verbindung() as c:
            offene = c.execute("SELECT 1 FROM empfaenger e JOIN entwurf w ON w.id=e.entwurf_id WHERE e.mandant_id=? AND e.status='queued' "
                               "AND w.status IN ('freigegeben','sendet') LIMIT 1", (m["id"],)).fetchone()
        if not offene:
            _abschliessen(m["id"])
            continue
        if modus == "aus":
            bilanz["wartet"] += 1
            continue
        limit = limit_pro_stunde(m["id"])
        for _ in range(mails_pro_lauf(limit)):
            with db.verbindung() as c:
                if _gesendet_letzte_stunde(c, m["id"]) >= limit:
                    break
                z = c.execute("SELECT e.*, w.ziel AS ziel, w.betreff AS betreff, w.text AS text, w.format AS format, w.blocks AS blocks, w.ansicht_token AS ansicht_token FROM empfaenger e JOIN entwurf w ON w.id=e.entwurf_id "
                              "WHERE e.mandant_id=? AND e.status='queued' AND w.status IN ('freigegeben','sendet') AND (e.fehler IS NULL OR e.zeit<?) "
                              "ORDER BY e.id LIMIT 1",
                              (m["id"], _iso(_jetzt() - timedelta(minutes=WIEDERHOLUNG_ABSTAND_MINUTEN)))).fetchone()
                if z is None:
                    break
                # Echtversand-Sperre gilt auch hier, nicht nur bei der Freigabe
                if z["ziel"] == "abonnenten" and not echtversand_freigegeben(m["id"]):
                    bilanz["wartet"] += 1
                    break
                # atomar beanspruchen: nur wer die Zeile von 'queued' auf 'sending' setzt, darf senden
                if c.execute("UPDATE empfaenger SET status='sending', zeit=?, versuche=versuche+1 WHERE id=? AND status='queued'", (_iso(_jetzt()), z["id"])).rowcount != 1:
                    continue
                c.execute("UPDATE entwurf SET status='sendet' WHERE id=? AND status='freigegeben'", (z["entwurf_id"],))
            ergebnis = _eine_senden(m, z)
            bilanz[ergebnis] = bilanz.get(ergebnis, 0) + 1
        _abschliessen(m["id"])
    return bilanz


def _eine_senden(m: dict, z) -> str:
    """Sendet eine beanspruchte Zeile und setzt ihren Endstatus. Gibt den Schlüssel für die Bilanz zurück."""
    adresse, abo = z["email"], None
    if z["abonnent_id"] is not None:
        with db.verbindung() as c:
            abo = c.execute("SELECT * FROM abonnent WHERE id=? AND mandant_id=?", (z["abonnent_id"], m["id"])).fetchone()
        if abo is None or abo["status"] != "bestaetigt" or not abo["email"]:         # Abmeldung wirkt beim nächsten Lauf
            _setzen(z["id"], "uebersprungen", "abgemeldet oder nicht mehr bestätigt")
            return "uebersprungen"
        adresse = abo["email"]
    token = abonnenten.persoenliches_token(abo) if abo is not None else None
    betreff, text, html_text, header = darstellen(m, z["betreff"], z["text"], token, blocks=_blocks_von(z), ansicht_token=z["ansicht_token"] if z["format"] == "layout" else None)
    ergebnis = mailer.senden(m, adresse, betreff, text, html_text, header)
    if ergebnis in ("gesendet", "datei"):
        _setzen(z["id"], "sent", None)
        return "gesendet"
    if ergebnis == "abgelehnt":
        _setzen(z["id"], "unzustellbar", "Empfänger abgelehnt")
        if abo is not None:
            with db.verbindung() as c:
                c.execute("UPDATE abonnent SET status='unzustellbar' WHERE id=? AND mandant_id=? AND status='bestaetigt'", (abo["id"], m["id"]))
        return "fehler"
    versuche = z["versuche"] + 1                                                       # die Zeile wurde beim Beanspruchen hochgezählt
    if versuche >= VERSUCHE_MAX:
        _setzen(z["id"], "fehlgeschlagen", "Versand nach %d Versuchen nicht möglich (%s)" % (VERSUCHE_MAX, ergebnis))
    else:
        _setzen(z["id"], "queued", "Versuch %d: %s" % (versuche, ergebnis))
    return "fehler"


def _setzen(empfaenger_id: int, status: str, fehler: str | None) -> None:
    with db.verbindung() as c:
        c.execute("UPDATE empfaenger SET status=?, zeit=?, fehler=? WHERE id=?", (status, _iso(_jetzt()), fehler, empfaenger_id))


def _abschliessen(mandant_id: int) -> None:
    """Entwürfe ohne offene Zeilen werden 'fertig'."""
    with db.verbindung() as c:
        c.execute("UPDATE entwurf SET status='fertig' WHERE mandant_id=? AND status IN ('freigegeben','sendet') AND NOT EXISTS "
                  "(SELECT 1 FROM empfaenger e WHERE e.entwurf_id=entwurf.id AND e.status IN ('queued','sending'))", (mandant_id,))
