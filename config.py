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


def basis_url() -> str:
    """Öffentliche Adresse von MailNext (für Links in Mails). Je Mandant überschreibbar (design.basis_url)."""
    return os.environ.get("MAILNEXT_BASIS_URL", "https://mailnext.bst-next.de").rstrip("/")


def proxy_anzahl() -> int:
    """Wie vielen vorgeschalteten Proxys (Coolify/Traefik) für X-Forwarded-For vertraut wird. 0 = Adresse der Verbindung."""
    try:
        return max(0, int(os.environ.get("MAILNEXT_PROXIES", "1")))
    except ValueError:
        return 1


def ausgang_verzeichnis() -> Path:
    """Ablage für Mails im Modus 'datei' (Test auf dem Pi, ohne echten Versand)."""
    return daten_verzeichnis() / "ausgang"
