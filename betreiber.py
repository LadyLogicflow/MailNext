"""Betreiber-Schnittstelle (Anmeldung über das Portal-Cookie, nur Betreiber): Mandanten, Design, Einwilligungstexte, Versandeinstellungen, Kennzahlen.

Jeder Aufruf wird im Audit-Log protokolliert, bevor geantwortet wird (Details: Mandant, Aktion, Zahlen, nie Inhalte oder Zugangsdaten). Scheitert das
Protokollieren, gibt es keine Antwort (500). Geheimnisse werden nie zurückgegeben, nur ob sie gesetzt sind."""
from functools import wraps

from flask import Blueprint, g, jsonify, request

import abonnenten
import betreiber_auth
import bilder
import db
import import_csv
import ki
import mandanten
import newsletter
from mandanten import Ungueltig

bp = Blueprint("betreiber", __name__, url_prefix="/api/v1/betreiber")


def _ip() -> str:
    from public import client_ip
    if g.betreiber.get("offen"):
        # Offen-Modus: Quelladresse nur als Pseudonym ins Audit (HMAC, nicht umkehrbar ohne Hauptschlüssel)
        import hashlib
        import hmac
        import schluessel
        return "h:" + hmac.new(schluessel._ableiten(b"mailnext-audit-ip-v1"), client_ip().encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return client_ip()


def _audit(aktion: str, details: str = "") -> None:
    db.audit(g.betreiber["email"], aktion, details, _ip())


def _fehler(text: str, status: int = 400):
    return jsonify({"error": "eingabe_ungueltig", "meldung": text}), status


def _mandant_oder_404(mandant_id: int):
    m = mandanten.lesen(mandant_id)
    return m


def _sicht(m: dict, mit_zahlen: bool = True) -> dict:
    daten = {"id": m["id"], "slug": m["slug"], "name": m["name"], "aktiv": m["aktiv"], "design": m["design"], "erstellt": m["erstellt"],
             "geaendert": m["geaendert"], "versand": mandanten.versand_zustand(m["id"]), "einwilligungen": [
                 {"version": e["version"], "sha256": e["sha256"], "gueltig_ab": e["gueltig_ab"]} for e in mandanten.einwilligungen(m["id"])]}
    if mit_zahlen:
        daten["abonnenten"] = abonnenten.kennzahlen(m["id"])
    return daten


def _json():
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else None


@bp.get("/mandanten")
@betreiber_auth.betreiber_pflicht
def liste():
    _audit("mandanten_liste")
    return jsonify({"mandanten": [_sicht(m) for m in mandanten.alle()]})


@bp.post("/mandanten")
@betreiber_auth.betreiber_pflicht
def anlegen():
    d = _json()
    if d is None:
        return _fehler("Objekt erwartet")
    try:
        m = mandanten.anlegen(d.get("slug"), d.get("name"), d.get("design"), g.betreiber["email"])
    except Ungueltig as exc:
        return _fehler(str(exc))
    _audit("mandant_angelegt", "mandant=%s" % m["slug"])
    return jsonify(_sicht(m)), 201


@bp.get("/mandanten/<int:mandant_id>")
@betreiber_auth.betreiber_pflicht
def lesen(mandant_id):
    m = _mandant_oder_404(mandant_id)
    if m is None:
        return jsonify({"error": "nicht_gefunden"}), 404
    _audit("mandant_gelesen", "mandant=%s" % m["slug"])
    return jsonify(_sicht(m))


@bp.put("/mandanten/<int:mandant_id>")
@betreiber_auth.betreiber_pflicht
def aendern(mandant_id):
    d = _json()
    if d is None:
        return _fehler("Objekt erwartet")
    if _mandant_oder_404(mandant_id) is None:
        return jsonify({"error": "nicht_gefunden"}), 404
    fremd = set(d) - {"name", "aktiv", "design"}
    if fremd:
        return _fehler("Unbekannte Felder: %s" % ", ".join(sorted(fremd)))
    try:
        m = mandanten.aendern(mandant_id, d.get("name"), d.get("aktiv"), d.get("design"))
    except Ungueltig as exc:
        return _fehler(str(exc))
    _audit("mandant_geaendert", "mandant=%s felder=%s" % (m["slug"], ",".join(sorted(d))))
    return jsonify(_sicht(m))


# ----- Bilder (Logo, später Newsletter-Bilder) -----

@bp.post("/mandanten/<int:mandant_id>/bilder")
@betreiber_auth.betreiber_pflicht
def bild_hochladen(mandant_id):
    """Bild annehmen: multipart mit file (Pflicht) und alt (Pflicht, 1-150 Zeichen). Neu-Kodierung ohne Metadaten, siehe bilder.py. Ins Audit kommen nur Zahlen."""
    m = _mandant_oder_404(mandant_id)
    if m is None:
        return jsonify({"error": "nicht_gefunden"}), 404
    datei = request.files.get("file")
    try:
        if datei is None:
            raise bilder.BildFehler("datei_fehlt")
        bild = bilder.speichern(m, datei.read(bilder.MAX_BYTES + 1), request.form.get("alt"))
    except bilder.BildFehler as f:
        return jsonify({"error": f.code, "meldung": f.meldung}), (413 if f.code == "zu_gross" else 400)
    _audit("bild_hochgeladen", "mandant=%s bild=%d bytes=%d" % (m["slug"], bild["id"], bild["groesse_bytes"]))
    return jsonify(bild), 201


@bp.get("/mandanten/<int:mandant_id>/bilder")
@betreiber_auth.betreiber_pflicht
def bilder_liste(mandant_id):
    m = _mandant_oder_404(mandant_id)
    if m is None:
        return jsonify({"error": "nicht_gefunden"}), 404
    liste_ = bilder.liste(m)
    _audit("bilder_gelesen", "mandant=%s anzahl=%d" % (m["slug"], len(liste_)))
    return jsonify(liste_)


@bp.delete("/mandanten/<int:mandant_id>/bilder/<int:bild_id>")
@betreiber_auth.betreiber_pflicht
def bild_loeschen(mandant_id, bild_id):
    m = _mandant_oder_404(mandant_id)
    if m is None or not bilder.gehoert_zu(mandant_id, bild_id):
        return jsonify({"error": "nicht_gefunden"}), 404
    if bilder.in_verwendung(m, bild_id):
        return jsonify({"error": "bild_in_verwendung", "meldung": "Das Bild wird gebraucht (Logo oder versendeter Newsletter) und kann nicht gelöscht werden."}), 409
    bilder.loeschen(m, bild_id)
    _audit("bild_geloescht", "mandant=%s bild=%d" % (m["slug"], bild_id))
    return "", 204


@bp.post("/mandanten/<int:mandant_id>/einwilligungen")
@betreiber_auth.betreiber_pflicht
def einwilligung(mandant_id):
    d = _json()
    if d is None:
        return _fehler("Objekt erwartet")
    m = _mandant_oder_404(mandant_id)
    if m is None:
        return jsonify({"error": "nicht_gefunden"}), 404
    try:
        e = mandanten.einwilligung_anlegen(mandant_id, d.get("version"), d.get("text"))
    except Ungueltig as exc:
        return _fehler(str(exc))
    _audit("einwilligung_angelegt", "mandant=%s version=%s sha256=%s" % (m["slug"], e["version"], e["sha256"]))
    return jsonify(e), 201


@bp.put("/mandanten/<int:mandant_id>/versand")
@betreiber_auth.betreiber_pflicht
def versand(mandant_id):
    d = _json()
    if d is None:
        return _fehler("Objekt erwartet")
    m = _mandant_oder_404(mandant_id)
    if m is None:
        return jsonify({"error": "nicht_gefunden"}), 404
    try:
        zustand = mandanten.versand_setzen(mandant_id, d, g.betreiber["email"])
    except Ungueltig as exc:
        return _fehler(str(exc))
    _audit("versand_geaendert", "mandant=%s felder=%s" % (m["slug"], ",".join(sorted(d))))          # nur die Namen der Felder, nie Werte
    return jsonify(zustand)


@bp.get("/mandanten/<int:mandant_id>/abonnenten")
@betreiber_auth.betreiber_pflicht
def abonnenten_liste(mandant_id):
    m = _mandant_oder_404(mandant_id)
    if m is None:
        return jsonify({"error": "nicht_gefunden"}), 404
    zeilen = abonnenten.liste(mandant_id)
    _audit("abonnenten_gelesen", "mandant=%s anzahl=%d" % (m["slug"], len(zeilen)))                 # enthält Adressen: darum protokolliert
    return jsonify({"abonnenten": zeilen, "kennzahlen": abonnenten.kennzahlen(mandant_id)})


@bp.post("/mandanten/<int:mandant_id>/abonnenten/import")
@betreiber_auth.betreiber_pflicht
def abonnenten_import(mandant_id):
    """Import von Bestandsadressen (Mailchimp-Export oder eine Adresse je Zeile). Body: daten (Text), quelle (1-100 Zeichen), nur_pruefen (bool), einwilligung_bestaetigt (Pflicht beim
    echten Import), optional rolle und interessen (Werte aus dem Mandanten, gelten für alle Zeilen). Ins Audit kommen nur Zahlen und die Quelle, nie Adressen."""
    m = _mandant_oder_404(mandant_id)
    if m is None:
        return jsonify({"error": "nicht_gefunden"}), 404
    d = _json()
    erlaubt = {"daten", "quelle", "nur_pruefen", "einwilligung_bestaetigt", "rolle", "interessen"}
    if d is None or set(d) - erlaubt:
        return _fehler("Bitte daten, quelle, nur_pruefen, einwilligung_bestaetigt, rolle und interessen als JSON senden.")
    daten, quelle = d.get("daten"), d.get("quelle")
    if not isinstance(daten, str) or not daten.strip():
        return jsonify({"error": "daten_fehlen", "meldung": "Es wurden keine Daten übergeben."}), 400
    if (not isinstance(quelle, str) or not 1 <= len(quelle.strip()) <= 100 or any(ord(ch) < 32 or ord(ch) == 127 for ch in quelle)):
        return _fehler("Bitte eine Quelle angeben (1 bis 100 Zeichen, z. B. Mailchimp-Export vom 13.11.2026).")
    nur_pruefen = d.get("nur_pruefen", False)
    if not isinstance(nur_pruefen, bool):
        return _fehler("nur_pruefen muss true oder false sein.")
    if not nur_pruefen and d.get("einwilligung_bestaetigt") is not True:
        return jsonify({"error": "einwilligung_nicht_bestaetigt", "meldung": "Bitte bestätigen, dass die Einwilligungen der Adressen vorliegen."}), 400
    try:
        ergebnis = abonnenten.importieren(m, daten, quelle.strip(), d.get("rolle"), d.get("interessen"), nur_pruefen)
    except abonnenten.FormFehler as f:
        return jsonify({"error": "eingabe_ungueltig", "feld": f.feld, "meldung": "Rolle oder Interessen gehören nicht zu diesem Mandanten."}), 400
    except import_csv.ImportFehler as f:
        return jsonify({"error": f.code, "meldung": f.meldung}), 400
    _audit("abonnenten_import_geprueft" if nur_pruefen else "abonnenten_import",
           "mandant=%s quelle=%s zeilen=%d neu=%d dublette=%d ungueltig=%d uebersprungen=%d zusammengefuehrt=%d" % (
               m["slug"], quelle.strip(), ergebnis["zeilen"], ergebnis["neu"], ergebnis["dublette"], ergebnis["ungueltig"], ergebnis["uebersprungen_gesamt"], ergebnis["zusammengefuehrt"]))
    return jsonify(ergebnis)


@bp.get("/mandanten/<int:mandant_id>/abonnenten/tags")
@betreiber_auth.betreiber_pflicht
def abonnenten_tags(mandant_id):
    """Vorhandene Tags dieses Mandanten mit Anzahl bestätigter Abonnentinnen (für die Auswahl; keine Adressen)."""
    m = _mandant_oder_404(mandant_id)
    if m is None:
        return jsonify({"error": "nicht_gefunden"}), 404
    tags = abonnenten.tags_liste(mandant_id)
    _audit("tags_gelesen", "mandant=%s anzahl=%d" % (m["slug"], len(tags)))
    return jsonify({"tags": tags})


@bp.post("/mandanten/<int:mandant_id>/abonnenten/vorschau")
@betreiber_auth.betreiber_pflicht
def abonnenten_vorschau(mandant_id):
    """Anzahl der Empfänger für ein Segment {rollen?, interessen?, tags?, tags_modus?}, ohne Entwurf. Body: {"segment": {...}}."""
    m = _mandant_oder_404(mandant_id)
    if m is None:
        return jsonify({"error": "nicht_gefunden"}), 404
    d = _json()
    if d is None or set(d) - {"segment"}:
        return _fehler("Bitte {\"segment\": {...}} senden.")
    try:
        v = newsletter.segment_anzahl(m, d.get("segment"))
    except newsletter.Fehler as fehler:
        return jsonify({"error": fehler.code, "meldung": fehler.meldung}), fehler.status
    _audit("segment_vorschau", "mandant=%s anzahl=%d" % (m["slug"], v["anzahl"]))
    return jsonify(v)


# ----- KI-Textverbesserung (Claude): Schalter je Mandant, Zugangsschlüssel (nur schreibbar), Vorschlag auf Klick -----

@bp.get("/ki")
@betreiber_auth.betreiber_pflicht
def ki_zugang_lesen():
    """Nur ob ein Zugangsschlüssel gesetzt ist, nie der Schlüssel."""
    return jsonify({"schluessel_gesetzt": ki.schluessel_gesetzt(), "modell": ki.MODELL})


@bp.put("/ki")
@betreiber_auth.betreiber_pflicht
def ki_zugang_setzen():
    d = _json()
    if d is None or set(d) != {"schluessel"}:
        return _fehler("Bitte {\"schluessel\": \"...\"} senden.")
    try:
        ki.schluessel_setzen(d["schluessel"], g.betreiber["email"])
    except ki.Fehler as f:
        return jsonify({"error": f.code, "meldung": f.meldung}), f.status
    _audit("ki_schluessel_gesetzt", "")                                              # nie der Wert
    return jsonify({"schluessel_gesetzt": True})


@bp.delete("/ki")
@betreiber_auth.betreiber_pflicht
def ki_zugang_loeschen():
    ki.schluessel_loeschen()
    _audit("ki_schluessel_geloescht", "")
    return jsonify({"schluessel_gesetzt": False})


@bp.get("/mandanten/<int:mandant_id>/ki")
@betreiber_auth.betreiber_pflicht
def ki_mandant_lesen(mandant_id):
    m = _mandant_oder_404(mandant_id)
    if m is None:
        return jsonify({"error": "nicht_gefunden"}), 404
    return jsonify(ki.zustand(m["id"]))


@bp.put("/mandanten/<int:mandant_id>/ki")
@betreiber_auth.betreiber_pflicht
def ki_mandant_setzen(mandant_id):
    m = _mandant_oder_404(mandant_id)
    if m is None:
        return jsonify({"error": "nicht_gefunden"}), 404
    d = _json()
    if d is None or set(d) != {"aktiv"} or not isinstance(d["aktiv"], bool):
        return _fehler("Bitte {\"aktiv\": true|false} senden.")
    ki.aktiv_setzen(m["id"], d["aktiv"], g.betreiber["email"])
    _audit("ki_schalter", "mandant=%s aktiv=%s" % (m["slug"], "ja" if d["aktiv"] else "nein"))
    return jsonify(ki.zustand(m["id"]))


@bp.post("/mandanten/<int:mandant_id>/entwuerfe/text-verbessern")
@betreiber_auth.betreiber_pflicht
def text_verbessern(mandant_id):
    """Vorschlag der KI für Betreff und Text. Wird nirgends gespeichert. Audit und Log enthalten nur Zeichenzahlen, nie Texte."""
    m = _mandant_oder_404(mandant_id)
    if m is None:
        return jsonify({"error": "nicht_gefunden"}), 404
    d = _json()
    if d is None or set(d) - {"betreff", "text", "anweisung"}:
        return _fehler("Bitte betreff (optional), text und anweisung (optional) als JSON senden.")
    try:
        ergebnis = ki.verbessern(m, g.betreiber["email"], d.get("betreff"), d.get("text"), d.get("anweisung"))
    except ki.Fehler as f:
        _audit("ki_textverbesserung_fehler", "mandant=%s grund=%s" % (m["slug"], f.code))
        return jsonify({"error": f.code, "meldung": f.meldung}), f.status
    _audit("ki_textverbesserung", "mandant=%s zeichen_ein=%d zeichen_aus=%d" % (m["slug"], ergebnis["zeichen_ein"], ergebnis["zeichen_aus"]))
    return jsonify({"vorschlag": ergebnis["vorschlag"]})


# ----- Newsletter (Meilenstein B): Entwürfe, Testmail, Freigabe, Versand, Protokoll -----

def _nl(f):
    """Mandant aus dem Pfad laden (404) und newsletter.Fehler in die Antwort übersetzen."""
    @wraps(f)
    def innen(mandant_id, *a, **kw):
        m = _mandant_oder_404(mandant_id)
        if m is None:
            return jsonify({"error": "nicht_gefunden"}), 404
        try:
            return f(m, *a, **kw)
        except newsletter.Fehler as fehler:
            antwort = {"error": fehler.code, "meldung": fehler.meldung}
            if fehler.feld:
                antwort["feld"] = fehler.feld
            return jsonify(antwort), fehler.status
    return innen


@bp.get("/mandanten/<int:mandant_id>/entwuerfe")
@betreiber_auth.betreiber_pflicht
@_nl
def entwuerfe(m):
    _audit("entwuerfe_liste", "mandant=%s" % m["slug"])
    return jsonify({"entwuerfe": newsletter.liste(m)})


@bp.post("/mandanten/<int:mandant_id>/entwuerfe")
@betreiber_auth.betreiber_pflicht
@_nl
def entwurf_anlegen(m):
    d = _json() or {}
    e = newsletter.anlegen(m, d.get("betreff"), d.get("text"), d.get("ziel", "testliste"), d.get("segment"), d.get("format", "text"), d.get("blocks"))
    _audit("entwurf_angelegt", "mandant=%s entwurf=%d ziel=%s" % (m["slug"], e["id"], e["ziel"]))
    antwort = {"id": e["id"], "content_hash": e["content_hash"]}
    if e["format"] == "layout":
        antwort["blocks"] = e["blocks"]                                  # die BEREINIGTE Fassung
    return jsonify(antwort), 201


@bp.post("/mandanten/<int:mandant_id>/entwuerfe/vorschau")
@betreiber_auth.betreiber_pflicht
@_nl
def entwurf_vorschau(m):
    """Vorschau eines Layout-Entwurfs (noch ungespeichert): {betreff, blocks} -> {html, text, warnungen, blocks}. Speichert nichts, sendet nichts."""
    d = _json() or {}
    erg = newsletter.layout_vorschau(m, d.get("betreff"), d.get("blocks"))
    _audit("entwurf_vorschau", "mandant=%s bilder=%d" % (m["slug"], len(erg["blocks"]["bilder"])))
    return jsonify(erg)


@bp.get("/mandanten/<int:mandant_id>/entwuerfe/<int:entwurf_id>")
@betreiber_auth.betreiber_pflicht
@_nl
def entwurf_lesen(m, entwurf_id):
    e = newsletter.lesen(m, entwurf_id)
    if e is None:
        return jsonify({"error": "nicht_gefunden"}), 404
    _audit("entwurf_gelesen", "mandant=%s entwurf=%d" % (m["slug"], entwurf_id))
    return jsonify(e)


@bp.put("/mandanten/<int:mandant_id>/entwuerfe/<int:entwurf_id>")
@betreiber_auth.betreiber_pflicht
@_nl
def entwurf_aendern(m, entwurf_id):
    d = _json() or {}
    e = newsletter.aendern(m, entwurf_id, d.get("betreff"), d.get("text"), d.get("ziel"), d.get("segment"), d.get("blocks"))
    _audit("entwurf_geaendert", "mandant=%s entwurf=%d" % (m["slug"], entwurf_id))
    antwort = {"content_hash": e["content_hash"]}
    if e["format"] == "layout":
        antwort["blocks"] = e["blocks"]                                  # die BEREINIGTE Fassung
    return jsonify(antwort)


@bp.post("/mandanten/<int:mandant_id>/entwuerfe/<int:entwurf_id>/testmail")
@betreiber_auth.betreiber_pflicht
@_nl
def testmail(m, entwurf_id):
    d = _json() or {}
    ergebnis = newsletter.testmail(m, entwurf_id, d.get("an"), g.betreiber["email"])
    _audit("testmail_gesendet", "mandant=%s entwurf=%d" % (m["slug"], entwurf_id))               # Adresse steht nicht im Audit
    return jsonify({"status": ergebnis["status"], "content_hash": ergebnis["content_hash"]})


@bp.get("/mandanten/<int:mandant_id>/entwuerfe/<int:entwurf_id>/empfaengervorschau")
@betreiber_auth.betreiber_pflicht
@_nl
def empfaengervorschau(m, entwurf_id):
    v = newsletter.vorschau(m, entwurf_id)
    _audit("empfaengervorschau", "mandant=%s entwurf=%d anzahl=%d" % (m["slug"], entwurf_id, v["anzahl"]))
    return jsonify(v)


@bp.post("/mandanten/<int:mandant_id>/entwuerfe/<int:entwurf_id>/freigeben")
@betreiber_auth.betreiber_pflicht
@_nl
def freigeben(m, entwurf_id):
    d = _json() or {}
    ergebnis = newsletter.freigeben(m, entwurf_id, d.get("content_hash"), d.get("bestaetigt"), g.betreiber["email"])
    _audit("entwurf_freigegeben", "mandant=%s entwurf=%d empfaenger=%d" % (m["slug"], entwurf_id, ergebnis["empfaenger"]))
    return jsonify(ergebnis)


@bp.post("/mandanten/<int:mandant_id>/entwuerfe/<int:entwurf_id>/stoppen")
@betreiber_auth.betreiber_pflicht
@_nl
def stoppen(m, entwurf_id):
    ergebnis = newsletter.stoppen(m, entwurf_id)
    _audit("entwurf_gestoppt", "mandant=%s entwurf=%d" % (m["slug"], entwurf_id))
    return jsonify(ergebnis)


@bp.get("/mandanten/<int:mandant_id>/entwuerfe/<int:entwurf_id>/status")
@betreiber_auth.betreiber_pflicht
@_nl
def entwurf_status(m, entwurf_id):
    s = newsletter.status(m, entwurf_id)
    _audit("entwurf_status", "mandant=%s entwurf=%d" % (m["slug"], entwurf_id))
    return jsonify(s)


@bp.get("/mandanten/<int:mandant_id>/entwuerfe/<int:entwurf_id>/protokoll")
@betreiber_auth.betreiber_pflicht
@_nl
def protokoll(m, entwurf_id):
    zeilen = newsletter.protokoll(m, entwurf_id)
    _audit("protokoll_gelesen", "mandant=%s entwurf=%d anzahl=%d" % (m["slug"], entwurf_id, len(zeilen)))      # enthält Adressen: protokolliert
    return jsonify({"empfaenger": zeilen})


@bp.get("/mandanten/<int:mandant_id>/entwuerfe/<int:entwurf_id>/protokoll.csv")
@betreiber_auth.betreiber_pflicht
@_nl
def protokoll_csv(m, entwurf_id):
    zeilen = newsletter.protokoll(m, entwurf_id)
    _audit("protokoll_csv_gelesen", "mandant=%s entwurf=%d anzahl=%d" % (m["slug"], entwurf_id, len(zeilen)))
    from flask import Response
    return Response(newsletter.protokoll_csv(zeilen), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="protokoll-%d.csv"' % entwurf_id})


@bp.get("/mandanten/<int:mandant_id>/testliste")
@betreiber_auth.betreiber_pflicht
@_nl
def testliste_lesen(m):
    adressen = newsletter.testliste(m)
    _audit("testliste_gelesen", "mandant=%s anzahl=%d" % (m["slug"], len(adressen)))
    return jsonify({"adressen": adressen})


@bp.put("/mandanten/<int:mandant_id>/testliste")
@betreiber_auth.betreiber_pflicht
@_nl
def testliste_setzen(m):
    d = _json() or {}
    adressen = newsletter.testliste_setzen(m, d.get("adressen"))
    _audit("testliste_gesetzt", "mandant=%s anzahl=%d" % (m["slug"], len(adressen)))
    return jsonify({"adressen": adressen})


@bp.get("/mandanten/<int:mandant_id>/versand-rate")
@betreiber_auth.betreiber_pflicht
@_nl
def versand_rate_lesen(m):
    return jsonify({"limit_pro_stunde": newsletter.limit_pro_stunde(m["id"]), "standard": newsletter.LIMIT_PRO_STUNDE,
                    "erlaubt_von": newsletter.LIMIT_PRO_STUNDE_MIN, "erlaubt_bis": newsletter.LIMIT_PRO_STUNDE_MAX})


@bp.put("/mandanten/<int:mandant_id>/versand-rate")
@betreiber_auth.betreiber_pflicht
@_nl
def versand_rate_setzen(m):
    d = _json() or {}
    wert = newsletter.limit_pro_stunde_setzen(m["id"], d.get("limit_pro_stunde"), g.betreiber["email"])
    _audit("versand_rate_geaendert", "mandant=%s limit_pro_stunde=%d" % (m["slug"], wert))
    return jsonify({"limit_pro_stunde": wert})


@bp.get("/mandanten/<int:mandant_id>/echtversand")
@betreiber_auth.betreiber_pflicht
@_nl
def echtversand_lesen(m):
    _audit("echtversand_gelesen", "mandant=%s" % m["slug"])
    return jsonify({"echtversand_freigegeben": newsletter.echtversand_freigegeben(m["id"])})


@bp.put("/mandanten/<int:mandant_id>/echtversand")
@betreiber_auth.betreiber_pflicht
@_nl
def echtversand_setzen(m):
    d = _json() or {}
    if not isinstance(d.get("freigegeben"), bool):
        return _fehler("freigegeben muss true oder false sein")
    newsletter.echtversand_setzen(m["id"], d["freigegeben"], g.betreiber["email"])
    _audit("echtversand_geaendert", "mandant=%s freigegeben=%s" % (m["slug"], str(d["freigegeben"]).lower()))
    return jsonify({"echtversand_freigegeben": d["freigegeben"]})
