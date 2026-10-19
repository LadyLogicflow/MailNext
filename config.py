"""Konfiguration von MailNext.

Grundsatz: Es gibt genau EINE geheime Umgebungsvariable (MAILNEXT_HAUPTSCHLUESSEL).
Alles andere hat einen festen Standardwert und steht danach in der Datenbank
(Tabelle einstellung), gepflegt über die Betreiber-Oberfläche."""
import os
from pathlib import Path

HAUPTSCHLUESSEL_MIN_LAENGE = 32


def version() -> str:
    try:
        return (Path(__file__).with_name("VERSION")).read_text(encoding="utf-8").strip()
    except OSError:
        return "unbekannt"


def daten_verzeichnis() -> Path:
    return Path(os.environ.get("MAILNEXT_DATEN", "/data"))


def sortnext_basis_url() -> str:
    return os.environ.get("SORTNEXT_BASE_URL", "https://sortnext.bst-next.de").rstrip("/")


def hauptschluessel() -> str | None:
    """Liefert den Hauptschlüssel oder None. Es gibt bewusst keinen Ersatzwert."""
    wert = os.environ.get("MAILNEXT_HAUPTSCHLUESSEL", "")
    if len(wert) < HAUPTSCHLUESSEL_MIN_LAENGE:
        return None
    return wert
