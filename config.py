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
    wert = os.environ.get("MAILNEXT_BASIS_URL", "").strip()
    if wert:
        return wert.rstrip("/")
    # Pi-Testinstanz ohne ausdrückliche Adresse: erste Pi-Adresse und öffentlicher Port am Pi (die Compose reicht beides durch)
    port = os.environ.get("MAILNEXT_PORT_OEFFENTLICH", "").strip()
    if port.isdigit() and pi_adresse():
        return "http://%s:%s" % (pi_adresse(), port)
    return "https://mailnext.bst-next.de"


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


def pi_adressen() -> list:
    """Adressen und Namen, unter denen die Testinstanz erreicht wird (Host-Prüfung im Offen-Modus): MAILNEXT_PI_ADRESSE, Komma-Liste, ohne Port
    (ein trotzdem angehängter Port wird entfernt). Beispiel: 192.168.1.50,100.101.102.103,pi5,pi5.beispiel.ts.net"""
    ergebnis = []
    for teil in os.environ.get("MAILNEXT_PI_ADRESSE", "").split(","):
        name = teil.strip().lower()
        if name.startswith("["):                                                        # [::1]
            name = name.split("]", 1)[0] + "]"
        elif name.count(":") == 1:                                                       # name:port
            name = name.split(":", 1)[0]
        if name and name not in ergebnis:
            ergebnis.append(name)
    return ergebnis


def pi_adresse() -> str:
    """Die erste Pi-Adresse (für Links), leer wenn keine gesetzt ist."""
    liste = pi_adressen()
    return liste[0] if liste else ""


def oeffentlicher_port() -> str | None:
    """Port, auf dem NUR die öffentlichen Seiten (Anmelden, Bestätigen, Abmelden, Einstellungen) beantwortet werden. None = keine Trennung."""
    wert = os.environ.get("MAILNEXT_OEFFENTLICHER_PORT", "").strip()
    return wert if wert.isdigit() else None
