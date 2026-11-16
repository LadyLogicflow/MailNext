"""Öffentliche Schnittstelle (Formulare der Mandanten-Websites, Links in Mails). Der Mandant steht immer als Kennung (slug) im Pfad.

Regeln: /anmelden antwortet bei Gültigkeit der Form IMMER 200 (kein Abfragen von Adressen); 400 nur bei Formfehlern des Aufrufers.
GET ändert nie etwas (Mail-Scanner rufen Links ab). CORS nur für die Ursprünge, die der Mandant hinterlegt hat."""
from flask import Blueprint, Response, jsonify, make_response, request

import abonnenten
import bilder
import config
import newsletter
import mandanten
import seiten
from abonnenten import BereitsAbgemeldet, FormFehler, TokenAbgelaufen, TokenUngueltig

bp = Blueprint("public", __name__)

MELDUNGEN = {
    "json_ungueltig": "Die Anfrage ist kein gültiges JSON-Objekt.",
    "feld_ungueltig": "Ein Feld hat einen unbekannten Wert.",
    "version_unbekannt": "Die Einwilligungsversion ist unbekannt.",
    "token_ungueltig": "Der Link ist ungültig.",
    "token_abgelaufen": "Der Link ist abgelaufen. Bitte melden Sie sich erneut an.",
    "bereits_abgemeldet": "Die Adresse ist bereits abgemeldet.",
    "token_erforderlich": "Für diese Aktion ist ein persönlicher Link nötig.",
    "mandant_unbekannt": "Unbekannt.",
}


def client_ip() -> str:
    """Adresse der Anfrage. Hinter n vertrauenswürdigen Proxys zählt der n-te Eintrag von rechts in X-Forwarded-For (ein vom Client vorangestellter
    Wert wird so ignoriert)."""
    n = config.proxy_anzahl()
    teile = [t.strip() for t in request.headers.get("X-Forwarded-For", "").split(",") if t.strip()]
    if n and len(teile) >= n:
        return teile[-n][:64]
    return (request.remote_addr or "")[:64]


def _fehler(code: str, status: int, feld: str | None = None):
    daten = {"error": code, "meldung": MELDUNGEN.get(code, code)}
    if feld:
        daten["feld"] = feld
    return jsonify(daten), status


def _mandant(slug: str):
    return mandanten.lesen_slug(slug)


def _cors(antwort, mandant):
    ursprung = request.headers.get("Origin", "")
    if mandant and ursprung and ursprung.rstrip("/") in mandant["design"]["cors_ursprunge"]:
        antwort.headers["Access-Control-Allow-Origin"] = ursprung
        antwort.headers["Vary"] = "Origin"
        antwort.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        antwort.headers["Access-Control-Allow-Headers"] = "Content-Type"
        antwort.headers["Access-Control-Max-Age"] = "600"
    return antwort


def _json_objekt():
    daten = request.get_json(silent=True)
    return daten if isinstance(daten, dict) else None


def _antwort(slug: str, funktion, offen_fuer_ruhende=False):
    """Gemeinsamer Rahmen der JSON-Endpunkte: Mandant, CORS, Preflight."""
    mandant = mandanten.lesen_slug(slug, nur_aktive=not offen_fuer_ruhende)
    if mandant is None:
        return _fehler("mandant_unbekannt", 404)
    if request.method == "OPTIONS":
        return _cors(Response(status=204), mandant)
    return _cors(make_response(funktion(mandant)), mandant)


@bp.route("/api/<slug>/newsletter/formular", methods=["GET", "OPTIONS"])
def formular(slug):
    def tun(m):
        e = mandanten.aktuelle_einwilligung(m["id"])
        return jsonify({"name": m["name"], "einwilligungs_version": e["version"] if e else None, "einwilligungs_text": e["text"] if e else None,
                        "rollen": m["design"]["rollen"], "interessen": m["design"]["interessen"]})
    return _antwort(slug, tun)


@bp.route("/api/<slug>/newsletter/anmelden", methods=["POST", "OPTIONS"])
def anmelden(slug):
    def tun(m):
        d = _json_objekt()
        if d is None:
            return _fehler("json_ungueltig", 400)
        if not isinstance(d.get("email", ""), str):
            return _fehler("feld_ungueltig", 400, "email")
        try:
            abonnenten.anmelden(m, d.get("email", ""), d.get("rolle"), d.get("interessen"), d.get("einwilligungs_version"), client_ip())
        except FormFehler as f:
            return _fehler(f.code, 400, f.feld)
        return jsonify({"status": "ok"})
    return _antwort(slug, tun)


@bp.route("/api/<slug>/newsletter/bestaetigen", methods=["POST", "OPTIONS"])
def bestaetigen_json(slug):
    def tun(m):
        d = _json_objekt()
        if d is None:
            return _fehler("json_ungueltig", 400)
        try:
            return jsonify({"status": abonnenten.bestaetigen(m, d.get("token"))})
        except TokenAbgelaufen:
            return _fehler("token_abgelaufen", 410)
        except TokenUngueltig:
            return _fehler("token_ungueltig", 400)
    return _antwort(slug, tun)


@bp.route("/api/<slug>/newsletter/praeferenzen", methods=["GET", "POST", "OPTIONS"])
def praeferenzen(slug):
    def tun(m):
        try:
            if request.method == "GET":
                p = abonnenten.praeferenzen_lesen(request.args.get("t", ""), m)
                p.pop("mandant")
                return jsonify(p)
            d = _json_objekt()
            if d is None:
                return _fehler("json_ungueltig", 400)
            abonnenten.praeferenzen_setzen(d.get("t", ""), d.get("rolle"), d.get("interessen"), m)
            return jsonify({"status": "ok"})
        except TokenUngueltig:
            return _fehler("token_ungueltig", 400)
        except BereitsAbgemeldet:
            return _fehler("bereits_abgemeldet", 409)
        except FormFehler as f:
            return _fehler(f.code, 400, f.feld)
    return _antwort(slug, tun, offen_fuer_ruhende=True)


@bp.route("/api/<slug>/newsletter/abmelden", methods=["POST", "OPTIONS"])
def abmelden_json(slug):
    def tun(m):
        d = _json_objekt()
        if d is None:
            return _fehler("json_ungueltig", 400)
        if "t" not in d:                                                                   # der alte Aufruf nur mit E-Mail löscht NICHTS
            return _fehler("token_erforderlich", 400)
        try:
            return jsonify({"status": abonnenten.abmelden(d.get("t"), m)})
        except TokenUngueltig:
            return _fehler("token_ungueltig", 400)
    return _antwort(slug, tun, offen_fuer_ruhende=True)


@bp.route("/<slug>/newsletter/abmelden-one-click/<token>", methods=["POST", "GET", "PUT", "DELETE", "PATCH"])
def abmelden_one_click(slug, token):
    """RFC 8058: Mailprogramme senden POST (List-Unsubscribe=One-Click). Alles andere ist 405 und ändert nie etwas."""
    if request.method != "POST":
        return Response(status=405, headers={"Allow": "POST"})
    mandant = mandanten.lesen_slug(slug, nur_aktive=False)
    if mandant is None:
        return Response(status=404)
    try:
        abonnenten.abmelden(token, mandant)
    except TokenUngueltig:
        return Response(status=400)
    return Response(status=200)


@bp.route("/<slug>/newsletter/bestaetigen/<token>", methods=["GET", "POST"])
def bestaetigen_seite(slug, token):
    mandant = mandanten.lesen_slug(slug)
    if mandant is None:
        return Response("Nicht gefunden", status=404)
    if request.method == "GET":
        return seiten.bestaetigen_formular(mandant, token)
    try:
        abonnenten.bestaetigen(mandant, token)
    except TokenAbgelaufen:
        return seiten.meldung(mandant, "Link abgelaufen", MELDUNGEN["token_abgelaufen"], 410)
    except TokenUngueltig:
        return seiten.meldung(mandant, "Link ungültig", MELDUNGEN["token_ungueltig"], 400)
    return seiten.meldung(mandant, "Danke!", "Ihre Anmeldung ist bestätigt.")


@bp.route("/<slug>/newsletter/einstellungen", methods=["GET", "POST"])
def einstellungen_seite(slug):
    mandant = mandanten.lesen_slug(slug, nur_aktive=False)
    if mandant is None:
        return Response("Nicht gefunden", status=404)
    token = request.args.get("t", "")
    try:
        if request.method == "POST":
            if request.form.get("aktion") == "abmelden":
                abonnenten.abmelden(token, mandant)
                return seiten.meldung(mandant, "Abgemeldet", "Sie sind abgemeldet. Wir senden Ihnen keine Newsletter mehr.")
            rolle = request.form.get("rolle") or None
            abonnenten.praeferenzen_setzen(token, rolle, request.form.getlist("interessen"), mandant)
            hinweis = "Ihre Einstellungen sind gespeichert."
        else:
            hinweis = ""
        return seiten.einstellungen_formular(mandant, token, abonnenten.praeferenzen_lesen(token, mandant), hinweis)
    except TokenUngueltig:
        return seiten.meldung(mandant, "Link ungültig", MELDUNGEN["token_ungueltig"], 400)
    except BereitsAbgemeldet:
        return seiten.meldung(mandant, "Newsletter", MELDUNGEN["bereits_abgemeldet"], 409)
    except FormFehler:
        return seiten.meldung(mandant, "Eingabe ungültig", "Ein Feld hat einen unbekannten Wert.", 400)


@bp.get("/<slug>/bild/<dateiname>")
def bild(slug, dateiname):
    """Bild eines Mandanten, nur lesend und ohne Anmeldung (Logo und Bilder in Newsletter-Mails). Fester Content-Type aus der Datenbank, nie aus der
    Dateiendung; jede Abweichung (Mandant, Token, Endung) ist ein gleichförmiges 404."""
    treffer = bilder.ausliefern(slug, dateiname)
    if treffer is None:
        return Response("Nicht gefunden", status=404, mimetype="text/plain")
    daten, typ = treffer
    antwort = Response(daten, status=200, mimetype=typ)
    antwort.headers["X-Content-Type-Options"] = "nosniff"
    antwort.headers["Cache-Control"] = "public, max-age=86400"
    antwort.headers["Content-Disposition"] = "inline"
    antwort.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    antwort.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
    return antwort


@bp.get("/<slug>/newsletter/ansicht/<kennung>")
def newsletter_ansicht(slug, kennung):
    """'Im Browser ansehen': der Layout-Newsletter als Webseite, dauerhaft erreichbar, ohne Anmeldung. Die Kennung ist die Berechtigung (nicht zu erraten); die Seite ist für alle
    gleich (keine persönlichen Links), ohne Skripte, ohne Tracking, nicht für Suchmaschinen."""
    seite = newsletter.ansicht_html(slug, kennung)
    if seite is None:
        return Response("Nicht gefunden", status=404, mimetype="text/plain")
    antwort = Response(seite, status=200, mimetype="text/html")
    antwort.headers["Content-Security-Policy"] = ("default-src 'none'; img-src https: http:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; "
                                                 "frame-ancestors 'none'")
    antwort.headers["X-Content-Type-Options"] = "nosniff"
    antwort.headers["Referrer-Policy"] = "no-referrer"
    antwort.headers["X-Robots-Tag"] = "noindex, nofollow"
    antwort.headers["Cache-Control"] = "private, max-age=300"
    return antwort
