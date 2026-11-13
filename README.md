# MailNext

Eigener Dienst für Einwilligungen (Double-Opt-in) und Newsletter-Versand von BST Next, für **beliebig viele Mandanten** (Kundinnen/Kunden).
Domain: mailnext.bst-next.de. Betreiber melden sich über das Portal-Cookie an (Prüfung bei SortNext).

## Stand
- Meilenstein 0 (Gerüst): `/health`, `/api/version`, verschlüsselte Einstellungen, Audit-Tabelle, Betreiber-Prüfung.
- **Meilenstein A (0.1.0): Mandanten, Anmelden, Bestätigen, Abmelden, Präferenzen.** Versand von Newslettern folgt mit Meilenstein B.

## Mandanten
Jeder Mandant hat eine Kennung (`slug`) und trennt alles strikt: eigenes Design (Farben, Schrift, Logo, Absender, Firmenangaben, Impressum/Datenschutz,
Rollen- und Interessenlisten, erlaubte Website-Ursprünge), eigene Einwilligungstexte (mit Version und SHA-256), eigene Kontakte, eigene Zugangsdaten.
Dieselbe E-Mail-Adresse hat in zwei Mandanten verschiedene Pseudonyme (HMAC), Tokens gelten nur im eigenen Mandanten.

## Öffentliche Schnittstelle (Kennung im Pfad)
- `GET  /api/<slug>/newsletter/formular` → Name, Einwilligungsversion und -text, Rollen, Interessen.
- `POST /api/<slug>/newsletter/anmelden` `{email, rolle?, interessen?, einwilligungs_version}` → immer `200 {"status":"ok"}` bei gültiger Form (kein Abfragen von Adressen); 400 nur `json_ungueltig | feld_ungueltig | version_unbekannt`.
- `GET /<slug>/newsletter/bestaetigen/<token>` (Seite mit Knopf, ändert nichts), `POST` bestätigt; JSON: `POST /api/<slug>/newsletter/bestaetigen {token}` (200 / 400 / 410).
- `GET /<slug>/newsletter/einstellungen?t=<persönliches Token>`: Seite zum Ändern von Rolle/Interessen und Abmelden. JSON: `GET|POST /api/<slug>/newsletter/praeferenzen`, `POST /api/<slug>/newsletter/abmelden {t}`.
- `POST /<slug>/newsletter/abmelden-one-click/<token>` (RFC 8058); alle anderen Methoden 405.
- Abmelden ersetzt den Eintrag durch den Minimaldatensatz (HMAC der Adresse, Zeitpunkt Anmeldung, Zeitpunkt Abmeldung).

## Betreiber-Schnittstelle (`/api/v1/betreiber`, Portal-Cookie, jeder Aufruf im Audit-Log)
`GET|POST /mandanten`, `GET|PUT /mandanten/<id>`, `POST /mandanten/<id>/einwilligungen`, `PUT /mandanten/<id>/versand`, `GET /mandanten/<id>/abonnenten`.
Geheimnisse (SMTP-Passwort) werden nie zurückgegeben, nur ob sie gesetzt sind.

## Versand
Standard je Mandant: `aus` (es geht keine Mail hinaus). `datei`: Mails landen als .eml unter `<Daten>/ausgang/<slug>/` (Test auf dem Pi, 7 Tage). `smtp`: über das SMTP-Konto des Mandanten.

## Kommandozeile (Einrichtung und Tests)
`python manage.py` – Mandant anlegen, Design ändern, Einwilligungstext anlegen, Versandmodus aus/datei, Liste, Abonnenten (siehe Kopf der Datei).

## Konfiguration
- `MAILNEXT_HAUPTSCHLUESSEL` (geheim, mind. 32 Zeichen, kein Standardwert): Ohne ihn startet der Dienst,
  meldet aber unter `/health` HTTP 503 mit `hauptschluessel_fehlt`; öffentliche Aufrufe antworten 503 `nicht_bereit`. Es wird nie ein Ersatzschlüssel erzeugt.
- `SORTNEXT_BASE_URL` (Standard `https://sortnext.bst-next.de`), `MAILNEXT_DATEN` (Standard `/data`),
  `MAILNEXT_BASIS_URL` (Standard `https://mailnext.bst-next.de`, für Links in Mails; je Mandant überschreibbar),
  `MAILNEXT_PROXIES` (Anzahl vorgeschalteter Proxys für `X-Forwarded-For`, Standard 1).
- Alles Weitere (Mail-Konten, Mandanten) liegt in der Datenbank, Zugangsdaten verschlüsselt.

## Betrieb
Produktion: `docker-compose.coolify.yaml` (Volume `mailnext-data` → `/data`, Port 8000, Healthcheck `/health`).
Deploy per Git-Tag, `main` bleibt auslieferbar. SQLite-Datei: `/data/mailnext.db` (Sicherung nötig).

## Tests
`python3 -m unittest discover -s tests`
