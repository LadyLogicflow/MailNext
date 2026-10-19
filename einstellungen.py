"""Verschlüsselte Einstellungen (Fernet). Der Schlüssel wird aus dem Hauptschlüssel
abgeleitet; fehlt dieser, gibt es keinen Zugriff (fail closed)."""
import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import config
import db


class HauptschluesselFehlt(RuntimeError):
    pass


def _fernet() -> Fernet:
    roh = config.hauptschluessel()
    if roh is None:
        raise HauptschluesselFehlt("MAILNEXT_HAUPTSCHLUESSEL fehlt oder ist zu kurz")
    schluessel = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                      info=b"mailnext-einstellungen-v1").derive(roh.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(schluessel))


def hauptschluessel_ok() -> bool:
    return config.hauptschluessel() is not None


def setzen(schluessel: str, wert: str, akteur: str) -> None:
    token = _fernet().encrypt(wert.encode("utf-8")).decode("ascii")
    with db.verbindung() as c:
        c.execute(
            "INSERT INTO einstellung(schluessel, wert_verschluesselt, geaendert_am, geaendert_von) "
            "VALUES (?,?,?,?) ON CONFLICT(schluessel) DO UPDATE SET "
            "wert_verschluesselt=excluded.wert_verschluesselt, "
            "geaendert_am=excluded.geaendert_am, geaendert_von=excluded.geaendert_von",
            (schluessel, token, db.jetzt(), akteur))


def lesen(schluessel: str, standard: str | None = None) -> str | None:
    with db.verbindung() as c:
        z = c.execute("SELECT wert_verschluesselt FROM einstellung WHERE schluessel=?",
                      (schluessel,)).fetchone()
    if z is None:
        return standard
    try:
        return _fernet().decrypt(z["wert_verschluesselt"].encode("ascii")).decode("utf-8")
    except InvalidToken:
        # Falscher Hauptschlüssel: nie still einen Standardwert vortäuschen.
        raise HauptschluesselFehlt("Einstellung nicht entschlüsselbar (Hauptschlüssel geändert?)")


def ist_gesetzt(schluessel: str) -> bool:
    with db.verbindung() as c:
        return c.execute("SELECT 1 FROM einstellung WHERE schluessel=?", (schluessel,)).fetchone() is not None
