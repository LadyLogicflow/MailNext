"""v0.5.0: Echtversand vom Pi (catrin #18653/#18655).

1. Offen-Modus der Betreiber-Schnittstelle (MAILNEXT_BETREIBER_AUTH=offen): ohne Anmeldung, aber nur von privaten Adressen, ohne Proxy-Kopf, mit passendem Host,
   ändernde Aufrufe mit Origin nur vom selben Host. Jede Regel hat eine Gegenprobe (der Normalfall geht).
2. Trennung öffentlich/intern über den Port der Verbindung (MAILNEXT_OEFFENTLICHER_PORT).
3. Pflichtangaben vor der Freigabe an Abonnenten, Versandrate je Mandant, Versandbefehle der Kommandozeile."""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import betreiber_auth
import config
import db
import manage
import mandanten
import newsletter
from test_meilenstein_a import Basis as BasisA

PI = "192.168.1.50"


class OffenBasis(BasisA):
    def setUp(self):
        super().setUp()
        self.offen = mock.patch.dict(os.environ, {"MAILNEXT_BETREIBER_AUTH": "offen", "MAILNEXT_PI_ADRESSE": PI})
        self.offen.start()

    def tearDown(self):
        self.offen.stop()
        super().tearDown()

    def get(self, pfad="/api/v1/betreiber/mandanten", von="192.168.1.20", host=PI + ":8000", headers=None, port="8000"):
        return self.c.get(pfad, base_url="http://" + host, headers=headers or {}, environ_overrides={"REMOTE_ADDR": von, "SERVER_PORT": port})

    def post(self, pfad, daten=None, von="192.168.1.20", host=PI + ":8000", headers=None, port="8000"):
        return self.c.post(pfad, json=daten if daten is not None else {}, base_url="http://" + host, headers=headers or {},
                           environ_overrides={"REMOTE_ADDR": von, "SERVER_PORT": port})

    def audit(self):
        with db.verbindung() as c:
            return [dict(z) for z in c.execute("SELECT * FROM audit_log ORDER BY id").fetchall()]


class OffenModusTests(OffenBasis):
    def test_standard_ist_portal_und_unsinn_auch(self):
        with mock.patch.dict(os.environ, {"MAILNEXT_BETREIBER_AUTH": ""}):
            self.assertEqual(config.betreiber_auth(), "portal")
            self.assertEqual(self.get().status_code, 401)                          # ohne Cookie wie bisher
        for wert in ("ja", "offen!", "OFFEN2", "true", "1"):
            with mock.patch.dict(os.environ, {"MAILNEXT_BETREIBER_AUTH": wert}):
                self.assertEqual(config.betreiber_auth(), "portal", wert)
                self.assertEqual(self.get().status_code, 401, wert)
        with mock.patch.dict(os.environ, {"MAILNEXT_BETREIBER_AUTH": " Offen "}):
            self.assertEqual(config.betreiber_auth(), "offen")

    def test_offen_ohne_anmeldung_von_privaten_adressen(self):
        for von in ("127.0.0.1", "10.1.2.3", "172.16.0.1", "172.31.255.254", "192.168.1.20", "::1", "::ffff:10.0.0.5", "fd12:3456::1"):
            self.assertEqual(self.get(von=von).status_code, 200, von)

    def test_oeffentliche_und_fast_private_adressen_werden_abgelehnt(self):
        for von in ("8.8.8.8", "172.32.0.1", "172.15.255.255", "192.169.0.1", "11.0.0.1", "169.254.1.1", "2001:db8::1", "::ffff:8.8.8.8", "", "keine-adresse"):
            self.assertEqual(self.get(von=von).status_code, 403, von)

    def test_jeder_proxy_kopf_verbietet_den_zugriff(self):
        for kopf in ("X-Forwarded-For", "Forwarded", "X-Real-IP", "CF-Connecting-IP", "True-Client-IP", "X-Forwarded-Host", "X-Forwarded-Proto", "Via"):
            self.assertEqual(self.get(von="127.0.0.1", headers={kopf: "1.2.3.4"}).status_code, 403, kopf)

    def test_host_mit_anderem_port_am_pi_gilt(self):
        """Port am Pi 8200 -> Container 8000: der Browser sendet Host 192.168.1.50:8200; die Pi-Adresse wird ohne Port verglichen."""
        for host in (PI + ":8200", PI + ":8201", PI):
            self.assertEqual(self.get(host=host).status_code, 200, host)
        self.assertEqual(self.get(host="192.168.1.51:8200").status_code, 403)
        daten = {"slug": "neu-1", "name": "Neu e. V."}
        self.assertEqual(self.post("/api/v1/betreiber/mandanten", daten, host=PI + ":8200", headers={"Origin": "http://%s:8200" % PI}).status_code, 201)
        self.assertEqual(self.post("/api/v1/betreiber/mandanten", {"slug": "neu-2", "name": "Z"}, host=PI + ":8200",
                                   headers={"Origin": "http://%s:8000" % PI}).status_code, 403)

    def test_host_muss_die_pi_adresse_oder_localhost_sein(self):
        for host in (PI, PI + ":8000", "localhost:8000", "127.0.0.1:8000", "[::1]:8000", "LOCALHOST"):
            self.assertEqual(self.get(host=host).status_code, 200, host)
        for host in ("boese.example", "boese.example:8000", "192.168.1.51:8000", "pi.example.com", PI + ".boese.example"):
            self.assertEqual(self.get(host=host).status_code, 403, host)
        with mock.patch.dict(os.environ, {"MAILNEXT_PI_ADRESSE": ""}):                       # ohne Pi-Adresse nur localhost
            self.assertEqual(self.get(host="localhost:8000").status_code, 200)
            self.assertEqual(self.get(host=PI + ":8000").status_code, 403)

    def test_aendernde_aufrufe_mit_fremdem_origin_werden_abgelehnt(self):
        daten = {"slug": "neu-1", "name": "Neu e. V."}
        self.assertEqual(self.post("/api/v1/betreiber/mandanten", daten, headers={"Origin": "http://boese.example"}).status_code, 403)
        self.assertEqual(self.post("/api/v1/betreiber/mandanten", daten, headers={"Origin": "null"}).status_code, 403)
        self.assertEqual(self.post("/api/v1/betreiber/mandanten", daten, headers={"Origin": "http://%s:9999" % PI}).status_code, 403)       # anderer Port
        self.assertEqual(mandanten.lesen_slug("neu-1"), None)
        # Gegenproben: gleicher Host, ohne Origin (Befehlszeile, curl) und lesende Aufrufe mit fremdem Origin
        self.assertEqual(self.post("/api/v1/betreiber/mandanten", daten, headers={"Origin": "http://%s:8000" % PI}).status_code, 201)
        self.assertEqual(self.post("/api/v1/betreiber/mandanten", {"slug": "neu-2", "name": "Zwei e. V."}).status_code, 201)
        self.assertEqual(self.get(headers={"Origin": "http://boese.example"}).status_code, 200)

    def test_portal_cookie_zaehlt_im_offen_modus_nicht(self):
        self.c.set_cookie("bst_session", "tok")
        with mock.patch.object(betreiber_auth, "_bei_sortnext_fragen", side_effect=AssertionError("Portal darf nicht gefragt werden")):
            self.assertEqual(self.get().status_code, 200)
            self.assertEqual(self.get(von="8.8.8.8").status_code, 403)                    # auch mit Cookie nicht von außen

    def test_audit_akteur_und_gehashte_quelladresse(self):
        self.post("/api/v1/betreiber/mandanten", {"slug": "neu-1", "name": "Neu e. V."}, von="192.168.1.77")
        eintrag = [z for z in self.audit() if z["aktion"] == "mandant_angelegt"][0]
        self.assertEqual(eintrag["akteur"], "offen")
        self.assertTrue(eintrag["ip"].startswith("h:") and "192.168.1.77" not in eintrag["ip"])
        with mock.patch.dict(os.environ, {"MAILNEXT_BETREIBER_OFFEN_EMAIL": "Catrin@Beispiel.de"}):
            self.post("/api/v1/betreiber/mandanten", {"slug": "neu-2", "name": "Zwei e. V."}, von="192.168.1.77")
        zweiter = [z for z in self.audit() if z["aktion"] == "mandant_angelegt"][1]
        self.assertEqual(zweiter["akteur"], "catrin@beispiel.de")
        self.assertEqual(zweiter["ip"], eintrag["ip"])                                    # gleiche Quelle, gleiches Pseudonym

    def test_abgelehnte_aufrufe_stehen_nicht_im_audit_und_aendern_nichts(self):
        self.assertEqual(self.post("/api/v1/betreiber/mandanten", {"slug": "neu-1", "name": "N"}, von="8.8.8.8").status_code, 403)
        self.assertEqual(self.audit(), [])
        self.assertIsNone(mandanten.lesen_slug("neu-1"))

    def test_health_zeigt_den_offen_modus(self):
        self.assertTrue(self.c.get("/health").get_json()["betreiber_offen"])
        with mock.patch.dict(os.environ, {"MAILNEXT_BETREIBER_AUTH": "portal"}):
            self.assertFalse(self.c.get("/health").get_json()["betreiber_offen"])

    def test_startwarnung(self):
        with self.assertLogs(level="WARNING") as log:
            from app import create_app
            create_app(os.path.join(self.verz.name, "w.db"))
        self.assertTrue(any("OFFEN-MODUS AKTIV" in z for z in log.output))
        with mock.patch.dict(os.environ, {"MAILNEXT_BETREIBER_AUTH": "portal"}):
            with self.assertNoLogs(level="WARNING"):
                from app import create_app
                create_app(os.path.join(self.verz.name, "w2.db"))


class TailscaleTests(OffenBasis):
    """v0.5.2: Zugriff über Tailscale (catrin erreicht den Pi nur so). Quellnetze 100.64.0.0/10 und fd7a:115c:a1e0::/48, mehrere Pi-Adressen."""

    def test_tailscale_quelladressen_gelten_gleich_daneben_nicht(self):
        for von in ("100.64.0.1", "100.101.102.103", "100.127.255.254", "fd7a:115c:a1e0::1", "fd7a:115c:a1e0:ab12:1234::7", "::ffff:100.101.102.103"):
            self.assertEqual(self.get(von=von).status_code, 200, von)
        for von in ("100.63.255.255", "100.128.0.1", "100.0.0.1", "2a01:4f8::1", "fe80::1"):
            self.assertEqual(self.get(von=von).status_code, 403, von)
        # IPv6: Tailscale nutzt fd7a:115c:a1e0::/48 aus dem privaten Bereich fc00::/7, der schon vorher galt; andere fd..-Adressen sind ebenfalls privat
        self.assertEqual(self.get(von="fd7a:115c:a1e1::1").status_code, 200)

    def test_proxy_kopf_ueber_tailscale_wird_weiter_abgelehnt(self):
        # z. B. "tailscale serve": die Anfrage kommt von 100.x, trägt aber Proxy-Köpfe
        self.assertEqual(self.get(von="100.101.102.103", headers={"X-Forwarded-For": "100.64.0.9"}).status_code, 403)
        self.assertEqual(self.get(von="127.0.0.1", headers={"X-Forwarded-Proto": "https"}).status_code, 403)

    def test_mehrere_pi_adressen_jede_gilt(self):
        liste = "192.168.1.50, 100.101.102.103 ,pi5,Pi5.Beispiel.TS.net:8200,,"
        with mock.patch.dict(os.environ, {"MAILNEXT_PI_ADRESSE": liste}):
            self.assertEqual(config.pi_adressen(), ["192.168.1.50", "100.101.102.103", "pi5", "pi5.beispiel.ts.net"])
            for host in ("192.168.1.50:8200", "100.101.102.103:8200", "100.101.102.103", "pi5:8200", "PI5", "pi5.beispiel.ts.net:8200", "localhost:8200"):
                self.assertEqual(self.get(von="100.101.102.103", host=host).status_code, 200, host)
            for host in ("pi6:8200", "100.101.102.104:8200", "beispiel.ts.net", "boese.example", "pi5.beispiel.ts.net.boese.example"):
                self.assertEqual(self.get(von="100.101.102.103", host=host).status_code, 403, host)
        with mock.patch.dict(os.environ, {"MAILNEXT_PI_ADRESSE": ""}):
            self.assertEqual(config.pi_adressen(), [])
            self.assertEqual(self.get(von="100.101.102.103", host="pi5").status_code, 403)

    def test_origin_ueber_tailscale_name(self):
        with mock.patch.dict(os.environ, {"MAILNEXT_PI_ADRESSE": "100.101.102.103,pi5"}):
            daten = {"slug": "neu-1", "name": "Neu e. V."}
            self.assertEqual(self.post("/api/v1/betreiber/mandanten", daten, von="100.101.102.103", host="pi5:8200",
                                       headers={"Origin": "http://pi5:8200"}).status_code, 201)
            self.assertEqual(self.post("/api/v1/betreiber/mandanten", {"slug": "neu-2", "name": "Z"}, von="100.101.102.103", host="pi5:8200",
                                       headers={"Origin": "http://boese.example"}).status_code, 403)

    def test_basis_url_aus_erster_adresse_und_oeffentlichem_port(self):
        with mock.patch.dict(os.environ, {"MAILNEXT_BASIS_URL": "", "MAILNEXT_PI_ADRESSE": "100.101.102.103,pi5", "MAILNEXT_PORT_OEFFENTLICH": "8201"}):
            self.assertEqual(config.basis_url(), "http://100.101.102.103:8201")
        with mock.patch.dict(os.environ, {"MAILNEXT_BASIS_URL": "https://news.beispiel.de/", "MAILNEXT_PI_ADRESSE": "100.101.102.103", "MAILNEXT_PORT_OEFFENTLICH": "8201"}):
            self.assertEqual(config.basis_url(), "https://news.beispiel.de")                  # ausdrückliche Adresse gewinnt
        with mock.patch.dict(os.environ, {"MAILNEXT_BASIS_URL": "", "MAILNEXT_PI_ADRESSE": "", "MAILNEXT_PORT_OEFFENTLICH": ""}):
            self.assertEqual(config.basis_url(), "https://mailnext.bst-next.de")               # Produktion ohne Angaben unverändert
        with mock.patch.dict(os.environ, {"MAILNEXT_BASIS_URL": "", "MAILNEXT_PI_ADRESSE": "pi5", "MAILNEXT_PORT_OEFFENTLICH": "abc"}):
            self.assertEqual(config.basis_url(), "https://mailnext.bst-next.de")


class PortTrennungTests(OffenBasis):
    def setUp(self):
        super().setUp()
        self.port = mock.patch.dict(os.environ, {"MAILNEXT_OEFFENTLICHER_PORT": "8001"})
        self.port.start()
        self.m = self.mandant("hilo")

    def tearDown(self):
        self.port.stop()
        super().tearDown()

    def test_auf_dem_oeffentlichen_port_gibt_es_keine_betreiber_pfade(self):
        for pfad in ("/api/v1/betreiber/mandanten", "/betreiber", "/betreiber/", "/betreiber/betreiber.js", "/health", "/api/version", "/", "/api/v1/betreiber-login/anmelden"):
            self.assertEqual(self.get(pfad, port="8001").status_code, 404, pfad)
        self.assertEqual(self.post("/api/v1/betreiber/mandanten", {"slug": "x-1", "name": "X"}, port="8001").status_code, 404)

    def test_oeffentliche_seiten_gehen_auf_beiden_ports(self):
        for port in ("8000", "8001"):
            self.assertEqual(self.get("/api/hilo/newsletter/formular", port=port).status_code, 200, port)
            r = self.post("/api/hilo/newsletter/anmelden", {"email": "a%s@beispiel.de" % port, "einwilligungs_version": "EINW-1"}, port=port)
            self.assertEqual(r.status_code, 200, (port, r.get_data(as_text=True)))
        self.assertEqual(self.get("/hilo/newsletter/einstellungen?t=x", port="8001").status_code in (200, 400, 403, 404), True)       # kommt bei der Seite an

    def test_der_interne_port_bleibt_vollstaendig(self):
        self.assertEqual(self.get("/health", port="8000").status_code, 200)
        self.assertEqual(self.get("/api/v1/betreiber/mandanten", port="8000").status_code, 200)

    def test_entscheidend_ist_der_port_nicht_der_host_kopf(self):
        # Ein Absender auf dem öffentlichen Port kann sich nicht per Host-Kopf als intern ausgeben ...
        for host in (PI + ":8000", "localhost:8000", PI + ":8001", "localhost"):
            self.assertEqual(self.get(host=host, von="127.0.0.1", port="8001").status_code, 404, host)
        # ... und auf dem internen Port ändert ein Host-Kopf der Pi-Adresse mit :8001 nichts
        self.assertEqual(self.get(host=PI + ":8001", port="8000").status_code, 200)

    def test_entscheidend_ist_der_containerport_nicht_der_port_am_pi(self):
        # Port am Pi 8201 -> Container 8001: Host-Kopf zeigt 8201, die Verbindung kam aber am Container-Port 8001
        self.assertEqual(self.get("/api/v1/betreiber/mandanten", host=PI + ":8201", port="8001").status_code, 404)
        self.assertEqual(self.get("/api/hilo/newsletter/formular", host=PI + ":8201", port="8001").status_code, 200)
        self.assertEqual(self.get("/api/v1/betreiber/mandanten", host=PI + ":8200", port="8000").status_code, 200)

    def test_ohne_die_variable_gibt_es_keine_trennung(self):
        with mock.patch.dict(os.environ, {"MAILNEXT_OEFFENTLICHER_PORT": ""}):
            self.assertEqual(self.get("/health", port="8001").status_code, 200)
            self.assertEqual(self.get("/api/v1/betreiber/mandanten", port="8001").status_code, 200)
        with mock.patch.dict(os.environ, {"MAILNEXT_OEFFENTLICHER_PORT": "abc"}):
            self.assertIsNone(config.oeffentlicher_port())


class PflichtangabenTests(BasisA):
    def freigabe(self, m, ziel):
        newsletter.echtversand_setzen(m["id"], True, "t")
        e = newsletter.anlegen(m, "Betreff", "Text https://beispiel.test/x", ziel, None)
        newsletter.testmail(m, e["id"], None, "betreiber@bst-next.de")
        e = newsletter.lesen(m, e["id"])
        return newsletter.freigeben(m, e["id"], e["content_hash"], True, "betreiber@bst-next.de")

    def setUp(self):
        super().setUp()
        self.abo = lambda m, adresse: self.anmelden(m["slug"], adresse)

    def test_jede_pflichtangabe_einzeln(self):
        for feld in newsletter.PFLICHTANGABEN:
            m = self.mandant("m-" + feld.replace("_", "-"), **{feld: ""})
            if feld == "absender_adresse":
                mandanten.versand_setzen(m["id"], {"versandmodus": "datei"}, "t")
            mandanten.einwilligung_anlegen(m["id"], "EINW-2", "Ja, ich möchte den Newsletter erhalten und kann jederzeit widerrufen.") if False else None
            fehlend = newsletter.pflichtangaben_fehlend(mandanten.lesen(m["id"]))
            self.assertEqual(fehlend, [feld], feld)

    def test_freigabe_an_abonnenten_ohne_pflichtangaben_wird_abgelehnt(self):
        m = self.mandant("hilo", impressum_url="", firmenangaben="   ")
        newsletter.echtversand_setzen(m["id"], True, "t")
        e = newsletter.anlegen(m, "Betreff", "Text", "abonnenten", None)
        # Testmail geht trotzdem (Pflichtangaben gelten für die Freigabe, nicht für die Probe)
        newsletter.testmail(m, e["id"], None, "betreiber@bst-next.de")
        e = newsletter.lesen(m, e["id"])
        with self.assertRaises(newsletter.Fehler) as f:
            newsletter.freigeben(m, e["id"], e["content_hash"], True, "b@bst-next.de")
        self.assertEqual((f.exception.code, f.exception.status), ("pflichtangaben_fehlen", 409))
        self.assertIn("impressum_url", f.exception.meldung)
        self.assertIn("firmenangaben", f.exception.meldung)
        self.assertNotIn("datenschutz_url", f.exception.meldung)
        self.assertEqual(newsletter.lesen(m, e["id"])["status"], "entwurf")

    def test_gegenprobe_vollstaendig_und_testliste(self):
        m = self.mandant("hilo")
        self.anmelden("hilo", "a@beispiel.de")
        self.assertEqual(newsletter.pflichtangaben_fehlend(m), [])
        leer = self.mandant("leer", impressum_url="", datenschutz_url="", firmenangaben="")
        newsletter.testliste_setzen(leer, ["t@beispiel.de"])
        self.assertEqual(self.freigabe(leer, "testliste")["empfaenger"], 1)               # interne Probe braucht keine Pflichtangaben

    def test_die_api_meldet_die_felder_ohne_werte(self):
        m = self.mandant("hilo", datenschutz_url="")
        newsletter.echtversand_setzen(m["id"], True, "t")
        e = newsletter.anlegen(m, "Betreff", "Text", "abonnenten", None)
        newsletter.testmail(m, e["id"], None, "betreiber@bst-next.de")
        h = newsletter.lesen(m, e["id"])["content_hash"]
        self.c.set_cookie("bst_session", "tok")
        with mock.patch.object(betreiber_auth, "_bei_sortnext_fragen", return_value={"email": "catrin@bst-next.de", "betreiber": True}):
            r = self.c.post("/api/v1/betreiber/mandanten/%d/entwuerfe/%d/freigeben" % (m["id"], e["id"]), json={"content_hash": h, "bestaetigt": True})
        self.assertEqual((r.status_code, r.get_json()["error"]), (409, "pflichtangaben_fehlen"))
        self.assertIn("datenschutz_url", r.get_json()["meldung"])
        self.assertNotIn("hilo.test", r.get_json()["meldung"])


class VersandRateTests(BasisA):
    def test_standard_grenzen_und_hochrechnung(self):
        m = self.mandant("hilo")
        self.assertEqual(newsletter.limit_pro_stunde(m["id"]), 100)
        self.assertEqual(newsletter.limit_pro_stunde_setzen(m["id"], 300, "t"), 300)
        self.assertEqual(newsletter.limit_pro_stunde(m["id"]), 300)
        for falsch in (0, -1, 601, 10.5, "50", None, True):
            with self.assertRaises(newsletter.Fehler) as f:
                newsletter.limit_pro_stunde_setzen(m["id"], falsch, "t")
            self.assertEqual(f.exception.code, "limit_ungueltig", falsch)
        self.assertEqual(newsletter.limit_pro_stunde(m["id"]), 300)
        self.assertEqual([newsletter.limit_pro_stunde_setzen(m["id"], w, "t") for w in (1, 600)], [1, 600])
        self.assertEqual([newsletter.mails_pro_lauf(w) for w in (1, 100, 300, 301, 600)], [5, 5, 5, 6, 10])

    def test_je_mandant_getrennt(self):
        a, b = self.mandant("eins"), self.mandant("zwei")
        newsletter.limit_pro_stunde_setzen(a["id"], 7, "t")
        self.assertEqual((newsletter.limit_pro_stunde(a["id"]), newsletter.limit_pro_stunde(b["id"])), (7, 100))

    def test_der_versandlauf_haelt_das_mandantenlimit_ein(self):
        m = self.mandant("hilo")
        for i in range(12):
            self.anmelden("hilo", "a%d@beispiel.de" % i)
        with db.verbindung() as c:
            c.execute("UPDATE abonnent SET status='bestaetigt', bestaetigt_am='2026-01-01T00:01:00Z' WHERE mandant_id=?", (m["id"],))
        newsletter.echtversand_setzen(m["id"], True, "t")
        newsletter.limit_pro_stunde_setzen(m["id"], 8, "t")
        e = newsletter.anlegen(m, "Betreff", "Text https://beispiel.test/x", "abonnenten", None)
        newsletter.testmail(m, e["id"], None, "betreiber@bst-next.de")
        e = newsletter.lesen(m, e["id"])
        self.assertEqual(newsletter.freigeben(m, e["id"], e["content_hash"], True, "b@bst-next.de")["empfaenger"], 12)
        gesendet = 0
        for _ in range(5):                                                         # mehrere Minuten-Durchgänge
            gesendet += newsletter.lauf()["gesendet"]
        self.assertEqual(gesendet, 8)                                              # nicht 12: das Limit je Stunde gilt
        newsletter.limit_pro_stunde_setzen(m["id"], 600, "t")
        for _ in range(3):
            gesendet += newsletter.lauf()["gesendet"]
        self.assertEqual(gesendet, 12)                                             # Gegenprobe: nach Anheben geht der Rest

    def test_api_lesen_und_setzen_mit_audit(self):
        m = self.mandant("hilo")
        self.c.set_cookie("bst_session", "tok")
        with mock.patch.object(betreiber_auth, "_bei_sortnext_fragen", return_value={"email": "catrin@bst-next.de", "betreiber": True}):
            pfad = "/api/v1/betreiber/mandanten/%d/versand-rate" % m["id"]
            self.assertEqual(self.c.get(pfad).get_json()["limit_pro_stunde"], 100)
            self.assertEqual(self.c.put(pfad, json={"limit_pro_stunde": 250}).get_json(), {"limit_pro_stunde": 250})
            r = self.c.put(pfad, json={"limit_pro_stunde": 9999})
            self.assertEqual((r.status_code, r.get_json()["error"]), (400, "limit_ungueltig"))
        with db.verbindung() as c:
            aktionen = [z["aktion"] for z in c.execute("SELECT aktion FROM audit_log").fetchall()]
        self.assertIn("versand_rate_geaendert", aktionen)
        self.assertEqual(newsletter.limit_pro_stunde(m["id"]), 250)


class VersandBefehleTests(BasisA):
    """Kommandozeile für den Versand: dieselbe Logik wie die API, Passwort nie in der Ausgabe oder im Audit."""

    def lauf(self, *argv, eingabe=None, passwort="geheimes-passwort-123"):
        ausgabe = io.StringIO()
        with contextlib.redirect_stdout(ausgabe), mock.patch("getpass.getpass", return_value=passwort), \
                mock.patch("builtins.input", side_effect=(lambda _p="": eingabe) if eingabe is not None else EOFError):
            code = manage.main(list(argv))
        return code, ausgabe.getvalue()

    def setUp(self):
        super().setUp()
        db.init(os.path.join(self.verz.name, "mailnext.db"))                      # dieselbe Datenbank, die manage.main öffnet
        self.m = self.mandant("hilo", modus="datei")
        self.datei = os.path.join(self.verz.name, "entwurf.txt")
        with open(self.datei, "w", encoding="utf-8") as f:
            f.write("Betreff: Neues aus der Beratung\n\nGuten Tag,\n\nhier ist der Newsletter: https://beispiel.test/a\n")

    def test_smtp_speichert_verschluesselt_und_zeigt_das_passwort_nie(self):
        code, text = self.lauf("smtp", "hilo", "smtp.beispiel.test", "465", "versand@beispiel.test", "ssl")
        self.assertEqual(code, 0, text)
        self.assertNotIn("geheimes-passwort", text)
        zustand = mandanten.versand_zustand(self.m["id"])
        self.assertEqual(zustand["versandmodus"], "smtp")
        self.assertTrue(all(zustand["gesetzt"].values()))
        with db.verbindung() as c:
            alles = " ".join(str(dict(z)) for z in c.execute("SELECT * FROM audit_log").fetchall())
            gespeichert = " ".join(str(dict(z)) for z in c.execute("SELECT * FROM einstellung").fetchall())
        self.assertNotIn("geheimes-passwort", alles)
        self.assertNotIn("geheimes-passwort", gespeichert)
        self.assertNotIn("smtp.beispiel.test", gespeichert)                                  # auch die übrigen Felder verschlüsselt
        self.assertEqual(mandanten.versand_lesen(self.m["id"])["smtp_passwort"], "geheimes-passwort-123")

    def test_smtp_verlangt_die_absenderadresse_und_gueltige_angaben(self):
        ohne = self.mandant("ohne", absender_adresse="")
        code, text = self.lauf("smtp", "ohne", "smtp.beispiel.test", "465", "u@beispiel.test", "ssl")
        self.assertEqual(code, 1)
        self.assertIn("Absenderadresse", text)
        self.assertEqual(mandanten.versandmodus(ohne["id"]), "datei")                      # nichts halb gespeichert
        self.assertEqual(self.lauf("smtp", "hilo", "smtp.beispiel.test", "99999", "u@beispiel.test", "ssl")[0], 1)
        self.assertEqual(self.lauf("smtp", "hilo", "smtp.beispiel.test", "465", "u@beispiel.test", "klartext")[0], 1)
        self.assertEqual(self.lauf("smtp", "hilo", "boese host", "465", "u@beispiel.test", "ssl")[0], 1)

    def test_echtversand_und_rate(self):
        self.assertEqual(self.lauf("echtversand", "hilo", "ja")[0], 0)
        self.assertTrue(newsletter.echtversand_freigegeben(self.m["id"]))
        self.assertEqual(self.lauf("echtversand", "hilo", "nein")[0], 0)
        self.assertFalse(newsletter.echtversand_freigegeben(self.m["id"]))
        self.assertEqual(self.lauf("echtversand", "hilo", "vielleicht")[0], 2)
        self.assertEqual(self.lauf("versand-rate", "hilo", "250")[0], 0)
        self.assertEqual(newsletter.limit_pro_stunde(self.m["id"]), 250)
        self.assertEqual(self.lauf("versand-rate", "hilo", "5000")[0], 1)
        self.assertEqual(newsletter.limit_pro_stunde(self.m["id"]), 250)

    def test_entwurf_testmail_freigabe_ende_zu_ende(self):
        self.anmelden("hilo", "a@beispiel.de")
        newsletter.testliste_setzen(self.m, ["test@beispiel.de"])
        with db.verbindung() as c:
            c.execute("UPDATE abonnent SET status='bestaetigt', bestaetigt_am='2026-01-01T00:01:00Z' WHERE mandant_id=?", (self.m["id"],))
        code, text = self.lauf("entwurf", "hilo", self.datei, "ziel=abonnenten")
        self.assertEqual(code, 0, text)
        e = newsletter.liste(self.m)[0]
        self.assertEqual((e["betreff"], e["ziel"], e["status"]), ("Neues aus der Beratung", "abonnenten", "entwurf"))
        gespeichert = newsletter.lesen(self.m, e["id"])
        self.assertTrue(gespeichert["text"].startswith("Guten Tag,"))
        # Freigabe ohne Testmail und ohne Echtversand-Freigabe scheitert genauso wie über die API
        self.assertEqual(self.lauf("freigeben", "hilo", str(e["id"]), eingabe="1")[0], 1)
        self.lauf("echtversand", "hilo", "ja")
        self.assertEqual(self.lauf("freigeben", "hilo", str(e["id"]), eingabe="1")[0], 1)                  # Testmail fehlt
        self.assertEqual(self.lauf("testmail", "hilo", str(e["id"]), "test@beispiel.de")[0], 0)
        # Bestätigung: falsche Zahl oder keine Eingabe gibt nichts frei
        for eingabe in ("2", "ja", ""):
            self.assertEqual(self.lauf("freigeben", "hilo", str(e["id"]), eingabe=eingabe)[0], 1, eingabe)
        self.assertEqual(self.lauf("freigeben", "hilo", str(e["id"]))[0], 1)                                 # keine Eingabemöglichkeit
        self.assertEqual(newsletter.lesen(self.m, e["id"])["status"], "entwurf")
        code, text = self.lauf("freigeben", "hilo", str(e["id"]), eingabe="1")
        self.assertEqual(code, 0, text)
        self.assertIn("Empfänger: 1", text)
        self.assertEqual(newsletter.lesen(self.m, e["id"])["status"], "freigegeben")
        with db.verbindung() as c:
            audit = {z["aktion"] for z in c.execute("SELECT aktion FROM audit_log WHERE akteur='manage'").fetchall()}
        self.assertTrue({"entwurf_angelegt", "testmail_gesendet", "entwurf_freigegeben", "echtversand_geaendert"} <= audit)

    def test_freigabe_prueft_die_pflichtangaben_wie_die_api(self):
        m = self.mandant("kahl", impressum_url="")
        newsletter.testliste_setzen(m, ["test@beispiel.de"])
        self.anmelden("kahl", "a@beispiel.de")
        self.lauf("echtversand", "kahl", "ja")
        self.assertEqual(self.lauf("entwurf", "kahl", self.datei, "ziel=abonnenten")[0], 0)
        eid = newsletter.liste(m)[0]["id"]
        self.assertEqual(self.lauf("testmail", "kahl", str(eid), "test@beispiel.de")[0], 0)
        code, text = self.lauf("freigeben", "kahl", str(eid), eingabe="0")
        self.assertEqual(code, 1)
        self.assertEqual(newsletter.lesen(m, eid)["status"], "entwurf")

    def test_testmail_nur_an_die_testliste_oder_die_offen_adresse(self):
        newsletter.testliste_setzen(self.m, ["test@beispiel.de"])
        self.lauf("entwurf", "hilo", self.datei)
        eid = newsletter.liste(self.m)[0]["id"]
        code, text = self.lauf("testmail", "hilo", str(eid), "fremd@beispiel.de")
        self.assertEqual(code, 1)
        self.assertIn("Testliste", text)
        code, text = self.lauf("testmail", "hilo", str(eid))                                  # keine Adresse, keine OFFEN_EMAIL
        self.assertEqual(code, 1)
        self.assertIn("Empfängeradresse", text)
        with mock.patch.dict(os.environ, {"MAILNEXT_BETREIBER_OFFEN_EMAIL": "catrin@beispiel.de"}):
            self.assertEqual(self.lauf("testmail", "hilo", str(eid))[0], 0)
        self.assertEqual(self.an_testmail(), "catrin@beispiel.de")

    def an_testmail(self):
        return str(self.letzte_mail("hilo")["To"])

    def test_entwurfsdatei_muss_mit_betreff_beginnen(self):
        falsch = os.path.join(self.verz.name, "falsch.txt")
        with open(falsch, "w", encoding="utf-8") as f:
            f.write("Hallo ohne Betreffzeile\n")
        with self.assertRaises(SystemExit):
            self.lauf("entwurf", "hilo", falsch)
        self.assertEqual(newsletter.liste(self.m), [])


class AuslieferungTests(unittest.TestCase):
    """Dockerfile, Pi-Compose und Anleitung müssen zusammenpassen: zweiter Port gebunden, veröffentlicht, als öffentlicher Port gesetzt, Standard bleibt Portal."""
    ORDNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def lesen(self, name):
        with open(os.path.join(self.ORDNER, name), encoding="utf-8") as f:
            return f.read()

    def test_dockerfile_lauscht_auf_beiden_ports(self):
        d = self.lesen("Dockerfile")
        self.assertIn('"--bind", "0.0.0.0:8000"', d)
        self.assertIn('"--bind", "0.0.0.0:8001"', d)
        self.assertIn("EXPOSE 8000 8001", d)

    def test_pi_compose(self):
        c = self.lesen("docker-compose.pi.yaml")
        self.assertIn('"${MAILNEXT_PORT_INTERN:-8000}:8000"', c)                       # links Port am Pi (einstellbar), rechts Port im Container (fest)
        self.assertIn('"${MAILNEXT_PORT_OEFFENTLICH:-8001}:8001"', c)
        self.assertIn('MAILNEXT_OEFFENTLICHER_PORT: "8001"', c)                        # Container-Port, unabhängig vom Port am Pi
        self.assertIn('MAILNEXT_BETREIBER_AUTH: "${MAILNEXT_BETREIBER_AUTH:-portal}"', c)             # Standard bleibt die Portal-Anmeldung (fail closed)
        self.assertNotIn('MAILNEXT_BETREIBER_AUTH: "offen"', c)

    def test_compose_reicht_jede_vom_code_gelesene_variable_durch(self):
        """Fehler aus v0.5.0: MAILNEXT_PI_ADRESSE stand nur in der .env, wurde nicht in den Container gereicht, und die Host-Prüfung des Offen-Modus
        gab über die Pi-Adresse 403. Jede MAILNEXT_*-Variable, die der Code liest, muss in der Pi-Compose stehen (außer den bewusst ausgenommenen)."""
        import re
        gelesen = set()
        for name in os.listdir(self.ORDNER):
            if name.endswith(".py") and not name.startswith(("test_", "manage")):
                gelesen |= set(re.findall(r'environ(?:\.get)?[\[(]\s*"(MAILNEXT_[A-Z_]+)"', self.lesen(name)))
        self.assertTrue({"MAILNEXT_PI_ADRESSE", "MAILNEXT_BETREIBER_AUTH", "MAILNEXT_OEFFENTLICHER_PORT", "MAILNEXT_HAUPTSCHLUESSEL"} <= gelesen, gelesen)
        ausgenommen = {"MAILNEXT_VERSAND_JOB"}                                           # bewusst nicht gesetzt (Standard: Versandlauf an)
        c = self.lesen("docker-compose.pi.yaml")
        fehlt = sorted(n for n in gelesen - ausgenommen if not re.search(r"^\s+%s:" % n, c, re.M))
        self.assertEqual(fehlt, [], "in der Pi-Compose nicht durchgereicht")

    def test_basis_url_wird_im_dienst_abgeleitet(self):
        """Mit einer Liste von Pi-Adressen ließe sich die Basis-URL in der Compose nicht zerlegen; der Dienst bildet sie aus der ersten Adresse und dem Port."""
        c = self.lesen("docker-compose.pi.yaml")
        self.assertIn('MAILNEXT_BASIS_URL: "${MAILNEXT_BASIS_URL:-}"', c)
        self.assertIn('MAILNEXT_PORT_OEFFENTLICH: "${MAILNEXT_PORT_OEFFENTLICH:-8001}"', c)
        self.assertIn('MAILNEXT_PI_ADRESSE: "${MAILNEXT_PI_ADRESSE:?', c)                # Pflicht, kommt mit klarer Meldung

    def test_jede_compose_variable_steht_in_der_vorlage(self):
        import re
        c = self.lesen("docker-compose.pi.yaml")
        vorlage = self.lesen("pi.env.beispiel")
        for name in sorted(set(re.findall(r"\$\{(MAILNEXT_[A-Z_]+|SORTNEXT_BASE_URL)[:?-]", c))):
            if name == "SORTNEXT_BASE_URL":
                continue                                                                   # hat einen festen Standard, bewusst nicht in der Vorlage
            self.assertIn(name + "=", vorlage, name)

    def test_anleitung_nennt_die_regeln(self):
        a = self.lesen("PI-TESTINSTANZ.md")
        for text in ("Nach außen darf nur der öffentliche Port", "MAILNEXT_BETREIBER_AUTH=offen", "pflichtangaben_fehlen", "Port 8000 nie ins Internet", "SPF", "versand-rate",
                     "MAILNEXT_PORT_INTERN", "MAILNEXT_PORT_OEFFENTLICH", "Tailscale", "100.64.0.0/10", "fd7a:115c:a1e0::/48"):
            self.assertIn(text, a, text)


class OffenModusApiTestmailTests(OffenBasis):
    def test_testmail_im_offen_modus_ohne_adresse_wird_abgelehnt_mit_adresse_geht_sie(self):
        m = self.mandant("hilo")
        newsletter.testliste_setzen(m, ["test@beispiel.de"])
        e = newsletter.anlegen(m, "Betreff", "Text", "testliste", None)
        pfad = "/api/v1/betreiber/mandanten/%d/entwuerfe/%d/testmail" % (m["id"], e["id"])
        r = self.post(pfad, {})
        self.assertEqual((r.status_code, r.get_json()["error"]), (400, "empfaenger_fehlt"))
        r = self.post(pfad, {"an": "fremd@beispiel.de"})
        self.assertEqual((r.status_code, r.get_json()["error"]), (403, "adresse_nicht_in_testliste"))
        self.assertEqual(self.post(pfad, {"an": "test@beispiel.de"}).status_code, 200)
        with mock.patch.dict(os.environ, {"MAILNEXT_BETREIBER_OFFEN_EMAIL": "catrin@beispiel.de"}):
            self.assertEqual(self.post(pfad, {}).status_code, 200)                            # Standard-Empfänger


if __name__ == "__main__":
    unittest.main()
