"""Mandanten: beliebig viele, jeder mit eigenem Design, eigenen Einwilligungstexten, eigenen Kontakten und eigenen Zugangsdaten.

Trennung: Alle Tabellen mit Personenbezug tragen mandant_id, jede Abfrage filtert darauf (siehe abonnenten.py). Zugangsdaten stehen verschlüsselt unter
Schlüsseln mit dem Präfix ``m<id>/`` (einstellungen.py), nie ein gemeinsamer Wert. Die Auslieferung nach außen nutzt nur die Kennung (slug)."""
import hashlib
import json
import re

import db
import einstellungen

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")
FARBE = re.compile(r"^#[0-9a-fA-F]{6}$")
WERT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,29}$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,40}$")
EMAIL_SIMPLE = re.compile(r"^[^@\s<>\"',;]{1,64}@[A-Za-z0-9.-]{1,200}\.[A-Za-z]{2,}$")
SCHRIFTEN = {"sans": "system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif", "serif": "Georgia,'Times New Roman',serif"}

#: Standarddesign (neutral). Jeder Mandant überschreibt, was er braucht.
STANDARD_DESIGN = {
    "farbe_primaer": "#1f3a5f", "farbe_akzent": "#a3e635", "farbe_hintergrund": "#f4f6f8", "farbe_text": "#1f2933",
    "schrift": "sans", "logo_url": "", "absender_name": "", "absender_adresse": "", "firmenangaben": "",
    "impressum_url": "", "datenschutz_url": "", "basis_url": "", "betreff_bestaetigung": "",
    "rollen": [], "interessen": [], "cors_ursprunge": [],
    "logo_bild_id": None, "balken_farbe": "",
}
ERLAUBT = set(STANDARD_DESIGN)

VERSANDMODI = ("aus", "datei", "smtp")
SMTP_FELDER = ("smtp_host", "smtp_port", "smtp_benutzer", "smtp_passwort", "smtp_verschluesselung")


class Ungueltig(ValueError):
    """Eingabe des Betreibers ist fehlerhaft; die Meldung ist für ihn bestimmt."""


def _url(wert, feld, leer_ok=True):
    wert = (wert or "").strip()
    if not wert:
        if leer_ok:
            return ""
        raise Ungueltig("%s fehlt" % feld)
    if not wert.startswith("https://") or len(wert) > 300 or re.search(r"[\s<>\"']", wert):
        raise Ungueltig("%s muss eine https-Adresse ohne Leerzeichen sein" % feld)
    return wert


def _text(wert, feld, maximum):
    wert = str(wert or "").strip()
    if len(wert) > maximum:
        raise Ungueltig("%s ist zu lang (höchstens %d Zeichen)" % (feld, maximum))
    return wert


def _liste_werte(daten, feld):
    """[{wert, label}] mit kleinen festen Werten (Rolle/Interesse); wert ist das, was gespeichert wird."""
    if not isinstance(daten, list) or len(daten) > 30:
        raise Ungueltig("%s muss eine Liste mit höchstens 30 Einträgen sein" % feld)
    ergebnis, gesehen = [], set()
    for e in daten:
        if not isinstance(e, dict) or set(e) - {"wert", "label"}:
            raise Ungueltig("%s: jeder Eintrag braucht wert und label" % feld)
        wert, label = str(e.get("wert", "")), _text(e.get("label", ""), feld + ".label", 60)
        if not WERT.match(wert) or not label or wert in gesehen:
            raise Ungueltig("%s: wert muss klein geschrieben, eindeutig und kurz sein, label nicht leer" % feld)
        gesehen.add(wert)
        ergebnis.append({"wert": wert, "label": label})
    return ergebnis


def design_pruefen(eingabe: dict, basis: dict | None = None) -> dict:
    """Prüft die Gestaltungsangaben und liefert das vollständige Design (Standard + Basis + Eingabe). Unbekannte Felder sind ein Fehler."""
    if not isinstance(eingabe, dict):
        raise Ungueltig("design muss ein Objekt sein")
    fremd = set(eingabe) - ERLAUBT
    if fremd:
        raise Ungueltig("Unbekannte Design-Felder: %s" % ", ".join(sorted(fremd)))
    d = {**STANDARD_DESIGN, **(basis or {}), **eingabe}
    for f in ("farbe_primaer", "farbe_akzent", "farbe_hintergrund", "farbe_text"):
        if not FARBE.match(str(d[f])):
            raise Ungueltig("%s muss eine Farbe wie #1f3a5f sein" % f)
    if d["schrift"] not in SCHRIFTEN:
        raise Ungueltig("schrift muss eine von %s sein" % ", ".join(sorted(SCHRIFTEN)))
    for f in ("logo_url", "impressum_url", "datenschutz_url", "basis_url"):
        d[f] = _url(d[f], f)
    if d["logo_bild_id"] is not None and (isinstance(d["logo_bild_id"], bool) or not isinstance(d["logo_bild_id"], int) or d["logo_bild_id"] < 1):
        raise Ungueltig("logo_bild_id muss eine Bild-Nummer oder null sein")
    if d["balken_farbe"] and not FARBE.match(str(d["balken_farbe"])):
        raise Ungueltig("balken_farbe muss eine Farbe wie #1f3a5f sein (oder leer = Primärfarbe)")
    d["balken_farbe"] = str(d["balken_farbe"] or "")
    d["absender_name"] = _text(d["absender_name"], "absender_name", 100)
    d["absender_adresse"] = _text(d["absender_adresse"], "absender_adresse", 254)
    if d["absender_adresse"] and not EMAIL_SIMPLE.match(d["absender_adresse"]):
        raise Ungueltig("absender_adresse ist keine E-Mail-Adresse")
    d["firmenangaben"] = _text(d["firmenangaben"], "firmenangaben", 1000)
    d["betreff_bestaetigung"] = _text(d["betreff_bestaetigung"], "betreff_bestaetigung", 150)
    d["rollen"] = _liste_werte(d["rollen"], "rollen")
    d["interessen"] = _liste_werte(d["interessen"], "interessen")
    ursprung = d["cors_ursprunge"]
    if not isinstance(ursprung, list) or len(ursprung) > 20:
        raise Ungueltig("cors_ursprunge muss eine Liste sein")
    d["cors_ursprunge"] = [_url(u, "cors_ursprunge", leer_ok=False).rstrip("/") for u in ursprung]
    return d


def _zeile_zu_dict(z) -> dict:
    return {"id": z["id"], "slug": z["slug"], "name": z["name"], "aktiv": bool(z["aktiv"]),
            "design": {**STANDARD_DESIGN, **json.loads(z["design"] or "{}")}, "erstellt": z["erstellt"], "geaendert": z["geaendert"]}


def anlegen(slug: str, name: str, design: dict | None, akteur: str) -> dict:
    slug = (slug or "").strip().lower()
    if not SLUG.match(slug):
        raise Ungueltig("slug: 2 bis 31 Zeichen, nur a-z, 0-9 und Bindestrich")
    name = _text(name, "name", 100)
    if not name:
        raise Ungueltig("name fehlt")
    d = design_pruefen(design or {})
    if d["logo_bild_id"] is not None:
        raise Ungueltig("logo_bild_id kann erst nach dem Anlegen gesetzt werden (das Bild gehört zu einem bestehenden Mandanten)")
    with db.verbindung() as c:
        if c.execute("SELECT 1 FROM mandant WHERE slug=?", (slug,)).fetchone():
            raise Ungueltig("Diese Kennung (slug) gibt es schon")
        zeit = db.jetzt()
        cur = c.execute("INSERT INTO mandant(slug, name, aktiv, design, erstellt, geaendert) VALUES (?,?,1,?,?,?)",
                        (slug, name, json.dumps(d, ensure_ascii=False), zeit, zeit))
        mandant_id = cur.lastrowid
    return lesen(mandant_id)


def lesen(mandant_id: int) -> dict | None:
    with db.verbindung() as c:
        z = c.execute("SELECT * FROM mandant WHERE id=?", (int(mandant_id),)).fetchone()
    return _zeile_zu_dict(z) if z else None


def lesen_slug(slug: str, nur_aktive: bool = True) -> dict | None:
    with db.verbindung() as c:
        z = c.execute("SELECT * FROM mandant WHERE slug=?", ((slug or "").lower(),)).fetchone()
    if not z or (nur_aktive and not z["aktiv"]):
        return None
    return _zeile_zu_dict(z)


def alle() -> list:
    with db.verbindung() as c:
        return [_zeile_zu_dict(z) for z in c.execute("SELECT * FROM mandant ORDER BY id").fetchall()]


def aendern(mandant_id: int, name=None, aktiv=None, design=None) -> dict:
    m = lesen(mandant_id)
    if m is None:
        raise Ungueltig("Mandant nicht gefunden")
    neuer_name = _text(name, "name", 100) if name is not None else m["name"]
    if not neuer_name:
        raise Ungueltig("name fehlt")
    neues_design = design_pruefen(design, basis=m["design"]) if design is not None else m["design"]
    if neues_design.get("logo_bild_id") is not None:
        import bilder
        if not bilder.gehoert_zu(mandant_id, neues_design["logo_bild_id"]):
            raise Ungueltig("logo_bild_id: Dieses Bild gibt es für diesen Mandanten nicht")
    with db.verbindung() as c:
        c.execute("UPDATE mandant SET name=?, aktiv=?, design=?, geaendert=? WHERE id=?",
                  (neuer_name, 1 if (m["aktiv"] if aktiv is None else bool(aktiv)) else 0,
                   json.dumps(neues_design, ensure_ascii=False), db.jetzt(), int(mandant_id)))
    return lesen(mandant_id)


# ----- Einwilligungstexte (je Mandant, mit Version und Prüfsumme) -----

def einwilligung_anlegen(mandant_id: int, version: str, text: str) -> dict:
    if not VERSION.match(version or ""):
        raise Ungueltig("version: 2 bis 41 Zeichen aus Buchstaben, Ziffern, Punkt, Unter- und Bindestrich")
    text = (text or "").strip()
    if not (20 <= len(text) <= 1000) or "\n" in text:
        raise Ungueltig("Der Einwilligungstext muss eine Zeile mit 20 bis 1000 Zeichen sein")
    if lesen(mandant_id) is None:
        raise Ungueltig("Mandant nicht gefunden")
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with db.verbindung() as c:
        if c.execute("SELECT 1 FROM einwilligung WHERE mandant_id=? AND version=?", (int(mandant_id), version)).fetchone():
            raise Ungueltig("Diese Version gibt es schon (Texte werden nie überschrieben, bitte eine neue Version anlegen)")
        c.execute("INSERT INTO einwilligung(mandant_id, version, text, sha256, gueltig_ab) VALUES (?,?,?,?,?)",
                  (int(mandant_id), version, text, sha, db.jetzt()))
    return {"version": version, "sha256": sha}


def einwilligungen(mandant_id: int) -> list:
    with db.verbindung() as c:
        return [dict(z) for z in c.execute(
            "SELECT version, text, sha256, gueltig_ab FROM einwilligung WHERE mandant_id=? ORDER BY id", (int(mandant_id),)).fetchall()]


def einwilligung_vorhanden(mandant_id: int, version: str) -> bool:
    with db.verbindung() as c:
        return c.execute("SELECT 1 FROM einwilligung WHERE mandant_id=? AND version=?", (int(mandant_id), version or "")).fetchone() is not None


def aktuelle_einwilligung(mandant_id: int) -> dict | None:
    with db.verbindung() as c:
        z = c.execute("SELECT version, text, sha256, gueltig_ab FROM einwilligung WHERE mandant_id=? ORDER BY id DESC LIMIT 1",
                      (int(mandant_id),)).fetchone()
    return dict(z) if z else None


# ----- Versandeinstellungen (verschlüsselt, je Mandant) -----

def _schluessel(mandant_id: int, feld: str) -> str:
    return "m%d/%s" % (int(mandant_id), feld)


def versandmodus(mandant_id: int) -> str:
    """'aus' (Standard: nichts wird versendet), 'datei' (Mails landen als .eml im Ausgang, für Tests) oder 'smtp'."""
    modus = einstellungen.lesen(_schluessel(mandant_id, "versandmodus"), "aus")
    return modus if modus in VERSANDMODI else "aus"


def versand_setzen(mandant_id: int, eingabe: dict, akteur: str) -> dict:
    """Schreibt nur die übergebenen Felder. Geheimes (Passwort) wird nie zurückgegeben."""
    if lesen(mandant_id) is None:
        raise Ungueltig("Mandant nicht gefunden")
    if not isinstance(eingabe, dict):
        raise Ungueltig("Objekt erwartet")
    fremd = set(eingabe) - set(SMTP_FELDER) - {"versandmodus"}
    if fremd:
        raise Ungueltig("Unbekannte Felder: %s" % ", ".join(sorted(fremd)))
    if "versandmodus" in eingabe and eingabe["versandmodus"] not in VERSANDMODI:
        raise Ungueltig("versandmodus muss aus, datei oder smtp sein")
    if "smtp_port" in eingabe:
        try:
            if not 1 <= int(eingabe["smtp_port"]) <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            raise Ungueltig("smtp_port muss eine Zahl von 1 bis 65535 sein")
    if "smtp_verschluesselung" in eingabe and eingabe["smtp_verschluesselung"] not in ("ssl", "starttls"):
        raise Ungueltig("smtp_verschluesselung muss ssl oder starttls sein")
    if "smtp_host" in eingabe and not re.match(r"^[A-Za-z0-9.-]{1,253}$", str(eingabe["smtp_host"])):
        raise Ungueltig("smtp_host ist ungültig")
    if eingabe.get("versandmodus") == "smtp":
        vorhanden = {f for f in SMTP_FELDER if einstellungen.ist_gesetzt(_schluessel(mandant_id, f))} | set(eingabe)
        fehlt = [f for f in ("smtp_host", "smtp_port", "smtp_benutzer", "smtp_passwort", "smtp_verschluesselung") if f not in vorhanden]
        if fehlt or not lesen(mandant_id)["design"]["absender_adresse"]:
            raise Ungueltig("smtp erst möglich, wenn Server, Port, Benutzer, Passwort, Verschlüsselung und die Absenderadresse im Design gesetzt sind")
    for feld, wert in eingabe.items():
        einstellungen.setzen(_schluessel(mandant_id, feld), str(wert), akteur)
    return versand_zustand(mandant_id)


def versand_zustand(mandant_id: int) -> dict:
    """Nur Zustände, nie Werte: welche Felder gesetzt sind."""
    return {"versandmodus": versandmodus(mandant_id),
            "gesetzt": {f: einstellungen.ist_gesetzt(_schluessel(mandant_id, f)) for f in SMTP_FELDER}}


def versand_lesen(mandant_id: int) -> dict:
    return {f: einstellungen.lesen(_schluessel(mandant_id, f)) for f in SMTP_FELDER}
