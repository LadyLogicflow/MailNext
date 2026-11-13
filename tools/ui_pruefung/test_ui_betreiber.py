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


if __name__ == "__main__":
    unittest.main()
