"""Betreiber-Schnittstelle (Anmeldung über das Portal-Cookie, nur Betreiber): Mandanten, Design, Einwilligungstexte, Versandeinstellungen, Kennzahlen.

Jeder Aufruf wird im Audit-Log protokolliert, bevor geantwortet wird (Details: Mandant, Aktion, Zahlen, nie Inhalte oder Zugangsdaten). Scheitert das
Protokollieren, gibt es keine Antwort (500). Geheimnisse werden nie zurückgegeben, nur ob sie gesetzt sind."""
from functools import wraps

from flask import Blueprint, g, jsonify, request

import abonnenten
import betreiber_auth
import db
import mandanten
import newsletter
from mandanten import Ungueltig

bp = Blueprint("betreiber", __name__, url_prefix="/api/v1/betreiber")


def _ip() -> str:
    from public import client_ip
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
            return jsonify({"error": fehler.code, "meldung": fehler.meldung}), fehler.status
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
    e = newsletter.anlegen(m, d.get("betreff"), d.get("text"), d.get("ziel", "testliste"), d.get("segment"))
    _audit("entwurf_angelegt", "mandant=%s entwurf=%d ziel=%s" % (m["slug"], e["id"], e["ziel"]))
    return jsonify({"id": e["id"], "content_hash": e["content_hash"]}), 201


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
    e = newsletter.aendern(m, entwurf_id, d.get("betreff"), d.get("text"), d.get("ziel"), d.get("segment"))
    _audit("entwurf_geaendert", "mandant=%s entwurf=%d" % (m["slug"], entwurf_id))
    return jsonify({"content_hash": e["content_hash"]})


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
