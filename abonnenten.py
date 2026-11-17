"""Abonnentinnen je Mandant: Anmeldung (Double-Opt-in), Bestätigung, Abmeldung, Präferenzen.

Alle Abfragen filtern auf mandant_id. Eine Adresse wird nur als Pseudonym (email_hmac, je Mandant verschieden) wiedererkannt; die Klartextadresse steht nur
solange jemand angemeldet ist. Nach der Abmeldung bleibt der Minimaldatensatz (HMAC, Zeitpunkt der Anmeldung, Zeitpunkt der Abmeldung)."""
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

import db
import import_csv
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
             "tags": json.loads(z["tags"] or "[]"), "herkunft": z["herkunft"] or "formular", "quelle": z["quelle"],
             "einwilligung_version": z["einwilligung_version"], "einwilligung_am": z["angemeldet_am"], "bestaetigt_am": z["bestaetigt_am"]}
            for z in zeilen]


# ----- Tags nachträglich ändern (v0.8.1-Stand, catrin #19236) -----

MAX_IDS_TAGS_AENDERN = 2000
MAX_TAGS_AENDERN = 20


def _tags_aendern_pruefen(werte, feld) -> list:
    if werte is None:
        return []
    if not isinstance(werte, list) or len(werte) > MAX_TAGS_AENDERN:
        raise FormFehler("tags_ungueltig", feld)
    ergebnis, gesehen = [], set()
    for w in werte:
        t = import_csv.tag_pruefen(w)
        if t is None:
            raise FormFehler("tag_ungueltig", feld)
        if t.lower() not in gesehen:
            gesehen.add(t.lower())
            ergebnis.append(t)
    return ergebnis


def tags_aendern(mandant: dict, abonnent_ids, hinzufuegen, entfernen) -> dict:
    """Tags vieler bestätigter Abonnentinnen dieses Mandanten gemeinsam ändern: ``hinzufuegen`` (höchstens MAX_TAGS_JE_ADRESSE je Adresse, Groß-/Kleinschreibung egal, vorhandene
    Schreibweise bleibt) und ``entfernen``. Abgemeldete, unzustellbare, unbestätigte und fremde/unbekannte Nummern werden übersprungen und gezählt, nie verändert. Alles in einer
    Transaktion; Antwort nur Zahlen und die neue Tag-Liste, nie Adressen. Jede Nummer zählt GENAU EINMAL: geaendert + unveraendert + Summe(uebersprungen) = Zahl der verschiedenen
    Nummern; ``tag_limit_teilweise`` ist nur ein Hinweis (davon in geaendert: ein neuer Tag passte wegen der 20er-Grenze nicht mehr), kein Zähler der Summe. Freigegebene Versandlisten bleiben festgeschrieben (eigene Tabelle), offene Entwürfe zählen neu."""
    if (not isinstance(abonnent_ids, list) or not 1 <= len(abonnent_ids) <= MAX_IDS_TAGS_AENDERN
            or any(isinstance(i, bool) or not isinstance(i, int) or i < 1 for i in abonnent_ids)):
        raise FormFehler("ids_ungueltig", "abonnent_ids")
    ids = list(dict.fromkeys(abonnent_ids))
    add, rem = _tags_aendern_pruefen(hinzufuegen, "hinzufuegen"), _tags_aendern_pruefen(entfernen, "entfernen")
    if not add and not rem:
        raise FormFehler("nichts_zu_tun", "hinzufuegen")
    if {t.lower() for t in add} & {t.lower() for t in rem}:
        raise FormFehler("tags_widerspruch", "entfernen")
    mid = int(mandant["id"])
    entfernen_klein = {t.lower() for t in rem}
    z = {"geaendert": 0, "unveraendert": 0, "uebersprungen": {"abgemeldet": 0, "unzustellbar": 0, "unbestaetigt": 0, "unbekannt": 0, "tag_limit": 0}, "tag_limit_teilweise": 0}
    with db.verbindung() as c:
        zeilen = {}
        for ab in range(0, len(ids), 500):
            teil = ids[ab:ab + 500]
            for r in c.execute("SELECT id, status, tags FROM abonnent WHERE mandant_id=? AND id IN (%s)" % ",".join("?" * len(teil)), [mid] + teil):
                zeilen[r["id"]] = r
        for i in ids:
            r = zeilen.get(i)
            if r is None:
                z["uebersprungen"]["unbekannt"] += 1
                continue
            if r["status"] != "bestaetigt":
                z["uebersprungen"][r["status"] if r["status"] in z["uebersprungen"] else "unbekannt"] += 1
                continue
            alt = json.loads(r["tags"] or "[]")
            neu = [t for t in alt if t.lower() not in entfernen_klein]
            bekannt = {t.lower() for t in neu}
            limit = False
            for t in add:
                if t.lower() in bekannt:
                    continue
                if len(neu) >= import_csv.MAX_TAGS_JE_ADRESSE:
                    limit = True
                    continue
                neu.append(t)
                bekannt.add(t.lower())
            if neu != alt:
                c.execute("UPDATE abonnent SET tags=? WHERE id=? AND mandant_id=?", (json.dumps(neu, ensure_ascii=False), i, mid))
                z["geaendert"] += 1
                if limit:                                           # geändert, aber ein neuer Tag passte nicht mehr (nur Hinweis, nicht Teil der Summe)
                    z["tag_limit_teilweise"] += 1
            elif limit:
                z["uebersprungen"]["tag_limit"] += 1               # nichts ging wegen der 20er-Grenze
            else:
                z["unveraendert"] += 1
    z["tags"] = tags_liste(mid)
    return z


# ----- Import von Bestandsadressen (Betreiber, Einwilligungen liegen laut Betreiber vor) -----

def _tags_vereinigen(alt: list, neu: list) -> list:
    """Vereinigung ohne Groß-/Kleinschreibung (die vorhandene Schreibweise bleibt), höchstens MAX_TAGS_JE_ADRESSE."""
    ergebnis = list(alt)
    bekannt = {t.lower() for t in alt}
    for t in neu:
        if t.lower() not in bekannt and len(ergebnis) < import_csv.MAX_TAGS_JE_ADRESSE:
            ergebnis.append(t)
            bekannt.add(t.lower())
    return ergebnis


def importieren(mandant: dict, daten: str, quelle: str, rolle=None, interessen=None, nur_pruefen: bool = False) -> dict:
    """Importiert Adressen als sofort bestätigte Abonnentinnen (Herkunft 'import', Datum und Quelle gespeichert), ohne Bestätigungsmail.
    Abgemeldete, unzustellbare und unbestätigte Adressen werden NIE verändert. Bei bekannter bestätigter Adresse werden Interessen und Tags vereinigt und die Rolle nur gesetzt,
    wenn noch keine da ist. ``nur_pruefen`` rechnet alles durch und speichert nichts. Wirft FormFehler (Auswahl) oder import_csv.ImportFehler.
    Antwort: nur Zahlen und Tag-Namen, nie Adressen."""
    rolle, interessen = _auswahl_pruefen(mandant, rolle, interessen)
    zeilen = import_csv.lesen(daten)
    mid = mandant["id"]
    jetzt = _iso(_jetzt())
    z = {"nur_pruefen": bool(nur_pruefen), "zeilen": len(zeilen), "neu": 0, "dublette": 0, "ungueltig": 0, "zusammengefuehrt": 0, "rolle_konflikt": 0,
         "uebersprungen": {"abgemeldet": 0, "unzustellbar": 0, "unbestaetigt": 0, "status": 0}}
    tag_zaehler: dict = {}
    tags_verworfen = 0
    with db.verbindung() as c:
        vorhanden = {r["email_hmac"]: dict(r) for r in c.execute("SELECT id, email_hmac, status, rolle, interessen, tags FROM abonnent WHERE mandant_id=?", (mid,))}
        gesehen = set()
        for adresse, status, tag_zelle in zeilen:
            if status is not None and status not in import_csv.STATUS_ABONNIERT:
                z["uebersprungen"]["status"] += 1
                continue
            email = schluessel.normalisiere_email(adresse)
            if not schluessel.email_gueltig(email):
                z["ungueltig"] += 1
                continue
            h = schluessel.email_hmac(mid, email)
            if h in gesehen:
                z["dublette"] += 1
                continue
            gesehen.add(h)
            tags, verworfen = import_csv.tags_lesen(tag_zelle) if tag_zelle else ([], 0)
            tags_verworfen += verworfen
            for t in tags:
                tag_zaehler[t] = tag_zaehler.get(t, 0) + 1
            v = vorhanden.get(h)
            if v is None:
                z["neu"] += 1
                if not nur_pruefen:
                    c.execute("INSERT INTO abonnent(mandant_id, email_hmac, status, email, rolle, interessen, tags, einwilligung_version, angemeldet_am, bestaetigt_am, ip, token_hash, "
                              "token_ablauf, nonce, herkunft, quelle, import_am) VALUES (?,?,'bestaetigt',?,?,?,?,'import',?,?,NULL,NULL,NULL,?,'import',?,?)",
                              (mid, h, email, rolle, json.dumps(interessen), json.dumps(tags), jetzt, jetzt, schluessel.neue_nonce(), quelle, jetzt))
                continue
            if v["status"] == "bestaetigt":
                z["dublette"] += 1
                alte_interessen = json.loads(v["interessen"] or "[]")
                neue_interessen = sorted(set(alte_interessen) | set(interessen))
                alte_tags = json.loads(v["tags"] or "[]")
                neue_tags = _tags_vereinigen(alte_tags, tags)
                neue_rolle = v["rolle"]
                if rolle and v["rolle"] is None:
                    neue_rolle = rolle
                elif rolle and v["rolle"] != rolle:
                    z["rolle_konflikt"] += 1
                if neue_interessen != sorted(alte_interessen) or neue_tags != alte_tags or neue_rolle != v["rolle"]:
                    z["zusammengefuehrt"] += 1
                    if not nur_pruefen:
                        c.execute("UPDATE abonnent SET rolle=?, interessen=?, tags=? WHERE id=? AND mandant_id=?",
                                  (neue_rolle, json.dumps(neue_interessen), json.dumps(neue_tags), v["id"], mid))
                continue
            schluessel_status = {"abgemeldet": "abgemeldet", "unzustellbar": "unzustellbar"}.get(v["status"], "unbestaetigt")
            z["uebersprungen"][schluessel_status] += 1
    z["uebersprungen_gesamt"] = sum(z["uebersprungen"].values())
    haeufigste = sorted(tag_zaehler.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    z["tags"] = {"verschiedene": len(tag_zaehler), "haeufigste": [{"tag": t, "anzahl": n} for t, n in haeufigste[:50]], "verworfen": tags_verworfen}
    z["kennzahlen"] = kennzahlen(mid)
    return z


def tags_liste(mandant_id: int) -> list:
    """Vorhandene Tags der bestätigten Abonnentinnen eines Mandanten mit Anzahl (ohne Groß-/Kleinschreibung zusammengefasst, häufigste Schreibweise). Keine Adressen."""
    zaehler: dict = {}
    schreibweisen: dict = {}
    with db.verbindung() as c:
        for z in c.execute("SELECT tags FROM abonnent WHERE mandant_id=? AND status='bestaetigt' AND tags IS NOT NULL AND tags!='[]'", (int(mandant_id),)):
            for t in json.loads(z["tags"] or "[]"):
                k = t.lower()
                zaehler[k] = zaehler.get(k, 0) + 1
                schreibweisen.setdefault(k, {}).setdefault(t, 0)
                schreibweisen[k][t] += 1
    liste = [{"tag": max(schreibweisen[k].items(), key=lambda kv: (kv[1], kv[0]))[0], "anzahl": n} for k, n in zaehler.items()]
    return sorted(liste, key=lambda e: (-e["anzahl"], e["tag"].lower()))
