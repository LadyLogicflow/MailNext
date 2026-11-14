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


def betreiber_auth() -> str:
    """Wie sich Betreiber anmelden: 'portal' (Standard, Portal-Cookie) oder 'offen' (Pi-Testinstanz im Heimnetz, ohne Anmeldung, nur von privaten Adressen).
    Jeder andere Wert gilt als 'portal' (fail closed)."""
    return "offen" if os.environ.get("MAILNEXT_BETREIBER_AUTH", "").strip().lower() == "offen" else "portal"


def betreiber_offen_email() -> str:
    """Im Offen-Modus: Adresse, die als Akteur im Audit steht und Standard-Empfänger der Testmail ist (leer = keine)."""
    return os.environ.get("MAILNEXT_BETREIBER_OFFEN_EMAIL", "").strip().lower()


def pi_adresse() -> str:
    """Adresse oder Name, unter der die Testinstanz im Heimnetz erreicht wird (Host-Prüfung im Offen-Modus)."""
    return os.environ.get("MAILNEXT_PI_ADRESSE", "").strip().lower()


def oeffentlicher_port() -> str | None:
    """Port, auf dem NUR die öffentlichen Seiten (Anmelden, Bestätigen, Abmelden, Einstellungen) beantwortet werden. None = keine Trennung."""
    wert = os.environ.get("MAILNEXT_OEFFENTLICHER_PORT", "").strip()
    return wert if wert.isdigit() else None
