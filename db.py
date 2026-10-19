"""SQLite (WAL) mit einer gemeinsamen, gesperrten Verbindung je Aufruf."""
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

_sperre = threading.RLock()
_pfad: str | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS einstellung (
    schluessel TEXT PRIMARY KEY,
    wert_verschluesselt TEXT NOT NULL,
    geaendert_am TEXT NOT NULL,
    geaendert_von TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zeit TEXT NOT NULL,
    akteur TEXT NOT NULL,
    aktion TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT ''
);
"""


def jetzt() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init(pfad: str) -> None:
    global _pfad
    _pfad = pfad
    with verbindung() as c:
        c.executescript(SCHEMA)
        c.execute("PRAGMA journal_mode=WAL")


@contextmanager
def verbindung():
    if _pfad is None:
        raise RuntimeError("Datenbank nicht initialisiert")
    with _sperre:
        c = sqlite3.connect(_pfad, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()


def audit(akteur: str, aktion: str, details: str = "", ip: str = "") -> None:
    """Schreibt einen Audit-Eintrag. Wirft bei Fehler (Aufrufer bricht dann ab)."""
    with verbindung() as c:
        c.execute("INSERT INTO audit_log(zeit, akteur, aktion, details, ip) VALUES (?,?,?,?,?)",
                  (jetzt(), akteur, aktion, details, ip))
