"""Auslieferung der Betreiber-Oberfläche (statische Dateien aus ``ui/betreiber/``) unter /betreiber.

Die Seite selbst ist öffentlich lesbar, alle Daten kommen von /api/v1/betreiber, das nur mit dem Portal-Cookie eines Betreibers antwortet. Keine externen
Ressourcen (CSP 'self'), nicht einbettbar, nicht cachebar. Nur flache Dateinamen aus dem Ordner, keine Unterordner, keine Pfadtricks."""
import re
from pathlib import Path

from flask import Blueprint, Response, abort, send_from_directory

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
