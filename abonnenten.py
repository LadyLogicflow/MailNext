"""Abonnentinnen je Mandant: Anmeldung (Double-Opt-in), Bestätigung, Abmeldung, Präferenzen.

Alle Abfragen filtern auf mandant_id. Eine Adresse wird nur als Pseudonym (email_hmac, je Mandant verschieden) wiedererkannt; die Klartextadresse steht nur
solange jemand angemeldet ist. Nach der Abmeldung bleibt der Minimaldatensatz (HMAC, Zeitpunkt der Anmeldung, Zeitpunkt der Abmeldung)."""
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

import db
import mailer
import schluessel

LOG = logging.getLogger("mailnext.abonnenten")
BESTAETIGUNG_STUNDEN = 48
MAX_MAILS_JE_ADRESSE_24H = 3
MAX_MAILS_JE_IP_STUNDE = 20


class FormFehler(Exception):
    """Fehler des Aufrufers (400). ``code`` und ``feld`` sind für die Antwort bestimmt und verraten nichts über Adressen."""

    def __init__(self, code, feld=None):
        super().__init__(code)
        self.code, self.feld = code, feld


class TokenUngueltig(Exception):
    pass


class TokenAbgelaufen(Exception):
    pass


class BereitsAbgemeldet(Exception):
    pass


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _jetzt() -> datetime:
    return datetime.now(timezone.utc)


def _auswahl_pruefen(mandant: dict, rolle, interessen) -> tuple[str | None, list]:
    erlaubte_rollen = {e["wert"] for e in mandant["design"]["rollen"]}
    erlaubte_interessen = {e["wert"] for e in mandant["design"]["interessen"]}
    if rolle is not None and (not isinstance(rolle, str) or rolle not in erlaubte_rollen):
        raise FormFehler("feld_ungueltig", "rolle")
    if interessen is None:
        interessen = []
    if (not isinstance(interessen, list) or len(interessen) > 30
            or any(not isinstance(i, str) or i not in erlaubte_interessen for i in interessen)):
        raise FormFehler("feld_ungueltig", "interessen")
    return rolle, sorted(set(interessen))


def anmelden(mandant: dict, email: str, rolle, interessen, version: str, ip: str) -> dict:
    """Immer ohne Ergebnis nach außen (der Aufrufer antwortet 200). Gibt für Tests zurück, was passiert ist."""
    rolle, interessen = _auswahl_pruefen(mandant, rolle, interessen)
    if not isinstance(version, str) or not version:
        raise FormFehler("version_unbekannt", "einwilligungs_version")
    import mandanten
    if not mandanten.einwilligung_vorhanden(mandant["id"], version):
        raise FormFehler("version_unbekannt", "einwilligungs_version")
    email = schluessel.normalisiere_email(email)
    if not schluessel.email_gueltig(email):
        return {"aktion": "ignoriert", "grund": "adresse_ungueltig"}
    mid = mandant["id"]
    h = schluessel.email_hmac(mid, email)
    jetzt = _jetzt()
    with db.verbindung() as c:
        c.execute("DELETE FROM anmelde_log WHERE zeit < ?", (_iso(jetzt - timedelta(days=2)),))
        je_adresse = c.execute("SELECT COUNT(*) FROM anmelde_log WHERE mandant_id=? AND email_hmac=? AND zeit>=?",
                               (mid, h, _iso(jetzt - timedelta(hours=24)))).fetchone()[0]
        je_ip = c.execute("SELECT COUNT(*) FROM anmelde_log WHERE mandant_id=? AND ip=? AND zeit>=?",
                          (mid, ip, _iso(jetzt - timedelta(hours=1)))).fetchone()[0]
        if je_adresse >= MAX_MAILS_JE_ADRESSE_24H or je_ip >= MAX_MAILS_JE_IP_STUNDE:
            return {"aktion": "gedrosselt"}
        z = c.execute("SELECT * FROM abonnent WHERE mandant_id=? AND email_hmac=?", (mid, h)).fetchone()
        if z is not None and z["status"] == "bestaetigt":
            return {"aktion": "schon_bestaetigt"}
        token, token_h = schluessel.neues_bestaetigungstoken()
        ablauf = _iso(jetzt + timedelta(hours=BESTAETIGUNG_STUNDEN))
        nonce = schluessel.neue_nonce()
        felder = (email, rolle, json.dumps(interessen), version, _iso(jetzt), ip, token_h, ablauf, nonce)
        if z is None:
            c.execute("INSERT INTO abonnent(mandant_id, email_hmac, status, email, rolle, interessen, einwilligung_version, angemeldet_am, ip, "
                      "token_hash, token_ablauf, nonce) VALUES (?,?,'unbestaetigt',?,?,?,?,?,?,?,?,?)", (mid, h) + felder)
        else:  # unbestätigt, abgemeldet oder unzustellbar: neue Einwilligung ersetzt den alten Stand
            c.execute("UPDATE abonnent SET status='unbestaetigt', email=?, rolle=?, interessen=?, einwilligung_version=?, angemeldet_am=?, ip=?, "
                      "token_hash=?, token_ablauf=?, nonce=?, bestaetigt_am=NULL, abgemeldet_am=NULL WHERE id=? AND mandant_id=?",
                      felder + (z["id"], mid))
        c.execute("INSERT INTO anmelde_log(mandant_id, email_hmac, ip, zeit) VALUES (?,?,?,?)", (mid, h, ip, _iso(jetzt)))
    betreff, text, html_text = mailer.bestaetigungsmail(mandant, token)
    return {"aktion": "mail", "mail": mailer.senden(mandant, email, betreff, text, html_text)}


def bestaetigen(mandant: dict, token: str) -> str:
    """'bestaetigt' (auch bei erneutem Klick). Wirft TokenUngueltig oder TokenAbgelaufen."""
    if not isinstance(token, str) or not token or len(token) > 200:
        raise TokenUngueltig()
    h = schluessel.token_hash(token)
    with db.verbindung() as c:
        z = c.execute("SELECT * FROM abonnent WHERE mandant_id=? AND token_hash=?", (mandant["id"], h)).fetchone()
        if z is None:
            raise TokenUngueltig()
        if z["status"] == "bestaetigt":
            return "bestaetigt"
        if z["status"] != "unbestaetigt":
            raise TokenUngueltig()
        if z["token_ablauf"] and z["token_ablauf"] < _iso(_jetzt()):
            raise TokenAbgelaufen()
        c.execute("UPDATE abonnent SET status='bestaetigt', bestaetigt_am=? WHERE id=? AND mandant_id=?", (_iso(_jetzt()), z["id"], mandant["id"]))
    return "bestaetigt"


def persoenliches_token(abonnent_zeile) -> str:
    return schluessel.persoenliches_token(abonnent_zeile["mandant_id"], abonnent_zeile["id"], abonnent_zeile["nonce"])


def _per_token(token: str):
    """(mandant, Zeile) für ein gültiges persönliches Token, sonst None. Auch bei stillgelegtem Mandanten: Abmelden muss immer gehen."""
    geprueft = schluessel.token_pruefen(token)
    if geprueft is None:
        return None
    mandant_id, abonnent_id, nonce = geprueft
    import mandanten
    mandant = mandanten.lesen(mandant_id)
    if mandant is None:
        return None
    with db.verbindung() as c:
        z = c.execute("SELECT * FROM abonnent WHERE id=? AND mandant_id=?", (abonnent_id, mandant_id)).fetchone()
    if z is None or not hmac.compare_digest(z["nonce"], nonce):
        return None
    return mandant, z


def mandant_zum_token(token: str) -> dict | None:
    r = _per_token(token)
    return r[0] if r else None


def abmelden(token: str, erwarteter_mandant: dict | None = None) -> str:
    """'abgemeldet' (idempotent). Ersetzt den Eintrag durch den Minimaldatensatz. Wirft TokenUngueltig."""
    r = _per_token(token)
    if r is None or (erwarteter_mandant is not None and r[0]["id"] != erwarteter_mandant["id"]):
        raise TokenUngueltig()
    mandant, z = r
    if z["status"] == "abgemeldet":
        return "abgemeldet"
    with db.verbindung() as c:
        c.execute("UPDATE abonnent SET status='abgemeldet', abgemeldet_am=?, email=NULL, rolle=NULL, interessen=NULL, einwilligung_version=NULL, "
                  "bestaetigt_am=NULL, ip=NULL, token_hash=NULL, token_ablauf=NULL WHERE id=? AND mandant_id=?",
                  (_iso(_jetzt()), z["id"], mandant["id"]))
    return "abgemeldet"


def _maskieren(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    lokal, domain = email.split("@", 1)
    return "%s***@%s" % (lokal[:1], domain)


def praeferenzen_lesen(token: str, erwarteter_mandant: dict | None = None) -> dict:
    r = _per_token(token)
    if r is None or (erwarteter_mandant is not None and r[0]["id"] != erwarteter_mandant["id"]):
        raise TokenUngueltig()
    mandant, z = r
    d = mandant["design"]
    return {"email_maskiert": _maskieren(z["email"]), "rolle": z["rolle"], "interessen": json.loads(z["interessen"] or "[]"),
            "status": z["status"], "erlaubte_rollen": d["rollen"], "erlaubte_interessen": d["interessen"], "mandant": mandant}


def praeferenzen_setzen(token: str, rolle, interessen, erwarteter_mandant: dict | None = None) -> None:
    r = _per_token(token)
    if r is None or (erwarteter_mandant is not None and r[0]["id"] != erwarteter_mandant["id"]):
        raise TokenUngueltig()
    mandant, z = r
    if z["status"] == "abgemeldet":
        raise BereitsAbgemeldet()
    rolle, interessen = _auswahl_pruefen(mandant, rolle, interessen)
    with db.verbindung() as c:
        c.execute("UPDATE abonnent SET rolle=?, interessen=? WHERE id=? AND mandant_id=?",
                  (rolle, json.dumps(interessen), z["id"], mandant["id"]))


# ----- Betreiber-Sicht (je Mandant) -----

def kennzahlen(mandant_id: int) -> dict:
    with db.verbindung() as c:
        zeilen = c.execute("SELECT status, COUNT(*) AS n FROM abonnent WHERE mandant_id=? GROUP BY status", (int(mandant_id),)).fetchall()
    zahlen = {"bestaetigt": 0, "unbestaetigt": 0, "abgemeldet": 0, "unzustellbar": 0}
    zahlen.update({z["status"]: z["n"] for z in zeilen})
    return zahlen


def liste(mandant_id: int) -> list:
    """Ohne IP und ohne Token. Abgemeldete erscheinen nur als Zahl in den Kennzahlen, nicht in der Liste."""
    with db.verbindung() as c:
        zeilen = c.execute("SELECT * FROM abonnent WHERE mandant_id=? AND status!='abgemeldet' ORDER BY id", (int(mandant_id),)).fetchall()
    return [{"id": z["id"], "email": z["email"], "status": z["status"], "rolle": z["rolle"], "interessen": json.loads(z["interessen"] or "[]"),
             "einwilligung_version": z["einwilligung_version"], "einwilligung_am": z["angemeldet_am"], "bestaetigt_am": z["bestaetigt_am"]}
            for z in zeilen]
