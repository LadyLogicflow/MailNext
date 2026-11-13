"""Verwaltung auf der Kommandozeile (für Einrichtung und Tests auf dem Pi, solange es keine Betreiber-Oberfläche gibt).

    python manage.py mandant-neu <slug> "<Name>" [design.json]
    python manage.py design <slug> design.json          (ändert nur die genannten Felder)
    python manage.py einwilligung <slug> <version> "<Text in einer Zeile>"
    python manage.py versand <slug> aus|datei            (smtp nur über die Betreiber-Schnittstelle, Passwörter nie in der Kommandozeile)
    python manage.py liste                               (Mandanten mit Zahlen)
    python manage.py abonnenten <slug>                   (Adressen und Status dieses Mandanten)

Braucht MAILNEXT_HAUPTSCHLUESSEL und MAILNEXT_DATEN wie der Dienst. Jede Aktion steht im Audit-Log (Akteur 'manage')."""
import json
import sys

import abonnenten
import config
import db
import mandanten


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
        else:
            print(__doc__)
            return 2
    except mandanten.Ungueltig as exc:
        print("Fehler: %s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
