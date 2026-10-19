# MailNext

Eigener Dienst für Einwilligungen (Double-Opt-in) und Newsletter-Versand von BST Next.
Domain: mailnext.bst-next.de. Betreiber melden sich über das Portal-Cookie an (Prüfung bei SortNext).

## Stand
Meilenstein 0 (Gerüst): `/health`, `/api/version`, verschlüsselte Einstellungen, Audit-Tabelle, Betreiber-Prüfung.

## Konfiguration
- `MAILNEXT_HAUPTSCHLUESSEL` (geheim, mind. 32 Zeichen, kein Standardwert): Ohne ihn startet der Dienst,
  meldet aber unter `/health` HTTP 503 mit `hauptschluessel_fehlt` und nutzt keine Einstellungen.
  Es wird nie ein Ersatzschlüssel erzeugt.
- `SORTNEXT_BASE_URL` (Standard `https://sortnext.bst-next.de`), `MAILNEXT_DATEN` (Standard `/data`).
- Alles Weitere (Mail-Konto, gemeinsames Geheimnis zu SortNext) liegt verschlüsselt in der Datenbank
  und wird in der Betreiber-Oberfläche gepflegt.

## Betrieb
Produktion: `docker-compose.coolify.yaml` (Volume `mailnext-data` → `/data`, Port 8000, Healthcheck `/health`).
Deploy per Git-Tag, `main` bleibt auslieferbar. SQLite-Datei: `/data/mailnext.db` (Sicherung nötig).

## Tests
`python3 -m unittest discover -s tests`
