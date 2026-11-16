"""Mailversand je Mandant. Standard ist 'aus': ohne ausdrückliche Einstellung geht keine einzige Mail hinaus.

Modi (je Mandant, mandanten.versandmodus):
- aus:   es wird nichts gesendet; das Ergebnis lautet 'aus'.
- datei: die Mail wird als .eml unter <Daten>/ausgang/<slug>/ abgelegt (Test auf dem Pi, Dateien werden nach 7 Tagen gelöscht).
- smtp:  Versand über das SMTP-Konto des Mandanten (verschlüsselt gespeichert). Fehlt etwas, wird nichts gesendet.
Kein Tracking-Pixel, Links bleiben unverändert."""
import html
import logging
import os
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import format_datetime, formataddr, make_msgid
from datetime import datetime, timezone

import config
import mandanten

LOG = logging.getLogger("mailnext.mailer")
AUFBEWAHRUNG_DATEI_TAGE = 7


def _basis(mandant: dict) -> str:
    return (mandant["design"].get("basis_url") or config.basis_url()).rstrip("/")


def link_bestaetigen(mandant: dict, token: str) -> str:
    return "%s/%s/newsletter/bestaetigen/%s" % (_basis(mandant), mandant["slug"], token)


def link_einstellungen(mandant: dict, persoenliches_token: str) -> str:
    return "%s/%s/newsletter/einstellungen?t=%s" % (_basis(mandant), mandant["slug"], persoenliches_token)


def _fusszeile_text(mandant: dict) -> str:
    d = mandant["design"]
    zeilen = []
    if d["firmenangaben"]:
        zeilen.append(d["firmenangaben"])
    if d["impressum_url"]:
        zeilen.append("Impressum: " + d["impressum_url"])
    if d["datenschutz_url"]:
        zeilen.append("Datenschutz: " + d["datenschutz_url"])
    return "\n".join(zeilen)


def _fusszeile_html(mandant: dict) -> str:
    d = mandant["design"]
    teile = []
    if d["firmenangaben"]:
        teile.append(html.escape(d["firmenangaben"]).replace("\n", "<br>"))
    links = []
    if d["impressum_url"]:
        links.append('<a href="%s" style="color:%s">Impressum</a>' % (html.escape(d["impressum_url"], quote=True), d["farbe_primaer"]))
    if d["datenschutz_url"]:
        links.append('<a href="%s" style="color:%s">Datenschutz</a>' % (html.escape(d["datenschutz_url"], quote=True), d["farbe_primaer"]))
    if links:
        teile.append(" · ".join(links))
    return "<br>".join(teile)


def html_rahmen(mandant: dict, titel: str, inhalt_html: str) -> str:
    """E-Mail-HTML im Design des Mandanten (nur Inline-Stil, wie Mailprogramme es brauchen)."""
    d = mandant["design"]
    schrift = mandanten.SCHRIFTEN[d["schrift"]]
    import layout                                                    # gemeinsamer Kopf mit den Layout-Mails (catrin #19144)
    kopf = layout.kopf_html(mandant)
    return ('<!doctype html><html lang="de"><head><meta charset="utf-8"><title>%s</title></head>'
            '<body style="margin:0;background:%s;font-family:%s;color:%s">'
            '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">'
            '<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%%;background:#ffffff;border-radius:8px;overflow:hidden">'
            '%s'
            '<tr><td style="padding:24px;font-size:16px;line-height:1.5">%s</td></tr>'
            '<tr><td style="padding:16px 24px;border-top:1px solid #e5e7eb;font-size:12px;color:#6b7280;line-height:1.5">%s</td></tr>'
            '</table></td></tr></table></body></html>'
            % (html.escape(titel), d["farbe_hintergrund"], schrift, d["farbe_text"], kopf, inhalt_html, _fusszeile_html(mandant)))


def bestaetigungsmail(mandant: dict, token: str) -> tuple[str, str, str]:
    """(Betreff, Text, HTML) der Double-Opt-in-Mail."""
    d = mandant["design"]
    betreff = (d["betreff_bestaetigung"] or "Bitte bestätigen Sie Ihre Anmeldung zum Newsletter von {name}").replace("{name}", mandant["name"])
    url = link_bestaetigen(mandant, token)
    text = ("Guten Tag,\n\nSie (oder jemand mit Ihrer E-Mail-Adresse) haben sich zum Newsletter von %s angemeldet.\n"
            "Bitte bestätigen Sie die Anmeldung mit diesem Link (gültig 48 Stunden):\n\n%s\n\n"
            "Wenn Sie sich nicht angemeldet haben, ignorieren Sie diese Nachricht. Dann passiert nichts und Sie erhalten keine weiteren Mails.\n\n%s\n"
            % (mandant["name"], url, _fusszeile_text(mandant)))
    knopf = ('<p style="margin:24px 0"><a href="%s" style="background:%s;color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:6px;display:inline-block">'
             'Anmeldung bestätigen</a></p>' % (html.escape(url, quote=True), d["farbe_primaer"]))
    inhalt = ("<p>Guten Tag,</p><p>Sie (oder jemand mit Ihrer E-Mail-Adresse) haben sich zum Newsletter von <b>%s</b> angemeldet. "
              "Bitte bestätigen Sie die Anmeldung (der Link gilt 48 Stunden):</p>%s"
              '<p style="font-size:13px;color:#6b7280">Funktioniert der Knopf nicht? Kopieren Sie diesen Link in den Browser:<br>%s</p>'
              "<p>Wenn Sie sich nicht angemeldet haben, ignorieren Sie diese Nachricht. Dann passiert nichts.</p>"
              % (html.escape(mandant["name"]), knopf, html.escape(url)))
    return betreff, text, html_rahmen(mandant, betreff, inhalt)


def _nachricht(mandant: dict, an: str, betreff: str, text: str, html_text: str, header: dict | None) -> EmailMessage:
    d = mandant["design"]
    m = EmailMessage()
    m["From"] = formataddr((d["absender_name"] or mandant["name"], d["absender_adresse"]))
    m["To"] = an
    m["Subject"] = betreff
    m["Date"] = format_datetime(datetime.now(timezone.utc))
    m["Message-ID"] = make_msgid(domain=d["absender_adresse"].split("@", 1)[1])
    for k, v in (header or {}).items():
        m[k] = v
    m.set_content(text)
    m.add_alternative(html_text, subtype="html")
    return m


def _aufraeumen(verz) -> None:
    grenze = time.time() - AUFBEWAHRUNG_DATEI_TAGE * 86400
    for p in verz.glob("*.eml"):
        try:
            if p.stat().st_mtime < grenze:
                p.unlink()
        except OSError:
            pass


def senden(mandant: dict, an: str, betreff: str, text: str, html_text: str, header: dict | None = None) -> str:
    """Gibt 'aus' | 'datei' | 'gesendet' | 'abgelehnt' | 'absender_fehlt' | 'konfiguration_fehlt' | 'fehler' zurück. Wirft nie; Adressen werden nicht protokolliert."""
    modus = mandanten.versandmodus(mandant["id"])
    if modus == "aus":
        return "aus"
    if not mandant["design"]["absender_adresse"]:
        return "absender_fehlt"
    try:
        nachricht = _nachricht(mandant, an, betreff, text, html_text, header)
        if modus == "datei":
            verz = config.ausgang_verzeichnis() / mandant["slug"]
            verz.mkdir(parents=True, exist_ok=True)
            _aufraeumen(verz)
            pfad = verz / ("%019d-%s.eml" % (time.time_ns(), secrets.token_hex(3)))        # Name sortiert nach Zeit
            fd = os.open(str(pfad), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(bytes(nachricht))
            return "datei"
        e = mandanten.versand_lesen(mandant["id"])
        if not all(e.get(f) for f in mandanten.SMTP_FELDER):
            return "konfiguration_fehlt"
        kontext = ssl.create_default_context()
        if e["smtp_verschluesselung"] == "ssl":
            smtp = smtplib.SMTP_SSL(e["smtp_host"], int(e["smtp_port"]), timeout=20, context=kontext)
        else:
            smtp = smtplib.SMTP(e["smtp_host"], int(e["smtp_port"]), timeout=20)
            smtp.starttls(context=kontext)
        with smtp:
            smtp.login(e["smtp_benutzer"], e["smtp_passwort"])
            smtp.send_message(nachricht)
        return "gesendet"
    except smtplib.SMTPRecipientsRefused:                                          # harte Ablehnung der Adresse: dauerhaft unzustellbar
        return "abgelehnt"
    except Exception as exc:
        LOG.warning("Mailversand fehlgeschlagen (Mandant %s, %s)", mandant["slug"], type(exc).__name__)
        return "fehler"
