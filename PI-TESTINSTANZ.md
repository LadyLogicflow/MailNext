# MailNext: Testinstanz auf dem Raspberry Pi

Zum Ausprobieren der öffentlichen Seiten (Newsletter-Anmeldung, Bestätigung, Einstellungen) mit erfundenen Daten. Kein Produktivbetrieb, keine echten Adressen, nie aus dem Internet erreichbar machen. Es werden keine echten Mails versendet: Der Versandmodus „datei“ legt jede Mail als Datei ab.

## Voraussetzungen
- Pi im Heimnetz mit Docker und dem Compose-Plugin (`docker compose version` zeigt eine Version), Git, rund 1 GB frei.
- Ein Rechner oder Handy im selben Netz.

## Starten (einmalig, einige Minuten)
1. Quelltext holen (Adresse des Repositorys von EFINITI): `git clone <Adresse> mailnext && cd mailnext` (bei Bedarf einen getesteten Stand wählen: `git checkout <Tag>`).
2. Einstellungen anlegen: `cp pi.env.beispiel .env`, dann `.env` bearbeiten: `MAILNEXT_HAUPTSCHLUESSEL` (mindestens 32 zufällige Zeichen, z. B. Ausgabe von `openssl rand -base64 36`) und `MAILNEXT_PI_ADRESSE` (Adresse des Pi im Heimnetz, z. B. `192.168.1.50`). Die Datei `.env` nicht weitergeben.
3. Bauen und starten: `docker compose -f docker-compose.pi.yaml up -d --build`
4. Prüfen: `docker compose -f docker-compose.pi.yaml ps` („healthy“ nach etwa einer Minute) und `curl http://<Adresse>:8000/health` (Antwort mit `"status":"ok"`).

## Einrichten und ausprobieren
Alle Kommandos laufen im Container: `docker compose -f docker-compose.pi.yaml exec mailnext python manage.py …`
1. Test-Mandant: `… manage.py mandant-neu demo "Demo-Beratungsstelle"`
2. Einwilligungstext: `… manage.py einwilligung demo v1 "Ich willige in den Erhalt des Newsletters ein (Testtext)."`
3. Versandmodus „datei“: `… manage.py versand demo datei`
4. Absender setzen (ohne Absender legt MailNext keine Mail ab): `docker compose -f docker-compose.pi.yaml exec mailnext sh -c "printf '%s' '{\"absender_adresse\":\"newsletter@example.org\",\"absender_name\":\"Demo-Beratungsstelle\"}' > /tmp/design.json && python manage.py design demo /tmp/design.json"`
5. Anmeldung auslösen (erfundene Adresse): `curl -X POST http://<Adresse>:8000/api/demo/newsletter/anmelden -H "Content-Type: application/json" -d '{"email":"test@example.org","einwilligungs_version":"v1"}'`
6. Die Bestätigungsmail liegt als Datei im Container: `docker compose -f docker-compose.pi.yaml exec mailnext sh -c 'ls /data/ausgang/demo; cat /data/ausgang/demo/*.eml'`. Den Link darin im Browser öffnen (Seite mit Knopf „bestätigen“).
7. Übersicht: `… manage.py liste` und `… manage.py abonnenten demo`.

## Was in dieser Testinstanz nicht geht
- **Betreiber-Oberfläche**: Sie braucht die Anmeldung über das Portal (Cookie der Domain bst-next.de). Auf dem Pi nicht möglich; die Einrichtung läuft über `manage.py`.
- **Echter Mailversand** (smtp): nicht in dieser Testinstanz.

## Aufräumen
- Anhalten: `docker compose -f docker-compose.pi.yaml down` (Daten bleiben).
- Alles löschen: `docker compose -f docker-compose.pi.yaml down -v`.

## Wenn etwas nicht klappt
- Dienst wird nicht „healthy“: `docker compose -f docker-compose.pi.yaml logs mailnext`. Häufigste Ursache: `MAILNEXT_HAUPTSCHLUESSEL` zu kurz oder leer.
- Seite nicht erreichbar: Adresse in `.env` stimmt nicht, oder Port 8000 ist auf dem Pi belegt.
