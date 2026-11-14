"""Auslieferung der Betreiber-Oberfläche (statische Dateien aus ``ui/betreiber/``) unter /betreiber.

Die Seite selbst ist öffentlich lesbar, alle Daten kommen von /api/v1/betreiber, das nur mit dem Portal-Cookie eines Betreibers antwortet. Keine externen
Ressourcen (CSP 'self'), nicht einbettbar, nicht cachebar. Nur flache Dateinamen aus dem Ordner, keine Unterordner, keine Pfadtricks."""
import re
from pathlib import Path

from flask import Blueprint, Response, abort, request, send_from_directory

bp = Blueprint("betreiber_ui", __name__)
ORDNER = Path(__file__).resolve().parent / "ui" / "betreiber"
DATEINAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}\.(html|css|js|svg|png|woff2)$")
KOPF = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' https: data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
                               "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


def _mit_kopf(antwort: Response) -> Response:
    for k, v in KOPF.items():
        antwort.headers[k] = v
    return antwort


@bp.get("/betreiber")
def start_ohne_schraegstrich():
    """index.html lädt betreiber.css und betreiber.js RELATIV. Unter /betreiber (ohne Schrägstrich) würde der Browser daraus /betreiber.css und /betreiber.js machen (404,
    leere Seite). Darum immer auf /betreiber/ umleiten: fester Pfad, Query bleibt, relativer Location-Kopf (stört Proxys und Tunnel mit anderem Host nicht)."""
    abfrage = request.query_string.decode("utf-8", "replace")
    return Response(status=308, headers={"Location": "/betreiber/" + ("?" + abfrage if abfrage else ""), "Cache-Control": "no-store"})


@bp.get("/betreiber/")
def start():
    if not (ORDNER / "index.html").is_file():
        abort(404)
    return _mit_kopf(send_from_directory(str(ORDNER), "index.html", mimetype="text/html"))


@bp.get("/betreiber/<name>")
def datei(name):
    if not DATEINAME.match(name) or not (ORDNER / name).is_file():
        abort(404)
    return _mit_kopf(send_from_directory(str(ORDNER), name))
