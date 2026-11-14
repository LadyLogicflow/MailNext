# MailNext: Testinstanz auf dem Raspberry Pi

Die Testinstanz läuft im Heimnetz, ohne Coolify. Sie kann
- **ausprobieren** (Newsletter-Anmeldung, Bestätigung, Einstellungen) mit erfundenen Daten, Versandmodus „datei“ (jede Mail wird als Datei abgelegt), und
- ab v0.5.0 **echt versenden** (Versandmodus „smtp“) an importierte Adressen, wenn die Bedingungen im Abschnitt „Echtversand“ erfüllt sind.

Beim Echtversand gehen echte Mails an echte Menschen. Vorher die Checkliste unten abarbeiten.

## Voraussetzungen
- Pi im Heimnetz mit Docker und dem Compose-Plugin (`docker compose version` zeigt eine Version), Git, rund 1 GB frei.
- Ein Rechner oder Handy im selben Netz.

## Starten (einmalig, einige Minuten)
1. Quelltext holen (Adresse des Repositorys von EFINITI): `git clone <Adresse> mailnext && cd mailnext` (bei Bedarf einen getesteten Stand wählen: `git checkout <Tag>`).
2. Einstellungen anlegen: `cp pi.env.beispiel .env`, dann die Datei `.env` bearbeiten: `MAILNEXT_HAUPTSCHLUESSEL` (mindestens 32 zufällige Zeichen, z. B. Ausgabe von `openssl rand -base64 36`) und `MAILNEXT_PI_ADRESSE` (Adresse des Pi, z. B. `192.168.1.50`; bei mehreren Zugangswegen alle mit Komma, siehe „Zugriff über Tailscale“). Die Datei `.env` nicht weitergeben.
3. Bauen und starten: `docker compose -f docker-compose.pi.yaml up -d --build`
4. Prüfen: `docker compose -f docker-compose.pi.yaml ps` („healthy“ nach etwa einer Minute) und `curl http://<Adresse>:8000/health` (Antwort mit `"status":"ok"`).

## Die zwei Ports
| Port | Wer darf hin | Was wird beantwortet |
|---|---|---|
| **8000** (intern) | nur das Heimnetz | alles: Betreiber-Oberfläche (`/betreiber/`), Betreiber-Schnittstelle, `/health`, öffentliche Seiten |
| **8001** (öffentlich) | darf per Tunnel oder Reverse Proxy nach außen | **nur** die öffentlichen Newsletter-Seiten: Anmelden, Bestätigen, Abmelden, Einstellungen, One-Click-Abmeldung. Alles andere (auch `/health`, `/betreiber`, `/api/v1/…`) antwortet dort mit 404. |

Die Trennung entscheidet der Port der Verbindung **im Container** (8000/8001), nicht der Host-Kopf, den ein Absender frei wählen kann, und nicht der Port am Pi. **Nach außen darf nur der öffentliche Port (8001) gezeigt werden, nie der interne (8000).**

**Sind 8000/8001 am Pi schon belegt?** Dann in `.env` andere Ports am Pi eintragen, z. B. `MAILNEXT_PORT_INTERN=8200` und `MAILNEXT_PORT_OEFFENTLICH=8201` (die Datei `docker-compose.pi.yaml` nicht von Hand ändern). Die Betreiber-Oberfläche liegt dann unter `http://<Pi-Adresse>:8200/betreiber`, ein Tunnel zeigt auf `http://<Pi>:8201`. Die Links in den Mails zeigen standardmäßig auf `http://<Pi-Adresse>:<öffentlicher Port>`; mit einer öffentlichen https-Adresse `MAILNEXT_BASIS_URL` setzen. `MAILNEXT_PI_ADRESSE` bleibt nur die Adresse, ohne Port (die Prüfung im Offen-Modus ignoriert den Port im Host-Kopf).

### Tunnel oder Reverse Proxy (öffentliche https-Adresse)
Empfänger brauchen eine öffentlich erreichbare **https**-Adresse für Bestätigungs-, Abmelde- und Einstellungslinks (und der One-Click-Abmeldelink verlangt sie). Die Adresse (Domain oder Tunnel) kommt von catrin. Einrichten:
1. Tunnel/Proxy so einstellen, dass er **ausschließlich** auf `http://<Pi>:<öffentlicher Port>` (Standard 8001) zeigt, nie auf den internen Port (Standard 8000). Den internen Port nicht im Router weiterleiten.
2. In `.env` eintragen: `MAILNEXT_BASIS_URL=https://<öffentliche Adresse>` und, wenn Tunnel/Proxy vor 8001 sitzt, `MAILNEXT_PROXIES=1` (damit die Anmeldebegrenzung die echte Adresse des Besuchers sieht).
3. Neu starten: `docker compose -f docker-compose.pi.yaml up -d`.
4. Prüfen von **außerhalb** des Heimnetzes: `https://<Adresse>/<slug>/newsletter/einstellungen` antwortet, `https://<Adresse>/health` und `https://<Adresse>/betreiber` antworten mit 404.

## Betreiber-Oberfläche ohne Anmeldung („Offen-Modus“)
Die Oberfläche (`http://<Pi-Adresse>:8000/betreiber/`, ein Aufruf ohne Schrägstrich am Ende wird dorthin umgeleitet) verlangt sonst die Portal-Anmeldung, die es im Heimnetz nicht gibt. Für die Testinstanz gibt es den **Offen-Modus**, der Anmeldung durch Netzschutz ersetzt:
- Einschalten in `.env`: `MAILNEXT_BETREIBER_AUTH=offen` (Standard `portal`, jeder andere Wert gilt als `portal`). Optional `MAILNEXT_BETREIBER_OFFEN_EMAIL=<Adresse>`: Sie steht als Akteur im Audit-Log und ist der Standard-Empfänger der Testmail.
- Betreiberaufrufe werden **nur** beantwortet, wenn alles zutrifft, sonst 403: die Verbindung kommt direkt von einer privaten Adresse (Loopback, 10.x, 172.16–31.x, 192.168.x, Tailscale 100.64.0.0/10 und fd7a:115c:a1e0::/48), die Anfrage trägt **keinen** Proxy-Kopf (`X-Forwarded-For`, `Forwarded`, `X-Real-IP`, `CF-Connecting-IP` …), der Host-Kopf ist eine der Adressen aus `MAILNEXT_PI_ADRESSE` oder localhost, und ändernde Aufrufe mit Origin-Kopf kommen vom selben Host (stoppt fremde Webseiten im Browser des Heimnetzes). Auf Port 8001 gibt es keine Betreiberpfade.
- Beim Start steht eine deutliche WARNUNG im Log, und `/health` zeigt `"betreiber_offen": true`.
- Das Audit-Log bleibt vollständig (Akteur „offen“ oder die Adresse aus `MAILNEXT_BETREIBER_OFFEN_EMAIL`, die Quelladresse nur als Pseudonym).
- **Risiko:** Jedes Gerät, das im Heimnetz die Pi-Adresse erreicht (auch ein Gast-WLAN, falls es nicht getrennt ist), kann Adressen ansehen, exportieren und importieren und Newsletter freigeben, ohne Anmeldung. Port 8000 nie ins Internet weiterleiten, Gast-WLAN vom Heimnetz trennen.

## Zugriff über Tailscale
Wird der Pi nur über Tailscale erreicht (Verbindung von 100.x.y.z), gilt im Offen-Modus zusätzlich: Quelladressen aus `100.64.0.0/10` (IPv4) und `fd7a:115c:a1e0::/48` (IPv6) sind erlaubt, alles andere außerhalb von Loopback und privaten Netzen bleibt 403.
- In `.env` **alle** Adressen eintragen, unter denen der Browser den Pi anspricht, mit Komma, ohne Port: `MAILNEXT_PI_ADRESSE=100.101.102.103,pi5,pi5.dein-tailnet.ts.net` (Tailscale-IP, kurzer Name, MagicDNS-Name; auch die LAN-Adresse, wenn sie benutzt wird). Der Host-Kopf der Anfrage muss zu einem Eintrag passen. Die erste Adresse bildet die Links in den Mails, solange `MAILNEXT_BASIS_URL` leer ist.
- Neu starten: `docker compose -f docker-compose.pi.yaml up -d`. Aufruf: `http://<Tailscale-IP>:<interner Port>/betreiber/`.
- **Nicht** `tailscale serve` oder `tailscale funnel` vor den internen Port setzen: Serve schickt Proxy-Köpfe mit, der Offen-Modus lehnt solche Anfragen ab (403, gewollt); Funnel würde den Dienst ins Internet stellen.
- Hinweis: `100.64.0.0/10` ist der gemeinsame Adressbereich für Carrier-Grade-NAT, nicht nur für Tailscale. Im Heimnetz ohne Tailscale diesen Bereich nicht benutzen.

## Einrichten und ausprobieren
Alle Kommandos laufen im Container: `docker compose -f docker-compose.pi.yaml exec mailnext python manage.py …` (Kopf von `manage.py` zeigt alle Befehle). Alternativ die Betreiber-Oberfläche im Offen-Modus.
1. Test-Mandant: `… manage.py mandant-neu demo "Demo-Beratungsstelle"`
2. Einwilligungstext: `… manage.py einwilligung demo v1 "Ich willige in den Erhalt des Newsletters ein (Testtext)."`
3. Versandmodus „datei“: `… manage.py versand demo datei`
4. Absender setzen (ohne Absender legt MailNext keine Mail ab): `docker compose -f docker-compose.pi.yaml exec mailnext sh -c "printf '%s' '{\"absender_adresse\":\"newsletter@example.org\",\"absender_name\":\"Demo-Beratungsstelle\"}' > /tmp/design.json && python manage.py design demo /tmp/design.json"`
5. Anmeldung auslösen (erfundene Adresse): `curl -X POST http://<Adresse>:8000/api/demo/newsletter/anmelden -H "Content-Type: application/json" -d '{"email":"test@example.org","einwilligungs_version":"v1"}'`
6. Die Bestätigungsmail liegt als Datei im Container: `docker compose -f docker-compose.pi.yaml exec mailnext sh -c 'ls /data/ausgang/demo; cat /data/ausgang/demo/*.eml'`. Den Link darin im Browser öffnen (Seite mit Knopf „bestätigen“).
7. Übersicht: `… manage.py liste` und `… manage.py abonnenten demo`.

## Echtversand (ab v0.5.0)
**Checkliste, bevor eine echte Mail hinausgeht:**
1. **Öffentliche https-Adresse** steht (Abschnitt „Tunnel oder Reverse Proxy“), `MAILNEXT_BASIS_URL` ist gesetzt, nur Port 8001 ist erreichbar.
2. **Design des Mandanten** enthält Absenderadresse, Absendername, **Impressum-URL, Datenschutz-URL und Firmenangaben**. Ohne diese vier Angaben verweigert MailNext die Freigabe an Abonnenten (`pflichtangaben_fehlen`). Freigaben an die Testliste sind davon ausgenommen.
3. **SMTP-Konto des Mandanten:** `… manage.py smtp <slug> <host> <port> <benutzer> ssl|starttls` (das Passwort wird am Terminal ohne Anzeige abgefragt und verschlüsselt gespeichert; setzt den Versandmodus auf „smtp“). Die Zertifikatsprüfung des Servers ist immer an und nicht abschaltbar; der Pi braucht die richtige Uhrzeit und aktuelle CA-Zertifikate.
4. **Zustellbarkeit:** MailNext signiert nichts selbst (kein DKIM). Die Domain der Absenderadresse muss im SPF den SMTP-Server des Anbieters erlauben, und der Anbieter muss für diese Domain DKIM signieren (DMARC-Ausrichtung). Erst eine Testmail an ein Postfach mit Header-Ansicht schicken und SPF/DKIM/DMARC prüfen.
5. **Testliste** pflegen (Betreiber-Oberfläche oder `PUT …/testliste`), dann **Testmail** an eine Adresse aus der Testliste: `… manage.py entwurf <slug> <datei> ziel=abonnenten` (Datei: erste Zeile `Betreff: …`, Leerzeile, Text), `… manage.py testmail <slug> <entwurf_id> <adresse>` (ohne Adresse geht sie an `MAILNEXT_BETREIBER_OFFEN_EMAIL`).
6. **Echtversand freigeben:** `… manage.py echtversand <slug> ja` (Standard ist „nein“, ohne Freigabe geht nichts an Abonnenten).
7. **Freigeben:** `… manage.py freigeben <slug> <entwurf_id>` zeigt Betreff, Ziel und Empfängerzahl und verlangt die Empfängerzahl als Bestätigung. Es gelten dieselben Prüfungen wie in der Betreiber-Schnittstelle (aktuelle Testmail, Echtversand freigegeben, Pflichtangaben).
8. **Versandrate:** Standard 100 Mails pro Stunde und Mandant (also 1000 Adressen in etwa 10 Stunden). Änderbar von 1 bis 600: `… manage.py versand-rate <slug> <zahl>`. Die Grenzen des SMTP-Anbieters (Mails pro Stunde/Tag) gelten zusätzlich und sind Sache des Anbieters.
9. Den Versand beobachten (Betreiber-Oberfläche: Protokoll/Status je Entwurf). Ein laufender Entwurf lässt sich über „stoppen“ anhalten.

## Was in dieser Testinstanz nicht geht
- Anmeldung über das Portal (Cookie der Domain bst-next.de): nicht möglich, dafür gibt es den Offen-Modus.
- Mehrere Dienst-Instanzen: Es läuft ein Worker (SQLite und der Versandlauf im selben Prozess).

## Aufräumen
- Anhalten: `docker compose -f docker-compose.pi.yaml down` (Daten bleiben).
- Alles löschen: `docker compose -f docker-compose.pi.yaml down -v`.

## Wenn etwas nicht klappt
- Dienst wird nicht „healthy“: `docker compose -f docker-compose.pi.yaml logs mailnext`. Häufigste Ursache: `MAILNEXT_HAUPTSCHLUESSEL` zu kurz oder leer.
- Seite nicht erreichbar: Adresse in `.env` stimmt nicht, oder Port 8000/8001 ist auf dem Pi belegt.
- Betreiber-Oberfläche meldet 403 im Offen-Modus: Die Adresse im Browser ist nicht `MAILNEXT_PI_ADRESSE` (z. B. Name statt IP), oder ein Proxy/Tunnel steht vor Port 8000 (dann nicht benutzen, den Tunnel auf 8001 stellen). Hinweis steht im Log („Offen-Modus: Betreiber-Aufruf abgelehnt (Grund)“).
