"""Liest eine Adressliste (Export aus Mailchimp oder eine Adresse je Zeile) für den Import von Bestandsadressen.

Datensparsamkeit: Gelesen werden NUR die Spalte mit der E-Mail-Adresse und, falls vorhanden, die Spalten Status und Tags (Entscheidung catrin: Mailchimp-Tags werden mitgenommen).
Namen, Telefon und alle anderen Spalten werden nie ausgewertet, gespeichert oder protokolliert. Erkannt werden BOM, Trennzeichen (Komma, Semikolon, Tabulator), Anführungszeichen und beide Zeilenenden."""
import csv
import io

MAX_ZEILEN = 20000
MAX_ZEICHEN = 3_000_000
EMAIL_KOEPFE = {"email address", "email", "e-mail", "e-mail-adresse", "e-mail address", "emailadresse", "mail", "e-mail adresse", "email-adresse", "email adresse", "e-mailadresse"}
STATUS_KOEPFE = {"status", "member status", "abo-status", "abostatus", "abonnementstatus", "subscription status"}
TAG_KOEPFE = {"tags", "tag"}
MAX_TAGS_JE_ADRESSE = 20
MAX_TAG_LAENGE = 40
STATUS_ABONNIERT = {"", "subscribed", "abonniert", "active", "aktiv"}
UNSICHTBAR = dict.fromkeys(map(ord, "​‌‍⁠﻿ "), None)


class ImportFehler(Exception):
    def __init__(self, code: str, meldung: str):
        super().__init__(code)
        self.code, self.meldung = code, meldung


def _trennzeichen(erste_zeile: str) -> str:
    """Zählt Trennzeichen außerhalb von Anführungszeichen."""
    zaehler = {",": 0, ";": 0, "\t": 0}
    in_anf = False
    for ch in erste_zeile:
        if ch == '"':
            in_anf = not in_anf
        elif not in_anf and ch in zaehler:
            zaehler[ch] += 1
    bestes = max(zaehler, key=lambda k: zaehler[k])
    return bestes if zaehler[bestes] else ","


def _zelle(wert: str) -> str:
    return (wert or "").translate(UNSICHTBAR).strip().strip('"').strip("'").strip()


def tag_pruefen(wert) -> str | None:
    """Ein einzelner Tag aus der Oberfläche (nachträgliches Vergeben): bereinigt wie beim Import (unsichtbare Zeichen, Umrahmung), ``None`` wenn leer, länger als
    MAX_TAG_LAENGE, mit Steuerzeichen oder mit einem der Trennzeichen , ; | (die beim Import Tags trennen würden)."""
    if not isinstance(wert, str):
        return None
    t = _zelle(wert)
    if not t or len(t) > MAX_TAG_LAENGE or any(ord(ch) < 32 or ord(ch) == 127 or ch in ",;|" for ch in t):
        return None
    return t


def tags_lesen(zelle: str) -> tuple[list, int]:
    """Zerlegt die Tag-Zelle (Mailchimp: "Tag A","Tag B"; auch Semikolon oder |) in (Tags, Anzahl verworfener). Doppelte (ohne Groß-/Kleinschreibung) zählen nicht,
    zu lange (> MAX_TAG_LAENGE), Steuerzeichen und alles über MAX_TAGS_JE_ADRESSE werden verworfen."""
    import re
    ergebnis, gesehen, verworfen = [], set(), 0
    for teil in re.split(r"[,;|]", zelle or ""):
        t = _zelle(teil)
        if not t:
            continue
        if len(t) > MAX_TAG_LAENGE or any(ord(ch) < 32 or ord(ch) == 127 for ch in t):
            verworfen += 1
            continue
        if t.lower() in gesehen:
            continue
        if len(ergebnis) >= MAX_TAGS_JE_ADRESSE:
            verworfen += 1
            continue
        gesehen.add(t.lower())
        ergebnis.append(t)
    return ergebnis, verworfen


def lesen(text: str) -> list:
    """Liefert [(adresse_roh, status_roh oder None, tag_zelle oder None), ...] für jede nicht leere Datenzeile. Wirft ImportFehler."""
    if not isinstance(text, str):
        raise ImportFehler("daten_fehlen", "Es wurden keine Daten übergeben.")
    if len(text) > MAX_ZEICHEN:
        raise ImportFehler("zu_gross", "Die Datei ist zu groß.")
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    zeilen_roh = [z for z in text.split("\n") if z.strip()]
    if not zeilen_roh:
        raise ImportFehler("daten_fehlen", "Die Datei enthält keine Zeilen.")
    trenn = _trennzeichen(zeilen_roh[0])
    tabelle = [r for r in csv.reader(io.StringIO("\n".join(zeilen_roh)), delimiter=trenn, quotechar='"') if any(_zelle(c) for c in r)]
    if not tabelle:
        raise ImportFehler("daten_fehlen", "Die Datei enthält keine Zeilen.")
    kopf = [_zelle(c).lower() for c in tabelle[0]]
    email_idx = next((i for i, c in enumerate(kopf) if c in EMAIL_KOEPFE), None)
    status_idx = next((i for i, c in enumerate(kopf) if c in STATUS_KOEPFE), None)
    tag_idx = next((i for i, c in enumerate(kopf) if c in TAG_KOEPFE), None)
    if email_idx is not None:
        daten = tabelle[1:]
    elif "@" in tabelle[0][0]:                                  # ohne Kopfzeile: erste Spalte
        email_idx, status_idx, tag_idx, daten = 0, None, None, tabelle
    else:
        raise ImportFehler("spalte_nicht_gefunden", "In der Datei wurde keine Spalte mit E-Mail-Adressen gefunden (erwartet: E-Mail-Adresse, Email Address, E-Mail oder Email).")
    if len(daten) > MAX_ZEILEN:
        raise ImportFehler("zu_viele_zeilen", "Die Datei hat mehr als %d Zeilen. Bitte in mehrere Dateien aufteilen." % MAX_ZEILEN)
    ergebnis = []
    for r in daten:
        adresse = _zelle(r[email_idx]) if email_idx < len(r) else ""
        status = _zelle(r[status_idx]).lower() if status_idx is not None and status_idx < len(r) else None
        tags = (r[tag_idx] if tag_idx is not None and tag_idx < len(r) else None)
        ergebnis.append((adresse, status, tags))
    return ergebnis
