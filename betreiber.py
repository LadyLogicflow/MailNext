"""Betreiber-Schnittstelle (Anmeldung über das Portal-Cookie, nur Betreiber): Mandanten, Design, Einwilligungstexte, Versandeinstellungen, Kennzahlen.

Jeder Aufruf wird im Audit-Log protokolliert, bevor geantwortet wird (Details: Mandant, Aktion, Zahlen, nie Inhalte oder Zugangsdaten). Scheitert das
Protokollieren, gibt es keine Antwort (500). Geheimnisse werden nie zurückgegeben, nur ob sie gesetzt sind."""
from functools import wraps

from flask import Blueprint, g, jsonify, request

import abonnenten
import betreiber_auth
import db
import mandanten
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
