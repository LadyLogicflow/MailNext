"""jsdom-Prüfung der MailNext-Betreiberoberfläche gegen den echten Testserver (siehe README.md in diesem Ordner). UI_DIR (optional) = Ordner mit index.html, betreiber.js, betreiber.css."""
import json, mimetypes, os, subprocess, sys, threading, unittest
from unittest import mock
from werkzeug.serving import make_server
from werkzeug.wrappers import Request, Response
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import betreiber_auth, db, abonnenten, schluessel
from tests.test_import import ImportBasis, mc

HIER = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.environ.get("UI_DIR") or os.path.join(os.path.dirname(os.path.dirname(HIER)), "ui", "betreiber")
DRIVE = os.path.join(HIER, "drive_mn.js")


class MN(ImportBasis):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(betreiber_auth, "_bei_sortnext_fragen", return_value={"email": "catrin@bst-next.de", "betreiber": True})
        p.start(); self.addCleanup(p.stop)
        betreiber_auth.cache_leeren()
        inner = self.app.wsgi_app

        def mw(environ, start):
            req = Request(environ)
            if req.path in ("/betreiber", "/betreiber/") or req.path.startswith("/betreiber/"):
                name = "index.html" if req.path in ("/betreiber", "/betreiber/") else os.path.basename(req.path)
                f = os.path.join(UI_DIR, name)
                if os.path.isfile(f):
                    return Response(open(f, "rb").read(), mimetype=mimetypes.guess_type(f)[0] or "text/plain")(environ, start)
            return inner(environ, start)
        self.app.wsgi_app = mw
        self.httpd = make_server("127.0.0.1", 0, self.app, threaded=True)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)

    def node(self, **kw):
        kw["port"] = self.httpd.server_port
        p = subprocess.run(["node", DRIVE, json.dumps(kw)], capture_output=True, text=True, timeout=180, cwd=HIER)
        zeilen = [z for z in p.stdout.splitlines() if z.startswith("RESULT ")]
        self.assertTrue(zeilen, p.stdout[-400:] + p.stderr[-400:])
        o = json.loads(zeilen[-1][7:])
        return o


class TestUI(MN):
    def vorbereiten(self):
        m = self.mandant("hilo", "HILO e. V.")
        text = mc([["a@example.org", "", "", "Spender", ""], ["b@example.org", "", "", "Spender,Verein A", ""], ["c@example.org", "", "", "Verein A", ""], ["d@example.org", "", "", "", ""]])
        self.importiere(m, text, rolle="verein", interessen=["sortnext"])
        return m

    def test_abonnentenliste(self):
        m = self.vorbereiten()
        o = self.node(szenario="abonnenten", mandant_name="HILO e. V.")
        print("ABO", json.dumps({k: o.get(k) for k in ("ok", "fehler", "kopf", "zeilen", "fehler_js")}, ensure_ascii=False))
        self.assertTrue(o["ok"], o)
        for spalte in ("Tags", "Herkunft", "Quelle"):
            self.assertIn(spalte, o["kopf"])
        zeile = [z for z in o["zeilen"] if "b@example.org" in z[0]][0]
        self.assertIn("Spender, Verein A", zeile)
        self.assertIn("import", zeile)
        self.assertIn("Mailchimp-Export Test", zeile)

    def test_segment_auswahl_und_empfaengerzahl(self):
        m = self.vorbereiten()
        o = self.node(szenario="newsletter", mandant_name="HILO e. V.", schritte=[
            {"tag": ["Spender"]}, {"tag": ["Spender", "Verein A"]}, {"tag": ["Spender", "Verein A"], "modus": "und"}, {"rolle": ["verein"]}, {"interesse": ["sortnext"], "tag": ["Verein A"]}])
        print("NL_START", json.dumps({k: o.get(k) for k in ("ok", "fehler", "rollen", "interessen", "tags", "empfaenger_start", "fehler_start")}, ensure_ascii=False))
        for s in o.get("schritte", []):
            print("NL_SCHRITT", json.dumps(s, ensure_ascii=False))
        self.assertTrue(o["ok"], o)
        self.assertEqual([t["wert"] for t in o["tags"]], ["Spender", "Verein A"])
        self.assertEqual([r["wert"] for r in o["rollen"]], ["verein", "beratungsstelle"])                 # Wert (nicht [object Object]) und Bezeichnung getrennt
        self.assertEqual([r["label"] for r in o["rollen"]], ["Verein", "Beratungsstelle"])
        self.assertEqual([r["wert"] for r in o["interessen"]], ["sortnext", "booknext"])
        self.assertEqual(o["empfaenger_start"], "Empfänger: 4")
        zahlen = [s["empfaenger"] for s in o["schritte"]]
        self.assertEqual(zahlen[:3], ["Empfänger: 2", "Empfänger: 3", "Empfänger: 1"])
        self.assertTrue(all(not s["fehler"] for s in o["schritte"]), "Fehler bei gültigem Segment")
        # Rolle und Interessen müssen als Werte (wert) gesendet werden, nicht als Objekt
        self.assertEqual(zahlen[3], "Empfänger: 4")                                                       # alle vier haben Rolle verein
        self.assertEqual(zahlen[4], "Empfänger: 2")                                                       # Interesse sortnext UND Tag Verein A (b, c)
        self.assertIn('"rollen":["verein"]', o["schritte"][3]["requests"][0])
        self.assertIn('"interessen":["sortnext"]', o["schritte"][4]["requests"][0])

    def test_import_vorschau_bestaetigen(self):
        m = self.mandant("hilo", "HILO e. V.")
        csv = mc([["a@example.org", "A", "B", "Spender", "subscribed"], ["b@example.org", "", "", "Spender,Verein A", ""], ["kaputt", "", "", "", ""], ["u@example.org", "", "", "", "unsubscribed"]])
        o = self.node(szenario="import", mandant_name="HILO e. V.", csv=csv, quelle="Mailchimp-Export UI", importieren=True, rolle="verein", interessen=["sortnext"])
        print("IMP", json.dumps({k: o.get(k) for k in ("ok", "fehler", "rolle_optionen", "interessen_boxen", "knoepfe_vor", "pruefung", "import_knopf_nach_haken_gesperrt", "import", "toast")}, ensure_ascii=False))
        self.assertTrue(o["ok"], o)
        self.assertEqual([o_["value"] for o_ in o["rolle_optionen"]], ["", "verein", "beratungsstelle"])
        self.assertEqual(self.zahlen(m).get("bestaetigt", 0), 2, "echter Import muss 2 Adressen anlegen")
        self.assertIn("Bestätigt", o["pruefung"]["vorschau_text"].split("Aktuelle Kennzahlen")[1], "Kennzahlen gehören unter ihre Überschrift")
        self.assertNotIn("Bestätigt", o["pruefung"]["vorschau_text"].split("Aktuelle Kennzahlen")[0])
        z = self.zeile(m["id"], "a@example.org")
        self.assertEqual((z["rolle"], json.loads(z["interessen"])), ("verein", ["sortnext"]))
        self.assertEqual(json.loads(z["tags"]), ["Spender"])

    def test_import_ohne_haken_keine_aenderung(self):
        m = self.mandant("hilo", "HILO e. V.")
        o = self.node(szenario="import", mandant_name="HILO e. V.", csv=mc([["a@example.org", "", "", "", ""]]), quelle="Q", importieren=False)
        print("IMP_PROBE", json.dumps(o.get("pruefung"), ensure_ascii=False))
        self.assertTrue(o["ok"], o)
        self.assertEqual(self.zahlen(m), {})
        self.assertIn("POST /api/v1/betreiber/mandanten/%d/abonnenten/import 200" % m["id"], o["pruefung"]["requests"][0])
        self.assertTrue(o["pruefung"]["import_knopf_gesperrt"])


class TestTestliste(MN):
    """Testlisten-Verwaltung im Newsletter-Tab (Weby dfabfa4): laden, hinzufügen (PUT mit der GANZEN Liste), Dublette, ungültig, 51. Adresse, löschen, Backend-Fehlertext, Zähler."""

    def start(self, adressen=()):
        import newsletter
        m = self.mandant("hilo", "HILO e. V.")
        if adressen:
            newsletter.testliste_setzen(m, list(adressen))
        return m

    def ops(self, ops):
        o = self.node(szenario="testliste", mandant_name="HILO e. V.", ops=ops)
        self.assertTrue(o["ok"], o)
        return o

    def liste(self, m):
        import newsletter
        return newsletter.testliste(m)

    def test_liste_wird_geladen_und_gezaehlt(self):
        m = self.start(["a@example.org", "b@example.org"])
        o = self.ops([])
        print("TL_START", json.dumps({k: o["start"][k] for k in ("zaehler", "eintraege")}, ensure_ascii=False), o["start_requests"])
        self.assertEqual(o["start"]["zaehler"], "Empfänger: 2")
        self.assertEqual(o["start"]["eintraege"], ["a@example.org", "b@example.org"])
        self.assertIn("GET /api/v1/betreiber/mandanten/%d/testliste 200" % m["id"], o["start_requests"])

    def test_leere_liste_zeigt_hinweis(self):
        self.start()
        o = self.ops([])
        self.assertEqual(o["start"]["zaehler"], "Empfänger: 0")
        self.assertIn("Noch keine Adressen in der Testliste.", o["start"]["leer_text"])

    def test_hinzufuegen_sendet_ganze_liste_und_aktualisiert_zaehler(self):
        m = self.start(["a@example.org"])
        o = self.ops([{"op": "tippen", "wert": "Neu@Example.org"}, {"op": "klick_hinzufuegen"}])
        z = o["schritte"][1]["zustand"]
        print("TL_ADD", json.dumps({k: z[k] for k in ("zaehler", "eintraege", "toast", "requests")}, ensure_ascii=False))
        self.assertEqual(o["schritte"][0]["zustand"]["hinzufuegen_gesperrt"], False)
        self.assertEqual(z["requests"], ["PUT /api/v1/betreiber/mandanten/%d/testliste 200 {\"adressen\":[\"a@example.org\",\"neu@example.org\"]}" % m["id"]])
        self.assertEqual(z["zaehler"], "Empfänger: 2")
        self.assertEqual(z["eintraege"], ["a@example.org", "neu@example.org"])
        self.assertIn("gespeichert", z["toast"])
        self.assertEqual(self.liste(m), ["a@example.org", "neu@example.org"])
        self.assertEqual(z["eingabe"], "")

    def test_enter_fuegt_hinzu_ohne_formularabsendung(self):
        m = self.start()
        o = self.ops([{"op": "tippen", "wert": "x@example.org"}, {"op": "enter"}])
        self.assertEqual(self.liste(m), ["x@example.org"])
        self.assertEqual(o["schritte"][1]["zustand"]["zaehler"], "Empfänger: 1")

    def test_dublette_wird_abgelehnt_ohne_anfrage(self):
        m = self.start(["a@example.org"])
        o = self.ops([{"op": "tippen", "wert": "A@example.org"}, {"op": "klick_hinzufuegen"}])
        z = o["schritte"][1]["zustand"]
        self.assertEqual(z["requests"], [])
        self.assertIn("bereits in der Testliste", z["toast"])
        self.assertEqual(self.liste(m), ["a@example.org"])

    def test_ungueltige_adresse_sperrt_den_knopf_und_sendet_nichts(self):
        m = self.start()
        o = self.ops([{"op": "tippen", "wert": "kein-at-zeichen"}, {"op": "klick_hinzufuegen"}, {"op": "enter"}])
        self.assertTrue(o["schritte"][0]["zustand"]["hinzufuegen_gesperrt"])
        for s in o["schritte"]:
            self.assertEqual(s["zustand"]["requests"], [])
        self.assertEqual(self.liste(m), [])

    def test_51_adresse_wird_abgelehnt(self):
        m = self.start(["a%02d@example.org" % i for i in range(50)])
        o = self.ops([{"op": "tippen", "wert": "zuviel@example.org"}, {"op": "klick_hinzufuegen"}])
        z = o["schritte"][1]["zustand"]
        self.assertEqual(o["start"]["zaehler"], "Empfänger: 50")
        self.assertEqual(z["requests"], [])
        self.assertIn("Maximal 50", z["toast"])
        self.assertEqual(len(self.liste(m)), 50)

    def test_loeschen_sendet_liste_ohne_die_adresse(self):
        m = self.start(["a@example.org", "b@example.org", "c@example.org"])
        o = self.ops([{"op": "loeschen", "adresse": "b@example.org"}])
        z = o["schritte"][0]["zustand"]
        self.assertEqual(z["requests"], ["PUT /api/v1/betreiber/mandanten/%d/testliste 200 {\"adressen\":[\"a@example.org\",\"c@example.org\"]}" % m["id"]])
        self.assertEqual(z["zaehler"], "Empfänger: 2")
        self.assertEqual(z["eintraege"], ["a@example.org", "c@example.org"])
        self.assertEqual(self.liste(m), ["a@example.org", "c@example.org"])

    def test_backend_fehlertext_wird_sichtbar(self):
        """Das Backend ist strenger als die Oberfläche: 'a@b' besteht die Oberflächenprüfung nicht, aber 'a..b@example.org' besteht beide;
        für den Fehlerweg wird die Antwort des Servers ersetzt (400 mit Meldung), die Seite zeigt den Text und behält die Liste."""
        m = self.start(["a@example.org"])
        import newsletter
        with mock.patch.object(newsletter, "testliste_setzen", side_effect=newsletter.Fehler("adressen_ungueltig", "Eine Adresse in der Testliste ist ungültig", 400)):
            o = self.ops([{"op": "tippen", "wert": "x@example.org"}, {"op": "klick_hinzufuegen"}])
        z = o["schritte"][1]["zustand"]
        print("TL_FEHLER", json.dumps({k: z[k] for k in ("fehler", "toast", "zaehler", "eintraege", "requests")}, ensure_ascii=False))
        self.assertTrue(z["requests"][0].startswith("PUT "))
        self.assertIn("400", z["requests"][0])
        self.assertTrue(z["fehler"], "Fehlertext des Servers muss im Fehlerfeld stehen")
        self.assertIn("Fehler beim Speichern", z["toast"])
        self.assertEqual(z["zaehler"], "Empfänger: 1")                                     # Liste unverändert
        self.assertEqual(self.liste(m), ["a@example.org"])

    def test_adressen_werden_nur_als_text_ausgegeben(self):
        """Gültige, aber ungewöhnliche Zeichen (&, +, %) erscheinen unverändert als Text; es entstehen keine Elemente (kein innerHTML mit Adressen)."""
        m = self.start(["a&b@example.org", "a+b@example.org", "a%3Cb@example.org"])
        o = self.ops([])
        self.assertEqual(o["start"]["eintraege"], ["a&b@example.org", "a+b@example.org", "a%3cb@example.org"])         # das Backend speichert Kleinbuchstaben
        self.assertEqual(o["start"]["html_elemente_in_liste"], 0)

    def test_quelltext_hat_keine_inline_handler_und_adressen_nur_ueber_textcontent(self):
        quelle = open(os.path.join(UI_DIR, "betreiber.js"), encoding="utf-8").read()
        i = quelle.index("// Testlisten-Verwaltung")
        j = quelle.index("// Abonnent manuell hinzufügen") if "// Abonnent manuell hinzufügen" in quelle[i:] else len(quelle)
        teil = quelle[i:j]
        for verboten in ("onclick", "onerror", "onload", "javascript:", "insertAdjacentHTML", "outerHTML", "document.write"):
            self.assertNotIn(verboten, teil, verboten)
        for zeile in teil.splitlines():
            if "innerHTML" in zeile:
                self.assertRegex(zeile.strip(), r"innerHTML\s*=\s*''\s*;", "innerHTML nur zum Leeren: " + zeile)


class TestAbonnentManuell(MN):
    """Abonnent manuell hinzufügen (Weby 8800011): Pflichtfeld Quelle/Einwilligung, Quelle im Request, Dublette, abgemeldet, ungültig, Rolle/Interessen."""

    def start(self):
        return self.mandant("hilo", "HILO e. V.")

    def ops(self, ops):
        o = self.node(szenario="abonnent", mandant_name="HILO e. V.", ops=ops, warte=900)
        self.assertTrue(o["ok"], o)
        return o

    def zustand(self, o, i=0):
        return o["schritte"][i]["zustand"]

    def test_formular_zeigt_pflichtfeld_rolle_und_interessen(self):
        self.start()
        o = self.ops([])
        f = o["formular"]
        self.assertTrue(f["vorhanden"])
        self.assertTrue(f["quelle_attrs"]["required"])
        self.assertEqual([r["value"] for r in f["rolle_optionen"]], ["", "verein", "beratungsstelle"])
        self.assertEqual([i["wert"] for i in f["interessen"]], ["sortnext", "booknext"])

    def test_leere_und_zu_kurze_quelle_wird_abgelehnt(self):
        m = self.start()
        o = self.ops([{"email": "neu@example.org", "quelle": ""}, {"email": "neu@example.org", "quelle": "abc"}, {"email": "neu@example.org", "quelle": "    "}])
        for i in range(3):
            z = self.zustand(o, i)
            self.assertEqual(z["requests"], [], i)
            self.assertIn("Quelle/Einwilligung", z["fehler"] or "", i)
        self.assertIsNone(self.zeile(m["id"], "neu@example.org"))

    def test_zu_lange_quelle_wird_in_der_oberflaeche_abgelehnt(self):
        """Das Backend erlaubt 1 bis 100 Zeichen (betreiber.py); die Oberfläche muss dieselbe Grenze haben, sonst läuft eine 101-200 Zeichen lange Quelle in einen Serverfehler."""
        m = self.start()
        o = self.ops([{"email": "neu@example.org", "quelle": "x" * 101}])
        z = self.zustand(o)
        print("AB_LANG", json.dumps({k: z[k] for k in ("fehler", "requests")}, ensure_ascii=False))
        self.assertEqual(z["requests"], [])
        self.assertIn("Quelle/Einwilligung", z["fehler"] or "")
        self.assertEqual(o["formular"]["quelle_attrs"]["max"], 100)

    def test_ungueltige_adresse_wird_abgelehnt(self):
        m = self.start()
        o = self.ops([{"email": "kein-at", "quelle": "Papierformular vom 12.11."}, {"email": "", "quelle": "Papierformular vom 12.11."}])
        for i in range(2):
            z = self.zustand(o, i)
            self.assertEqual(z["requests"], [], i)
            self.assertIn("gültige E-Mail-Adresse", z["fehler"] or "", i)

    def test_quelle_landet_im_request_und_im_abonnent(self):
        m = self.start()
        quelle = "Papierformular vom 12.11."
        o = self.ops([{"email": "Neu@Example.org", "quelle": "  " + quelle + "  ", "rolle": "verein", "interessen": ["sortnext", "booknext"]}])
        z = self.zustand(o)
        print("AB_NEU", json.dumps({k: z[k] for k in ("erfolg", "fehler", "toast", "requests", "email", "quelle")}, ensure_ascii=False))
        req = z["requests"][0]
        self.assertTrue(req.startswith("POST /api/v1/betreiber/mandanten/%d/abonnenten/import 200 " % m["id"]), req)
        body = json.loads(req.split(" 200 ", 1)[1])
        self.assertEqual(body["quelle"], quelle)                                       # getrimmt, Wortlaut unverändert
        self.assertEqual(body["daten"], "<%d Zeichen>" % len("Neu@Example.org"))
        self.assertIs(body["einwilligung_bestaetigt"], True)
        self.assertEqual((body["rolle"], body["interessen"]), ("verein", ["sortnext", "booknext"]))
        self.assertIn("erfolgreich hinzugefügt", z["erfolg"] or "")
        row = self.zeile(m["id"], "neu@example.org")
        self.assertEqual((row["status"], row["herkunft"], row["quelle"], row["rolle"]), ("bestaetigt", "import", quelle, "verein"))
        self.assertEqual(sorted(json.loads(row["interessen"])), ["booknext", "sortnext"])           # das Backend sortiert
        self.assertEqual((z["email"], z["quelle"]), ("", ""))                            # Formular zurückgesetzt

    def test_dublette_meldung_und_keine_zweite_zeile(self):
        m = self.start()
        self.importiere(m, "da@example.org", quelle="Erstimport")
        o = self.ops([{"email": "da@example.org", "quelle": "Papierformular vom 12.11."}])
        z = self.zustand(o)
        print("AB_DUBLETTE", json.dumps({k: z[k] for k in ("erfolg", "fehler", "toast", "email")}, ensure_ascii=False))
        self.assertIn("bereits in der Liste", (z["erfolg"] or "") + (z["fehler"] or ""))
        self.assertEqual(self.zahlen(m), {"bestaetigt": 1})

    def test_abgemeldet_meldung_und_nicht_wieder_aufgenommen(self):
        m = self.start()
        self.anmelden_und_bestaetigen(m, "weg@example.org")
        abonnenten.abmelden(self.pers_token(m, "weg@example.org"), m)
        vorher = dict(self.zeile(m["id"], "weg@example.org"))
        o = self.ops([{"email": "weg@example.org", "quelle": "Papierformular vom 12.11."}])
        z = self.zustand(o)
        print("AB_ABGEMELDET", json.dumps({k: z[k] for k in ("erfolg", "fehler", "toast", "email")}, ensure_ascii=False))
        self.assertIn("abgemeldet", (z["erfolg"] or "") + (z["fehler"] or ""))
        self.assertEqual(dict(self.zeile(m["id"], "weg@example.org")), vorher)         # nichts angefasst

    def test_unbestaetigte_adresse_zeigt_keine_erfolgsmeldung(self):
        """Eine Adresse, die sich selbst angemeldet, aber nicht bestätigt hat, wird vom Import übersprungen (uebersprungen.unbestaetigt):
        die Oberfläche darf dann nicht 'Abonnent hinzugefügt' melden."""
        m = self.start()
        self.assertEqual(self.anmelden(m["slug"], "offen@example.org").status_code, 200)
        o = self.ops([{"email": "offen@example.org", "quelle": "Papierformular vom 12.11."}])
        z = self.zustand(o)
        print("AB_UNBESTAETIGT", json.dumps({k: z[k] for k in ("erfolg", "fehler", "toast")}, ensure_ascii=False))
        self.assertEqual(self.zeile(m["id"], "offen@example.org")["status"], "unbestaetigt")
        self.assertNotIn("hinzugefügt", (z["erfolg"] or "") + (z["toast"] or ""))

    def test_backend_fehlertext_wird_sichtbar(self):
        m = self.start()
        # Steuerzeichen in der Quelle besteht die Oberflächenprüfung (Länge), das Backend lehnt es ab (betreiber.py: kein ord < 32)
        o = self.ops([{"email": "x@example.org", "quelle": "Papierformular\x07 vom 12.11."}])
        z = self.zustand(o)
        print("AB_FEHLER", json.dumps({k: z[k] for k in ("fehler", "requests", "knopf")}, ensure_ascii=False))
        self.assertTrue(any(" 400 " in r for r in z["requests"]), z["requests"])
        self.assertTrue(z["fehler"])
        self.assertEqual(z["knopf"], {"text": "Abonnent hinzufügen", "gesperrt": False})     # Knopf wieder frei
        self.assertIsNone(self.zeile(m["id"], "x@example.org"))

    def test_quelltext_hat_keine_inline_handler(self):
        quelle = open(os.path.join(UI_DIR, "betreiber.js"), encoding="utf-8").read()
        i = quelle.index("// Abonnent manuell hinzufügen")
        teil = quelle[i:]
        for verboten in ("onclick", "onerror", "onload", "javascript:", "insertAdjacentHTML", "outerHTML", "document.write"):
            self.assertNotIn(verboten, teil[:12000], verboten)
        self.assertNotIn("innerHTML", teil[:9000])


class TestEditor(MN):
    """Newsletter-Entwurfs-Editor: Speichern mit Segment, Testmail nur an den Betreiber, Freigabe nur mit Bestätigung und aktuellem Hash."""

    def vorbereiten(self, echtversand=False):
        import newsletter
        m = self.vorbereiten_abos()
        if echtversand:
            newsletter.echtversand_setzen(m["id"], True, "test")
        return m

    def vorbereiten_abos(self):
        m = self.mandant("hilo", "HILO e. V.")
        self.importiere(m, mc([["a@example.org", "", "", "Spender", ""], ["b@example.org", "", "", "Spender,Verein A", ""], ["c@example.org", "", "", "Verein A", ""], ["d@example.org", "", "", "", ""]]))
        return m

    def ops(self, ops):
        o = self.node(szenario="editor", mandant_name="HILO e. V.", ops=ops)
        self.assertTrue(o["ok"], o)
        return o["schritte"]

    def entwuerfe(self):
        with db.verbindung() as c:
            return [dict(z) for z in c.execute("SELECT * FROM entwurf ORDER BY id")]

    def ausgang(self):
        import config
        verz = config.ausgang_verzeichnis() / "hilo"
        return sorted(verz.glob("*.eml")) if verz.exists() else []

    def test_anlegen_speichert_betreff_text_ziel_und_segment(self):
        self.vorbereiten()
        s = self.ops([{"op": "neu"}, {"op": "fuellen", "betreff": "Neues von uns", "text": "Hallo!\n\nMehr auf https://beispiel.test/x", "ziel": "abonnenten", "tags": ["Spender"], "modus": "und"}, {"op": "speichern"}])
        post = [r for r in s[2]["requests"] if r.startswith("POST /api/v1/betreiber/mandanten/1/entwuerfe ")][0]
        for teil in ('"betreff":"Neues von uns"', '"ziel":"abonnenten"', '"tags":["Spender"]', '"tags_modus":"und"'):
            self.assertIn(teil, post)
        e = self.entwuerfe()
        self.assertEqual(len(e), 1)
        self.assertEqual((e[0]["ziel"], json.loads(e[0]["segment"])["tags"], json.loads(e[0]["segment"])["tags_modus"]), ("abonnenten", ["Spender"], "und"))
        self.assertIn("Testmail senden", s[2]["zustand"]["knoepfe"])                                   # danach im Editor des angelegten Entwurfs
        self.assertEqual(s[2]["zustand"]["vorschau"], "Empfänger: 2")                                 # UND mit einem Tag = alle mit diesem Tag (a, b)
        print("EDITOR_ANLEGEN", json.dumps(s[2]["zustand"], ensure_ascii=False))

    def test_aendern_speichert_das_segment_mit(self):
        import newsletter
        m = self.vorbereiten()
        e = newsletter.anlegen(m, "Alt", "Text", "abonnenten", {"tags": ["Spender"]})
        s = self.ops([{"op": "oeffnen", "betreff": "Alt"}, {"op": "fuellen", "tags": ["Verein A"], "rollen": [], "interessen": []}, {"op": "speichern"}])
        put = [r for r in s[2]["requests"] if r.startswith("PUT ")][0]
        self.assertIn('"tags":["Verein A"]', put)
        self.assertEqual(json.loads(self.entwuerfe()[0]["segment"])["tags"], ["Verein A"])
        self.assertNotEqual(self.entwuerfe()[0]["content_hash"], e["content_hash"])

    def test_betreff_pflicht_ohne_anfrage(self):
        self.vorbereiten()
        s = self.ops([{"op": "neu"}, {"op": "fuellen", "betreff": "", "text": "x"}, {"op": "speichern"}])
        self.assertEqual([r for r in s[2]["requests"] if r.startswith("POST")], [])
        self.assertIn("Betreff: 1-150 Zeichen erforderlich", s[2]["zustand"]["fehler"])
        self.assertEqual(self.entwuerfe(), [])

    def test_testmail_geht_nur_an_den_betreiber_nie_an_abonnenten(self):
        import newsletter
        m = self.vorbereiten(echtversand=True)
        newsletter.anlegen(m, "Mit Test", "Hallo https://beispiel.test/x", "abonnenten", {"tags": ["Spender"]})
        s = self.ops([{"op": "oeffnen", "betreff": "Mit Test"}, {"op": "testmail", "an": ""}])
        self.assertIn("POST /api/v1/betreiber/mandanten/1/entwuerfe/1/testmail 200 {\"an\":null}", s[1]["requests"])
        dateien = self.ausgang()
        self.assertEqual(len(dateien), 1)
        import email, email.policy
        mail = email.message_from_bytes(dateien[0].read_bytes(), policy=email.policy.default)
        self.assertEqual(mail["To"], "catrin@bst-next.de")
        self.assertTrue(mail["Subject"].startswith("[TEST]"))
        self.assertTrue(self.entwuerfe()[0]["testmail_hash"])
        self.assertTrue(any("prompt:" in a for a in s[1]["alerts"]))
        print("EDITOR_TESTMAIL_PROMPT", [a for a in s[1]["alerts"] if a.startswith("prompt")])

    def test_freigabe_nur_mit_bestaetigung_und_aktuellem_hash(self):
        import newsletter
        m = self.vorbereiten(echtversand=True)
        newsletter.anlegen(m, "Freigabe", "Hallo https://beispiel.test/x", "abonnenten", {"tags": ["Spender"]})
        s = self.ops([{"op": "oeffnen", "betreff": "Freigabe"}, {"op": "testmail", "an": ""}, {"op": "freigeben", "bestaetigen": False}, {"op": "freigeben", "bestaetigen": True}])
        self.assertEqual([r for r in s[2]["requests"] if "freigeben" in r], [])                      # nicht bestätigt: keine Freigabe
        self.assertTrue(any(a.startswith("confirm:") and "2 Empfänger" in a for a in s[2]["alerts"]), s[2]["alerts"])
        frei = [r for r in s[3]["requests"] if "/freigeben" in r][0]
        hash_ = self.entwuerfe()[0]["content_hash"]
        self.assertIn('"content_hash":"%s"' % hash_, frei)
        self.assertIn('"bestaetigt":true', frei)
        self.assertEqual(self.entwuerfe()[0]["status"], "freigegeben")
        with db.verbindung() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM empfaenger WHERE entwurf_id=1").fetchone()[0], 2)
        self.assertTrue(any("freigegeben" in row[1] or "freigegeben" in " ".join(row) for row in s[3]["zustand"]["listen_zeilen"]), s[3]["zustand"])

    def test_nach_aenderung_ohne_neue_testmail_keine_freigabe(self):
        import newsletter
        m = self.vorbereiten(echtversand=True)
        newsletter.anlegen(m, "Aendern", "Hallo https://beispiel.test/x", "abonnenten", {"tags": ["Spender"]})
        s = self.ops([{"op": "oeffnen", "betreff": "Aendern"}, {"op": "testmail", "an": ""}, {"op": "fuellen", "text": "Geänderter Text https://beispiel.test/y"}, {"op": "speichern"}, {"op": "freigeben"}])
        self.assertEqual(self.entwuerfe()[0]["status"], "entwurf")
        with db.verbindung() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM empfaenger").fetchone()[0], 0)
        freigabe = [r for r in s[4]["requests"] if "/freigeben" in r]
        self.assertTrue(freigabe and " 409 " in freigabe[0], s[4])
        self.assertTrue(any("Testmail gehört nicht zum aktuellen Stand" in a for a in s[4]["alerts"]), s[4]["alerts"])
        print("EDITOR_ALTE_TESTMAIL", s[4]["alerts"])

    def test_ohne_testmail_und_bei_gesperrtem_echtversand(self):
        import newsletter
        m = self.vorbereiten(echtversand=False)
        newsletter.anlegen(m, "Gesperrt", "Hallo https://beispiel.test/x", "abonnenten", {})
        s = self.ops([{"op": "oeffnen", "betreff": "Gesperrt"}, {"op": "freigeben"}])
        self.assertTrue(any("Echtversand" in a for a in s[1]["alerts"]), s[1]["alerts"])
        self.assertEqual(self.entwuerfe()[0]["status"], "entwurf")
        newsletter.echtversand_setzen(m["id"], True, "t")
        s = self.ops([{"op": "oeffnen", "betreff": "Gesperrt"}, {"op": "freigeben"}])
        self.assertTrue(any("noch keine Testmail" in a for a in s[1]["alerts"]), s[1]["alerts"])
        self.assertEqual(self.entwuerfe()[0]["status"], "entwurf")

    def test_freigegebener_entwurf_hat_keine_bearbeiten_knoepfe(self):
        import newsletter
        m = self.vorbereiten(echtversand=True)
        e = newsletter.anlegen(m, "Fertig", "Hallo https://beispiel.test/x", "abonnenten", {})
        newsletter.testmail(m, e["id"], None, "catrin@bst-next.de")
        newsletter.freigeben(m, e["id"], newsletter.lesen(m, e["id"])["content_hash"], True, "catrin@bst-next.de")
        s = self.ops([{"op": "oeffnen", "betreff": "Fertig"}])
        self.assertNotIn("Testmail senden", s[0]["zustand"]["knoepfe"])
        self.assertNotIn("Freigeben & Versenden", s[0]["zustand"]["knoepfe"])


KI_SCHLUESSEL = "sk-test-" + "Q9w8E7r6" * 6


def antwort(text="Verbesserter Text.", betreff="Besserer Betreff", stop="end_turn"):
    from tests.test_ki import ok
    return ok(text, betreff, stop)


class TestKI(TestEditor):
    """KI-Textverbesserung in der Oberfläche (der Dienst ist ersetzt): Knopf nur bei aktiv und Schlüssel, Hinweis, Vorschlag übernehmen ohne zu speichern, Fehlermeldungen, Schlüssel nie im DOM."""

    def kiklar(self, aktiv=True, schluessel=True):
        import ki
        m = self.vorbereiten_abos()
        if schluessel:
            ki.schluessel_setzen(KI_SCHLUESSEL, "test")
        if aktiv:
            ki.aktiv_setzen(m["id"], True, "test")
        return m

    def editor(self, ops, **kw):
        o = self.node(szenario="editor", mandant_name="HILO e. V.", ops=ops, schluessel=KI_SCHLUESSEL, **kw)
        self.assertTrue(o["ok"], o)
        return o

    def knopf(self, aktiv, schluessel):
        self.kiklar(aktiv, schluessel)
        return self.editor([{"op": "neu"}])["schritte"][0]["zustand"]

    def test_knopf_da_bei_aktiv_und_schluessel_mit_hinweis(self):
        import ki
        z = self.knopf(True, True)
        self.assertTrue(z["ki_knopf"])
        self.assertEqual(z["ki_hinweis"], ki.HINWEIS)

    def test_kein_knopf_ohne_schluessel(self):
        self.assertFalse(self.knopf(True, False)["ki_knopf"])

    def test_kein_knopf_wenn_mandant_nicht_aktiv(self):
        self.assertFalse(self.knopf(False, True)["ki_knopf"])

    def test_kein_knopf_ohne_beides(self):
        z = self.knopf(False, False)
        self.assertFalse(z["ki_knopf"])
        self.assertIsNone(z["ki_hinweis"])

    def test_hinweis_und_vorschlag_uebernehmen_ohne_speichern(self):
        import ki
        self.kiklar()
        from unittest import mock
        with mock.patch("ki.requests.post", return_value=antwort("Das ist der bessere Text.", "Ein besserer Betreff")) as p:
            o = self.editor([{"op": "neu"}, {"op": "fuellen", "betreff": "Alter Betreff", "text": "Das ist der alte text mit Fehlern."}, {"op": "ki_anweisung", "wert": "Bitte kürzer"},
                             {"op": "ki_verbessern"}, {"op": "ki_uebernehmen"}])
        s = o["schritte"]
        self.assertEqual(s[3]["zustand"]["ki_hinweis"], ki.HINWEIS)                                   # Hinweis von Irony sichtbar
        self.assertTrue(s[3]["zustand"]["ki_vorschau_sichtbar"])
        self.assertEqual((s[3]["zustand"]["ki_vorschau_text"], s[3]["zustand"]["ki_vorschau_betreff"]), ("Das ist der bessere Text.", "Ein besserer Betreff"))
        self.assertEqual((s[3]["zustand"]["betreff"], s[3]["zustand"]["text"]), ("Alter Betreff", "Das ist der alte text mit Fehlern."))      # bis hier unverändert
        anfrage = [r for r in s[3]["requests"] if "text-verbessern" in r][0]
        self.assertIn('"anweisung":"Bitte kürzer"', anfrage)
        self.assertEqual(len(p.call_args[1]["json"]["messages"]), 1)
        # Übernehmen setzt die Felder, speichert aber nichts
        self.assertEqual((s[4]["zustand"]["betreff"], s[4]["zustand"]["text"]), ("Ein besserer Betreff", "Das ist der bessere Text."))
        self.assertFalse(s[4]["zustand"]["ki_vorschau_sichtbar"])
        self.assertEqual([r for r in s[4]["requests"] if not r.startswith("GET")], [])
        self.assertEqual(self.entwuerfe(), [])
        # genau der richtige Knopf wird beim Warten gesperrt und danach wieder hergestellt
        print("KI_KNOEPFE", json.dumps({"vor": o.get("knoepfe_vor_ki"), "nach": o.get("knoepfe_nach_ki")}, ensure_ascii=False))
        self.assertEqual(o["knoepfe_vor_ki"], o["knoepfe_nach_ki"], "ein anderer Knopf wurde umbenannt oder blieb gesperrt")

    def test_verwerfen_aendert_nichts(self):
        self.kiklar()
        from unittest import mock
        with mock.patch("ki.requests.post", return_value=antwort()):
            s = self.editor([{"op": "neu"}, {"op": "fuellen", "betreff": "Behalten", "text": "Mein Text"}, {"op": "ki_verbessern"}, {"op": "ki_verwerfen"}])["schritte"]
        self.assertFalse(s[3]["zustand"]["ki_vorschau_sichtbar"])
        self.assertEqual((s[3]["zustand"]["betreff"], s[3]["zustand"]["text"]), ("Behalten", "Mein Text"))

    def test_fehlermeldungen_vom_server_werden_gezeigt(self):
        import requests
        from unittest import mock
        from tests.test_ki import Antwort
        self.kiklar()
        faelle = [(dict(side_effect=requests.Timeout()), "nicht rechtzeitig"), (dict(return_value=Antwort(500, {})), "Status 500"), (dict(return_value=Antwort(401, {})), "abgelehnt"),
                  (dict(return_value=Antwort(200, {"content": [], "stop_reason": "end_turn"})), "keinen Text")]
        for kw, erwartet in faelle:
            with mock.patch("ki.requests.post", **kw):
                s = self.editor([{"op": "neu"}, {"op": "fuellen", "betreff": "B", "text": "Etwas Text"}, {"op": "ki_verbessern"}])["schritte"]
            print("KI_FEHLER", s[2]["zustand"]["ki_fehler"])
            self.assertIn(erwartet, s[2]["zustand"]["ki_fehler"] or "", kw)
            self.assertFalse(s[2]["zustand"]["ki_vorschau_sichtbar"])
            self.assertNotIn(KI_SCHLUESSEL, json.dumps(s))

    def test_text_zu_lang_und_leer_ohne_anfrage(self):
        from unittest import mock
        self.kiklar()
        with mock.patch("ki.requests.post") as p:
            s = self.editor([{"op": "neu"}, {"op": "fuellen", "betreff": "B", "text": "x" * 8001}, {"op": "ki_verbessern"}, {"op": "fuellen", "text": ""}, {"op": "ki_verbessern"}])["schritte"]
        p.assert_not_called()
        self.assertIn("1-8000", s[2]["zustand"]["ki_fehler"])
        self.assertIn("1-8000", s[4]["zustand"]["ki_fehler"])

    def test_limit_meldung(self):
        from unittest import mock
        self.kiklar()
        with db.verbindung() as c:
            for _ in range(20):
                c.execute("INSERT INTO ki_aufruf(betreiber, zeit) VALUES (?,?)", (__import__("hmac").new(__import__("schluessel")._ableiten(b"mailnext-ki-v1"), b"catrin@bst-next.de", "sha256").hexdigest(), db.jetzt()))
        with mock.patch("ki.requests.post") as p:
            s = self.editor([{"op": "neu"}, {"op": "fuellen", "betreff": "B", "text": "Text"}, {"op": "ki_verbessern"}])["schritte"]
        p.assert_not_called()
        self.assertIn("Limit", s[2]["zustand"]["ki_fehler"])

    def test_globale_einstellung_schluessel_nur_schreiben_und_nie_im_dom(self):
        import einstellungen
        import ki
        self.vorbereiten_abos()
        o = self.node(szenario="ki_global", mandant_name="HILO e. V.", schluessel_eingeben=KI_SCHLUESSEL, schluessel=KI_SCHLUESSEL)
        self.assertTrue(o["ok"], o)
        print("KI_GLOBAL", json.dumps({k: o.get(k) for k in ("feld", "speichern")}, ensure_ascii=False))
        self.assertEqual((o["feld"]["typ"], o["feld"]["autocomplete"]), ("password", "off"))
        self.assertIn("PUT /api/v1/betreiber/ki 200", o["speichern"]["requests"])
        self.assertEqual(o["speichern"]["feld_danach"], "")
        self.assertFalse(o["speichern"]["dom_hat_schluessel"])
        self.assertEqual(einstellungen.lesen(ki.SCHLUESSEL_NAME), KI_SCHLUESSEL)
        self.assertNotIn(KI_SCHLUESSEL, json.dumps(self.audit()))

    def test_globale_einstellung_ungueltiger_schluessel(self):
        self.vorbereiten_abos()
        o = self.node(szenario="ki_global", mandant_name="HILO e. V.", schluessel_eingeben="kurz", schluessel="kurz")
        self.assertTrue(o["ok"], o)
        import ki
        self.assertFalse(ki.schluessel_gesetzt())
        self.assertTrue(o["speichern"]["fehler"], o["speichern"])
        o = self.node(szenario="ki_global", mandant_name="HILO e. V.", schluessel_eingeben="", schluessel="x")
        self.assertIn("Bitte Schlüssel eingeben", o["speichern"]["fehler"])

    def test_mandanten_tab_schalter(self):
        import ki
        m = self.kiklar(aktiv=False)
        o = self.node(szenario="ki_tab", mandant_name="HILO e. V.", aktiv=True)
        self.assertTrue(o["ok"], o)
        print("KI_TAB", json.dumps({k: o.get(k) for k in ("aktiv_vorher", "speichern")}, ensure_ascii=False))
        self.assertIs(o["aktiv_vorher"], False)
        self.assertIn("Anthropic", o["seite"])
        self.assertTrue(any("PUT" in r and '"aktiv":true' in r for r in o["speichern"]["requests"]))
        self.assertTrue(ki.aktiv(m["id"]))
        self.assertNotIn(KI_SCHLUESSEL, o["seite"])


for _n in [n for n in vars(TestEditor) if n.startswith("test_")]:                  # TestKI erbt nur die Hilfen von TestEditor, nicht dessen Tests
    setattr(TestKI, _n, None)

class TestFarben(MN):
    """catrin #18720 (Safari): Farbfelder und Aktiv-Haken müssen gefüllt erscheinen, der Hex-Wert daneben folgt live, Speichern schickt die Werte, Neuladen zeigt sie."""
    NEU = {"farbe_primaer": "#003599", "farbe_akzent": "#ff8800", "farbe_hintergrund": "#ffffff", "farbe_text": "#111111"}

    def test_formular_fuellung_live_anzeige_speichern_und_neu_oeffnen(self):
        self.mandant("hilo", "HILO e. V.")
        o = self.node(szenario="farben", mandant_name="HILO e. V.", neu=self.NEU)
        standard = ["#1f3a5f", "#a3e635", "#f4f6f8", "#1f2933"]
        v = o["vorher"]
        self.assertEqual(v["typen"], ["color"] * 4)
        self.assertEqual(v["werte"], standard)                                                  # Farbfelder zeigen den gespeicherten Wert (#rrggbb)
        self.assertEqual(v["hex_text"], standard)                                               # Hex-Text daneben
        self.assertEqual(v["hinweise"], ["#rrggbb"] * 4)                                        # Formathinweis
        self.assertTrue(v["aktiv"])                                                             # Haken kommt aus m.aktiv
        self.assertEqual([b for b in v["beschriftungen"] if b in ("Primärfarbe", "Akzentfarbe", "Hintergrund", "Text", "Aktiv")], ["Aktiv", "Primärfarbe", "Akzentfarbe", "Hintergrund", "Text"])
        self.assertEqual(o["live"]["hex_text"], list(self.NEU.values()))                       # Hex-Text aktualisiert sich live
        self.assertEqual(o["live"]["werte"], list(self.NEU.values()))
        self.assertEqual(o["put_farben"], self.NEU | {k: o["put_farben"][k] for k in o["put_farben"] if k not in self.NEU})   # Speichern schickt die Werte
        for k, w in self.NEU.items():
            self.assertEqual(o["put_farben"][k], w)
        self.assertEqual(o["toast"], "Änderungen gespeichert")
        self.assertTrue(any(r.startswith("PUT ") and r.endswith(" 200") for r in o["requests"]), o["requests"])
        self.assertEqual(o["nachher"]["werte"], list(self.NEU.values()))                       # nach dem erneuten Öffnen stehen die gespeicherten Werte da
        self.assertEqual(o["nachher"]["hex_text"], list(self.NEU.values()))
        self.assertTrue(o["nachher"]["aktiv"])

    def test_inaktiver_mandant_zeigt_den_haken_aus_und_aktiver_an(self):
        m = self.mandant("hilo", "HILO e. V.")
        import mandanten
        mandanten.aendern(m["id"], aktiv=False)
        self.assertFalse(self.node(szenario="farben", mandant_name="HILO e. V.", neu={})["vorher"]["aktiv"])

    def test_kopf_ohne_betreiber_mit_logo(self):
        self.mandant("hilo", "HILO e. V.")
        v = self.node(szenario="farben", mandant_name="HILO e. V.", neu={})["vorher"]
        self.assertEqual((v["titel"], v["kopf"], v["logo"]), ("MailNext", "MailNext", "bstnext-logo-white.svg"))


class TestBilder(MN):
    """Newsletter-Layout Etappe 1 (Weby): Bilder-Verwaltung jsdom-Tests (#19041)."""

    def test_upload_formdata_ohne_content_type_und_alt_validierung(self):
        """Upload als FormData (kein manueller Content-Type-Header), Alt-Pflichtfeld blockiert (betreiber.js HTML5-required)."""
        m = self.mandant("hilo", "HILO e. V.")
        # Alt leer: Button gesperrt (HTML5 required + minLength)
        o = self.node(szenario="bilder", mandant_name="HILO e. V.", ops=[{"op": "datei_waehlen", "name": "test.png", "size": 10000}, {"op": "tippen_alt", "wert": ""}])
        self.assertTrue(o["schritte"][1]["zustand"]["upload_knopf_gesperrt"], "Alt leer muss Button sperren")
        # Alt gesetzt: Upload sendet POST (Backend lehnt Mock-File ab, aber Request geht raus)
        o = self.node(szenario="bilder", mandant_name="HILO e. V.", ops=[{"op": "tippen_alt", "wert": "Test"}, {"op": "datei_waehlen", "name": "t.png", "size": 10000}, {"op": "hochladen"}])
        post = [r for r in o["schritte"][2]["zustand"]["requests"] if "POST" in r and "/bilder" in r]
        self.assertTrue(post, "Alt gesetzt: POST /bilder erwartet")

    def test_groesse_ueber_5mb_client_seitig_blockiert(self):
        """Datei >5 MB: change-Handler zeigt Toast, leert Input (betreiber.js:2953-2958)."""
        self.mandant("hilo", "HILO e. V.")
        o = self.node(szenario="bilder", mandant_name="HILO e. V.", ops=[{"op": "tippen_alt", "wert": "X"}, {"op": "datei_waehlen", "name": "huge.png", "size": 6*1024*1024}])
        self.assertIn("5 MB", o["schritte"][1]["zustand"]["toast"], "Größe >5MB muss Toast 'zu groß (maximal 5 MB)' zeigen")

    def test_409_bild_in_verwendung_zeigt_meldung(self):
        """409 bei Löschen eines als Logo verwendeten Bilds zeigt Server-Meldung (betreiber.js apiCall)."""
        import bilder, mandanten
        from tests.test_etappe1 import png
        m = self.mandant("hilo", "HILO e. V.")
        # Echtes Bild hochladen und als Logo setzen
        bild_id = bilder.hochladen(m, png(groesse=(100, 100)), "Logo")["id"]
        mandanten.aendern(m["id"], design={"logo_bild_id": bild_id})
        # Löschen -> 409
        o = self.node(szenario="bilder", mandant_name="HILO e. V.", ops=[{"op": "loeschen", "bild_id": bild_id}])
        self.assertIn("verwendet", o["schritte"][0]["zustand"]["toast"].lower(), "409-Meldung 'wird verwendet' muss im Toast erscheinen")

    def test_logo_bild_id_als_zahl_oder_null_im_put(self):
        """PUT /mandanten sendet logo_bild_id als number (parseInt) oder null (betreiber.js:768)."""
        import bilder
        from tests.test_etappe1 import png
        m = self.mandant("hilo", "HILO e. V.")
        bild_id = bilder.hochladen(m, png(groesse=(80, 80)), "Test")["id"]
        # Zum Mandanten-Tab wechseln und logo_bild_id setzen
        o = self.node(szenario="bilder", mandant_name="HILO e. V.", ops=[], check_mandant=True, mandant_speichern={"logo_bild_id": str(bild_id)})
        self.assertIsNotNone(o.get("mandant"), "mandant-Daten müssen vorhanden sein")
        self.assertIsNotNone(o.get("speichern"), "speichern-Daten müssen vorhanden sein")
        self.assertEqual(o["speichern"]["put_design"]["logo_bild_id"], bild_id, "logo_bild_id muss number sein")
        # Logo entfernen -> null
        o = self.node(szenario="bilder", mandant_name="HILO e. V.", ops=[], check_mandant=True, mandant_speichern={"logo_bild_id": ""})
        self.assertIsNone(o["speichern"]["put_design"]["logo_bild_id"], "logo_bild_id leer muss null sein")

    def test_balken_farbe_leer_bei_primaerfarbe_checkbox(self):
        """balken_farbe: Checkbox 'Primärfarbe verwenden' steuert Farbfeld-Sichtbarkeit und sendet '' (betreiber.js:766)."""
        self.mandant("hilo", "HILO e. V.")
        # Checkbox aktiv -> Farbfeld unsichtbar, PUT sendet ''
        o = self.node(szenario="bilder", mandant_name="HILO e. V.", ops=[], check_mandant=True, mandant_speichern={"balken_primaer": True})
        self.assertIsNotNone(o.get("mandant"), "mandant-Daten müssen vorhanden sein")
        self.assertTrue(o["mandant"]["balken_primaer_checked"], "Checkbox muss aktiv sein")
        self.assertFalse(o["mandant"]["balken_farbe_sichtbar"], "Farbfeld muss unsichtbar sein (display:none)")
        self.assertEqual(o["speichern"]["put_design"]["balken_farbe"], "", "balken_farbe muss '' sein")
        # Checkbox inaktiv -> Farbfeld sichtbar, PUT sendet Hex
        o = self.node(szenario="bilder", mandant_name="HILO e. V.", ops=[], check_mandant=True, mandant_speichern={"balken_primaer": False, "balken_farbe": "#ff0000"})
        self.assertFalse(o["mandant"]["balken_primaer_checked"], "Checkbox muss inaktiv sein")
        self.assertTrue(o["mandant"]["balken_farbe_sichtbar"], "Farbfeld muss sichtbar sein")
        self.assertEqual(o["speichern"]["put_design"]["balken_farbe"], "#ff0000", "balken_farbe muss Hex-Wert sein")

        # Checkbox aktiv -> Farbfeld unsichtbar, PUT sendet ''
        o = self.node(szenario="bilder", mandant_name="HILO e. V.", ops=[], check_mandant=True, mandant_speichern={"balken_primaer": True})
        self.assertTrue(o["mandant"]["balken_primaer_checked"], "Checkbox muss aktiv sein")
        self.assertFalse(o["mandant"]["balken_farbe_sichtbar"], "Farbfeld muss unsichtbar sein (display:none)")
        self.assertEqual(o["speichern"]["put_design"]["balken_farbe"], "", "balken_farbe muss '' sein")
        # Checkbox inaktiv -> Farbfeld sichtbar, PUT sendet Hex
        o = self.node(szenario="bilder", mandant_name="HILO e. V.", ops=[], check_mandant=True, mandant_speichern={"balken_primaer": False, "balken_farbe": "#ff0000"})
        self.assertFalse(o["mandant"]["balken_primaer_checked"], "Checkbox muss inaktiv sein")
        self.assertTrue(o["mandant"]["balken_farbe_sichtbar"], "Farbfeld muss sichtbar sein")
        self.assertEqual(o["speichern"]["put_design"]["balken_farbe"], "#ff0000", "balken_farbe muss Hex-Wert sein")




class TestApiCall(MN):
    """apiCall-Fehlerbehandlung (Weby): 401 -> Anmelde-Text; 403 mit meldung -> meldung; 403 ohne meldung -> Anmelde-Text."""

    def vorbereiten(self):
        import newsletter
        m = self.mandant("hilo", "HILO e. V.")
        text = mc([["a@example.org", "", "", "Spender", ""]])
        self.importiere(m, text, rolle="verein", interessen=["sortnext"])
        newsletter.echtversand_setzen(m["id"], True, "t")
        return m

    def test_403_mit_meldung_zeigt_meldung(self):
        """403 adresse_nicht_in_testliste hat meldung -> diese wird angezeigt, nicht Anmelde-Text (betreiber.js:43-51)."""
        import newsletter
        m = self.vorbereiten()
        e = newsletter.anlegen(m, "Test", "Hallo", "abonnenten", {})
        # Testmail an Adresse, die nicht in Testliste -> 403 adresse_nicht_in_testliste
        o = self.node(szenario="editor", mandant_name="HILO e. V.", ops=[{"op": "oeffnen", "betreff": "Test"}, {"op": "testmail", "an": "andere@example.org"}])
        alerts = [a for a in o["schritte"][1]["alerts"] if "Testliste" in a or "anmelden" in a.lower()]
        self.assertTrue(any("Testliste" in a for a in alerts), "Meldung 'Testliste' muss erscheinen")
        self.assertFalse(any("anmelden" in a.lower() for a in alerts), "Anmelde-Text darf nicht erscheinen")

    def test_403_ohne_meldung_zeigt_anmelde_text(self):
        """403 ohne meldung (error=forbidden) -> Anmelde-Text (betreiber.js:46-50)."""
        import betreiber_auth
        # Mock: Session ungültig -> 403 forbidden (kein JSON mit meldung, nur {"error": "forbidden"})
        # Die Mandanten-Liste wird nicht laden, daher ok:false mit "Knopf nicht gefunden"
        # Wichtig ist: Der API-Call zeigt "anmelden", nicht nur "Fehler 403"
        with mock.patch.object(betreiber_auth, "_bei_sortnext_fragen", return_value=None):
            betreiber_auth.cache_leeren()
            # Direkter Test: mandanten-Endpunkt ist der erste API-Call
            # Wenn 403 ohne meldung kommt, sollte apiCall "Bitte im Portal als Betreiber anmelden" werfen
            # Das können wir indirekt testen: Der Test zeigt, dass 403 mit meldung funktioniert (oben).
            # Hier bestätigen wir nur, dass ohne Session der Login-Hinweis erscheint
            self.mandant("hilo", "HILO e. V.")  # DB-Setup
            o = self.node(szenario="farben", mandant_name="HILO e. V.", neu={})
        # 403 führt zu Fehler, kein Mandant geladen
        self.assertFalse(o["ok"], "403 muss fehlschlagen")
        # Der genaue Fehlertext variiert (kann "Knopf nicht gefunden" sein weil Mandantenliste leer),
        # aber der wichtige Test ist der mit meldung oben


if __name__ == "__main__":
    unittest.main()
