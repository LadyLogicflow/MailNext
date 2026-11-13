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
CREATE TABLE IF NOT EXISTS mandant (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    aktiv INTEGER NOT NULL DEFAULT 1,
    design TEXT NOT NULL DEFAULT '{}',
    erstellt TEXT NOT NULL,
    geaendert TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS einwilligung (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mandant_id INTEGER NOT NULL REFERENCES mandant(id),
    version TEXT NOT NULL,
    text TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    gueltig_ab TEXT NOT NULL,
    UNIQUE(mandant_id, version)
);
-- Eine Zeile je Person und Mandant. Nach der Abmeldung bleibt nur der Minimaldatensatz (email NULL, email_hmac, Zeitpunkte).
CREATE TABLE IF NOT EXISTS abonnent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mandant_id INTEGER NOT NULL REFERENCES mandant(id),
    email TEXT,
    email_hmac TEXT NOT NULL,
    status TEXT NOT NULL,
    rolle TEXT,
    interessen TEXT,
    einwilligung_version TEXT,
    angemeldet_am TEXT NOT NULL,
    bestaetigt_am TEXT,
    abgemeldet_am TEXT,
    ip TEXT,
    token_hash TEXT,
    token_ablauf TEXT,
    nonce TEXT NOT NULL,
    UNIQUE(mandant_id, email_hmac)
);
-- Kurzlebig, nur für die Drosselung (HMAC statt Adresse, wird nach 2 Tagen gelöscht).
CREATE TABLE IF NOT EXISTS anmelde_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mandant_id INTEGER NOT NULL,
    email_hmac TEXT NOT NULL,
    ip TEXT NOT NULL,
    zeit TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_anmelde_log_zeit ON anmelde_log(mandant_id, zeit);
CREATE TABLE IF NOT EXISTS testadresse (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mandant_id INTEGER NOT NULL REFERENCES mandant(id),
    email TEXT NOT NULL,
    UNIQUE(mandant_id, email)
);
CREATE TABLE IF NOT EXISTS entwurf (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mandant_id INTEGER NOT NULL REFERENCES mandant(id),
    betreff TEXT NOT NULL,
    text TEXT NOT NULL,
    ziel TEXT NOT NULL,
    segment TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'entwurf',
    content_hash TEXT NOT NULL,
    testmail_hash TEXT,
    testmail_am TEXT,
    erstellt TEXT NOT NULL,
    geaendert TEXT NOT NULL,
    freigegeben_am TEXT,
    freigegeben_von TEXT,
    gestoppt_am TEXT
);
-- Eine Zeile je Empfängerin und Entwurf; schluessel ist 'a<abonnent_id>' oder 't<HMAC der Testadresse>': höchstens einmal je Person und Entwurf.
CREATE TABLE IF NOT EXISTS empfaenger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entwurf_id INTEGER NOT NULL REFERENCES entwurf(id),
    mandant_id INTEGER NOT NULL,
    abonnent_id INTEGER,
    email TEXT,
    schluessel TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    versuche INTEGER NOT NULL DEFAULT 0,
    zeit TEXT,
    fehler TEXT,
    UNIQUE(entwurf_id, schluessel)
);
CREATE INDEX IF NOT EXISTS idx_empfaenger_status ON empfaenger(mandant_id, status, zeit);
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
