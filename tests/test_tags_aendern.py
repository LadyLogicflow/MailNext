"""Tags nachträglich ändern (catrin #19236): POST .../abonnenten/tags-aendern. Nur erfundene Adressen."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import abonnenten
import betreiber_auth
import db
import import_csv
import newsletter
from test_meilenstein_b import Basis


class BasisTags(Basis):
    def tags_setzen(self, m, adresse, tags):
        with db.verbindung() as c:
            c.execute("UPDATE abonnent SET tags=? WHERE id=?", (json.dumps(tags, ensure_ascii=False), self.zeile(m["id"], adresse)["id"]))

    def tags(self, m, adresse):
        return json.loads(self.zeile(m["id"], adresse)["tags"] or "[]")

    def nr(self, m, adresse):
        return self.zeile(m["id"], adresse)["id"]

    def vorbereiten(self):
        m = self.mandant("hilo")
        for a, tags in (("a@beispiel.de", ["Spender"]), ("b@beispiel.de", []), ("c@beispiel.de", ["Verein A", "Spender"])):
            self.abo(m, a)
            self.tags_setzen(m, a, tags)
        return m

    def aendern(self, m, ids, hinzufuegen=None, entfernen=None):
        return abonnenten.tags_aendern(m, ids, hinzufuegen, entfernen)

    def fehler(self, m, *args):
        with self.assertRaises(abonnenten.FormFehler) as ctx:
            self.aendern(m, *args)
        return ctx.exception.code, ctx.exception.feld


class TestFunktion(BasisTags):
    def test_hinzufuegen_und_entfernen_ohne_gross_klein(self):
        m = self.vorbereiten()
        ids = [self.nr(m, a) for a in ("a@beispiel.de", "b@beispiel.de", "c@beispiel.de")]
        z = self.aendern(m, ids, ["Neu", "spender"], ["VEREIN a"])
        self.assertEqual((z["geaendert"], z["unveraendert"]), (3, 0))
        self.assertEqual(self.tags(m, "a@beispiel.de"), ["Spender", "Neu"])                 # vorhandene Schreibweise bleibt, Neu kommt dazu
        self.assertEqual(self.tags(m, "b@beispiel.de"), ["Neu", "spender"])
        self.assertEqual(self.tags(m, "c@beispiel.de"), ["Spender", "Neu"])                 # Verein A entfernt (Gross/Klein egal)
        self.assertEqual({e["tag"]: e["anzahl"] for e in z["tags"]}, {"Spender": 3, "Neu": 3})                      # Zählung ohne Groß-/Kleinschreibung (häufigste Schreibweise)

    def test_nur_entfernen_oder_nur_hinzufuegen(self):
        m = self.vorbereiten()
        i = self.nr(m, "c@beispiel.de")
        self.assertEqual(self.aendern(m, [i], None, ["Spender"])["geaendert"], 1)
        self.assertEqual(self.tags(m, "c@beispiel.de"), ["Verein A"])
        self.assertEqual(self.aendern(m, [i], ["Neu"], None)["geaendert"], 1)
        self.assertEqual(self.tags(m, "c@beispiel.de"), ["Verein A", "Neu"])

    def test_unveraendert_wird_gezaehlt(self):
        m = self.vorbereiten()
        z = self.aendern(m, [self.nr(m, "a@beispiel.de")], ["Spender"], ["Gibt es nicht"])
        self.assertEqual((z["geaendert"], z["unveraendert"]), (0, 1))

    def test_doppelte_nummern_zaehlen_einmal(self):
        m = self.vorbereiten()
        i = self.nr(m, "b@beispiel.de")
        z = self.aendern(m, [i, i, i], ["Neu"])
        self.assertEqual(z["geaendert"], 1)

    def test_nur_bestaetigte_werden_geaendert_andere_uebersprungen_und_gezaehlt(self):
        m = self.vorbereiten()
        for adresse, status in (("u@beispiel.de", "unbestaetigt"), ("z@beispiel.de", "unzustellbar"), ("w@beispiel.de", "abgemeldet")):
            self.abo(m, adresse, status=status)
        ids = [self.zeile(m["id"], a)["id"] for a in ("a@beispiel.de", "u@beispiel.de", "z@beispiel.de", "w@beispiel.de")] + [999999]
        z = self.aendern(m, ids, ["Neu"])
        self.assertEqual(z["geaendert"], 1)
        self.assertEqual(z["uebersprungen"], {"abgemeldet": 1, "unzustellbar": 1, "unbestaetigt": 1, "unbekannt": 1, "tag_limit": 0})
        self.assertEqual(self.tags(m, "u@beispiel.de"), [])
        self.assertEqual(self.tags(m, "z@beispiel.de"), [])

    def test_fremder_mandant_wird_nie_veraendert(self):
        m = self.vorbereiten()
        andere = self.mandant("andere", "Andere")
        self.abo(andere, "x@beispiel.de")
        fremd = self.nr(andere, "x@beispiel.de")
        z = self.aendern(m, [fremd], ["Neu"])
        self.assertEqual((z["geaendert"], z["uebersprungen"]["unbekannt"]), (0, 1))
        self.assertEqual(self.tags(andere, "x@beispiel.de"), [])
        self.assertEqual(z["tags"], [{"tag": "Spender", "anzahl": 2}, {"tag": "Verein A", "anzahl": 1}])        # nur Tags dieses Mandanten

    def test_hoechstens_20_tags_je_adresse(self):
        m = self.vorbereiten()
        voll = ["T%d" % i for i in range(19)]
        self.tags_setzen(m, "b@beispiel.de", voll)
        i = self.nr(m, "b@beispiel.de")
        z = self.aendern(m, [i, self.nr(m, "a@beispiel.de")], ["Eins", "Zwei"])
        self.assertEqual(len(self.tags(m, "b@beispiel.de")), import_csv.MAX_TAGS_JE_ADRESSE)
        self.assertEqual(self.tags(m, "b@beispiel.de")[-1], "Eins")                         # Zwei passte nicht mehr
        self.assertEqual((z["geaendert"], z["unveraendert"], z["uebersprungen"]["tag_limit"], z["tag_limit_teilweise"]), (2, 0, 0, 1))
        self.assertEqual(self.tags(m, "a@beispiel.de"), ["Spender", "Eins", "Zwei"])         # die andere Adresse bekommt beide

    def test_adresse_an_der_grenze_zaehlt_genau_einmal(self):
        """Webys Beobachtung (Backend a6ed673): eine Adresse mit schon 20 Tags stand unter tag_limit UND unter unveraendert (3 Zähler für 2 Adressen)."""
        m = self.vorbereiten()
        self.tags_setzen(m, "b@beispiel.de", ["T%d" % i for i in range(20)])
        z = self.aendern(m, [self.nr(m, "a@beispiel.de"), self.nr(m, "b@beispiel.de")], ["Neu"])
        self.assertEqual((z["geaendert"], z["unveraendert"], z["uebersprungen"]["tag_limit"], z["tag_limit_teilweise"]), (1, 0, 1, 0))
        self.assertEqual(z["geaendert"] + z["unveraendert"] + sum(z["uebersprungen"].values()), 2)

    def test_jede_nummer_genau_einmal_in_der_summe(self):
        m = self.vorbereiten()
        for adresse, status in (("u@beispiel.de", "unbestaetigt"), ("z@beispiel.de", "unzustellbar"), ("w@beispiel.de", "abgemeldet")):
            self.abo(m, adresse, status=status)
        self.abo(m, "voll@beispiel.de")
        self.tags_setzen(m, "voll@beispiel.de", ["T%d" % i for i in range(20)])
        self.abo(m, "fast@beispiel.de")
        self.tags_setzen(m, "fast@beispiel.de", ["T%d" % i for i in range(19)])
        ids = [self.nr(m, a) for a in ("a@beispiel.de", "b@beispiel.de", "c@beispiel.de", "u@beispiel.de", "z@beispiel.de", "w@beispiel.de", "voll@beispiel.de", "fast@beispiel.de")] + [999999]
        z = self.aendern(m, ids + ids[:3], ["Spender", "X", "Y"])                         # dazu doppelte Nummern
        self.assertEqual(z["geaendert"] + z["unveraendert"] + sum(z["uebersprungen"].values()), len(set(ids)))
        self.assertEqual((z["geaendert"], z["unveraendert"]), (4, 0))
        self.assertEqual(z["uebersprungen"], {"abgemeldet": 1, "unzustellbar": 1, "unbestaetigt": 1, "unbekannt": 1, "tag_limit": 1})
        self.assertEqual(z["tag_limit_teilweise"], 1)                                      # fast: nur X passte

    def test_entfernen_schafft_platz_im_selben_aufruf(self):
        m = self.vorbereiten()
        self.tags_setzen(m, "b@beispiel.de", ["T%d" % i for i in range(20)])
        z = self.aendern(m, [self.nr(m, "b@beispiel.de")], ["Neu"], ["T0"])
        self.assertEqual(z["uebersprungen"]["tag_limit"], 0)
        self.assertIn("Neu", self.tags(m, "b@beispiel.de"))
        self.assertNotIn("T0", self.tags(m, "b@beispiel.de"))

    def test_tags_werden_bereinigt_wie_beim_import(self):
        m = self.vorbereiten()
        self.aendern(m, [self.nr(m, "b@beispiel.de")], ['  "Rahmen"  ', "mit​Unsichtbar"])
        self.assertEqual(self.tags(m, "b@beispiel.de"), ["Rahmen", "mitUnsichtbar"])

    def test_ungueltige_eingaben(self):
        m = self.vorbereiten()
        i = self.nr(m, "a@beispiel.de")
        faelle = [
            (([], ["x"]), ("ids_ungueltig", "abonnent_ids")), ((None, ["x"]), ("ids_ungueltig", "abonnent_ids")), ((["1"], ["x"]), ("ids_ungueltig", "abonnent_ids")),
            (([True], ["x"]), ("ids_ungueltig", "abonnent_ids")), (([0], ["x"]), ("ids_ungueltig", "abonnent_ids")), (([i] * 2001 if False else list(range(1, 2002)), ["x"]), ("ids_ungueltig", "abonnent_ids")),
            (([i], "x"), ("tags_ungueltig", "hinzufuegen")), (([i], ["x"] * 21), ("tags_ungueltig", "hinzufuegen")), (([i], None, "x"), ("tags_ungueltig", "entfernen")),
            (([i], [""]), ("tag_ungueltig", "hinzufuegen")), (([i], ["x" * 41]), ("tag_ungueltig", "hinzufuegen")), (([i], ["a,b"]), ("tag_ungueltig", "hinzufuegen")),
            (([i], ["a;b"]), ("tag_ungueltig", "hinzufuegen")), (([i], ["a|b"]), ("tag_ungueltig", "hinzufuegen")), (([i], ["a\nb"]), ("tag_ungueltig", "hinzufuegen")),
            (([i], [5]), ("tag_ungueltig", "hinzufuegen")), (([i], None, [""]), ("tag_ungueltig", "entfernen")),
            (([i],), ("nichts_zu_tun", "hinzufuegen")), (([i], [], []), ("nichts_zu_tun", "hinzufuegen")),
            (([i], ["Neu"], ["neu"]), ("tags_widerspruch", "entfernen")),
        ]
        for args, erwartet in faelle:
            self.assertEqual(self.fehler(m, *args), erwartet, repr(args)[:80])
        self.assertEqual(self.tags(m, "a@beispiel.de"), ["Spender"])                         # nichts verändert

    def test_genau_2000_nummern_gehen(self):
        m = self.vorbereiten()
        z = self.aendern(m, list(range(1, 2001)), ["Neu"])
        self.assertEqual(z["geaendert"], 3)
        self.assertEqual(z["uebersprungen"]["unbekannt"], 1997)


class TestSchnittstelle(BasisTags):
    def aufruf(self, m, body, methode="post", pfad="tags-aendern"):
        with mock.patch.object(betreiber_auth, "_bei_sortnext_fragen", return_value={"email": "catrin@bst-next.de", "betreiber": True}):
            betreiber_auth.cache_leeren()
            self.c.set_cookie("bst_session", "tok")
            return getattr(self.c, methode)("/api/v1/betreiber/mandanten/%d/abonnenten/%s" % (m["id"], pfad), **({"json": body} if body is not None else {}))

    def test_antwort_audit_und_liste(self):
        m = self.vorbereiten()
        ids = [self.nr(m, "a@beispiel.de"), self.nr(m, "b@beispiel.de")]
        r = self.aufruf(m, {"abonnent_ids": ids, "hinzufuegen": ["Neu"], "entfernen": ["Spender"]})
        j = r.get_json()
        self.assertEqual(r.status_code, 200, j)
        self.assertEqual((j["geaendert"], j["unveraendert"]), (2, 0))
        self.assertEqual(set(j), {"geaendert", "unveraendert", "uebersprungen", "tag_limit_teilweise", "tags"})
        self.assertNotIn("@", r.get_data(as_text=True))
        with mock.patch.object(betreiber_auth, "_bei_sortnext_fragen", return_value={"email": "catrin@bst-next.de", "betreiber": True}):
            betreiber_auth.cache_leeren()
            self.c.set_cookie("bst_session", "tok")
            liste = self.c.get("/api/v1/betreiber/mandanten/%d/abonnenten" % m["id"]).get_json()["abonnenten"]
        self.assertEqual({x["id"]: x["tags"] for x in liste}[ids[0]], ["Neu"])
        with db.verbindung() as c:
            audit = [tuple(z) for z in c.execute("SELECT * FROM audit_log").fetchall()]
        zeile = [str(z) for z in audit if "tags_geaendert" in str(z)]
        self.assertEqual(len(zeile), 1)
        self.assertIn("geaendert=2", zeile[0])
        self.assertNotIn("beispiel.de", zeile[0])                                            # keine Adressen der Abonnentinnen (der Akteur steht im Audit)
        self.assertNotIn("Neu", zeile[0])                                                    # keine Tag-Namen im Audit

    def test_fehlerantworten(self):
        m = self.vorbereiten()
        i = self.nr(m, "a@beispiel.de")
        r = self.aufruf(m, {"abonnent_ids": [i], "hinzufuegen": ["a,b"]})
        self.assertEqual((r.status_code, r.get_json()["error"], r.get_json()["feld"]), (400, "tag_ungueltig", "hinzufuegen"))
        r = self.aufruf(m, {"abonnent_ids": [i]})
        self.assertEqual((r.status_code, r.get_json()["error"]), (400, "nichts_zu_tun"))
        r = self.aufruf(m, {"abonnent_ids": [i], "hinzufuegen": ["x"], "extra": 1})
        self.assertEqual((r.status_code, r.get_json()["error"]), (400, "eingabe_ungueltig"))
        r = self.aufruf(m, {"abonnent_ids": [], "hinzufuegen": ["x"]})
        self.assertEqual((r.status_code, r.get_json()["error"], r.get_json()["feld"]), (400, "ids_ungueltig", "abonnent_ids"))
        r = self.c.post("/api/v1/betreiber/mandanten/99999/abonnenten/tags-aendern", json={"abonnent_ids": [1], "hinzufuegen": ["x"]})
        self.assertIn(r.status_code, (401, 403, 404))

    def test_nur_betreiber(self):
        m = self.vorbereiten()
        r = self.c.post("/api/v1/betreiber/mandanten/%d/abonnenten/tags-aendern" % m["id"], json={"abonnent_ids": [1], "hinzufuegen": ["x"]})
        self.assertIn(r.status_code, (401, 403))
        self.assertEqual(self.tags(m, "a@beispiel.de"), ["Spender"])


class TestWirkungAufVersand(BasisTags):
    def test_freigegebene_liste_bleibt_offene_vorschau_zaehlt_neu(self):
        m = self.vorbereiten()
        segment = {"tags": ["Spender"], "tags_modus": "oder"}
        eid = self.freigegeben(m, "abonnenten", segment=segment)                            # Empfänger: a, c
        offen = newsletter.anlegen(m, "Offen", "Text", "abonnenten", segment)["id"]
        self.assertEqual(newsletter.vorschau(m, offen)["anzahl"], 2)
        self.aendern(m, [self.nr(m, "b@beispiel.de")], ["Spender"], None)                    # b kommt dazu
        self.aendern(m, [self.nr(m, "a@beispiel.de")], None, ["Spender"])                    # a fällt weg
        self.assertEqual(newsletter.vorschau(m, offen)["anzahl"], 2)                         # b, c
        self.assertEqual(sorted(newsletter._empfaenger_ermitteln(m, {"ziel": "abonnenten", "segment": json.dumps(newsletter._segment_pruefen(m, segment))}), key=lambda x: x[2])[0][2], "b@beispiel.de")
        newsletter.lauf()
        an = sorted(str(x["To"]) for x in self.eml("hilo") if not str(x["Subject"]).startswith("[TEST] "))
        self.assertEqual(an, ["a@beispiel.de", "c@beispiel.de"])                              # festgeschriebene Liste unverändert
        self.assertEqual(len(self.zeilen(eid)), 2)


if __name__ == "__main__":
    unittest.main()
