"""Bilder je Mandant (Logo, später Newsletter-Bilder): Annahme, Neu-Kodierung, Ablage und Auslieferung.

Regeln (catrin 16.11.2026): nur jpg/png/webp, bis 5 MB. Erkannt wird am INHALT, nie an Endung oder Content-Type des Aufrufers. Jedes Bild wird neu kodiert
(Metadaten wie EXIF/GPS und Farbprofil fallen weg, die Ausrichtung wird vorher angewandt) und auf höchstens 1600 Pixel Kantenlänge verkleinert. Der Dateiname
ist ein Zufallstoken, der Mandant steht nicht im öffentlichen Namen. Ablage unter <Daten>/bilder/<mandant_id>/. Ausgeliefert wird nur lesend über den
öffentlichen Port (public.py) mit festem Content-Type. Kein SVG, keine animierten Bilder."""
import io
import logging
import os
import re
import secrets

import config
import db

LOG = logging.getLogger("mailnext.bilder")

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXEL = 25_000_000
MAX_KANTE = 1600
ALT_MAX = 150
FORMATE = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png"), "WEBP": ("image/webp", "webp")}
ENDUNG_ZU_TYP = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
DATEINAME = re.compile(r"^([A-Za-z0-9_-]{16,64})\.(jpg|png|webp)$")

MELDUNGEN = {
    "datei_fehlt": "Es wurde keine Datei übergeben.",
    "zu_gross": "Das Bild ist zu groß (höchstens 5 MB).",
    "typ_nicht_erlaubt": "Erlaubt sind nur Bilder im Format JPG, PNG oder WebP.",
    "bild_ungueltig": "Das Bild lässt sich nicht lesen oder ist beschädigt (animierte Bilder sind nicht erlaubt).",
    "zu_viele_pixel": "Das Bild hat zu viele Bildpunkte (höchstens 25 Megapixel).",
    "alt_fehlt": "Bitte einen Alternativtext angeben (1 bis 150 Zeichen).",
}


class BildFehler(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
        self.meldung = MELDUNGEN.get(code, code)


def alt_pruefen(alt) -> str:
    alt = " ".join(str(alt or "").split())
    if not alt or len(alt) > ALT_MAX or any(ord(z) < 32 for z in alt):
        raise BildFehler("alt_fehlt")
    return alt


def verarbeiten(daten: bytes) -> tuple:
    """Prüft und kodiert ein Bild neu. Gibt (Bytes, Content-Type, Endung, Breite, Höhe) zurück oder wirft BildFehler."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    if not daten:
        raise BildFehler("datei_fehlt")
    if len(daten) > MAX_BYTES:
        raise BildFehler("zu_gross")
    try:
        bild = Image.open(io.BytesIO(daten))
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise BildFehler("typ_nicht_erlaubt")
    if bild.format not in FORMATE:
        raise BildFehler("typ_nicht_erlaubt")
    breite, hoehe = bild.size
    if breite < 1 or hoehe < 1 or breite * hoehe > MAX_PIXEL:                          # vor dem Dekodieren: Schutz vor Dekompressionsbomben
        raise BildFehler("zu_viele_pixel")
    if getattr(bild, "n_frames", 1) > 1:
        raise BildFehler("bild_ungueltig")
    typ, endung = FORMATE[bild.format]
    try:
        bild.load()
        bild = ImageOps.exif_transpose(bild)
        mit_alpha = bild.mode in ("RGBA", "LA") or (bild.mode == "P" and "transparency" in bild.info)
        ziel_modus = "RGBA" if (mit_alpha and endung != "jpg") else "RGB"
        if endung == "jpg" and mit_alpha:
            hintergrund = Image.new("RGB", bild.size, (255, 255, 255))
            hintergrund.paste(bild.convert("RGBA"), mask=bild.convert("RGBA").split()[-1])
            bild = hintergrund
        bild = bild.convert(ziel_modus)
        bild = Image.frombytes(bild.mode, bild.size, bild.tobytes())                   # frische Pixeldaten: keine Metadaten, kein Farbprofil
        bild.thumbnail((MAX_KANTE, MAX_KANTE), Image.LANCZOS)
        ausgabe = io.BytesIO()
        if endung == "jpg":
            bild.save(ausgabe, "JPEG", quality=85, optimize=True)
        elif endung == "png":
            bild.save(ausgabe, "PNG", optimize=True)
        else:
            bild.save(ausgabe, "WEBP", quality=85)
    except BildFehler:
        raise
    except Exception as exc:                                                         # beschädigtes Bild, Speicher, Plugin-Fehler
        LOG.warning("Bild nicht verarbeitbar (%s)", type(exc).__name__)
        raise BildFehler("bild_ungueltig")
    return ausgabe.getvalue(), typ, endung, bild.size[0], bild.size[1]


def _verzeichnis(mandant_id: int):
    return config.daten_verzeichnis() / "bilder" / str(int(mandant_id))


def _sicht(z) -> dict:
    return {"id": z["id"], "token": z["token"], "url": "/%s/bild/%s.%s" % (z["slug"], z["token"], z["endung"]) if "slug" in z.keys() else None,
            "breite": z["breite"], "hoehe": z["hoehe"], "content_type": z["content_type"], "groesse_bytes": z["groesse"], "alt": z["alt"],
            "erstellt": z["erstellt"]}


def speichern(mandant: dict, daten: bytes, alt) -> dict:
    """Prüft, kodiert neu, legt Datei und Datenbankzeile an. Wirft BildFehler."""
    alt = alt_pruefen(alt)
    ausgabe, typ, endung, breite, hoehe = verarbeiten(daten)
    token = secrets.token_urlsafe(18)
    verz = _verzeichnis(mandant["id"])
    verz.mkdir(parents=True, exist_ok=True)
    pfad = verz / ("%s.%s" % (token, endung))
    fd = os.open(str(pfad), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(ausgabe)
    try:
        import hashlib
        with db.verbindung() as c:
            cur = c.execute("INSERT INTO bild(mandant_id, token, endung, content_type, breite, hoehe, groesse, sha256, alt, erstellt) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (int(mandant["id"]), token, endung, typ, breite, hoehe, len(ausgabe), hashlib.sha256(ausgabe).hexdigest(), alt, db.jetzt()))
            bild_id = cur.lastrowid
    except Exception:
        try:
            pfad.unlink()
        except OSError:
            pass
        raise
    return lesen(mandant, bild_id)


def lesen(mandant: dict, bild_id) -> dict | None:
    try:
        bild_id = int(bild_id)
    except (TypeError, ValueError):
        return None
    with db.verbindung() as c:
        z = c.execute("SELECT b.*, m.slug AS slug FROM bild b JOIN mandant m ON m.id=b.mandant_id WHERE b.id=? AND b.mandant_id=?",
                      (bild_id, int(mandant["id"]))).fetchone()
    return _sicht(z) if z else None


def gehoert_zu(mandant_id: int, bild_id) -> bool:
    try:
        bild_id = int(bild_id)
    except (TypeError, ValueError):
        return False
    with db.verbindung() as c:
        return c.execute("SELECT 1 FROM bild WHERE id=? AND mandant_id=?", (bild_id, int(mandant_id))).fetchone() is not None


def liste(mandant: dict) -> list:
    with db.verbindung() as c:
        zeilen = c.execute("SELECT b.*, m.slug AS slug FROM bild b JOIN mandant m ON m.id=b.mandant_id WHERE b.mandant_id=? ORDER BY b.id DESC",
                           (int(mandant["id"]),)).fetchall()
    ergebnis = []
    for z in zeilen:
        d = _sicht(z)
        d["in_verwendung"] = in_verwendung(mandant, z["id"])
        ergebnis.append(d)
    return ergebnis


def in_verwendung(mandant: dict, bild_id) -> bool:
    """Ob das Bild gerade gebraucht wird: als Logo des Mandanten oder in einem Layout-Entwurf (jeder Status: bei freigegebenen und versendeten Newslettern
    müssen die Bilder weiter laden, bei Entwürfen soll die Freigabe nicht an einem gelöschten Bild scheitern)."""
    bild_id = int(bild_id)
    if mandant["design"].get("logo_bild_id") == bild_id:
        return True
    import json
    with db.verbindung() as c:
        for z in c.execute("SELECT blocks FROM entwurf WHERE mandant_id=? AND format='layout' AND blocks IS NOT NULL", (int(mandant["id"]),)).fetchall():
            try:
                blocks = json.loads(z["blocks"])
                eintraege = list(blocks.get("bilder", []))
                if blocks.get("version") == 2:                                        # Version 2: Bildblöcke in beiden Spalten
                    eintraege = [b for s in blocks.get("spalten", {}).values() for b in s if isinstance(b, dict) and b.get("typ") == "bild"]
                if any(b.get("bild_id") == bild_id for b in eintraege):
                    return True
            except (ValueError, AttributeError):
                continue
    return False


def loeschen(mandant: dict, bild_id) -> bool:
    """Löscht Datei und Zeile. False, wenn es das Bild nicht (für diesen Mandanten) gibt. Verwendete Bilder löscht der Aufrufer nicht (409)."""
    with db.verbindung() as c:
        z = c.execute("SELECT * FROM bild WHERE id=? AND mandant_id=?", (int(bild_id), int(mandant["id"]))).fetchone()
        if z is None:
            return False
        c.execute("DELETE FROM bild WHERE id=?", (z["id"],))
    try:
        (_verzeichnis(mandant["id"]) / ("%s.%s" % (z["token"], z["endung"]))).unlink()
    except OSError:
        pass
    return True


def oeffentliche_adresse(bild_id) -> tuple | None:
    """(Mandanten-Kennung, Token, Endung) für den Link in Mails, oder None."""
    try:
        bild_id = int(bild_id)
    except (TypeError, ValueError):
        return None
    with db.verbindung() as c:
        z = c.execute("SELECT b.token, b.endung, m.slug FROM bild b JOIN mandant m ON m.id=b.mandant_id WHERE b.id=?", (bild_id,)).fetchone()
    return (z["slug"], z["token"], z["endung"]) if z else None


def ausliefern(slug: str, dateiname: str) -> tuple | None:
    """(Bytes, Content-Type) für den öffentlichen Pfad /<slug>/bild/<token>.<endung>, sonst None. Mandant und Endung müssen zum Token passen."""
    m = DATEINAME.match(dateiname or "")
    if not m:
        return None
    token, endung = m.groups()
    with db.verbindung() as c:
        z = c.execute("SELECT b.*, m.slug AS slug, m.aktiv AS aktiv FROM bild b JOIN mandant m ON m.id=b.mandant_id WHERE b.token=?", (token,)).fetchone()
    if z is None or z["slug"] != (slug or "").lower() or not z["aktiv"] or z["endung"] != endung:
        return None
    try:
        return (_verzeichnis(z["mandant_id"]) / ("%s.%s" % (token, endung))).read_bytes(), z["content_type"]
    except OSError:
        return None
