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


if __name__ == "__main__":
    unittest.main()
