"""HTML-Seiten für Empfängerinnen (Bestätigen, Einstellungen/Abmelden) im Design des Mandanten.

Alles Dynamische wird mit html.escape eingesetzt. Seiten sind noindex, ohne Referrer, nicht cachebar, nicht einbettbar; Skripte gibt es keine."""
import html

from flask import make_response

import mandanten

KOPF = {
    "Content-Security-Policy": "default-src 'none'; img-src https: data:; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


def _e(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def seite(mandant: dict, titel: str, inhalt: str, status: int = 200):
    d = mandant["design"]
    logo = ('<img src="%s" alt="%s" class="logo">' % (_e(d["logo_url"]), _e(mandant["name"]))) if d["logo_url"] else \
        '<span class="name">%s</span>' % _e(mandant["name"])
    links = []
    if d["impressum_url"]:
        links.append('<a href="%s">Impressum</a>' % _e(d["impressum_url"]))
    if d["datenschutz_url"]:
        links.append('<a href="%s">Datenschutz</a>' % _e(d["datenschutz_url"]))
    fuss = "<br>".join(x for x in (_e(d["firmenangaben"]).replace("\n", "<br>"), " · ".join(links)) if x)
    seite_html = (
        '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer"><title>%(titel)s</title>'
        "<style>body{margin:0;background:%(bg)s;color:%(text)s;font-family:%(schrift)s;line-height:1.5}"
        ".kopf{background:%(primaer)s;padding:16px 24px;color:#fff;font-size:20px;font-weight:bold}.logo{max-height:48px;max-width:240px;display:block}"
        ".inhalt{max-width:640px;margin:24px auto;padding:24px;background:#fff;border-radius:8px}"
        "button{background:%(primaer)s;color:#fff;border:0;border-radius:6px;padding:12px 22px;font-size:16px;cursor:pointer;margin:6px 6px 6px 0}"
        "button.zweit{background:#6b7280}label{display:block;margin:6px 0}select{padding:8px;font-size:16px}"
        ".fuss{max-width:640px;margin:0 auto 24px;padding:0 24px;font-size:12px;color:#6b7280}a{color:%(primaer)s}"
        ".hinweis{background:%(akzent)s33;border-left:4px solid %(akzent)s;padding:8px 12px;margin:12px 0}</style></head><body>"
        '<div class="kopf">%(logo)s</div><div class="inhalt"><h1 style="font-size:22px;margin-top:0">%(titel)s</h1>%(inhalt)s</div>'
        '<div class="fuss">%(fuss)s</div></body></html>'
        % {"titel": _e(titel), "bg": d["farbe_hintergrund"], "text": d["farbe_text"], "schrift": mandanten.SCHRIFTEN[d["schrift"]],
           "primaer": d["farbe_primaer"], "akzent": d["farbe_akzent"], "logo": logo, "inhalt": inhalt, "fuss": fuss})
    antwort = make_response(seite_html, status)
    antwort.headers["Content-Type"] = "text/html; charset=utf-8"
    for k, v in KOPF.items():
        antwort.headers[k] = v
    return antwort


def meldung(mandant: dict, titel: str, text: str, status: int = 200):
    return seite(mandant, titel, "<p>%s</p>" % _e(text), status)


def bestaetigen_formular(mandant: dict, token: str):
    """GET ändert nichts (Mail-Scanner rufen Links ab); bestätigt wird erst per Klick (POST)."""
    inhalt = ('<p>Bitte bestätigen Sie Ihre Anmeldung zum Newsletter von <b>%s</b>.</p>'
              '<form method="post"><button type="submit">Anmeldung bestätigen</button></form>' % _e(mandant["name"]))
    return seite(mandant, "Anmeldung bestätigen", inhalt)


def einstellungen_formular(mandant: dict, token: str, daten: dict, hinweis: str = ""):
    if daten["status"] == "abgemeldet":
        return seite(mandant, "Newsletter", "<p>Sie sind abgemeldet. Wir senden Ihnen keine Newsletter mehr.</p>")
    rollen = "".join('<option value="%s"%s>%s</option>' % (_e(r["wert"]), " selected" if daten["rolle"] == r["wert"] else "", _e(r["label"]))
                     for r in daten["erlaubte_rollen"])
    rolle_feld = ('<label>Ihre Rolle: <select name="rolle"><option value="">keine Angabe</option>%s</select></label>' % rollen) if rollen else ""
    interessen = "".join('<label><input type="checkbox" name="interessen" value="%s"%s> %s</label>'
                         % (_e(i["wert"]), " checked" if i["wert"] in daten["interessen"] else "", _e(i["label"]))
                         for i in daten["erlaubte_interessen"])
    interessen_feld = ("<p>Ihre Interessen:</p>%s" % interessen) if interessen else ""
    kopf = ('<div class="hinweis">%s</div>' % _e(hinweis)) if hinweis else ""
    inhalt = ('%s<p>Newsletter für <b>%s</b></p><form method="post">%s%s'
              '<button type="submit" name="aktion" value="speichern">Speichern</button>'
              '<button type="submit" name="aktion" value="abmelden" class="zweit">Vom Newsletter abmelden</button></form>'
              % (kopf, _e(daten["email_maskiert"]), rolle_feld, interessen_feld))
    return seite(mandant, "Newsletter-Einstellungen", inhalt)
