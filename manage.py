"""Verwaltung auf der Kommandozeile (für Einrichtung und Tests auf dem Pi, solange es keine Betreiber-Oberfläche gibt).

    python manage.py mandant-neu <slug> "<Name>" [design.json]
    python manage.py design <slug> design.json          (ändert nur die genannten Felder)
    python manage.py einwilligung <slug> <version> "<Text in einer Zeile>"
    python manage.py versand <slug> aus|datei            (smtp nur über die Betreiber-Schnittstelle, Passwörter nie in der Kommandozeile)
    python manage.py smtp <slug> <host> <port> <benutzer> ssl|starttls   (SMTP-Konto des Mandanten; das Passwort wird am Terminal ohne Anzeige abgefragt; schaltet den Versandmodus auf smtp,
                                                         setzt die Absenderadresse im Design voraus)
    python manage.py echtversand <slug> ja|nein         (Echtversand an Abonnenten für diesen Mandanten freigeben oder sperren)
    python manage.py versand-rate <slug> <1-600>        (Mails pro Stunde, Standard 100)
    python manage.py entwurf <slug> <datei> [ziel=testliste|abonnenten] [segment=<datei.json>]
                                                         (Datei: erste Zeile "Betreff: ...", dann eine Leerzeile, dann der Text; Standard-Ziel testliste)
    python manage.py testmail <slug> <entwurf_id> [adresse]   (ohne Adresse an die ganze Testliste; eine Adresse muss in der Testliste stehen; leere Testliste = Fehler)
    python manage.py freigeben <slug> <entwurf_id>       (zeigt Ziel und Empfängerzahl, verlangt die Empfängerzahl zur Bestätigung; gleiche Prüfungen wie die Betreiber-Schnittstelle)
    python manage.py liste                               (Mandanten mit Zahlen)
    python manage.py abonnenten <slug>                   (Adressen und Status dieses Mandanten)
    python manage.py ki-schluessel                       (KI-Zugangsschlüssel eingeben, wird am Terminal ohne Anzeige abgefragt und verschlüsselt gespeichert; "ki-schluessel-loeschen" entfernt ihn)
    python manage.py ki-aktiv <slug> ja|nein             (KI-Textverbesserung je Mandant, Standard nein)
    python manage.py import <slug> <datei.csv> "<Quelle>" [nur-pruefen] [einwilligung-liegt-vor] [rolle=<Wert>] [interessen=<Wert,Wert>]
                                                         (Bestandsadressen aus einem Mailchimp-Export; ohne einwilligung-liegt-vor nur Prüfung, es wird nichts gespeichert)

Braucht MAILNEXT_HAUPTSCHLUESSEL und MAILNEXT_DATEN wie der Dienst. Jede Aktion steht im Audit-Log (Akteur 'manage')."""
import json
import sys

import abonnenten
import config
import db
import import_csv
import mandanten
import newsletter


def _start() -> None:
    verz = config.daten_verzeichnis()
    verz.mkdir(parents=True, exist_ok=True)
    db.init(str(verz / "mailnext.db"))


def _mandant(slug: str) -> dict:
    m = mandanten.lesen_slug(slug, nur_aktive=False)
    if m is None:
        raise SystemExit("Mandant '%s' gibt es nicht" % slug)
    return m


def _datei(pfad: str) -> dict:
    with open(pfad, encoding="utf-8") as f:
        return json.load(f)


def _text(pfad: str) -> str:
    """Datei lesen: UTF-8 (mit oder ohne BOM), sonst Windows-1252 (Excel)."""
    roh = open(pfad, "rb").read()
    try:
        return roh.decode("utf-8-sig")
    except UnicodeDecodeError:
        return roh.decode("cp1252", errors="replace")


def _import(rest: list) -> int:
    m = _mandant(rest[0])
    optionen = rest[3:]
    echt = "einwilligung-liegt-vor" in optionen and "nur-pruefen" not in optionen
    rolle = next((o.split("=", 1)[1] for o in optionen if o.startswith("rolle=")), None)
    interessen = next((o.split("=", 1)[1].split(",") for o in optionen if o.startswith("interessen=")), None)
    if not 1 <= len(rest[2].strip()) <= 100:
        print("Fehler: Die Quelle muss 1 bis 100 Zeichen haben.")
        return 1
    try:
        e = abonnenten.importieren(m, _text(rest[1]), rest[2].strip(), rolle, interessen, nur_pruefen=not echt)
    except abonnenten.FormFehler:
        print("Fehler: Rolle oder Interessen gehören nicht zu diesem Mandanten.")
        return 1
    except import_csv.ImportFehler as f:
        print("Fehler: %s" % f.meldung)
        return 1
    except OSError:
        print("Fehler: Die Datei kann nicht gelesen werden.")
        return 1
    db.audit("manage", "abonnenten_import" if echt else "abonnenten_import_geprueft",
             "mandant=%s quelle=%s zeilen=%d neu=%d dublette=%d ungueltig=%d uebersprungen=%d zusammengefuehrt=%d" % (
                 m["slug"], rest[2].strip(), e["zeilen"], e["neu"], e["dublette"], e["ungueltig"], e["uebersprungen_gesamt"], e["zusammengefuehrt"]))
    print("%s: %d Zeilen, neu %d, Dubletten %d (zusammengeführt %d, Rolle abweichend %d), ungültig %d, übersprungen %d (abgemeldet %d, unzustellbar %d, unbestätigt %d, Status %d)" % (
        "IMPORTIERT" if echt else "PRÜFUNG (nichts gespeichert)", e["zeilen"], e["neu"], e["dublette"], e["zusammengefuehrt"], e["rolle_konflikt"], e["ungueltig"],
        e["uebersprungen_gesamt"], e["uebersprungen"]["abgemeldet"], e["uebersprungen"]["unzustellbar"], e["uebersprungen"]["unbestaetigt"], e["uebersprungen"]["status"]))
    if e["tags"]["verschiedene"]:
        print("Tags: %d verschiedene, häufigste: %s%s" % (e["tags"]["verschiedene"], ", ".join("%s (%d)" % (t["tag"], t["anzahl"]) for t in e["tags"]["haeufigste"][:10]),
                                                         (", verworfen: %d" % e["tags"]["verworfen"]) if e["tags"]["verworfen"] else ""))
    if not echt:
        print("Zum echten Import 'einwilligung-liegt-vor' anhängen (und 'nur-pruefen' weglassen).")
    return 0


def _entwurf_datei(pfad: str) -> tuple:
    """(Betreff, Text) aus einer Datei: erste Zeile 'Betreff: ...', dann eine Leerzeile, dann der Text."""
    zeilen = _text(pfad).replace("\r\n", "\n").split("\n")
    if not zeilen or not zeilen[0].startswith("Betreff:"):
        raise SystemExit("Die erste Zeile der Datei muss mit 'Betreff:' beginnen")
    return zeilen[0][len("Betreff:"):].strip(), "\n".join(zeilen[1:]).strip("\n")


def _versand_befehl(befehl: str, rest: list) -> int | None:
    """Versandbefehle. Sie rufen dieselben Funktionen wie die Betreiber-Schnittstelle auf (keine zweite Logik). None = kein Versandbefehl."""
    akteur = config.betreiber_offen_email() or "manage"
    if befehl == "smtp" and len(rest) == 5:
        import getpass
        m = _mandant(rest[0])
        passwort = getpass.getpass("SMTP-Passwort (keine Anzeige): ")
        mandanten.versand_setzen(m["id"], {"smtp_host": rest[1], "smtp_port": rest[2], "smtp_benutzer": rest[3], "smtp_verschluesselung": rest[4],
                                           "smtp_passwort": passwort, "versandmodus": "smtp"}, "manage")
        db.audit("manage", "versand_geaendert", "mandant=%s smtp versandmodus=smtp" % m["slug"])            # nie das Passwort
        print("SMTP-Konto von %s gespeichert (verschlüsselt), Versandmodus: smtp" % m["slug"])
    elif befehl == "echtversand" and len(rest) == 2 and rest[1] in ("ja", "nein"):
        m = _mandant(rest[0])
        newsletter.echtversand_setzen(m["id"], rest[1] == "ja", "manage")
        db.audit("manage", "echtversand_geaendert", "mandant=%s freigegeben=%s" % (m["slug"], "true" if rest[1] == "ja" else "false"))
        print("Echtversand für %s: %s" % (m["slug"], rest[1]))
    elif befehl == "versand-rate" and len(rest) == 2 and rest[1].isdigit():
        m = _mandant(rest[0])
        wert = newsletter.limit_pro_stunde_setzen(m["id"], int(rest[1]), "manage")
        db.audit("manage", "versand_rate_geaendert", "mandant=%s limit_pro_stunde=%d" % (m["slug"], wert))
        print("Versandrate von %s: %d Mails pro Stunde" % (m["slug"], wert))
    elif befehl == "entwurf" and len(rest) >= 2:
        m = _mandant(rest[0])
        ziel = next((o.split("=", 1)[1] for o in rest[2:] if o.startswith("ziel=")), "testliste")
        segment_datei = next((o.split("=", 1)[1] for o in rest[2:] if o.startswith("segment=")), None)
        betreff, text = _entwurf_datei(rest[1])
        e = newsletter.anlegen(m, betreff, text, ziel, _datei(segment_datei) if segment_datei else None)
        db.audit("manage", "entwurf_angelegt", "mandant=%s entwurf=%d ziel=%s" % (m["slug"], e["id"], e["ziel"]))
        print("Entwurf %d für %s angelegt (Ziel %s)" % (e["id"], m["slug"], e["ziel"]))
    elif befehl == "testmail" and len(rest) in (2, 3) and rest[1].isdigit():
        m = _mandant(rest[0])
        erg = newsletter.testmail(m, int(rest[1]), rest[2] if len(rest) == 3 else None)
        db.audit("manage", "testmail_gesendet", "mandant=%s entwurf=%d gesendet=%d fehler=%d" % (m["slug"], int(rest[1]), erg["gesendet"], erg["fehler"]))               # Adressen stehen nicht im Audit
        print("Testmail zu Entwurf %s: %d gesendet, %d fehlgeschlagen" % (rest[1], erg["gesendet"], erg["fehler"]))
    elif befehl == "freigeben" and len(rest) == 2 and rest[1].isdigit():
        m = _mandant(rest[0])
        entwurf_id = int(rest[1])
        e = newsletter.lesen(m, entwurf_id)
        if e is None:
            raise SystemExit("Entwurf %d gibt es bei %s nicht" % (entwurf_id, m["slug"]))
        anzahl = newsletter.vorschau(m, entwurf_id)["anzahl"]
        print("Entwurf %d: \"%s\"\nZiel: %s, Empfänger: %d, Versandmodus: %s, Echtversand freigegeben: %s" % (
            entwurf_id, e["betreff"], e["ziel"], anzahl, mandanten.versandmodus(m["id"]), "ja" if newsletter.echtversand_freigegeben(m["id"]) else "nein"))
        try:
            eingabe = input("Zur Bestätigung die Empfängerzahl eingeben (%d): " % anzahl).strip()
        except EOFError:
            eingabe = ""
        if eingabe != str(anzahl):
            print("Abgebrochen: nichts freigegeben.")
            return 1
        ergebnis = newsletter.freigeben(m, entwurf_id, e["content_hash"], True, akteur)
        db.audit("manage", "entwurf_freigegeben", "mandant=%s entwurf=%d empfaenger=%d" % (m["slug"], entwurf_id, ergebnis["empfaenger"]))
        print("Freigegeben: %d Empfänger werden im Rahmen der Versandrate bedient." % ergebnis["empfaenger"])
    else:
        return None
    return 0


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    _start()
    befehl, rest = argv[0], argv[1:]
    try:
        if befehl == "mandant-neu" and len(rest) in (2, 3):
            m = mandanten.anlegen(rest[0], rest[1], _datei(rest[2]) if len(rest) == 3 else {}, "manage")
            db.audit("manage", "mandant_angelegt", "mandant=%s" % m["slug"])
            print("Mandant %s angelegt (id %d)" % (m["slug"], m["id"]))
        elif befehl == "design" and len(rest) == 2:
            m = _mandant(rest[0])
            mandanten.aendern(m["id"], design=_datei(rest[1]))
            db.audit("manage", "mandant_geaendert", "mandant=%s" % m["slug"])
            print("Design von %s aktualisiert" % m["slug"])
        elif befehl == "einwilligung" and len(rest) == 3:
            m = _mandant(rest[0])
            e = mandanten.einwilligung_anlegen(m["id"], rest[1], rest[2])
            db.audit("manage", "einwilligung_angelegt", "mandant=%s version=%s sha256=%s" % (m["slug"], e["version"], e["sha256"]))
            print("Einwilligung %s für %s angelegt (SHA-256 %s)" % (e["version"], m["slug"], e["sha256"]))
        elif befehl == "versand" and len(rest) == 2 and rest[1] in ("aus", "datei"):
            m = _mandant(rest[0])
            mandanten.versand_setzen(m["id"], {"versandmodus": rest[1]}, "manage")
            db.audit("manage", "versand_geaendert", "mandant=%s versandmodus" % m["slug"])
            print("Versandmodus von %s: %s" % (m["slug"], rest[1]))
        elif befehl == "liste" and not rest:
            for m in mandanten.alle():
                print("%-20s %-30s aktiv=%s versand=%s %s" % (m["slug"], m["name"], m["aktiv"], mandanten.versandmodus(m["id"]), abonnenten.kennzahlen(m["id"])))
        elif befehl == "abonnenten" and len(rest) == 1:
            m = _mandant(rest[0])
            zeilen = abonnenten.liste(m["id"])
            db.audit("manage", "abonnenten_gelesen", "mandant=%s anzahl=%d" % (m["slug"], len(zeilen)))
            for z in zeilen:
                print("%-8s %s" % (z["status"], z["email"]))
        elif befehl == "ki-schluessel" and not rest:
            import getpass
            import ki
            ki.schluessel_setzen(getpass.getpass("KI-Zugangsschlüssel (keine Anzeige): ").strip(), "manage")
            db.audit("manage", "ki_schluessel_gesetzt", "")
            print("KI-Zugangsschlüssel gespeichert (verschlüsselt).")
        elif befehl == "ki-schluessel-loeschen" and not rest:
            import ki
            ki.schluessel_loeschen()
            db.audit("manage", "ki_schluessel_geloescht", "")
            print("KI-Zugangsschlüssel gelöscht.")
        elif befehl == "ki-aktiv" and len(rest) == 2 and rest[1] in ("ja", "nein"):
            import ki
            m_ = _mandant(rest[0])
            ki.aktiv_setzen(m_["id"], rest[1] == "ja", "manage")
            db.audit("manage", "ki_schalter", "mandant=%s aktiv=%s" % (m_["slug"], rest[1]))
            print("KI-Textverbesserung für %s: %s" % (m_["slug"], rest[1]))
        elif befehl == "import" and len(rest) >= 3:
            return _import(rest)
        elif befehl in ("smtp", "echtversand", "versand-rate", "entwurf", "testmail", "freigeben") and (ergebnis := _versand_befehl(befehl, rest)) is not None:
            return ergebnis
        else:
            print(__doc__)
            return 2
    except mandanten.Ungueltig as exc:
        print("Fehler: %s" % exc)
        return 1
    except Exception as exc:                                   # KI-Schlüssel mit ungültigem Format u. a.: nie Werte ausgeben
        if exc.__class__.__name__ == "Fehler":
            print("Fehler: %s" % getattr(exc, "meldung", "ungültige Eingabe"))
            return 1
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
