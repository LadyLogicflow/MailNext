"""MailNext: eigener Dienst für Einwilligungen und Newsletter-Versand (BST Next)."""
import logging
import os

from flask import Flask, jsonify

import config
import db
import einstellungen


def _health_daten() -> tuple[dict, bool]:
    """Liefert (Daten, gesund). Keine personenbezogenen Daten, nur Zustände."""
    daten = {"app": "mailnext", "version": config.version()}
    gesund = True
    if einstellungen.hauptschluessel_ok():
        daten["hauptschluessel"] = "ok"
    else:
        daten["hauptschluessel"] = "hauptschluessel_fehlt"
        gesund = False
    try:
        with db.verbindung() as c:
            c.execute("SELECT 1").fetchone()
        daten["datenbank"] = "ok"
    except Exception:
        logging.exception("Health: Datenbank nicht erreichbar")
        daten["datenbank"] = "fehler"
        gesund = False
    daten["status"] = "ok" if gesund else "fehler"
    return daten, gesund


def create_app(db_pfad: str | None = None) -> Flask:
    app = Flask(__name__)
    verz = config.daten_verzeichnis()
    if db_pfad is None:
        verz.mkdir(parents=True, exist_ok=True)
        db_pfad = str(verz / "mailnext.db")
    db.init(db_pfad)

    @app.get("/health")
    def health():
        daten, gesund = _health_daten()
        return jsonify(daten), (200 if gesund else 503)

    @app.get("/api/version")
    def api_version():
        return jsonify({"app": "mailnext", "version": config.version()})

    return app


def _wsgi():
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    return create_app()
