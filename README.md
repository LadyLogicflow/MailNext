# MailNext

Eigener Dienst für Einwilligungen (Double-Opt-in) und Newsletter-Versand von BST Next, für **beliebig viele Mandanten** (Kundinnen/Kunden).
Domain: mailnext.bst-next.de. Betreiber melden sich über das Portal-Cookie an (Prüfung bei SortNext).

## Stand
- Meilenstein 0 (Gerüst): `/health`, `/api/version`, verschlüsselte Einstellungen, Audit-Tabelle, Betreiber-Prüfung.
- Meilenstein A (0.1.0): Mandanten, Anmelden, Bestätigen, Abmelden, Präferenzen.
- **Meilenstein B (0.2.0): Newsletter schreiben, Testmail, Freigabe, Versand mit Limit, Protokoll.** Echtversand bleibt je Mandant gesperrt, bis ein Betreiber ihn ausdrücklich freigibt.

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

## Import von Bestandsadressen (ab 0.3.0)
Für Adressen, die schon eine Einwilligung gegeben haben (z. B. Export aus Mailchimp). Nur Betreiber, Einwilligungen müssen vorliegen (der Betreiber bestätigt das bei jedem echten Import, es steht im Audit).
`POST /api/v1/betreiber/mandanten/<id>/abonnenten/import`, JSON: `daten` (Text der CSV-Datei oder eine Adresse je Zeile; höchstens 3 MB und 20 000 Zeilen), `quelle` (Pflicht, 1–100 Zeichen), `nur_pruefen` (true = nur zählen, nichts speichern), `einwilligung_bestaetigt` (Pflicht beim echten Import), optional `rolle` und `interessen` (Werte aus dem Mandanten, gelten für den ganzen Lauf; unbekannte Werte → 400).
Gelesen werden nur die Spalten E-Mail (am Kopf erkannt: Email Address, E-Mail-Adresse, E-Mail, Email, Mail; ohne Kopf die erste Spalte), Status und Tags. Trennzeichen, BOM, Anführungszeichen und Zeilenenden werden erkannt; Namen und alle anderen Spalten werden nie gelesen oder gespeichert. Nur Zeilen mit leerem Status oder `subscribed`/`abonniert` werden übernommen (unsubscribed, cleaned, non-subscribed, pending usw. nicht).
Importierte Adressen sind sofort bestätigt (kein Double-Opt-in, keine Mail), mit Herkunft `import`, Datum und Quelle, und haben wie alle persönliche Abmelde-Links. Abgemeldete, unzustellbare und unbestätigte Adressen werden NIE verändert (insbesondere nie wieder aktiviert). Bekannte bestätigte Adressen werden nicht doppelt angelegt: Interessen und Tags werden vereinigt, die Rolle nur gesetzt, wenn noch keine da ist (sonst `rolle_konflikt`).
Tags (Mailchimp-Spalte `TAGS`): freie Schlagwörter je Abonnent (höchstens 20, je höchstens 40 Zeichen, Komma, Semikolon oder | als Trenner, Groß-/Kleinschreibung egal), in der Abonnentenliste sichtbar.
Antwort: `{nur_pruefen, zeilen, neu, dublette, ungueltig, uebersprungen: {abgemeldet, unzustellbar, unbestaetigt, status}, uebersprungen_gesamt, zusammengefuehrt, rolle_konflikt, tags: {verschiedene, haeufigste: [{tag, anzahl}], verworfen}, kennzahlen}`. Fehler: 400 `daten_fehlen`, `spalte_nicht_gefunden`, `zu_viele_zeilen`, `einwilligung_nicht_bestaetigt`, `eingabe_ungueltig`; 413 `zu_gross`. Audit: nur Anzahlen und Quelle, nie Adressen. Auf dem Pi: `python manage.py import <slug> <datei.csv> "<Quelle>" [nur-pruefen] [einwilligung-liegt-vor] [rolle=<Wert>] [interessen=<Wert,Wert>]` (ohne `einwilligung-liegt-vor` nur Prüfung).
**Versand nach Tags.** Die Zielgruppe eines Newsletters (`segment`) kennt neben `rollen` und `interessen` jetzt `tags` (Liste vorhandener Tags des Mandanten, höchstens 20) und `tags_modus` (`oder` = Standard, `und`). Innerhalb einer Auswahl gilt ODER (bei `tags` wählbar UND), zwischen Rolle, Interessen und Tags UND; nur bestätigte Abonnentinnen, nie Abgemeldete, Unzustellbare oder Unbestätigte. `GET /api/v1/betreiber/mandanten/<id>/abonnenten/tags` liefert die vorhandenen Tags mit Anzahl (nur bestätigte, keine Adressen); `POST …/abonnenten/vorschau {"segment": {…}}` die Zahl der Empfänger für ein Segment, ohne Entwurf.

## Newsletter (je Mandant, Betreiber-Schnittstelle `/api/v1/betreiber/mandanten/<id>/…`)
- `entwuerfe` (GET, POST `{betreff, text, ziel: testliste|abonnenten, segment: {rollen, interessen}}`), `entwuerfe/<eid>` (GET, PUT nur im Status entwurf).
- `entwuerfe/<eid>/testmail` (POST `{an?}`: ohne `an` an den eingeloggten Betreiber, `an` nur aus der Testliste), `…/empfaengervorschau` (nur Zahl), `…/freigeben` (POST `{content_hash, bestaetigt: true}`),
  `…/stoppen`, `…/status`, `…/protokoll` und `…/protokoll.csv` (Adressen, wird protokolliert; CSV mit Formelschutz).
- `testliste` (GET, PUT, höchstens 50), `echtversand` (GET, PUT `{freigegeben: bool}`, Standard false).
- Regeln: Freigabe nur mit Testmail zum aktuellen Stand (SHA-256 über Betreff, Text, Ziel, Segment); Empfängerliste wird bei der Freigabe festgeschrieben (nur bestätigte Adressen);
  Echtversand (`ziel: abonnenten`) nur nach Freigabe des Mandanten, auch der Versandlauf prüft das nochmals; Abmeldestatus wird vor jedem Senden erneut geprüft.
- Versandlauf: jede Minute im Hintergrund (`MAILNEXT_VERSAND_JOB=0` schaltet ihn ab), höchstens 5 Mails je Lauf und 100 je Stunde und Mandant, höchstens einmal je Person und Entwurf.
  Vorübergehende Fehler: bis zu 3 Versuche im Abstand von 5 Minuten, dann `fehlgeschlagen`. Harte Ablehnung: Adresse wird `unzustellbar`. Hängt eine Zeile über 10 Minuten in `sending`, wird sie `unklar` und nie automatisch wiederholt.
- Jede Mail: Text und HTML im Mandantendesign, persönlicher Einstellungs- und Abmeldelink, `List-Unsubscribe` mit One-Click, kein Tracking.

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
Testinstanz auf dem Pi (ohne Coolify): `docker-compose.pi.yaml`, Anleitung in `PI-TESTINSTANZ.md`.
Produktion: `docker-compose.coolify.yaml` (Volume `mailnext-data` → `/data`, Port 8000, Healthcheck `/health`).
Deploy per Git-Tag, `main` bleibt auslieferbar. SQLite-Datei: `/data/mailnext.db` (Sicherung nötig).

## Tests
`python3 -m unittest discover -s tests`
