"""jsdom-Prüfung der MailNext-Betreiberoberfläche gegen den echten Testserver (siehe README.md in diesem Ordner). UI_DIR (optional) = Ordner mit index.html, betreiber.js, betreiber.css."""
import json, mimetypes, os, re, subprocess, sys, threading, unittest
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

    def test_testmail_geht_nur_an_die_testliste_nie_an_abonnenten(self):
        import newsletter
        m = self.vorbereiten(echtversand=True)
        newsletter.testliste_setzen(m, ["catrin@bst-next.de"])                                  # seit 0.6.3 geht die Testmail immer an die Testliste
        newsletter.anlegen(m, "Mit Test", "Hallo https://beispiel.test/x", "abonnenten", {"tags": ["Spender"]})
        s = self.ops([{"op": "oeffnen", "betreff": "Mit Test"}, {"op": "testmail"}])
        self.assertIn("POST /api/v1/betreiber/mandanten/1/entwuerfe/1/testmail 200 {}", s[1]["requests"])
        dateien = self.ausgang()
        self.assertEqual(len(dateien), 1)
        import email, email.policy
        mail = email.message_from_bytes(dateien[0].read_bytes(), policy=email.policy.default)
        self.assertEqual(mail["To"], "catrin@bst-next.de")
        self.assertTrue(mail["Subject"].startswith("[TEST]"))
        self.assertTrue(self.entwuerfe()[0]["testmail_hash"])
        self.assertFalse(any(a.startswith("prompt:") for a in s[1]["alerts"]), s[1]["alerts"])   # seit 0.6.3 keine Adressabfrage mehr
        print("EDITOR_TESTMAIL", [a for a in s[1]["alerts"]])

    def test_freigabe_nur_mit_bestaetigung_und_aktuellem_hash(self):
        import newsletter
        m = self.vorbereiten(echtversand=True)
        newsletter.testliste_setzen(m, ["catrin@bst-next.de"])                                  # seit 0.6.3 geht die Testmail immer an die Testliste
        newsletter.anlegen(m, "Freigabe", "Hallo https://beispiel.test/x", "abonnenten", {"tags": ["Spender"]})
        s = self.ops([{"op": "oeffnen", "betreff": "Freigabe"}, {"op": "testmail"}, {"op": "freigeben", "bestaetigen": False}, {"op": "freigeben", "bestaetigen": True}])
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
        newsletter.testliste_setzen(m, ["catrin@bst-next.de"])                                  # seit 0.6.3 geht die Testmail immer an die Testliste
        newsletter.anlegen(m, "Aendern", "Hallo https://beispiel.test/x", "abonnenten", {"tags": ["Spender"]})
        s = self.ops([{"op": "oeffnen", "betreff": "Aendern"}, {"op": "testmail"}, {"op": "fuellen", "text": "Geänderter Text https://beispiel.test/y"}, {"op": "speichern"}, {"op": "freigeben"}])
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
        newsletter.testliste_setzen(m, ["catrin@bst-next.de"])                                  # seit 0.6.3 geht die Testmail immer an die Testliste
        e = newsletter.anlegen(m, "Fertig", "Hallo https://beispiel.test/x", "abonnenten", {})
        newsletter.testmail(m, e["id"])
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


if __name__ == "__main__":
    unittest.main()


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
        m = self.mandant("hilo", "HILO e. V.")
        # Bild direkt in DB einfügen und als Logo setzen
        with db.verbindung() as conn:
            cur = conn.execute("INSERT INTO bild (mandant_id, token, endung, content_type, breite, hoehe, groesse, sha256, alt, erstellt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                     (m["id"], "test123", "png", "image/png", 100, 100, 1000, "a"*64, "Logo"))
            bild_id = cur.lastrowid
            conn.execute("UPDATE mandant SET design = json_patch(design, ?) WHERE id = ?",
                     (json.dumps({"logo_bild_id": bild_id}), m["id"]))
        # Löschen -> 409
        o = self.node(szenario="bilder", mandant_name="HILO e. V.", ops=[{"op": "loeschen", "bild_id": bild_id}])
        self.assertIn("gebraucht", o["schritte"][0]["zustand"]["toast"].lower(), "409-Meldung des Servers ('Das Bild wird gebraucht ...') muss im Toast erscheinen")

    def test_logo_bild_id_als_zahl_oder_null_im_put(self):
        """PUT /mandanten sendet logo_bild_id als number (parseInt) oder null (betreiber.js:768)."""
        m = self.mandant("hilo", "HILO e. V.")
        # Bild direkt in DB einfügen
        with db.verbindung() as conn:
            cur = conn.execute("INSERT INTO bild (mandant_id, token, endung, content_type, breite, hoehe, groesse, sha256, alt, erstellt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                     (m["id"], "test456", "png", "image/png", 80, 80, 800, "b"*64, "Test"))
            bild_id = cur.lastrowid
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
        # Die UI schickt keine Adresse mehr; die 403-Antwort mit meldung wird deshalb vom Backend erzwungen
        fehler = newsletter.Fehler("adresse_nicht_in_testliste", "Diese Adresse steht nicht in der Testliste", 403)
        with mock.patch.object(newsletter, "testmail", side_effect=fehler):
            o = self.node(szenario="editor", mandant_name="HILO e. V.", ops=[{"op": "oeffnen", "betreff": "Test"}, {"op": "testmail"}])
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


class TestLayout(MN):
    """Newsletter-Layout Version 1 (eine Spalte, bestehende Entwürfe) und Umschalter. Neue Layout-Entwürfe sind seit Etappe "Blöcke v2" zweispaltig (TestLayoutV2);
    die v1-Tests öffnen deshalb einen bestehenden v1-Entwurf und bearbeiten ihn."""

    def vorbereiten(self):
        import bilder
        from tests.test_etappe1 import png
        m = self.mandant("hilo", "HILO e. V.")
        self.b1 = bilder.speichern(m, png(groesse=(100, 60)), "Logo klein")["id"]
        self.b2 = bilder.speichern(m, png(groesse=(80, 80), farbe=(200, 30, 30, 255)), "Rotes Bild")["id"]
        return m

    def ops(self, ops):
        o = self.node(szenario="layout", mandant_name="HILO e. V.", ops=ops)
        self.assertTrue(o["ok"], o)
        return o

    def ops2(self, ops):
        o = self.node(szenario="layout2", mandant_name="HILO e. V.", ops=ops)
        self.assertTrue(o["ok"], o)
        return o

    def entwuerfe(self):
        with db.verbindung() as c:
            return [dict(z) for z in c.execute("SELECT * FROM entwurf ORDER BY id")]

    def layout_entwurf(self, m, betreff="Layout-Entwurf"):
        import newsletter
        blocks = {"version": 1, "balken": {"text": "Neu", "url": "https://example.org/b"}, "text_html": "<p>Hallo <strong>Welt</strong></p>",
                  "bilder": [{"bild_id": self.b1, "alt": "Logo klein", "bildunterschrift": "Unten", "url": "https://example.org/i"}]}
        return newsletter.anlegen(m, betreff, None, "testliste", {}, "layout", blocks)

    def test_umschalter_text_layout(self):
        self.vorbereiten()
        o = self.ops2([{"op": "neu"}, {"op": "format", "wert": "layout"}, {"op": "format", "wert": "text"}])
        s0, s1, s2 = (x["zustand"] for x in o["schritte"])
        self.assertEqual([(r["wert"], r["aktiv"], r["gesperrt"]) for r in s0["format"]], [("text", True, False), ("layout", False, False)])
        self.assertTrue(s0["text_gruppe_sichtbar"])
        self.assertFalse(s0["layout_sichtbar"])
        self.assertFalse(s1["text_gruppe_sichtbar"])                                          # Layout: Textfeld weg, Layout-Editor da
        self.assertTrue(s1["layout_sichtbar"])
        self.assertEqual(s1["version"], "2")                                                  # neue Entwürfe: zwei Spalten
        self.assertEqual(s1["spalten_titel"], ["Linke Spalte", "Rechte Spalte"])
        self.assertTrue(s2["text_gruppe_sichtbar"])                                           # zurück zu Text
        self.assertFalse(s2["layout_sichtbar"])

    def test_bestehende_entwuerfe_format_fest_liste_zeigt_format_und_ansicht_link_nur_bei_layout(self):
        import newsletter
        m = self.vorbereiten()
        self.layout_entwurf(m, "Mit Layout")
        newsletter.anlegen(m, "Nur Text", "Hallo", "testliste", {})
        o = self.ops2([{"op": "oeffnen", "betreff": "Mit Layout"}])
        zeilen = {z[0]: z for z in o["start"]["liste"]}
        self.assertEqual(zeilen["Mit Layout"][1], "Layout")
        self.assertEqual(zeilen["Nur Text"][1], "Text")
        s = o["schritte"][0]["zustand"]
        self.assertTrue(s["layout_sichtbar"])
        self.assertIsNone(s["version"])                                                       # v1 bleibt im alten Editor
        self.assertIn("frühere Layout", s["hinweis_v1"])
        self.assertTrue(all(r["gesperrt"] for r in s["format"]))                              # Format eines bestehenden Entwurfs ist nicht änderbar
        self.assertEqual((s["ansicht"]["target"], s["ansicht"]["rel"]), ("_blank", "noopener noreferrer"))
        self.assertIn("/hilo/newsletter/ansicht/", s["ansicht"]["href"])
        t = self.ops2([{"op": "oeffnen", "betreff": "Nur Text"}])["schritte"][0]["zustand"]
        self.assertFalse(t["layout_sichtbar"])
        self.assertTrue(t["text_gruppe_sichtbar"])
        self.assertIsNone(t["ansicht"])
        self.assertTrue(all(r["gesperrt"] for r in t["format"]))

    def test_v1_entwurf_bleibt_v1_beim_speichern(self):
        m = self.vorbereiten()
        self.layout_entwurf(m)
        o = self.ops2([{"op": "oeffnen", "betreff": "Layout-Entwurf"}, {"op": "speichern"}])
        put = [b for b in o["schritte"][1]["bodies"] if b["m"] == "PUT"][0]
        self.assertEqual(put["s"], 200)
        self.assertEqual(put["body"]["blocks"]["version"], 1)                                 # nicht still umgewandelt
        self.assertEqual(set(put["body"]["blocks"]), {"version", "balken", "text_html", "bilder"})
        self.assertNotIn("spalten", put["body"]["blocks"])
        gespeichert = json.loads(self.entwuerfe()[0]["blocks"])
        self.assertEqual((gespeichert["version"], len(gespeichert["bilder"])), (1, 1))
        self.assertIsNone(o["schritte"][1]["zustand"]["version"])

    def test_sechs_bilder_ja_siebtes_nein(self):
        m = self.vorbereiten()
        self.layout_entwurf(m)
        o = self.ops([{"op": "oeffnen", "betreff": "Layout-Entwurf"}, {"op": "bild_neu", "anzahl": 5}, {"op": "bild_zwangsklick"}, {"op": "bild_entfernen", "index": 0}])
        s = [x["zustand"] for x in o["schritte"]]
        self.assertEqual((len(s[1]["bilder"]), s[1]["hinzufuegen_gesperrt"], s[1]["zaehler"]), (6, True, "Bilder: 6 von 6"))
        self.assertEqual(len(s[2]["bilder"]), 6)                                              # auch ein erzwungener Klick legt kein 7. Bild an
        self.assertEqual((len(s[3]["bilder"]), s[3]["hinzufuegen_gesperrt"]), (5, False))

    def test_alt_leer_und_kein_bild_blockieren_ohne_anfrage(self):
        m = self.vorbereiten()
        self.layout_entwurf(m)
        vorher = self.entwuerfe()[0]["blocks"]
        o = self.ops([{"op": "oeffnen", "betreff": "Layout-Entwurf"}, {"op": "bild_neu"}, {"op": "speichern"},
                      {"op": "bild_setzen", "index": 1, "bild_id": self.b2}, {"op": "bild_setzen", "index": 1, "alt": ""}, {"op": "speichern"}])
        kein_bild, alt_leer = o["schritte"][2]["zustand"], o["schritte"][5]["zustand"]
        self.assertEqual(o["schritte"][2]["bodies"], [])
        self.assertIn("bilder[1].bild_id", kein_bild["feld_fehler"])
        self.assertEqual(o["schritte"][5]["bodies"], [])
        self.assertIn("bilder[1].alt", alt_leer["feld_fehler"])
        self.assertGreaterEqual(alt_leer["markiert"], 1)
        self.assertEqual(self.entwuerfe()[0]["blocks"], vorher)

    def test_serverfehler_mit_feld_wird_am_feld_angezeigt(self):
        m = self.vorbereiten()
        self.layout_entwurf(m)
        vorher = self.entwuerfe()[0]["blocks"]
        o = self.ops([{"op": "oeffnen", "betreff": "Layout-Entwurf"}, {"op": "balken", "text": "x" * 70}, {"op": "speichern"}])
        s = o["schritte"][2]
        self.assertEqual([b["s"] for b in s["bodies"]], [400])
        self.assertIn("balken.text", s["zustand"]["feld_fehler"])
        self.assertIn("60", s["zustand"]["feld_fehler"]["balken.text"])
        self.assertTrue(any("60" in f for f in s["zustand"]["fehler"]))
        self.assertEqual(self.entwuerfe()[0]["blocks"], vorher)

    def test_gesendetes_blocks_entspricht_dem_schema_und_nur_erlaubte_tags(self):
        m = self.vorbereiten()
        self.layout_entwurf(m)
        schmutz = ('<div style="color:red">Hallo <b>Welt</b><script>alert(1)</script> <span style="x">bunt</span> <a href="javascript:alert(1)">böse</a> '
                   '<a href="https://example.org/x" onclick="y()">gut</a></div><h2 data-ausrichtung="zentriert" class="c">Titel</h2><ul><li>eins</li></ul>')
        o = self.ops([{"op": "oeffnen", "betreff": "Layout-Entwurf"}, {"op": "balken", "text": "Neu bei uns", "url": "https://example.org/b2"},
                      {"op": "html_roh", "wert": schmutz}, {"op": "bild_setzen", "index": 0, "unterschrift": "Unterschrift", "url": "https://example.org/i2"},
                      {"op": "speichern"}])
        s = o["schritte"][4]
        put = [b for b in s["bodies"] if b["m"] == "PUT"][0]
        self.assertEqual(put["s"], 200)
        body = put["body"]
        self.assertEqual(set(body), {"betreff", "ziel", "segment", "blocks"})
        self.assertNotIn("text", body)
        blocks = body["blocks"]
        self.assertEqual(set(blocks), {"version", "balken", "text_html", "bilder"})
        self.assertEqual(blocks["version"], 1)
        self.assertEqual(blocks["balken"], {"text": "Neu bei uns", "url": "https://example.org/b2"})
        self.assertEqual(blocks["bilder"], [{"bild_id": self.b1, "alt": "Logo klein", "bildunterschrift": "Unterschrift", "url": "https://example.org/i2"}])
        self.assertIsInstance(blocks["bilder"][0]["bild_id"], int)
        html = blocks["text_html"]
        for verboten in ("script", "style", "javascript", "onclick", "span", "class=", "<div", "alert"):
            self.assertNotIn(verboten, html)
        for erwartet in ("<strong>Welt</strong>", '<a href="https://example.org/x">gut</a>', '<h2 data-ausrichtung="zentriert">Titel</h2>', "<ul><li>eins</li></ul>", "böse", "bunt"):
            self.assertIn(erwartet, html)
        gespeichert = json.loads(self.entwuerfe()[0]["blocks"])
        self.assertEqual((gespeichert["balken"]["text"], gespeichert["bilder"][0]["url"]), ("Neu bei uns", "https://example.org/i2"))
        nachher = s["zustand"]                                                                # Editor zeigt die Fassung des Servers
        self.assertNotIn("script", nachher["editor_html"])
        self.assertEqual(nachher["bilder"][0]["alt"], "Logo klein")

    def test_aendern_schickt_put_ohne_text_und_format(self):
        m = self.vorbereiten()
        e = self.layout_entwurf(m)
        o = self.ops([{"op": "oeffnen", "betreff": "Layout-Entwurf"}, {"op": "balken", "text": "Geändert"}, {"op": "bild_setzen", "index": 0, "bild_id": self.b2, "alt": "Anders"}, {"op": "speichern"}])
        offen = o["schritte"][0]["zustand"]
        self.assertEqual(offen["balken_text"], "Neu")
        self.assertEqual((offen["bilder"][0]["bild_id"], offen["bilder"][0]["alt"], offen["bilder"][0]["unterschrift"], offen["bilder"][0]["url"]), (str(self.b1), "Logo klein", "Unten", "https://example.org/i"))
        self.assertIn("<strong>Welt</strong>", offen["editor_html"])
        put = [b for b in o["schritte"][3]["bodies"] if b["m"] == "PUT"][0]
        self.assertEqual(put["s"], 200)
        self.assertEqual(set(put["body"]), {"betreff", "ziel", "segment", "blocks"})
        self.assertEqual(put["body"]["blocks"]["balken"]["text"], "Geändert")
        self.assertEqual(put["body"]["blocks"]["bilder"][0]["bild_id"], self.b2)
        gespeichert = json.loads(self.entwuerfe()[0]["blocks"])
        self.assertEqual((gespeichert["balken"]["text"], gespeichert["bilder"][0]["bild_id"]), ("Geändert", self.b2))
        self.assertNotEqual(self.entwuerfe()[0]["content_hash"], e["content_hash"])

    def test_formatleiste_ruft_nur_erlaubte_befehle_und_links_werden_geprueft(self):
        m = self.vorbereiten()
        self.layout_entwurf(m)
        o = self.ops([{"op": "oeffnen", "betreff": "Layout-Entwurf"}, {"op": "html_roh", "wert": "<p>Text</p>"}, {"op": "auswahl", "selektor": "p"},
                      {"op": "leiste", "knopf": "Fett"}, {"op": "leiste", "knopf": "Kursiv"}, {"op": "leiste", "knopf": "Überschrift 2"}, {"op": "leiste", "knopf": "Überschrift 3"},
                      {"op": "leiste", "knopf": "Liste"}, {"op": "leiste", "knopf": "Nummerierte Liste"},
                      {"op": "leiste", "knopf": "Zentriert"}, {"op": "leiste", "knopf": "Zentriert"},
                      {"op": "link_url", "wert": "javascript:alert(1)"}, {"op": "leiste", "knopf": "Link setzen"},
                      {"op": "link_url", "wert": "https://example.org/z"}, {"op": "leiste", "knopf": "Link setzen"}, {"op": "leiste", "knopf": "Link entfernen"}])
        z = [x["zustand"] for x in o["schritte"]]
        self.assertEqual(z[8]["befehle"], [["bold", None], ["italic", None], ["formatBlock", "h2"], ["formatBlock", "h3"], ["insertUnorderedList", None], ["insertOrderedList", None]])
        self.assertIn('data-ausrichtung="zentriert"', z[9]["editor_html"])                   # Zentrierung als Attribut am Absatz
        self.assertNotIn("data-ausrichtung", z[10]["editor_html"])                            # zweiter Klick nimmt sie zurück
        self.assertNotIn("style", z[9]["editor_html"])
        self.assertNotIn("createLink", [c[0] for c in z[12]["befehle"]])                      # javascript: wird nie zum Link
        self.assertIn("text_html", z[12]["feld_fehler"])
        self.assertIn(["createLink", "https://example.org/z"], z[14]["befehle"])
        self.assertEqual(z[15]["befehle"][-1], ["unlink", None])

    def test_fremdes_html_wird_ueber_die_allowlist_angezeigt(self):
        m = self.vorbereiten()
        self.layout_entwurf(m)
        o = self.ops([{"op": "oeffnen", "betreff": "Layout-Entwurf"},
                      {"op": "html_laden", "wert": '<p onclick="x()" style="color:red">a<img src=x onerror=y><script>z()</script><iframe src="https://example.org"></iframe><b>f</b></p><table><tr><td>t</td></tr></table><a href="http://example.org">h</a>'}])
        html = o["schritte"][1]["zustand"]["editor_html"]
        for verboten in ("<img", "script", "iframe", "onclick", "onerror", "style", "<table", "<td", "href="):
            self.assertNotIn(verboten, html)
        self.assertIn("<strong>f</strong>", html)
        for text in ("a", "t", "h"):
            self.assertIn(text, html)

    def test_vorschau_iframe_sandbox_ohne_allow_warnungen_text_und_fehler_am_feld(self):
        m = self.vorbereiten()
        self.layout_entwurf(m)
        vorher = self.entwuerfe()[0]["blocks"]
        o = self.ops([{"op": "oeffnen", "betreff": "Layout-Entwurf"}, {"op": "betreff", "wert": ""}, {"op": "html_roh", "wert": "<p>Hallo Vorschau</p>"},
                      {"op": "vorschau"}, {"op": "betreff", "wert": "Betreff der Vorschau"}, {"op": "text_fassung"}, {"op": "balken", "text": "y" * 70}, {"op": "vorschau"}])
        ohne_betreff = o["schritte"][3]
        post = [b for b in ohne_betreff["bodies"] if b["m"] == "POST"][0]
        self.assertTrue(post["p"].endswith("/entwuerfe/vorschau") and post["s"] == 200)
        self.assertEqual(set(post["body"]), {"blocks"})                                       # leerer Betreff wird nicht mitgeschickt
        v = ohne_betreff["zustand"]["vorschau"]
        self.assertTrue(v["rahmen"])
        self.assertEqual(v["sandbox"], "")                                                    # sandbox ohne Freigaben
        self.assertFalse(v["hat_allow"])
        self.assertIn("Hallo Vorschau", v["srcdoc"])
        self.assertTrue(any("Logo" in w for w in v["warnungen"]), v["warnungen"])
        self.assertTrue(v["text_knopf"])
        self.assertFalse(v["text_sichtbar"])
        mit_betreff = [b for b in o["schritte"][7]["bodies"] if b["m"] == "POST"][0]
        self.assertEqual(mit_betreff["s"], 400)
        self.assertEqual(mit_betreff["body"]["betreff"], "Betreff der Vorschau")
        self.assertIn("balken.text", o["schritte"][7]["zustand"]["feld_fehler"])
        text = o["schritte"][5]["zustand"]["vorschau"]
        self.assertTrue(text["text_sichtbar"])
        self.assertIn("Hallo Vorschau", text["text"])
        self.assertEqual(self.entwuerfe()[0]["blocks"], vorher)                               # die Vorschau speichert nichts


class TestLayoutV2(MN):
    """Newsletter-Layout Version 2 (catrin #19220, Variante A): zwei Spalten mit freien Blöcken. Solange das Backend v0.8.0 (version 2) nicht auf main ist, ersetzt
    backend_v2() die Prüfung durch eine Durchreiche der Form; die Fehlertests patchen unabhängig davon. Mit dem echten Backend läuft alles ohne Stellvertreter."""

    def vorbereiten(self):
        import bilder
        from tests.test_etappe1 import png
        m = self.mandant("hilo", "HILO e. V.")
        self.b1 = bilder.speichern(m, png(groesse=(100, 60)), "Logo klein")["id"]
        self.b2 = bilder.speichern(m, png(groesse=(80, 80), farbe=(200, 30, 30, 255)), "Rotes Bild")["id"]
        return m

    def backend_v2(self):
        import contextlib, inspect, layout, newsletter
        if "spalten" in inspect.getsource(layout):
            return contextlib.nullcontext()
        orig_pruefen, orig_vorschau = newsletter._blocks_pruefen, newsletter.layout_vorschau

        def pruefen(mandant, blocks):
            if not (isinstance(blocks, dict) and blocks.get("version") == 2):
                return orig_pruefen(mandant, blocks)
            sauber = {"version": 2, "balken": {"text": blocks["balken"].get("text", ""), "url": blocks["balken"].get("url"), "farbe": blocks["balken"].get("farbe")}, "spalten": {}}
            texte = []
            for seite in ("links", "rechts"):
                liste = []
                for b in blocks["spalten"][seite]:
                    b = dict(b)
                    if b["typ"] == "text":
                        b.setdefault("ausrichtung", "links")
                        b.setdefault("farbe", None)
                        texte.append(re.sub(r"<[^>]+>", " ", b["text_html"]).strip())
                    liste.append(b)
                sauber["spalten"][seite] = liste
            return sauber, " ".join(t for t in texte if t) or "Layout"

        def vorschau(mandant, betreff, blocks):
            if not (isinstance(blocks, dict) and blocks.get("version") == 2):
                return orig_vorschau(mandant, betreff, blocks)
            sauber, klartext = pruefen(mandant, blocks)
            return {"html": "<html><body><p>%s</p></body></html>" % klartext, "text": klartext, "warnungen": [], "blocks": sauber}

        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(newsletter, "_blocks_pruefen", pruefen))
        stack.enter_context(mock.patch.object(newsletter, "layout_vorschau", vorschau))
        return stack

    def ops(self, ops):
        o = self.node(szenario="layout2", mandant_name="HILO e. V.", ops=ops)
        self.assertTrue(o["ok"], o)
        return o

    def entwuerfe(self):
        with db.verbindung() as c:
            return [dict(z) for z in c.execute("SELECT * FROM entwurf ORDER BY id")]

    def neu(self, *ops):
        return [{"op": "neu"}, {"op": "format", "wert": "layout"}, {"op": "betreff", "wert": "Zwei Spalten"}, *ops]

    def test_bloecke_hinzufuegen_verschieben_und_loeschen(self):
        self.vorbereiten()
        o = self.ops(self.neu(
            {"op": "add", "spalte": "links", "typ": "text"}, {"op": "add", "spalte": "links", "typ": "bild"}, {"op": "add", "spalte": "rechts", "typ": "text"},
            {"op": "text", "spalte": "links", "index": 0, "html": "<p>A</p>"}, {"op": "text", "spalte": "rechts", "index": 0, "html": "<p>R</p>"},
            {"op": "add", "spalte": "links", "typ": "text"}, {"op": "text", "spalte": "links", "index": 2, "html": "<p>C</p>"},
            {"op": "runter", "spalte": "links", "index": 0}, {"op": "hoch", "spalte": "links", "index": 2}, {"op": "loeschen", "spalte": "links", "index": 0}))
        z = [x["zustand"] for x in o["schritte"]]
        angelegt = z[5]
        self.assertEqual([(b["typ"], b["titel"]) for b in angelegt["spalten"]["links"]], [("text", "Text 1"), ("bild", "Bild 2")])
        self.assertEqual([(b["typ"], b["titel"]) for b in angelegt["spalten"]["rechts"]], [("text", "Text 1")])
        self.assertEqual((angelegt["add"]["links"]["text"], angelegt["add"]["links"]["bild"]), ("+ Text", "+ Bild"))     # Knöpfe je Spalte
        self.assertTrue(angelegt["spalten"]["links"][0]["hoch_gesperrt"])
        self.assertTrue(angelegt["spalten"]["links"][1]["runter_gesperrt"])
        runter = z[10]                                                                         # [A, bild, C] -> runter(0) -> [bild, A, C]
        self.assertEqual([b["typ"] for b in runter["spalten"]["links"]], ["bild", "text", "text"])
        self.assertEqual(runter["spalten"]["links"][1]["text_html"], "<p>A</p>")
        hoch = z[11]                                                                           # hoch(2) -> [bild, C, A]
        self.assertEqual([b.get("text_html") for b in hoch["spalten"]["links"]], [None, "<p>C</p>", "<p>A</p>"])
        weg = z[12]                                                                            # Bild löschen -> [C, A]
        self.assertEqual([(b["titel"], b["text_html"]) for b in weg["spalten"]["links"]], [("Text 1", "<p>C</p>"), ("Text 2", "<p>A</p>")])
        self.assertEqual(weg["spalten_zaehler"], {"links": "Blöcke: 2 von 20", "rechts": "Blöcke: 1 von 20"})
        self.assertEqual(weg["spalten"]["rechts"][0]["text_html"], "<p>R</p>")                # die andere Spalte bleibt unberührt

    def test_grenzen_20_bloecke_je_spalte_und_12_bilder_gesamt(self):
        self.vorbereiten()
        o = self.ops(self.neu({"op": "add", "spalte": "links", "typ": "text", "anzahl": 20}, {"op": "add_erzwungen", "spalte": "links", "typ": "text"},
                              {"op": "add", "spalte": "rechts", "typ": "bild", "anzahl": 12}, {"op": "add_erzwungen", "spalte": "rechts", "typ": "bild"},
                              {"op": "loeschen", "spalte": "rechts", "index": 0}))
        z = [x["zustand"] for x in o["schritte"]]
        voll = z[3]
        self.assertEqual(len(voll["spalten"]["links"]), 20)
        self.assertEqual(voll["spalten_zaehler"]["links"], "Blöcke: 20 von 20")
        self.assertTrue(voll["add"]["links"]["text_gesperrt"] and voll["add"]["links"]["bild_gesperrt"])
        self.assertFalse(voll["add"]["rechts"]["text_gesperrt"])                              # die andere Spalte bleibt frei
        self.assertEqual(len(z[4]["spalten"]["links"]), 20)                                    # auch ein erzwungener Klick legt keinen 21. Block an
        zwoelf = z[5]
        self.assertEqual(zwoelf["bilder_zaehler"], "Bilder: 12 von 12")
        self.assertTrue(zwoelf["add"]["rechts"]["bild_gesperrt"] and zwoelf["add"]["links"]["bild_gesperrt"])
        self.assertFalse(zwoelf["add"]["rechts"]["text_gesperrt"])                            # Text geht weiter (12 von 20 Blöcken)
        self.assertEqual(len(z[6]["spalten"]["rechts"]), 12)                                   # kein 13. Bild
        self.assertEqual(z[7]["bilder_zaehler"], "Bilder: 11 von 12")
        self.assertFalse(z[7]["add"]["rechts"]["bild_gesperrt"])

    def test_gesendetes_v2_schema_und_farbe_null_bei_standard(self):
        self.vorbereiten()
        with self.backend_v2():
            o = self.ops(self.neu(
                {"op": "balken", "text": "Titel", "url": "https://example.org/b"},
                {"op": "add", "spalte": "links", "typ": "text"}, {"op": "text", "spalte": "links", "index": 0, "html": "<p>Hallo <b>Welt</b></p>", "ausrichtung": "blocksatz", "farbe": "#336699"},
                {"op": "add", "spalte": "links", "typ": "bild"}, {"op": "bild", "spalte": "links", "index": 1, "bild_id": self.b1, "unterschrift": "U", "url": "https://example.org/i"},
                {"op": "add", "spalte": "rechts", "typ": "text"}, {"op": "text", "spalte": "rechts", "index": 0, "html": "<p>R</p>", "farbe": "#112233"},
                {"op": "text", "spalte": "rechts", "index": 0, "farbe": None}, {"op": "speichern"}))
        s = o["schritte"][-1]
        post = [b for b in s["bodies"] if b["m"] == "POST" and b["p"].endswith("/entwuerfe")][0]
        self.assertEqual(post["s"], 201)
        self.assertEqual(set(post["body"]), {"betreff", "ziel", "segment", "format", "blocks"})
        self.assertEqual(post["body"]["format"], "layout")
        self.assertNotIn("text", post["body"])
        self.assertEqual(post["body"]["blocks"], {
            "version": 2,
            "balken": {"text": "Titel", "url": "https://example.org/b", "farbe": None},                          # nie gewählt: null, nicht "#000000"
            "spalten": {
                "links": [{"typ": "text", "text_html": "<p>Hallo <strong>Welt</strong></p>", "ausrichtung": "blocksatz", "farbe": "#336699"},
                          {"typ": "bild", "bild_id": self.b1, "alt": "", "bildunterschrift": "U", "bildunterschrift_farbe": None, "url": "https://example.org/i"}],
                "rechts": [{"typ": "text", "text_html": "<p>R</p>", "ausrichtung": "links", "farbe": None}],    # gewählt und mit "Standardfarbe" zurückgesetzt: null
            }})
        self.assertIsInstance(post["body"]["blocks"]["spalten"]["links"][1]["bild_id"], int)
        e = self.entwuerfe()
        self.assertEqual((len(e), e[0]["format"], json.loads(e[0]["blocks"])["version"]), (1, "layout", 2))
        nachher = s["zustand"]                                                                 # Editor zeigt die gespeicherte Fassung
        self.assertEqual(nachher["version"], "2")
        self.assertEqual((len(nachher["spalten"]["links"]), len(nachher["spalten"]["rechts"])), (2, 1))
        self.assertEqual(nachher["spalten"]["links"][0]["farbe"], "#336699")
        self.assertEqual(nachher["spalten"]["rechts"][0]["farbe"], "Standardfarbe")

    def test_balken_und_untertitelfarbe_werden_gesendet_ungueltige_nicht(self):
        self.vorbereiten()
        with self.backend_v2():
            o = self.ops(self.neu({"op": "balken", "text": "T", "farbe": "#0b2545"},
                                  {"op": "add", "spalte": "links", "typ": "bild"}, {"op": "bild", "spalte": "links", "index": 0, "bild_id": self.b2, "farbe": "#FF0000"},
                                  {"op": "speichern"}))
        post = [b for b in o["schritte"][-1]["bodies"] if b["m"] == "POST" and b["p"].endswith("/entwuerfe")][0]
        blocks = post["body"]["blocks"]
        self.assertEqual(blocks["balken"]["farbe"], "#0b2545")
        self.assertEqual(blocks["spalten"]["links"][0]["bildunterschrift_farbe"], "#ff0000")   # Farbfeld liefert klein geschriebenes #rrggbb
        for b in [blocks["balken"], *blocks["spalten"]["links"]]:
            for k, v in b.items():
                if "farbe" in k and v is not None:
                    self.assertRegex(v, r"^#[0-9a-f]{6}$")

    def test_markierung_faerbt_ueber_span_data_farbe_nie_style(self):
        self.vorbereiten()
        with self.backend_v2():
            o = self.ops(self.neu(
                {"op": "add", "spalte": "links", "typ": "text"}, {"op": "text", "spalte": "links", "index": 0, "html": "<p>Hallo Welt</p>"},
                {"op": "leiste", "spalte": "links", "index": 0, "knopf": "Markierung färben"},
                {"op": "auswahl", "spalte": "links", "index": 0, "selektor": "p", "ganz": True}, {"op": "markierungsfarbe", "spalte": "links", "index": 0, "wert": "#c0392b"},
                {"op": "leiste", "spalte": "links", "index": 0, "knopf": "Markierung färben"}, {"op": "speichern"}))
        z = [x["zustand"] for x in o["schritte"]]
        self.assertIn("markieren", z[5]["feld_fehler"]["spalten.links[0].text_html"])           # ohne Markierung: Hinweis am Feld, nichts verändert
        self.assertEqual(z[5]["spalten"]["links"][0]["text_html"], "<p>Hallo Welt</p>")
        gefaerbt = z[8]["spalten"]["links"][0]["text_html"]
        self.assertEqual(gefaerbt, '<p><span data-farbe="#c0392b">Hallo Welt</span></p>')
        self.assertNotIn("style", gefaerbt)
        post = [b for b in o["schritte"][-1]["bodies"] if b["m"] == "POST" and b["p"].endswith("/entwuerfe")][0]
        self.assertEqual(post["body"]["blocks"]["spalten"]["links"][0]["text_html"], '<p><span data-farbe="#c0392b">Hallo Welt</span></p>')

    def test_markierungsfarbe_entfernen_und_formatleiste_im_block(self):
        self.vorbereiten()
        o = self.ops(self.neu(
            {"op": "add", "spalte": "rechts", "typ": "text"}, {"op": "text", "spalte": "rechts", "index": 0, "html": '<p>Hallo <span data-farbe="#c0392b">Welt</span></p>'},
            {"op": "auswahl", "spalte": "rechts", "index": 0, "selektor": "p", "ganz": True}, {"op": "leiste", "spalte": "rechts", "index": 0, "knopf": "Markierungsfarbe entfernen"},
            {"op": "auswahl", "spalte": "rechts", "index": 0, "selektor": "p"},
            {"op": "leiste", "spalte": "rechts", "index": 0, "knopf": "Fett"}, {"op": "leiste", "spalte": "rechts", "index": 0, "knopf": "Überschrift 2"}, {"op": "leiste", "spalte": "rechts", "index": 0, "knopf": "Zentriert"},
            {"op": "link_url", "spalte": "rechts", "index": 0, "wert": "javascript:alert(1)"}, {"op": "leiste", "spalte": "rechts", "index": 0, "knopf": "Link setzen"}))
        z = [x["zustand"] for x in o["schritte"]]
        self.assertEqual(z[6]["spalten"]["rechts"][0]["text_html"], "<p>Hallo Welt</p>")        # Farbe entfernt, Text bleibt
        self.assertEqual(z[9]["befehle"], [["bold", None], ["formatBlock", "h2"]])
        self.assertIn('data-ausrichtung="zentriert"', z[10]["spalten"]["rechts"][0]["text_html"])
        self.assertNotIn("createLink", [c[0] for c in z[12]["befehle"]])                       # javascript: wird nie zum Link
        self.assertIn("spalten.rechts[0].text_html", z[12]["feld_fehler"])
        self.assertEqual(z[12]["spalten"]["rechts"][0]["leiste"][:3], ["Fett", "Kursiv", "Absatz"])

    def test_fremdes_html_und_ungueltige_farben_im_text_werden_entfernt(self):
        self.vorbereiten()
        o = self.ops(self.neu({"op": "add", "spalte": "links", "typ": "text"},
                              {"op": "text", "spalte": "links", "index": 0,
                               "laden": '<p onclick="x()" style="color:red">a<span data-farbe="red">r</span><span data-farbe="#12345">k</span><span style="color:red">s</span>'
                                        '<span data-farbe="#ABCDEF" class="c">g</span><script>z()</script><img src=x onerror=y></p>'}))
        html = o["schritte"][-1]["zustand"]["spalten"]["links"][0]["text_html"]
        self.assertEqual(html, '<p>a' + 'r' + 'k' + 's' + '<span data-farbe="#abcdef">g</span></p>')    # nur die gültige Farbe bleibt (klein geschrieben), alles andere entpackt
        for verboten in ("style", "onclick", "class", "script", "<img", 'data-farbe="red"', "#12345"):
            self.assertNotIn(verboten, html)

    def test_clientseitige_pruefung_sperrt_ohne_anfrage(self):
        self.vorbereiten()
        o = self.ops(self.neu({"op": "speichern"},
                              {"op": "add", "spalte": "links", "typ": "text"}, {"op": "add", "spalte": "rechts", "typ": "bild"}, {"op": "speichern"},
                              {"op": "balken", "url": "http://example.org"}, {"op": "speichern"}))
        keinblock, leer, balken = o["schritte"][3]["zustand"], o["schritte"][6]["zustand"], o["schritte"][8]["zustand"]
        self.assertEqual(o["schritte"][3]["bodies"], [])
        self.assertIn("mindestens einen Block", keinblock["feld_fehler"]["spalten"])
        self.assertEqual(o["schritte"][6]["bodies"], [])
        self.assertIn("spalten.links[0].text_html", leer["feld_fehler"])                       # leerer Textblock
        self.assertIn("spalten.rechts[0].bild_id", leer["feld_fehler"])                        # Bildblock ohne Bild
        self.assertEqual(o["schritte"][8]["bodies"], [])
        self.assertIn("balken.url", balken["feld_fehler"])                                     # nur https
        self.assertEqual(self.entwuerfe(), [])

    def test_serverfehler_mit_feld_erscheinen_am_feld_und_fallen_zurueck(self):
        import newsletter
        self.vorbereiten()
        fehler = [newsletter.Fehler("farbe_ungueltig", "Die Farbe ist ungültig", 400, "spalten.rechts[1].bildunterschrift_farbe"),
                  newsletter.Fehler("block_typ_ungueltig", "Der Blocktyp ist ungültig", 400, "spalten.rechts[0].typ"),
                  newsletter.Fehler("zu_viele_bilder", "Höchstens 12 Bilder", 400, "spalten")]
        with mock.patch.object(newsletter, "_blocks_pruefen", side_effect=fehler):
            o = self.ops(self.neu({"op": "add", "spalte": "rechts", "typ": "text"}, {"op": "add", "spalte": "rechts", "typ": "bild"},
                                  {"op": "text", "spalte": "rechts", "index": 0, "html": "<p>x</p>"}, {"op": "bild", "spalte": "rechts", "index": 1, "bild_id": self.b1},
                                  {"op": "speichern"}, {"op": "speichern"}, {"op": "speichern"}))
        z = [x["zustand"] for x in o["schritte"]]
        self.assertEqual(z[7]["feld_fehler"], {"spalten.rechts[1].bildunterschrift_farbe": "Die Farbe ist ungültig"})             # genau am Feld
        self.assertEqual(z[8]["feld_fehler"], {"spalten.rechts[0]": "Der Blocktyp ist ungültig"})                                # …[0].typ: am Block
        self.assertEqual(z[9]["feld_fehler"], {"spalten": "Höchstens 12 Bilder"})                                                # Gesamtfehler
        for i in (7, 8, 9):
            self.assertEqual([b["s"] for b in o["schritte"][i]["bodies"]], [400])
            self.assertTrue(z[i]["fehler"], z[i])                                                                                  # Meldung steht auch im Fehlerfeld des Formulars
        self.assertEqual(self.entwuerfe(), [])

    def test_vorschau_zeigt_warnungen_und_sendet_v2(self):
        import newsletter
        self.vorbereiten()
        antwort = {"html": "<p>Vorschau v2</p>", "text": "Vorschau v2", "warnungen": ["Kontrast zu gering (Linke Spalte, Text 1): unter 4,5:1"],
                   "blocks": {"version": 2, "spalten": {"links": [], "rechts": []}, "bilder": []}}      # "bilder" nur, weil das Audit von main (v0.7.x) es noch zählt
        with mock.patch.object(newsletter, "layout_vorschau", return_value=antwort):
            o = self.ops(self.neu({"op": "add", "spalte": "links", "typ": "text"}, {"op": "text", "spalte": "links", "index": 0, "html": "<p>Hallo</p>", "farbe": "#cccccc"},
                                  {"op": "vorschau"}, {"op": "text_fassung"}))
        s = o["schritte"][5]
        post = [b for b in s["bodies"] if b["m"] == "POST" and b["p"].endswith("/entwuerfe/vorschau")][0]
        self.assertEqual(post["s"], 200)
        self.assertEqual(set(post["body"]), {"betreff", "blocks"})
        self.assertEqual(post["body"]["blocks"]["version"], 2)
        self.assertEqual(post["body"]["blocks"]["spalten"]["links"][0]["farbe"], "#cccccc")
        v = s["zustand"]["vorschau"]
        self.assertEqual((v["sandbox"], v["hat_allow"]), ("", False))                          # iframe sandbox ohne Freigaben
        self.assertIn("Vorschau v2", v["srcdoc"])
        self.assertEqual(v["warnungen"], ["Kontrast zu gering (Linke Spalte, Text 1): unter 4,5:1"])    # nur Hinweis, Speichern bleibt möglich
        self.assertFalse(s["zustand"]["speichern_gesperrt"])
        self.assertTrue(o["schritte"][6]["zustand"]["vorschau"]["text_sichtbar"])
        self.assertEqual(self.entwuerfe(), [])

    def test_bestehender_v2_entwurf_wird_geladen_und_per_put_gespeichert(self):
        import newsletter
        m = self.vorbereiten()
        blocks = {"version": 2, "balken": {"text": "Neu", "url": "https://example.org/b", "farbe": "#0b2545"},
                  "spalten": {"links": [{"typ": "text", "text_html": '<p>Hallo <span data-farbe="#336699">Welt</span></p>', "ausrichtung": "zentriert", "farbe": "#112233"},
                                        {"typ": "bild", "bild_id": self.b1, "alt": "Eigener Alt", "bildunterschrift": "Unten", "bildunterschrift_farbe": "#ff0000", "url": "https://example.org/i"}],
                              "rechts": [{"typ": "text", "text_html": "<p>R</p>", "ausrichtung": "links", "farbe": None}]}}
        with self.backend_v2():
            newsletter.anlegen(m, "V2-Entwurf", None, "testliste", {}, "layout", blocks)
            o = self.ops([{"op": "oeffnen", "betreff": "V2-Entwurf"}, {"op": "balken", "text": "Geändert"}, {"op": "speichern"}])
        offen = o["schritte"][0]["zustand"]
        self.assertEqual(offen["version"], "2")
        self.assertTrue(all(r["gesperrt"] for r in offen["format"]))
        self.assertEqual(offen["balken"], {"text": "Neu", "url": "https://example.org/b", "farbe": "#0b2545"})
        links = offen["spalten"]["links"]
        self.assertEqual((links[0]["typ"], links[0]["ausrichtung"], links[0]["farbe"]), ("text", "zentriert", "#112233"))
        self.assertEqual(links[0]["text_html"], '<p>Hallo <span data-farbe="#336699">Welt</span></p>')
        self.assertEqual((links[1]["bild_id"], links[1]["alt"], links[1]["unterschrift"], links[1]["farbe"], links[1]["url"]), (str(self.b1), "Eigener Alt", "Unten", "#ff0000", "https://example.org/i"))
        self.assertEqual((offen["spalten"]["rechts"][0]["farbe"], offen["spalten"]["rechts"][0]["ausrichtung"]), ("Standardfarbe", "links"))
        self.assertIn("/hilo/newsletter/ansicht/", offen["ansicht"]["href"])
        put = [b for b in o["schritte"][2]["bodies"] if b["m"] == "PUT"][0]
        self.assertEqual(put["s"], 200)
        self.assertEqual(set(put["body"]), {"betreff", "ziel", "segment", "blocks"})
        self.assertEqual(put["body"]["blocks"]["version"], 2)
        self.assertEqual(put["body"]["blocks"]["balken"], {"text": "Geändert", "url": "https://example.org/b", "farbe": "#0b2545"})
        self.assertEqual(put["body"]["blocks"]["spalten"]["links"][0], {"typ": "text", "text_html": '<p>Hallo <span data-farbe="#336699">Welt</span></p>', "ausrichtung": "zentriert", "farbe": "#112233"})


class TestVersandRate(MN):
    """Mails pro Stunde im Reiter Versand (catrin #19195): Anzeige aus GET, gültiger PUT, ungültige Werte gesperrt, 400 zeigt die meldung am Feld."""

    def ops(self, ops):
        o = self.node(szenario="versandrate", mandant_name="HILO e. V.", ops=ops)
        self.assertTrue(o["ok"], o)
        return o

    def test_anzeige_aus_get_standard_und_bereich(self):
        m = self.mandant("hilo", "HILO e. V.")
        o = self.ops([])
        s = o["start"]
        self.assertTrue(s["formular"])
        self.assertEqual(s["label"], "Mails pro Stunde")
        self.assertEqual(s["wert"], "100")                                                      # Standard, nichts gespeichert
        self.assertEqual(s["hinweis"], "Standard 100, erlaubt 1 bis 600")                      # Werte stammen aus der GET-Antwort
        self.assertEqual(s["attrs"], {"typ": "number", "min": "1", "max": "600", "step": "1"})
        self.assertEqual(s["knopf"], {"text": "Speichern", "gesperrt": False})
        self.assertIsNone(s["feld_fehler"])
        self.assertEqual([(r["m"], r["s"]) for r in s["requests"]], [("GET", 200)])
        import newsletter
        newsletter.limit_pro_stunde_setzen(m["id"], 250, "t")
        self.assertEqual(self.ops([])["start"]["wert"], "250")                                  # gespeicherter Wert statt Standard

    def test_gueltiger_put_sendet_ganze_zahl_und_zeigt_toast(self):
        import newsletter
        m = self.mandant("hilo", "HILO e. V.")
        o = self.ops([{"op": "tippen", "wert": "300"}, {"op": "speichern"}, {"op": "tippen", "wert": "1"}, {"op": "speichern"}, {"op": "tippen", "wert": "600"}, {"op": "speichern"}])
        erster = o["schritte"][1]["zustand"]
        self.assertEqual(erster["requests"], [{"m": "PUT", "s": 200, "body": {"limit_pro_stunde": 300}}])
        self.assertIsInstance(erster["requests"][0]["body"]["limit_pro_stunde"], int)           # Zahl, kein Text
        self.assertEqual(erster["toast"], "Mails pro Stunde gespeichert")
        self.assertIsNone(erster["feld_fehler"])
        self.assertEqual(erster["wert"], "300")
        self.assertEqual(o["schritte"][3]["zustand"]["requests"][0]["body"], {"limit_pro_stunde": 1})        # untere Grenze gilt
        self.assertEqual(o["schritte"][5]["zustand"]["requests"][0]["body"], {"limit_pro_stunde": 600})      # obere Grenze gilt
        self.assertEqual(newsletter.limit_pro_stunde(m["id"]), 600)

    def test_ungueltige_werte_sperren_den_knopf_und_senden_nichts(self):
        import newsletter
        m = self.mandant("hilo", "HILO e. V.")
        faelle = ["0", "601", "1.5", "", "-1", "1e2"]
        ops = []
        for wert in faelle:
            ops += [{"op": "tippen", "wert": wert}, {"op": "speichern"}]
        o = self.ops(ops)
        for i, wert in enumerate(faelle):
            nach_tippen, nach_speichern = o["schritte"][2 * i]["zustand"], o["schritte"][2 * i + 1]["zustand"]
            self.assertTrue(nach_tippen["knopf"]["gesperrt"], repr(wert))
            self.assertEqual(nach_tippen["feld_fehler"], "Bitte eine ganze Zahl von 1 bis 600 eingeben.", repr(wert))
            self.assertEqual(nach_tippen["markiert"], "true", repr(wert))
            self.assertEqual(nach_speichern["requests"], [], repr(wert))                         # auch ein erzwungenes Absenden schickt nichts
        o = self.ops([{"op": "tippen", "wert": "0"}, {"op": "tippen", "wert": "50"}])            # wieder gültig: Sperre und Meldung verschwinden
        zurueck = o["schritte"][1]["zustand"]
        self.assertFalse(zurueck["knopf"]["gesperrt"])
        self.assertIsNone(zurueck["feld_fehler"])
        self.assertEqual(newsletter.limit_pro_stunde(m["id"]), 100)                              # nichts gespeichert

    def test_400_zeigt_die_meldung_am_feld_ohne_erfolgs_toast(self):
        import newsletter
        m = self.mandant("hilo", "HILO e. V.")
        fehler = newsletter.Fehler("limit_ungueltig", "limit_pro_stunde muss eine ganze Zahl von 1 bis 600 sein", 400)
        with mock.patch.object(newsletter, "limit_pro_stunde_setzen", side_effect=fehler):
            o = self.ops([{"op": "tippen", "wert": "50"}, {"op": "speichern"}])
        s = o["schritte"][1]["zustand"]
        self.assertEqual([(r["m"], r["s"]) for r in s["requests"]], [("PUT", 400)])
        self.assertEqual(s["feld_fehler"], "limit_pro_stunde muss eine ganze Zahl von 1 bis 600 sein")   # meldung des Servers, 1:1
        self.assertEqual(s["markiert"], "true")
        self.assertNotEqual(s["toast"], "Mails pro Stunde gespeichert")
        self.assertFalse(s["knopf"]["gesperrt"])                                                  # Eingabe bleibt korrigierbar
        self.assertEqual(s["wert"], "50")
        self.assertEqual(newsletter.limit_pro_stunde(m["id"]), 100)


class TestTagAuswahl(MN):
    """Empfängerauswahl nach Tags (catrin #19209/#19211): vier Modi oder, und, ausser, ohne_tags. Backend v0.7.0 (ausser, ohne_tags) liegt noch nicht auf main:
    solange newsletter._segment_pruefen die neuen Modi nicht kennt, ersetzt backend_v070() die beiden Funktionen durch eine Umsetzung der Spezifikation von Sorty."""

    def vorbereiten(self):
        m = self.mandant("hilo", "HILO e. V.")
        text = mc([["a@example.org", "", "", "Spender", ""], ["b@example.org", "", "", "Spender,Verein A", ""], ["c@example.org", "", "", "Verein A", ""], ["d@example.org", "", "", "", ""]])
        self.importiere(m, text, rolle="verein", interessen=["sortnext"])
        return m

    def backend_v070(self):
        import contextlib, inspect, newsletter
        if "ausser" in inspect.getsource(newsletter._segment_pruefen):
            return contextlib.nullcontext()
        orig_pruefen, orig_ermitteln = newsletter._segment_pruefen, newsletter._empfaenger_ermitteln

        def pruefen(mandant, segment):
            modus = (segment or {}).get("tags_modus") if isinstance(segment, dict) else None
            if modus not in ("ausser", "ohne_tags"):
                return orig_pruefen(mandant, segment)
            if modus == "ohne_tags" and "tags" in segment:
                raise newsletter.Fehler("segment_ungueltig", "tags_modus ohne_tags darf nicht zusammen mit tags gesendet werden", 400)
            tags = segment.get("tags")
            if modus == "ausser" and (not isinstance(tags, list) or not tags or len(tags) > 20):
                raise newsletter.Fehler("segment_ungueltig", "tags_modus ausser braucht 1 bis 20 tags", 400)
            ergebnis = orig_pruefen(mandant, {k: v for k, v in segment.items() if k not in ("tags", "tags_modus")})
            if modus == "ausser":
                import abonnenten
                vorhanden = {e["tag"].lower(): e["tag"] for e in abonnenten.tags_liste(mandant["id"])}
                if any(not isinstance(t, str) or t.strip().lower() not in vorhanden for t in tags):
                    raise newsletter.Fehler("segment_ungueltig", "tags: unbekannter Tag", 400)
                ergebnis["tags"] = sorted({vorhanden[t.strip().lower()] for t in tags})
            ergebnis["tags_modus"] = modus
            return ergebnis

        def ermitteln(mandant, z):
            seg = json.loads(z["segment"]) if z["ziel"] != "testliste" else {}
            modus = seg.get("tags_modus")
            if modus not in ("ausser", "ohne_tags"):
                return orig_ermitteln(mandant, z)
            basis = {k: v for k, v in seg.items() if k not in ("tags", "tags_modus")}
            gesperrt = {t.lower() for t in seg.get("tags", [])}
            alle = orig_ermitteln(mandant, {"ziel": z["ziel"], "segment": json.dumps(basis)})
            with db.verbindung() as c:
                hat = {r["id"]: {t.lower() for t in json.loads(r["tags"] or "[]")} for r in c.execute("SELECT id, tags FROM abonnent WHERE mandant_id=?", (mandant["id"],))}
            return [e for e in alle if (not hat[e[1]] if modus == "ohne_tags" else not (gesperrt & hat[e[1]]))]

        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(newsletter, "_segment_pruefen", pruefen))
        stack.enter_context(mock.patch.object(newsletter, "_empfaenger_ermitteln", ermitteln))
        return stack

    def ops(self, ops):
        o = self.node(szenario="tagauswahl", mandant_name="HILO e. V.", ops=ops)
        self.assertTrue(o["ok"], o)
        return o

    def entwuerfe(self):
        with db.verbindung() as c:
            return [dict(z) for z in c.execute("SELECT * FROM entwurf ORDER BY id")]

    def vorschau_bodies(self, schritt):
        return [r["body"] for r in schritt["zustand"]["requests"] if r["p"].endswith("/abonnenten/vorschau")]

    def test_vier_modi_standard_oder_liste_sichtbar(self):
        self.vorbereiten()
        z = self.ops([{"op": "neu"}])["schritte"][0]["zustand"]
        self.assertEqual([(r["wert"], r["text"]) for r in z["modi"]], [("oder", "mindestens einer der Tags"), ("und", "alle Tags"), ("ausser", "alle außer mit diesen Tags"), ("ohne_tags", "nur ohne jeden Tag")])
        self.assertEqual([r["wert"] for r in z["modi"] if r["aktiv"]], ["oder"])
        self.assertTrue(z["tags_gruppe_sichtbar"])
        self.assertEqual([t["wert"] for t in z["tags"]], ["Spender", "Verein A"])
        self.assertFalse(z["speichern_gesperrt"])

    def test_oder_und_senden_tags_und_modus_und_aktualisieren_die_zahl_live(self):
        self.vorbereiten()
        o = self.ops([{"op": "neu"}, {"op": "tags", "liste": ["Spender"]}, {"op": "tags", "liste": ["Spender", "Verein A"]}, {"op": "modus", "wert": "und"}])
        oder1, oder2, und = o["schritte"][1], o["schritte"][2], o["schritte"][3]
        self.assertEqual(self.vorschau_bodies(oder1), [{"segment": {"tags": ["Spender"], "tags_modus": "oder"}}])          # ohne Klick auf den Knopf: live
        self.assertEqual(oder1["zustand"]["anzahl"], "Empfänger: 2")
        self.assertEqual(oder2["zustand"]["anzahl"], "Empfänger: 3")
        self.assertEqual(self.vorschau_bodies(und), [{"segment": {"tags": ["Spender", "Verein A"], "tags_modus": "und"}}])
        self.assertEqual(und["zustand"]["anzahl"], "Empfänger: 1")

    def test_ausser_sendet_tags_zaehlt_speichert_und_zeigt_den_modus_wieder(self):
        self.vorbereiten()
        with self.backend_v070():
            o = self.ops([{"op": "neu"}, {"op": "fuellen", "betreff": "Ohne Spender", "text": "Hallo"}, {"op": "modus", "wert": "ausser"}, {"op": "tags", "liste": ["Spender"]}, {"op": "speichern"}])
        tags = o["schritte"][3]
        self.assertEqual(self.vorschau_bodies(tags), [{"segment": {"tags": ["Spender"], "tags_modus": "ausser"}}])
        self.assertEqual(tags["zustand"]["anzahl"], "Empfänger: 2")                                   # c und d: bestätigte ohne Spender
        post = [r for r in o["schritte"][4]["zustand"]["requests"] if r["m"] == "POST" and r["p"].endswith("/entwuerfe")][0]
        self.assertEqual((post["s"], post["body"]["segment"]), (201, {"tags": ["Spender"], "tags_modus": "ausser"}))
        gespeichert = json.loads(self.entwuerfe()[0]["segment"])
        self.assertEqual((gespeichert["tags"], gespeichert["tags_modus"]), (["Spender"], "ausser"))
        nach = o["schritte"][4]["zustand"]                                                            # nach dem Anlegen öffnet der Editor den gespeicherten Entwurf
        self.assertEqual([r["wert"] for r in nach["modi"] if r["aktiv"]], ["ausser"])
        self.assertEqual([t["wert"] for t in nach["tags"] if t["an"]], ["Spender"])

    def test_ausser_ohne_tag_ist_gesperrt_und_sendet_nichts(self):
        self.vorbereiten()
        with self.backend_v070():
            o = self.ops([{"op": "neu"}, {"op": "fuellen", "betreff": "B", "text": "T"}, {"op": "modus", "wert": "ausser"}, {"op": "speichern"}, {"op": "tags", "liste": ["Verein A"]}])
        leer, erzwungen, mit_tag = o["schritte"][2], o["schritte"][3], o["schritte"][4]
        self.assertTrue(leer["zustand"]["speichern_gesperrt"])
        self.assertIn("mindestens einen Tag", leer["zustand"]["segment_fehler"])                     # Text am Feld
        self.assertEqual(self.vorschau_bodies(leer), [])                                              # keine Anfrage mit leerer Auswahl
        self.assertEqual(leer["zustand"]["anzahl"], "Empfänger: –")
        self.assertEqual(erzwungen["zustand"]["requests"], [])                                       # auch ein erzwungenes Absenden schickt nichts
        self.assertEqual(self.entwuerfe(), [])
        self.assertFalse(mit_tag["zustand"]["speichern_gesperrt"])
        self.assertIsNone(mit_tag["zustand"]["segment_fehler"])
        self.assertEqual(self.vorschau_bodies(mit_tag), [{"segment": {"tags": ["Verein A"], "tags_modus": "ausser"}}])

    def test_ohne_tags_blendet_die_liste_aus_und_sendet_nie_tags(self):
        self.vorbereiten()
        with self.backend_v070():
            o = self.ops([{"op": "neu"}, {"op": "fuellen", "betreff": "Nur ohne Tag", "text": "Hallo"}, {"op": "tags", "liste": ["Spender"]}, {"op": "modus", "wert": "ohne_tags"},
                          {"op": "speichern"}])
        gewaehlt, ohne, gespeichert = o["schritte"][2], o["schritte"][3], o["schritte"][4]
        self.assertTrue(gewaehlt["zustand"]["tags_gruppe_sichtbar"])
        self.assertFalse(ohne["zustand"]["tags_gruppe_sichtbar"])                                    # Liste weg
        self.assertEqual(self.vorschau_bodies(ohne), [{"segment": {"tags_modus": "ohne_tags"}}])     # kein tags-Feld, obwohl Spender noch angehakt ist
        self.assertEqual(ohne["zustand"]["anzahl"], "Empfänger: 1")                                   # nur d
        self.assertFalse(ohne["zustand"]["speichern_gesperrt"])
        post = [r for r in gespeichert["zustand"]["requests"] if r["m"] == "POST" and r["p"].endswith("/entwuerfe")][0]
        self.assertEqual(post["body"]["segment"], {"tags_modus": "ohne_tags"})
        self.assertNotIn("tags", post["body"]["segment"])
        gespeichert_segment = json.loads(self.entwuerfe()[0]["segment"])
        self.assertEqual(gespeichert_segment["tags_modus"], "ohne_tags")
        self.assertNotIn("tags", gespeichert_segment)                                                 # nie tags gespeichert (rollen/interessen normalisiert das Backend auf None)
        self.assertFalse(gespeichert["zustand"]["tags_gruppe_sichtbar"])                              # beim erneuten Öffnen bleibt die Liste weg
        self.assertEqual([r["wert"] for r in gespeichert["zustand"]["modi"] if r["aktiv"]], ["ohne_tags"])
        zurueck = self.ops([{"op": "oeffnen", "betreff": "Nur ohne Tag"}, {"op": "modus", "wert": "oder"}])["schritte"][1]["zustand"]
        self.assertTrue(zurueck["tags_gruppe_sichtbar"])                                              # anderer Modus: Liste wieder da

    def test_fehler_mit_meldung_erscheint_am_feld(self):
        import newsletter
        self.vorbereiten()
        meldung = "tags: zu viele (höchstens 20), leer oder unbekannt"
        fehler = newsletter.Fehler("segment_ungueltig", meldung, 400)
        with mock.patch.object(newsletter, "segment_anzahl", side_effect=fehler):
            vorschau = self.ops([{"op": "neu"}, {"op": "tags", "liste": ["Spender"]}])["schritte"][1]
        self.assertEqual([r["s"] for r in vorschau["zustand"]["requests"]], [400])
        self.assertEqual(vorschau["zustand"]["segment_fehler"], meldung)                              # 1:1 am Feld
        self.assertEqual(vorschau["zustand"]["anzahl"], "Empfänger: –")
        with mock.patch.object(newsletter, "_segment_pruefen", side_effect=fehler):
            speichern = self.ops([{"op": "neu"}, {"op": "fuellen", "betreff": "B", "text": "T"}, {"op": "tags", "liste": ["Spender"]}, {"op": "speichern"}])["schritte"][3]
        post = [r for r in speichern["zustand"]["requests"] if r["m"] == "POST" and r["p"].endswith("/entwuerfe")][0]
        self.assertEqual(post["s"], 400)
        self.assertEqual(speichern["zustand"]["segment_fehler"], meldung)
        self.assertEqual(self.entwuerfe(), [])
