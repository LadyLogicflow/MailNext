"""KI-Textverbesserung für Newsletter-Entwürfe (Claude von Anthropic), nur auf ausdrücklichen Klick des Betreibers, nur als Vorschlag.

Datenschutz (Vorgaben Irony):
- Funktion je Mandant nur nach Aktivierung (Standard AUS).
- An den Dienst gehen ausschließlich Betreff, Text, optional eine kurze Anweisung und die feste Systemanweisung unten: keine Adressen, keine Abonnentendaten, keine
  Mandanten-Kennung, kein Name oder Adresse des Betreibers.
- Text und Antwort stehen nie in Logs oder im Audit (nur Zeitpunkt, Mandant, Zeichenzahlen). Der Schlüssel liegt verschlüsselt in den Einstellungen und wird nie zurückgegeben.
- Limit je Betreiber und Stunde sowie je Tag; die Kosten je Aufruf sind durch max_tokens begrenzt."""
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import requests

import db
import einstellungen
import schluessel

LOG = logging.getLogger("mailnext.ki")
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MODELL = "claude-sonnet-5-5"
MAX_TOKENS = 8192                                   # großzügig (Lehre ShareNext: 700 war zu knapp und lieferte leeren Text)
ZEITLIMIT = (5, 60)                                 # Verbindung, Antwort in Sekunden
LIMIT_JE_STUNDE = 20                                # je Betreiber
LIMIT_JE_TAG = 100                                  # insgesamt
MAX_BETREFF, MAX_TEXT, MAX_ANWEISUNG = 150, 8000, 300
SCHLUESSEL_NAME = "ki/anthropic_schluessel"
HINWEIS = ("Beim Klick wird Ihr Text (Betreff und Inhalt) zur Überarbeitung an einen KI-Dienst (Anthropic, USA) gesendet. Bitte schreiben Sie keine personenbezogenen Daten, "
           "keine Namen von Mitgliedern oder Mandanten und keine vertraulichen Angaben in den Text. Prüfen Sie den Vorschlag, bevor Sie ihn verwenden.")
SYSTEM = ("Du überarbeitest deutschsprachige Newsletter-Texte für Vereine und Beratungsstellen: Rechtschreibung, Grammatik, Verständlichkeit und freundlicher, sachlicher Ton. "
          "Behalte Inhalt, Aussagen, Zahlen, Termine, Links (URLs) und die Absatzstruktur bei. Erfinde nichts hinzu. Folge der Anweisung des Nutzers nur für Stil und Länge. "
          "Antworte ausschließlich mit einem JSON-Objekt der Form {\"betreff\": \"...\", \"text\": \"...\"} ohne weiteren Text; ist kein Betreff übergeben, setze betreff auf null.")


class Fehler(Exception):
    def __init__(self, code: str, meldung: str, status: int = 400):
        super().__init__(code)
        self.code, self.meldung, self.status = code, meldung, status


def _schluessel_mandant(mandant_id: int) -> str:
    return "m%d/ki_aktiv" % int(mandant_id)


def aktiv(mandant_id: int) -> bool:
    return einstellungen.lesen(_schluessel_mandant(mandant_id), "nein") == "ja"


def aktiv_setzen(mandant_id: int, an: bool, akteur: str) -> None:
    einstellungen.setzen(_schluessel_mandant(mandant_id), "ja" if an else "nein", akteur)


def schluessel_gesetzt() -> bool:
    return einstellungen.ist_gesetzt(SCHLUESSEL_NAME)


def schluessel_setzen(wert, akteur: str) -> None:
    if not isinstance(wert, str) or not 20 <= len(wert) <= 300 or re.search(r"\s", wert) or not wert.isascii():
        raise Fehler("schluessel_ungueltig", "Der Zugangsschlüssel hat ein ungültiges Format.")
    einstellungen.setzen(SCHLUESSEL_NAME, wert, akteur)


def schluessel_loeschen() -> None:
    with db.verbindung() as c:
        c.execute("DELETE FROM einstellung WHERE schluessel=?", (SCHLUESSEL_NAME,))


def zustand(mandant_id: int) -> dict:
    return {"aktiv": aktiv(mandant_id), "schluessel_gesetzt": schluessel_gesetzt(), "hinweis": HINWEIS, "modell": MODELL, "limit_je_stunde": LIMIT_JE_STUNDE, "limit_je_tag": LIMIT_JE_TAG}


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _pruefen(betreff, text, anweisung) -> tuple:
    if betreff is not None and (not isinstance(betreff, str) or len(betreff) > MAX_BETREFF or "\n" in betreff or "\r" in betreff):
        raise Fehler("betreff_ungueltig", "Der Betreff darf höchstens %d Zeichen haben und nur eine Zeile." % MAX_BETREFF)
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= MAX_TEXT:
        raise Fehler("text_ungueltig", "Der Text muss 1 bis %d Zeichen haben." % MAX_TEXT)
    if anweisung is not None and (not isinstance(anweisung, str) or len(anweisung) > MAX_ANWEISUNG):
        raise Fehler("anweisung_ungueltig", "Die Anweisung darf höchstens %d Zeichen haben." % MAX_ANWEISUNG)
    return (betreff or "").strip(), text.strip(), (anweisung or "").strip()


def _begrenzen(betreiber_email: str) -> None:
    """Zählt den Aufruf (auch gescheiterte, denn sie kosten Zeit und Geld) und lehnt ab dem Limit ab. Gespeichert wird nur ein Pseudonym des Betreibers."""
    jetzt = datetime.now(timezone.utc)
    pseudo = hmac.new(schluessel._ableiten(b"mailnext-ki-v1"), (betreiber_email or "").strip().lower().encode("utf-8"), hashlib.sha256).hexdigest()
    with db.verbindung() as c:
        c.execute("DELETE FROM ki_aufruf WHERE zeit < ?", (_iso(jetzt - timedelta(days=2)),))
        je_stunde = c.execute("SELECT COUNT(*) FROM ki_aufruf WHERE betreiber=? AND zeit>=?", (pseudo, _iso(jetzt - timedelta(hours=1)))).fetchone()[0]
        je_tag = c.execute("SELECT COUNT(*) FROM ki_aufruf WHERE zeit>=?", (_iso(jetzt - timedelta(days=1)),)).fetchone()[0]
        if je_stunde >= LIMIT_JE_STUNDE or je_tag >= LIMIT_JE_TAG:
            raise Fehler("limit_erreicht", "Das Limit für die KI-Textverbesserung ist erreicht. Bitte später erneut versuchen.", 429)
        c.execute("INSERT INTO ki_aufruf(betreiber, zeit) VALUES (?,?)", (pseudo, _iso(jetzt)))


def _antwort_lesen(daten) -> dict:
    """Aus der Antwort der API den Vorschlag holen. Wirft Fehler('ki_fehler')."""
    if not isinstance(daten, dict) or daten.get("stop_reason") == "max_tokens":
        raise Fehler("ki_antwort_unbrauchbar", "Die KI-Antwort war unvollständig. Bitte mit kürzerem Text erneut versuchen.", 502)
    teile = [b.get("text", "") for b in (daten.get("content") or []) if isinstance(b, dict) and b.get("type") == "text"]
    roh = "".join(teile).strip()
    if not roh:
        raise Fehler("ki_antwort_unbrauchbar", "Die KI hat keinen Text geliefert.", 502)
    roh = re.sub(r"^```(?:json)?\s*|\s*```$", "", roh).strip()
    betreff, text = None, roh
    try:
        j = json.loads(roh)
        if isinstance(j, dict) and isinstance(j.get("text"), str):
            text = j["text"].strip()
            b = j.get("betreff")
            betreff = b.strip() if isinstance(b, str) and b.strip() and len(b.strip()) <= MAX_BETREFF and "\n" not in b and "\r" not in b else None
    except ValueError:
        pass                                                # kein JSON: die ganze Antwort gilt als Text
    if not 1 <= len(text) <= 50000:
        raise Fehler("ki_antwort_unbrauchbar", "Die KI hat keinen brauchbaren Text geliefert.", 502)
    return {"betreff": betreff, "text": text}


def verbessern(mandant: dict, betreiber_email: str, betreff, text, anweisung=None) -> dict:
    """Liefert {'vorschlag': {betreff, text}, 'zeichen_ein', 'zeichen_aus'}. Wirft Fehler. Nichts davon wird gespeichert."""
    if not aktiv(mandant["id"]):
        raise Fehler("funktion_nicht_aktiv", "Die KI-Textverbesserung ist für diesen Mandanten nicht aktiviert.", 409)
    betreff, text, anweisung = _pruefen(betreff, text, anweisung)
    if not schluessel_gesetzt():
        raise Fehler("kein_ki_zugang", "Es ist kein KI-Zugang eingerichtet.", 503)
    schluessel_wert = einstellungen.lesen(SCHLUESSEL_NAME)
    _begrenzen(betreiber_email)
    nutzer = "BETREFF:\n%s\n\nTEXT:\n%s" % (betreff or "(kein Betreff)", text) + (("\n\nANWEISUNG:\n" + anweisung) if anweisung else "")
    body = {"model": MODELL, "max_tokens": MAX_TOKENS, "system": SYSTEM, "messages": [{"role": "user", "content": nutzer}]}
    try:
        r = requests.post(API_URL, headers={"x-api-key": schluessel_wert, "anthropic-version": API_VERSION, "content-type": "application/json"}, json=body, timeout=ZEITLIMIT)
    except requests.Timeout:
        LOG.warning("KI-Aufruf: Zeitüberschreitung")
        raise Fehler("zeitueberschreitung", "Die KI hat nicht rechtzeitig geantwortet. Bitte erneut versuchen.", 504)
    except requests.RequestException:
        LOG.warning("KI-Aufruf: Verbindungsfehler")
        raise Fehler("ki_fehler", "Die KI ist derzeit nicht erreichbar.", 502)
    finally:
        schluessel_wert = None
    if r.status_code in (401, 403):
        LOG.warning("KI-Aufruf: Zugang abgelehnt (%d)", r.status_code)
        raise Fehler("ki_zugang_ungueltig", "Der KI-Zugang wurde abgelehnt. Bitte den Zugangsschlüssel prüfen.", 502)
    if r.status_code != 200:
        LOG.warning("KI-Aufruf: Status %d", r.status_code)
        raise Fehler("ki_fehler", "Die KI hat den Aufruf nicht angenommen (Status %d)." % r.status_code, 502)
    try:
        daten = r.json()
    except ValueError:
        raise Fehler("ki_antwort_unbrauchbar", "Die KI-Antwort war nicht lesbar.", 502)
    vorschlag = _antwort_lesen(daten)
    return {"vorschlag": vorschlag, "zeichen_ein": len(betreff) + len(text), "zeichen_aus": len(vorschlag["text"]) + len(vorschlag["betreff"] or "")}
