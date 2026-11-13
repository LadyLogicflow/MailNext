"""MailNext: eigener Dienst für Einwilligungen und Newsletter-Versand (BST Next)."""
import logging
import os

from flask import Flask, Request, jsonify

import config
import db
import einstellungen
import betreiber
import betreiber_ui
import newsletter
import public


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


IMPORT_MAX_BYTES = 3_500_000                                       # Import von Bestandsadressen (bis 20 000 Zeilen); alle anderen Aufrufe bleiben bei 300 000


class _Anfrage(Request):
    @property
    def max_content_length(self):
        return IMPORT_MAX_BYTES if self.endpoint == "betreiber.abonnenten_import" else 300000

    @max_content_length.setter
    def max_content_length(self, wert):
        pass


def create_app(db_pfad: str | None = None, versand_job: bool = False) -> Flask:
    app = Flask(__name__)
    app.request_class = _Anfrage
    verz = config.daten_verzeichnis()
    if db_pfad is None:
        verz.mkdir(parents=True, exist_ok=True)
        db_pfad = str(verz / "mailnext.db")
    db.init(db_pfad)

    app.config["MAX_CONTENT_LENGTH"] = 300000
    app.register_blueprint(public.bp)
    app.register_blueprint(betreiber.bp)
    app.register_blueprint(betreiber_ui.bp)

    @app.errorhandler(einstellungen.HauptschluesselFehlt)
    def _nicht_bereit(_):
        return jsonify({"error": "nicht_bereit", "meldung": "Der Dienst ist nicht vollständig eingerichtet."}), 503

    @app.errorhandler(413)
    def _zu_gross(_):
        return jsonify({"error": "zu_gross"}), 413

    @app.get("/health")
    def health():
        daten, gesund = _health_daten()
        return jsonify(daten), (200 if gesund else 503)

    @app.get("/api/version")
    def api_version():
        return jsonify({"app": "mailnext", "version": config.version()})

    if versand_job:
        _versand_job_starten()
    return app


_job_gestartet = False


def _versand_job_starten(intervall: float = 60.0) -> None:
    """Hintergrundthread: ein Versandlauf je Minute (ein gunicorn-Worker, SQLite). Fehler stoppen den Job nie."""
    global _job_gestartet
    if _job_gestartet:
        return
    _job_gestartet = True
    import threading
    import time

    def schleife():
        while True:
            time.sleep(intervall)
            try:
                newsletter.lauf()
            except Exception:
                logging.exception("Versandlauf fehlgeschlagen")

    threading.Thread(target=schleife, name="mailnext-versand", daemon=True).start()


def _wsgi():
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    return create_app(versand_job=os.environ.get("MAILNEXT_VERSAND_JOB", "1") != "0")
