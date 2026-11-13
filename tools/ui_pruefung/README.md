# UI-Prüfung der Betreiberoberfläche (jsdom)

Treibt die echte `ui/betreiber/betreiber.js` in jsdom gegen den echten MailNext-Server (Testdatenbank, Anmeldung per Test-Ersatz): Abonnentenliste mit Tags, Segment-Auswahl mit
Empfängerzahl, Import mit Vorschau und Bestätigung. Es ersetzt keinen Test im echten Browser (Layout, Dateiauswahl, Touch), fängt aber Vertragsfehler zwischen Oberfläche und Schnittstelle.

Einmalig: `cd tools/ui_pruefung && npm install jsdom@24 --no-save` (Node 20). Dann im Repository-Wurzelordner:
`python -m unittest discover -s tools/ui_pruefung -p "test_ui_betreiber.py"` (optional `UI_DIR=<Ordner>` für einen anderen Stand der Oberfläche).
Nicht Teil des Gates (braucht Node und jsdom).
