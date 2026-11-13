"""Aus dem Hauptschlüssel abgeleitete Schlüssel (HKDF) je Zweck UND je Mandant.

Grundsatz Mandantentrennung: Derselbe Mensch hat in zwei Mandanten verschiedene Pseudonyme (email_hmac), und ein Token aus Mandant 1 lässt sich in
Mandant 2 nicht prüfen, weil dort ein anderer Schlüssel gilt. Fehlt der Hauptschlüssel, gibt es nichts (fail closed, kein Ersatzschlüssel)."""
import base64
import hashlib
import hmac
import re
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import config
from einstellungen import HauptschluesselFehlt


def _ableiten(info: bytes) -> bytes:
    roh = config.hauptschluessel()
    if roh is None:
        raise HauptschluesselFehlt("MAILNEXT_HAUPTSCHLUESSEL fehlt oder ist zu kurz")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(roh.encode("utf-8"))


def b64(daten: bytes) -> str:
    return base64.urlsafe_b64encode(daten).decode("ascii").rstrip("=")


def b64_zurueck(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def normalisiere_email(email: str) -> str:
    return (email or "").strip().lower()


_EMAIL = re.compile(r"^[^@\s<>\"',;:()\[\]\\]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


def email_gueltig(email: str) -> bool:
    return bool(email) and len(email) <= 254 and bool(_EMAIL.match(email))


def email_hmac(mandant_id: int, email: str) -> str:
    """Pseudonym der Adresse in DIESEM Mandanten (Sperrliste/Minimaldatensatz, Drosselung, Eindeutigkeit)."""
    schluessel = _ableiten(b"mailnext-email-v1-m%d" % int(mandant_id))
    return hmac.new(schluessel, normalisiere_email(email).encode("utf-8"), hashlib.sha256).hexdigest()


def neues_bestaetigungstoken() -> tuple[str, str]:
    """(Token für den Link, SHA-256 für die Datenbank). 32 Zufallsbytes."""
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode("ascii")).hexdigest()


def token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8", "ignore")).hexdigest()


def neue_nonce() -> str:
    return secrets.token_urlsafe(12)


def persoenliches_token(mandant_id: int, abonnent_id: int, nonce: str) -> str:
    """'u1.' + b64(mandant|abonnent|nonce) + '.' + b64(HMAC über den Teil davor). Kein Ablaufdatum (Abmelden muss immer gehen)."""
    teil = "u1." + b64(("%d|%d|%s" % (mandant_id, abonnent_id, nonce)).encode("utf-8"))
    schluessel = _ableiten(b"mailnext-token-v1-m%d" % int(mandant_id))
    return teil + "." + b64(hmac.new(schluessel, teil.encode("ascii"), hashlib.sha256).digest())


def token_pruefen(token: str) -> tuple[int, int, str] | None:
    """(mandant_id, abonnent_id, nonce) bei gültiger Signatur, sonst None. Gegen den Datensatz prüft der Aufrufer die nonce."""
    try:
        teile = (token or "").split(".")
        if len(teile) != 3 or teile[0] != "u1":
            return None
        mandant_s, abonnent_s, nonce = b64_zurueck(teile[1]).decode("utf-8").split("|", 2)
        mandant_id, abonnent_id = int(mandant_s), int(abonnent_s)
        schluessel = _ableiten(b"mailnext-token-v1-m%d" % mandant_id)
        erwartet = b64(hmac.new(schluessel, ("u1." + teile[1]).encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(erwartet, teile[2]):
            return None
        return mandant_id, abonnent_id, nonce
    except HauptschluesselFehlt:
        raise
    except Exception:
        return None
